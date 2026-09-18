"""Extendible Hash adapter over a borrowed, independently stored HeapFile."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
import os
from typing import NoReturn

from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.storage.heap_file import HeapFile
from engine.storage.record import Record, RecordValue
from engine.storage.rid import RID

from .base import Index
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .extendible_hash import ExtendibleHashIndex, HashValidationReport
from .hash_metrics import HashBuildMetrics


class UnclusteredHashIndex(Index):


    """Mantiene un índice de igualdad persistente contra RIDs de HeapFile en vivo.
    El adaptador posee y cierra su núcleo hash, pero toma prestado el HeapFile. Esto
    refleja el límite de propiedad de B+ no agrupado de la Etapa 4 sin pretender
    que el hashing ofrezca acceso ordenado o por rango. """

    def __init__(self, index: ExtendibleHashIndex, heap: HeapFile) -> None:
        if not isinstance(index, ExtendibleHashIndex):
            raise InvalidTypeError("index must be an ExtendibleHashIndex")
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        column = heap.schema.column(index.header.key_column)
        if column.data_type is not index.key_type:
            raise ValidationError("Hash key type does not match the Heap column")
        self._index = index
        self._heap = heap

    @classmethod
    def build(
        cls,
        path: str | os.PathLike[str],
        *,
        heap: HeapFile,
        index_name: str,
        table_name: str,
        key_column: str,
        allow_duplicate_keys: bool = True,
    ) -> "UnclusteredHashIndex":
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        index = ExtendibleHashIndex.build_from_storage(
            path,
            storage=heap,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            return cls(index, heap)
        except BaseException:
            index.close()
            raise

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        heap: HeapFile,
        index_name: str | None = None,
        table_name: str | None = None,
        key_column: str | None = None,
        allow_duplicate_keys: bool | None = None,
    ) -> "UnclusteredHashIndex":
        if not isinstance(heap, HeapFile):
            raise InvalidTypeError("heap must be a HeapFile")
        index = ExtendibleHashIndex.open(
            path,
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        try:
            runtime = cls(index, heap)
            runtime.validate_structure()
            return runtime
        except BaseException:
            index.close()
            raise

    @property
    def index(self) -> ExtendibleHashIndex:
        self._require_open()
        return self._index

    @property
    def heap(self) -> HeapFile:
        self._require_open()
        if self._heap.closed:
            raise RuntimeError("Borrowed HeapFile is closed")
        return self._heap

    @property
    def key_column(self) -> str:
        return self.index.header.key_column

    @property
    def entry_count(self) -> int:
        return self.index.entry_count

    @property
    def build_metrics(self) -> HashBuildMetrics | None:
        return self.index.build_metrics

    @property
    def closed(self) -> bool:
        return self._index.closed

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("Unclustered hash index is closed")

    def _require_ready(self) -> None:
        self._require_open()
        if not self._index.header.build_complete:
            raise ValidationError("Hash index is incomplete; rebuild before use")

    def _rollback_failed(
        self, message: str, operation_error: BaseException,
        cleanup_errors: list[BaseException],
    ) -> NoReturn:
        errors = [operation_error, *cleanup_errors]
        try:
            self._index.mark_incomplete()
            self._index.flush()
        except BaseException as marker_error:
            errors.append(marker_error)
            # Do not leave an uncertain runtime usable if even invalidation
            # fails. Retain every cause, including a possible close failure.
            try:
                self._index.close()
            except BaseException as close_error:
                errors.append(close_error)
        raise BaseExceptionGroup(message, errors) from operation_error

    def _record_for_association(
        self,
        key: RecordValue,
        rid: RID,
    ) -> tuple[RecordValue, Record]:
        self._require_ready()
        checked_key = BPlusKeyCodec.validate(self.index.key_type, key)
        BPlusRIDCodec.encode(rid)
        record = self.heap.read(rid)
        if BPlusKeyCodec.compare(
            self.index.key_type, checked_key, record[self.key_column]
        ) != 0:
            raise InvalidReferenceError(
                "Hash key/RID association does not match the Heap record"
            )
        return checked_key, record

    def insert(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.index.insert(checked_key, rid)

    def delete(self, key: RecordValue, rid: RID) -> None:
        checked_key, _ = self._record_for_association(key, rid)
        self.index.delete(checked_key, rid)

    def search(self, key: RecordValue) -> Generator[RID, None, None]:
        matches = self.search_records(key)

        def iterator() -> Generator[RID, None, None]:
            with closing(matches):
                for rid, _ in matches:
                    yield rid

        return iterator()

    def search_records(
        self, key: RecordValue
    ) -> Generator[tuple[RID, Record], None, None]:
        self._require_ready()
        checked_key = BPlusKeyCodec.validate(self.index.key_type, key)

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_ready()
            with closing(self.index.search(checked_key)) as matches:
                for rid in matches:
                    _, record = self._record_for_association(checked_key, rid)
                    yield rid, record

        return iterator()

    def insert_record(self, record: Record) -> RID:
        """Insert one row and undo it if its hash association cannot be added."""

        self._require_ready()
        rid = self.heap.insert(record)
        try:
            self.index.insert(record[self.key_column], rid)
            return rid
        except BaseException as index_error:
            try:
                self.heap.delete(rid)
            except BaseException as cleanup_error:
                self._rollback_failed(
                    "Hash insertion and Heap rollback both failed",
                    index_error, [cleanup_error],
                )
            raise

    def delete_record(self, rid: RID) -> None:
        """Remove the association before freeing its referenced Heap slot."""

        self._require_ready()
        BPlusRIDCodec.encode(rid)
        record = self.heap.read(rid)
        key = record[self.key_column]
        self.index.delete(key, rid)
        try:
            self.heap.delete(rid)
        except BaseException as storage_error:
            try:
                self.index.insert(key, rid)
            except BaseException as cleanup_error:
                self._rollback_failed(
                    "Heap deletion and hash rollback both failed",
                    storage_error, [cleanup_error],
                )
            raise

    def update_record(self, rid: RID, record: Record) -> RID:

        """Reemplaza una fila de Heap y actualiza la clave indexada con deshacer best-effort.
        HeapFile no tiene contrato de actualización in-place, por lo que el reemplazo puede devolver un
        RID diferente. La fila original permanece activa hasta que existan la nueva fila y su
        asociación, y cualquier error de limpieza marca el índice como incompleto. """

        self._require_ready()
        if not isinstance(record, Record):
            raise InvalidTypeError("Hash record update requires a Record")
        if record.schema != self.heap.schema:
            raise SchemaError("Record schema differs from HeapFile schema")
        BPlusRIDCodec.encode(rid)
        old_record = self.heap.read(rid)
        old_key = old_record[self.key_column]
        new_key = record[self.key_column]
        new_rid = self.heap.insert(record)
        new_association_added = False
        old_association_removed = False
        try:
            same_unique_key = (
                not self.index.header.allow_duplicate_keys
                and BPlusKeyCodec.compare(self.index.key_type, old_key, new_key) == 0
            )
            if same_unique_key:
                self.index.delete(old_key, rid)
                old_association_removed = True
            self.index.insert(new_key, new_rid)
            new_association_added = True
            if not old_association_removed:
                self.index.delete(old_key, rid)
                old_association_removed = True
            self.heap.delete(rid)
            return new_rid
        except BaseException as operation_error:
            cleanup_errors: list[BaseException] = []
            if new_association_added:
                try:
                    self.index.delete(new_key, new_rid)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            if old_association_removed:
                try:
                    self.index.insert(old_key, rid)
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                self.heap.delete(new_rid)
            except BaseException as exc:
                cleanup_errors.append(exc)
            if cleanup_errors:
                self._rollback_failed(
                    "Heap/hash update failed and rollback was incomplete",
                    operation_error, cleanup_errors,
                )
            raise

    def rebuild(self) -> HashBuildMetrics:
        """Atomically reconstruct associations from all active Heap rows."""

        self._require_open()
        return self.index.rebuild_from_storage(self.heap)

    def mark_incomplete(self) -> None:
        """Persistently disable this adapter until a complete rebuild succeeds."""

        self._require_open()
        self._index.mark_incomplete()
        self._index.flush()

    def validate_structure(self) -> HashValidationReport:
        """Validate physical hash invariants and one-to-one live Heap coverage."""

        report = self.index.validate_structure()
        if report.association_count != self.heap.record_count:
            raise ValidationError("Hash entry count does not match active Heap rows")
        with closing(self.heap.scan()) as rows:
            for rid, record in rows:
                key = record[self.key_column]
                with closing(self.index.search(key)) as matches:
                    if rid not in matches:
                        raise ValidationError(
                            "Active Heap record is missing from the hash index"
                        )
        return report

    def read(self, rid: RID) -> Record:
        self._require_open()
        return self.heap.read(rid)

    def flush(self) -> None:
        self._require_open()
        self.heap.flush()
        self.index.flush()

    def close(self) -> None:
        self._index.close()

    def __enter__(self) -> "UnclusteredHashIndex":
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
