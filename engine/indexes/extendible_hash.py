from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
from dataclasses import dataclass, replace
from functools import wraps
import os
from pathlib import Path
from threading import RLock
from time import perf_counter

from engine.catalog.schema import Schema
from engine.catalog.types import DataType
from engine.errors import (
    DuplicateError,
    HashBucketOverflowError,
    HashDepthLimitError,
    InvalidTypeError,
    ValidationError,
)
from engine.storage.base import Storage
from engine.storage.page_manager import PageManager
from engine.storage.record import RecordValue
from engine.storage.rid import RID

from .base import Index
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .hash_binary import (
    HASH_BUCKET_PAYLOAD_SIZE,
    HASH_DEFAULT_MAX_GLOBAL_DEPTH,
    HASH_DIRECTORY_ENTRIES_PER_PAGE,
    HASH_INITIAL_GLOBAL_DEPTH,
    HASH_UINT64_MAX,
)
from .hash_bucket import HashAssociation, HashBucket
from .hash_codec import HashCodec
from .hash_directory import HashDirectory, HashDirectoryPage
from .hash_header import HashFileHeader
from .hash_io import HashBucketPageIO, HashDirectoryPageIO, HashHeaderPageIO
from .hash_metrics import HashBuildMetrics, HashMetrics, HashStructuralMetrics


def _metric_latched(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._metrics_mutex:
            return method(self, *args, **kwargs)

    return call


@dataclass(frozen=True, slots=True)
class _SplitPlan:
    #La estructura de directorios(topología - > que asocia los bits del código hash) con las páginas de datos osea buckets en memoria.

    global_depth: int
    directory_entries: tuple[int, ...]
    buckets: dict[int, tuple[int, tuple[HashAssociation, ...]]]
    virtual_page_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True) # reporte solo de lectura y optimización para que python no cree un diccionario de atributos para cada instancia, lo que ahorra memoria
class HashValidationReport:
    #ver la estructura del indice hash (topología) en el disco después de un proceso de validación, para ver si es consistente y no tiene errores.

    global_depth: int
    directory_entry_count: int
    directory_page_count: int
    bucket_count: int
    association_count: int
    orphan_page_count: int


class ExtendibleHashIndex(Index):

    #El motor no destruye el bucket ni la página de directorio, aunque estén vacios.
    #Los buckets se van vaciando pero el motor no hace el proceso inverso a split (buddy merge , directory shrink), que son parte del algorimto de extendible hashing standar
    # Extendible Hashing orientado a disco donde el directorio(tabla de punteros) y los buckets viven en archivos binarios en el almacenamiento fisico

    def __init__(self, manager: PageManager, header: HashFileHeader) -> None:
        if not isinstance(manager, PageManager):
            raise InvalidTypeError("manager must be a PageManager")
        if not isinstance(header, HashFileHeader):
            raise InvalidTypeError("header must be a HashFileHeader")
        if manager.allocated_page_count != header.index_page_count + 1:
            raise ValidationError("Hash header page count does not match the file")
        self._manager = manager
        self._metrics_mutex = RLock()
        self._header = header
        self._directories = HashDirectoryPageIO(
            manager, counter_lock=self._metrics_mutex
        )
        self._buckets = HashBucketPageIO(
            manager, header.key_type, counter_lock=self._metrics_mutex
        )
        self._build_metrics: HashBuildMetrics | None = None
        self._structural_metrics = HashStructuralMetrics()

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        *,
        index_name: str,
        table_name: str,
        key_column: str,
        key_type: DataType,
        allow_duplicate_keys: bool = True,
        initial_global_depth: int = HASH_INITIAL_GLOBAL_DEPTH,
        maximum_global_depth: int = HASH_DEFAULT_MAX_GLOBAL_DEPTH,
        _build_complete: bool = True,
    ) -> "ExtendibleHashIndex":
        # Verifica que los tipos de datos y las profundidades del hash sean correctos antes de crear el índice en disco.
        if type(initial_global_depth) is not int or type(maximum_global_depth) is not int:
            raise InvalidTypeError("Hash depths must be built-in integers")
        if not (
            0
            <= initial_global_depth
            <= maximum_global_depth
            <= HASH_DEFAULT_MAX_GLOBAL_DEPTH
        ):
            raise ValidationError(
                "Hash depths must satisfy 0 <= initial <= maximum <= 20"
            )
        if not isinstance(key_type, DataType):
            raise InvalidTypeError("key_type must be a DataType")
        if type(allow_duplicate_keys) is not bool:
            raise InvalidTypeError("allow_duplicate_keys must be a bool")
        if type(_build_complete) is not bool:
            raise InvalidTypeError("_build_complete must be a bool")

        target = Path(path).absolute() if isinstance(path, (str, os.PathLike)) else path
        manager = PageManager.create(path)
        try:
            #La página cero es la cabecera del índice hash, que contiene metadatos sobre el índice, como su nombre o de la tabla, etc. 
            #Esta página se asigna primero pero solo se llena con los metadatos finales después de que todas las páginas iniciales del directorio y los buckets sean válidas.
            if manager.allocate_page() != 0:
                raise ValidationError("Hash metadata page must be physical page 0")
            directory_io = HashDirectoryPageIO(manager)
            bucket_io = HashBucketPageIO(manager, key_type)
            entry_count = 1 << initial_global_depth
            directory_page_count = (
                entry_count + HASH_DIRECTORY_ENTRIES_PER_PAGE - 1
            ) // HASH_DIRECTORY_ENTRIES_PER_PAGE
            directory_page_ids = tuple(
                directory_io.allocate_page() for _ in range(directory_page_count)
            )
            bucket_page_ids = tuple(
                bucket_io.allocate_page() for _ in range(entry_count)
            )

            for page_id in bucket_page_ids:
                bucket_io.write_bucket(
                    HashBucket(page_id, key_type, initial_global_depth)
                )
            cls._write_directory_pages(
                directory_io,
                HashDirectory(initial_global_depth, bucket_page_ids),
                directory_page_ids,
            )
            header = HashFileHeader(
                index_name=index_name,
                table_name=table_name,
                key_column=key_column,
                key_type=key_type,
                allow_duplicate_keys=allow_duplicate_keys,
                build_complete=_build_complete,
                initial_global_depth=initial_global_depth,
                global_depth=initial_global_depth,
                maximum_global_depth=maximum_global_depth,
                directory_first_page_id=directory_page_ids[0],
                directory_page_count=directory_page_count,
                directory_entry_count=entry_count,
                bucket_count=entry_count,
                index_page_count=manager.allocated_page_count - 1,
            )
            HashHeaderPageIO.write(manager, header)
            index = cls(manager, header)
            # Keep the typed I/O objects that performed creation, including
            # their real allocation/write counters for this same session.
            index._directories = directory_io
            index._buckets = bucket_io
            index._validate_open_topology()
            return index
        except BaseException:
            try:
                manager.close()
            finally:
                if isinstance(target, Path):
                    target.unlink(missing_ok=True)
            raise

    @classmethod
    def build_from_storage(
        cls,
        path: str | os.PathLike[str],
        *,
        storage: Storage,
        index_name: str,
        table_name: str,
        key_column: str,
        allow_duplicate_keys: bool = True,
        initial_global_depth: int = HASH_INITIAL_GLOBAL_DEPTH,
        maximum_global_depth: int = HASH_DEFAULT_MAX_GLOBAL_DEPTH,
    ) -> "ExtendibleHashIndex":
   
        """ Construir cada asociación de almacenamiento activa en un nuevo archivo hash. La fuente se toma prestada y permanece abierta. """
        

        if not isinstance(storage, Storage):
            raise InvalidTypeError("storage must implement Storage")
        try:
            schema = storage.schema
        except AttributeError as exc:
            raise InvalidTypeError("storage must expose its Schema") from exc
        if not isinstance(schema, Schema):
            raise InvalidTypeError("storage schema must be a Schema")
        column = schema.column(key_column)
        try:
            storage_reads_before = storage.pages_read
        except AttributeError as exc:
            raise InvalidTypeError(
                "storage must expose actual page-I/O counters"
            ) from exc
        if type(storage_reads_before) is not int:
            raise InvalidTypeError("storage pages_read must be an int")

        started_at = perf_counter()
        index = cls.create(
            path,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            key_type=column.data_type,
            allow_duplicate_keys=allow_duplicate_keys,
            initial_global_depth=initial_global_depth,
            maximum_global_depth=maximum_global_depth,
            _build_complete=False,
        )
        indexed = 0
        try:
            with closing(storage.scan()) as rows:
                for rid, record in rows:
                    index.insert(record[key_column], rid)
                    indexed += 1
            
            index.validate_structure()
            index._write_header(replace(index._header, build_complete=True))
            index.flush()
            index._build_metrics = HashBuildMetrics(
                elapsed_seconds=perf_counter() - started_at,
                associations_indexed=indexed,
                storage_pages_read=storage.pages_read - storage_reads_before,
                index_pages_read=index.pages_read,
                index_pages_written=index.pages_written,
                index_pages_allocated=index.pages_allocated,
                index_file_size=index.file_size,
            )
            return index
        except BaseException:
            # Publication (including fsync) must succeed before a builder can
            # expose this index to Catalog. Mark a failed final flush too.
            try:
                if not index.closed:
                    index.mark_incomplete()
            except BaseException:
                pass  # No WAL: the original failure remains authoritative.
            try:
                index.close()
            except BaseException:
                pass
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        index_name: str | None = None,
        table_name: str | None = None,
        key_column: str | None = None,
        key_type: DataType | None = None,
        allow_duplicate_keys: bool | None = None,
    ) -> "ExtendibleHashIndex":
        manager = PageManager.open(path)
        try:
            header = HashHeaderPageIO.read(manager)
            if not header.build_complete:
                raise ValidationError("Extendible Hash index build is incomplete")
            expected = {
                "index_name": index_name,
                "table_name": table_name,
                "key_column": key_column,
                "key_type": key_type,
                "allow_duplicate_keys": allow_duplicate_keys,
            }
            for field, value in expected.items():
                if value is None:
                    continue
                actual = getattr(header, field)
                if type(value) is not type(actual):
                    raise InvalidTypeError(f"Invalid type for expected hash {field}")
                if actual != value:
                    raise ValidationError(f"Hash index metadata mismatch for {field}")
            index = cls(manager, header)
            index._validate_open_topology()
            return index
        except BaseException:
            try:
                manager.close()
            except BaseException:
                pass
            raise

    @property
    def header(self) -> HashFileHeader:
        self._require_open()
        return self._header

    @property
    def key_type(self) -> DataType:
        return self.header.key_type

    @property
    def global_depth(self) -> int:
        return self.header.global_depth

    @property
    def entry_count(self) -> int:
        return self.header.association_count

    @property
    def bucket_count(self) -> int:
        return self.header.bucket_count

    @property
    def build_metrics(self) -> HashBuildMetrics | None:        

        self._require_open()
        return self._build_metrics

    @property
    @_metric_latched
    def structural_metrics(self) -> HashStructuralMetrics:
        

        self._require_open()
        return self._structural_metrics

    @property
    @_metric_latched
    def metrics(self) -> HashMetrics:
        """combina la I/O física tipada con datos de topología lógica y duradera."""

        self._require_open()
        structural = self._structural_metrics
        return HashMetrics(
            directory_page_reads=self._directories.pages_read,
            directory_page_writes=self._directories.pages_written,
            directory_page_allocations=self._directories.pages_allocated,
            bucket_page_reads=self._buckets.pages_read,
            bucket_page_writes=self._buckets.pages_written,
            bucket_page_allocations=self._buckets.pages_allocated,
            bucket_page_frees=self._buckets.pages_freed,
            bucket_splits=structural.bucket_splits,
            directory_doublings=structural.directory_doublings,
            bucket_merges=structural.bucket_merges,
            directory_shrinks=structural.directory_shrinks,
            associations_inspected=structural.associations_inspected,
            current_global_depth=self._header.global_depth,
            current_live_bucket_count=self._header.bucket_count,
            allocated_index_pages=self._header.index_page_count,
            allocated_index_bytes=self.file_size,
        )

    @property
    def allocated_page_count(self) -> int:
        self._require_open()
        return self._manager.allocated_page_count

    @property
    def file_size(self) -> int:
        self._require_open()
        return self._manager.file_size

    @property
    def pages_read(self) -> int:
        return self._manager.pages_read

    @property
    def pages_written(self) -> int:
        return self._manager.pages_written

    @property
    def pages_allocated(self) -> int:
        return self._manager.pages_allocated

    @property
    def closed(self) -> bool:
        return self._manager.closed

    @property
    def directory_entries(self) -> tuple[int, ...]:
       

        directory, _ = self._read_directory()
        return directory.entries

    @_metric_latched
    def reset_counters(self) -> None:
        self._require_open()
        self._manager.reset_counters()
        self._directories.reset_counters()
        self._buckets.reset_counters()
        self._structural_metrics = HashStructuralMetrics()

    def _count_structural(self, field: str, amount: int = 1) -> None:
        with self._metrics_mutex:
            self._structural_metrics = replace(
                self._structural_metrics,
                **{field: getattr(self._structural_metrics, field) + amount},
            )

    def mark_incomplete(self) -> None:

        self._require_open()
        if self._header.build_complete:
            self._write_header(replace(self._header, build_complete=False))

    def rebuild_from_storage(self, storage: Storage) -> HashBuildMetrics:
        """Atomicamente reemplaza este índice desde las filas activas actuales de la fuente."""

        self._require_open()
        temporary_path = self._manager.temporary_replacement_path()
        candidate: ExtendibleHashIndex | None = None
        committed = False
        try:
            candidate = type(self).build_from_storage(
                temporary_path,
                storage=storage,
                index_name=self._header.index_name,
                table_name=self._header.table_name,
                key_column=self._header.key_column,
                allow_duplicate_keys=self._header.allow_duplicate_keys,
                initial_global_depth=self._header.initial_global_depth,
                maximum_global_depth=self._header.maximum_global_depth,
            )
            candidate.validate_structure()
            candidate.flush()
            metrics = candidate.build_metrics
            if metrics is None:  # pragma: no cover - construction guarantees it
                raise ValidationError("Replacement hash build produced no metrics")
            structural_metrics = candidate.structural_metrics
            candidate.close()
            candidate = None

            self._manager.commit_replacement(temporary_path)
            committed = True
            header = HashHeaderPageIO.read(self._manager)
            expected = {
                "index_name": self._header.index_name,
                "table_name": self._header.table_name,
                "key_column": self._header.key_column,
                "key_type": self._header.key_type,
                "allow_duplicate_keys": self._header.allow_duplicate_keys,
                "initial_global_depth": self._header.initial_global_depth,
                "maximum_global_depth": self._header.maximum_global_depth,
            }
            for field, value in expected.items():
                if getattr(header, field) != value:
                    raise ValidationError(
                        f"Replacement hash metadata mismatch for {field}"
                    )
            if not header.build_complete:
                raise ValidationError("Replacement hash build is incomplete")
            self._header = header
            self._directories = HashDirectoryPageIO(
                self._manager, counter_lock=self._metrics_mutex
            )
            self._buckets = HashBucketPageIO(
                self._manager, header.key_type,
                counter_lock=self._metrics_mutex,
            )
            self._build_metrics = metrics
            self._structural_metrics = structural_metrics
            return metrics
        finally:
            if candidate is not None:
                candidate.close()
            if not committed:
                self._manager.discard_replacement(temporary_path)

    def flush(self) -> None:
        self._require_open()
        self._manager.flush()

    def close(self) -> None:
        self._manager.close()

    def __enter__(self) -> "ExtendibleHashIndex":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("Extendible Hash index is closed")

    def _validate_page_reference(self, page_id: object, label: str) -> int:
        if type(page_id) is not int or not 1 <= page_id <= self._header.index_page_count:
            raise ValidationError(
                f"{label} {page_id!r} is outside the hash index page range"
            )
        return page_id

    @staticmethod
    def _write_directory_pages(
        directory_io: HashDirectoryPageIO,
        directory: HashDirectory,
        page_ids: tuple[int, ...],
    ) -> None:
        required = (
            len(directory.entries) + HASH_DIRECTORY_ENTRIES_PER_PAGE - 1
        ) // HASH_DIRECTORY_ENTRIES_PER_PAGE
        if len(page_ids) != required:
            raise ValidationError("Directory page allocation does not match its size")
        for ordinal, page_id in enumerate(page_ids):
            start = ordinal * HASH_DIRECTORY_ENTRIES_PER_PAGE
            chunk = directory.entries[start : start + HASH_DIRECTORY_ENTRIES_PER_PAGE]
            next_page_id = page_ids[ordinal + 1] if ordinal + 1 < required else None
            directory_io.write_page(
                page_id,
                HashDirectoryPage(ordinal, chunk, next_page_id=next_page_id),
            )

    def _read_directory(self) -> tuple[HashDirectory, tuple[int, ...]]:
        self._require_open()
        entries: list[int] = []
        page_ids: list[int] = []
        next_page_id: int | None = self._header.directory_first_page_id
        for expected_ordinal in range(self._header.directory_page_count):
            if next_page_id is None:
                raise ValidationError("Hash directory chain ended early")
            checked = self._validate_page_reference(next_page_id, "directory page")
            if checked in page_ids:
                raise ValidationError(
                    f"Cycle detected in hash directory pages at page {checked}"
                )
            try:
                page = self._directories.read_page(checked)
                page.validate_position(self._header.directory_entry_count)
            except (ValidationError, InvalidTypeError) as exc:
                raise type(exc)(f"Hash directory page {checked}: {exc}") from exc
            if page.ordinal != expected_ordinal:
                raise ValidationError(
                    f"Hash directory page {checked} ordinal is incorrect"
                )
            page_ids.append(checked)
            entries.extend(page.bucket_page_ids)
            next_page_id = page.next_page_id
        if next_page_id is not None:
            raise ValidationError("Hash directory chain exceeds persisted page count")
        if len(entries) != self._header.directory_entry_count:
            raise ValidationError("Hash directory entry count differs from its header")
        return HashDirectory(self._header.global_depth, entries), tuple(page_ids)

    def _lookup_bucket_page_id(self, hash_value: int) -> int:
        

        directory_index = HashCodec.directory_index(
            hash_value, self._header.global_depth
        )
        target_ordinal, offset = divmod(
            directory_index, HASH_DIRECTORY_ENTRIES_PER_PAGE
        )
        next_page_id: int | None = self._header.directory_first_page_id
        visited: set[int] = set()
        for expected_ordinal in range(target_ordinal + 1):
            if next_page_id is None:
                raise ValidationError("Hash directory chain ended before lookup")
            checked = self._validate_page_reference(next_page_id, "directory page")
            if checked in visited:
                raise ValidationError("Cycle detected in hash directory pages")
            visited.add(checked)
            page = self._directories.read_page(checked)
            if page.ordinal != expected_ordinal:
                raise ValidationError("Hash directory page ordinal is incorrect")
            page.validate_position(self._header.directory_entry_count)
            if page.next_page_id is not None:
                self._validate_page_reference(page.next_page_id, "next directory page")
                if page.next_page_id in visited:
                    raise ValidationError("Cycle detected in hash directory pages")
            if expected_ordinal == target_ordinal:
                if offset >= len(page.bucket_page_ids):
                    raise ValidationError("Hash directory lookup offset is missing")
                return page.bucket_page_ids[offset]
            next_page_id = page.next_page_id
        raise ValidationError("Hash directory lookup did not reach its entry")

    def _validate_open_topology(self) -> None:
        """Perform the lifecycle-level checks needed before exposing the index."""

        self.validate_structure()

    def validate_structure(self, deep: bool = True) -> HashValidationReport:
       

        """lee el archivo completo y prueba sus invariantes hash persistentes. deep=False verifica la propiedad de la página y la topología del directorio/bucket"""
        self._require_open()
        if type(deep) is not bool:
            raise InvalidTypeError("deep must be a bool")
        # Check both sources: serialization alone does not rerun dataclass
        # invariants, and a cached header cannot prove the disk page is intact.
        try:
            cached_header = HashFileHeader.deserialize(self._header.serialize())
            persisted_header = HashHeaderPageIO.read(self._manager)
        except (ValidationError, InvalidTypeError) as exc:
            raise type(exc)(f"Hash metadata page 0: {exc}") from exc
        if persisted_header != cached_header:
            raise ValidationError("Hash metadata page 0 differs from the active header")
        if self._manager.allocated_page_count != self._header.index_page_count + 1:
            raise ValidationError("Hash header page count does not match the file")
        directory, directory_pages = self._read_directory()
        aliases_by_bucket: dict[int, list[int]] = {}
        for position, bucket_id in enumerate(directory.entries):
            aliases_by_bucket.setdefault(bucket_id, []).append(position)
        bucket_ids = set(aliases_by_bucket)
        overlap = bucket_ids & set(directory_pages)
        if overlap:
            raise ValidationError(
                f"Hash directory and bucket pages overlap at page {min(overlap)}"
            )
        if len(bucket_ids) != self._header.bucket_count:
            raise ValidationError(
                "Hash bucket count in metadata page 0 differs from directory reachability"
            )
        observed_associations = 0
        seen_unique_keys: set[bytes] = set()
        for bucket_id in sorted(bucket_ids):
            checked = self._validate_page_reference(bucket_id, "bucket page")
            try:
                bucket = self._buckets.read_bucket(checked)
            except (ValidationError, InvalidTypeError) as exc:
                raise type(exc)(f"Hash bucket page {checked}: {exc}") from exc
            if bucket.local_depth > directory.global_depth:
                raise ValidationError(
                    f"Hash bucket {bucket_id} local depth exceeds global depth"
                )
            aliases = aliases_by_bucket[bucket_id]
            if len(aliases) != 1 << (directory.global_depth - bucket.local_depth):
                raise ValidationError(
                    f"Hash bucket {bucket_id} has an invalid directory alias count"
                )
            prefix = aliases[0] & ((1 << bucket.local_depth) - 1)
            if any(
                index & ((1 << bucket.local_depth) - 1) != prefix
                for index in aliases
            ):
                raise ValidationError(
                    f"Hash directory aliases for bucket {bucket_id} disagree "
                    "with local depth"
                )
            if deep:
                for entry_position, (key, _) in enumerate(bucket.entries):
                    routed_bucket = directory.lookup_bucket(
                        HashCodec.hash_key(self._header.key_type, key)
                    )
                    if routed_bucket != bucket_id:
                        raise ValidationError(
                            f"Hash association is stored in wrong bucket {bucket_id}, "
                            f"entry {entry_position}"
                        )
                    if not self._header.allow_duplicate_keys:
                        encoded = HashCodec.encode_key(self._header.key_type, key)
                        if encoded in seen_unique_keys:
                            raise ValidationError(
                                "Unique hash index contains duplicate keys in "
                                f"bucket page {bucket_id}, entry {entry_position}"
                            )
                        seen_unique_keys.add(encoded)
            observed_associations += bucket.entry_count
        if observed_associations != self._header.association_count:
            raise ValidationError(
                "Hash association count in metadata page 0 differs from reachable buckets"
            )
        owned_pages = set(directory_pages) | bucket_ids
        expected_pages = set(range(1, self._header.index_page_count + 1))
        orphan_pages = expected_pages - owned_pages
        if orphan_pages:
            first = min(orphan_pages)
            raise ValidationError(f"Hash file contains orphan page {first}")
        if owned_pages - expected_pages:
            raise ValidationError("Hash file owns a page outside its declared range")
        return HashValidationReport(
            global_depth=directory.global_depth,
            directory_entry_count=len(directory.entries),
            directory_page_count=len(directory_pages),
            bucket_count=len(bucket_ids),
            association_count=observed_associations,
            orphan_page_count=0,
        )

    def _write_header(self, header: HashFileHeader) -> None:
        # Buckets and directory pages are written first; this final page-zero
        # image publishes the new logical topology for normal close/reopen.
        HashHeaderPageIO.write(self._manager, header)
        self._header = header

    def _read_routed_bucket(self, page_id: int) -> HashBucket:
        """Validate the selected page without reading unrelated buckets.

        The codec checks type, identity and the absolute depth bound; this
        check relates local depth to this index's current global depth.
        """
        bucket = self._buckets.read_bucket(
            self._validate_page_reference(page_id, "bucket page")
        )
        if bucket.local_depth > self._header.global_depth:
            raise ValidationError(
                f"Hash bucket {page_id} local depth exceeds global depth"
            )
        return bucket

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        hash_value = HashCodec.hash_key(self._header.key_type, checked_key)

        def iterator() -> Generator[RID, None, None]:
            self._require_open()
            bucket_id = self._lookup_bucket_page_id(hash_value)
            bucket = self._read_routed_bucket(bucket_id)
            self._count_structural("associations_inspected", bucket.entry_count)
            # Routing narrows the read to one bucket; equality is still decided
            # with the complete typed key, never with the hash alone.
            yield from bucket.find(checked_key)

        return iterator()

    def insert(self, key: RecordValue, rid: RID) -> None:
        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        BPlusRIDCodec.encode(rid)
        if HashBucket.serialized_size_for(
            self._header.key_type, ((checked_key, rid),)
        ) > HASH_BUCKET_PAYLOAD_SIZE:
            raise HashBucketOverflowError("One hash association exceeds a bucket page")

        directory, directory_page_ids = self._read_directory()
        hash_value = HashCodec.hash_key(self._header.key_type, checked_key)
        bucket_id = directory.lookup_bucket(hash_value)
        bucket = self._read_routed_bucket(bucket_id)
        self._count_structural("associations_inspected", bucket.entry_count)
        if bucket.contains(checked_key, rid):
            return
        if not self._header.allow_duplicate_keys and bucket.find(checked_key):
            raise DuplicateError(
                f"Duplicate key is not allowed by this hash index: {checked_key!r}"
            )
        # Only new associations consume the counter. Exact reinsertion remains
        # idempotent even at the persisted uint64 boundary.
        if self._header.association_count == HASH_UINT64_MAX:
            raise ValidationError("Hash association count reached the uint64 limit")

        if bucket.can_fit(checked_key, rid):
            self._buckets.write_bucket(bucket.insert(checked_key, rid))
            self._write_header(
                replace(
                    self._header,
                    association_count=self._header.association_count + 1,
                )
            )
            return

        plan = self._plan_split_insert(
            directory, bucket, (checked_key, rid)
        )
        self._publish_split_plan(plan, directory_page_ids)

    def _plan_split_insert(
        self,
        directory: HashDirectory,
        bucket: HashBucket,
        pending: HashAssociation,
    ) -> _SplitPlan:
        """Plan every required split in memory so bounded rejection is write-free."""

        planned_directory = list(directory.entries)
        planned_depth = directory.global_depth
        planned_buckets: dict[int, tuple[int, tuple[HashAssociation, ...]]] = {
            bucket.page_id: (bucket.local_depth, (*bucket.entries, pending))
        }
        virtual_ids: list[int] = []
        next_virtual_id = -1

        while True:
            overflowing = next(
                (
                    page_id
                    for page_id, (_, entries) in planned_buckets.items()
                    if HashBucket.serialized_size_for(
                        self._header.key_type, entries
                    ) > HASH_BUCKET_PAYLOAD_SIZE
                ),
                None,
            )
            if overflowing is None:
                break
            local_depth, entries = planned_buckets[overflowing]
            hashes = tuple(
                HashCodec.hash_key(self._header.key_type, key) for key, _ in entries
            )
            # Equal complete hashes can never be separated by further bits, so
            # reject before allocating or rewriting any page.
            if len(set(hashes)) == 1:
                raise HashBucketOverflowError(
                    "Full-hash collisions cannot fit in one bucket"
                )
            if local_depth >= self._header.maximum_global_depth:
                raise HashDepthLimitError(
                    "Hash insertion reached maximum_global_depth"
                )
            if local_depth == planned_depth:
                if planned_depth >= self._header.maximum_global_depth:
                    raise HashDepthLimitError(
                        "Hash directory cannot double beyond maximum_global_depth"
                    )
                # LSB directory doubling duplicates the old logical half; lookup
                # remains equivalent until aliases are redirected below.
                planned_directory.extend(planned_directory)
                planned_depth += 1

            split_bit = local_depth
            left_entries: list[HashAssociation] = []
            right_entries: list[HashAssociation] = []
            for association, hash_value in zip(entries, hashes):
                destination = right_entries if (hash_value >> split_bit) & 1 else left_entries
                destination.append(association)

            virtual_id = next_virtual_id
            next_virtual_id -= 1
            virtual_ids.append(virtual_id)
            new_local_depth = local_depth + 1
            planned_buckets[overflowing] = (new_local_depth, tuple(left_entries))
            planned_buckets[virtual_id] = (new_local_depth, tuple(right_entries))

            redirected = 0
            retained = 0
            for index, page_id in enumerate(planned_directory):
                if page_id != overflowing:
                    continue
                if (index >> split_bit) & 1:
                    planned_directory[index] = virtual_id
                    redirected += 1
                else:
                    retained += 1
            if redirected == 0 or retained == 0:
                raise ValidationError("Hash split could not divide directory aliases")

        return _SplitPlan(
            planned_depth,
            tuple(planned_directory),
            planned_buckets,
            tuple(virtual_ids),
        )

    def _publish_split_plan(
        self,
        plan: _SplitPlan,
        existing_directory_page_ids: tuple[int, ...],
    ) -> None:
        """Allocate plan pages, then publish buckets, directory, and header."""

        virtual_to_physical = {
            virtual: self._buckets.allocate_page()
            for virtual in plan.virtual_page_ids
        }
        physical_entries = tuple(
            virtual_to_physical.get(page_id, page_id)
            for page_id in plan.directory_entries
        )
        directory = HashDirectory(plan.global_depth, physical_entries)

        required_directory_pages = (
            len(physical_entries) + HASH_DIRECTORY_ENTRIES_PER_PAGE - 1
        ) // HASH_DIRECTORY_ENTRIES_PER_PAGE
        directory_page_ids = list(existing_directory_page_ids)
        while len(directory_page_ids) < required_directory_pages:
            directory_page_ids.append(self._directories.allocate_page())
        if len(directory_page_ids) != required_directory_pages:
            raise ValidationError("Hash directory unexpectedly requires fewer pages")

        materialized: list[HashBucket] = []
        for planned_id, (local_depth, entries) in plan.buckets.items():
            physical_id = virtual_to_physical.get(planned_id, planned_id)
            materialized.append(
                HashBucket(
                    physical_id,
                    self._header.key_type,
                    local_depth,
                    entries,
                )
            )
        # New buckets are written before any old bucket or directory pointer can
        # expose them; complete crash atomicity remains deferred until WAL.
        for bucket in sorted(
            materialized,
            key=lambda value: (value.page_id not in virtual_to_physical.values(), value.page_id),
        ):
            self._buckets.write_bucket(bucket)
        self._write_directory_pages(
            self._directories, directory, tuple(directory_page_ids)
        )
        previous_depth = self._header.global_depth
        self._write_header(
            replace(
                self._header,
                global_depth=plan.global_depth,
                directory_entry_count=len(physical_entries),
                directory_page_count=len(directory_page_ids),
                bucket_count=self._header.bucket_count + len(plan.virtual_page_ids),
                association_count=self._header.association_count + 1,
                index_page_count=self._manager.allocated_page_count - 1,
            )
        )
        # Count only structural changes made reachable by the final header.
        self._count_structural("bucket_splits", len(plan.virtual_page_ids))
        self._count_structural(
            "directory_doublings", plan.global_depth - previous_depth
        )

    def delete(self, key: RecordValue, rid: RID) -> None:
        """Remove one exact association while preserving the current topology."""

        self._require_open()
        checked_key = BPlusKeyCodec.validate(self._header.key_type, key)
        BPlusRIDCodec.encode(rid)
        hash_value = HashCodec.hash_key(self._header.key_type, checked_key)
        bucket_id = self._lookup_bucket_page_id(hash_value)
        bucket = self._read_routed_bucket(bucket_id)
        self._count_structural("associations_inspected", bucket.entry_count)
        updated = bucket.delete(checked_key, rid)
        # Validate the next header before the first physical write.
        # In particular, corrupt zero counters must not erase a live entry.
        updated_header = replace(
            self._header,
            association_count=self._header.association_count - 1,
        )
        self._buckets.write_bucket(updated)
        self._write_header(updated_header)
