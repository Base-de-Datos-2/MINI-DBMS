"""Manifest-backed database owner and synchronous CREATE orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from engine.catalog import Catalog, DataType, IndexMetadata, IndexType, TableMetadata
from engine.errors import DuplicateError, InvalidTypeError, ValidationError
from engine.indexes import build_catalog_index, open_catalog_index
from engine.indexes.bplus_header import BPlusFileHeader
from engine.maintenance import MaintenanceIndex, MutationReport, MutationService
from engine.operators.context import DEFAULT_BUDGET_BYTES, DEFAULT_MAX_OPEN_HANDLES
from engine.query.ddl import CreatedTable
from engine.query.environment import QueryEnvironment
from engine.query.executor import DEFAULT_MATERIALIZATION_LIMIT, SqlEngine
from engine.maintenance.validation import build_validated_record
from engine.storage import HeapFile
from engine.storage.organization import OrganizationMetadata, OrganizationType
from engine.storage.record import RecordValue

from .manifest import (
    DatabaseManifest,
    DatabaseManifestError,
    MANIFEST_FILENAME,
    ManifestIndex,
    ManifestTable,
    encode_manifest,
    managed_path,
    new_manifest,
    read_manifest,
    write_manifest_atomic,
)


class DatabaseSetupError(ValidationError):
    """A managed database cannot be created or safely opened."""


class DatabaseUnavailableError(ValidationError):
    """The owner cannot safely continue after a failed cleanup."""


class Database:
    """Own one manifest, Catalog, runtime registry, and all permanent handles."""

    __slots__ = (
        "_directory",
        "_manifest_path",
        "_manifest",
        "_catalog",
        "_environment",
        "_engine",
        "_storages",
        "_indexes",
        "_paths",
        "_closed",
        "_available",
    )

    def __init__(self) -> None:
        raise TypeError("Use Database.create() or Database.open()")

    @classmethod
    def create(
        cls,
        directory: object,
        *,
        name: str = "database",
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
    ) -> "Database":
        """Create an empty manifest-backed database in an empty directory."""

        root = Path(directory)
        if root.exists():
            if not root.is_dir():
                raise DatabaseSetupError("Database root must be a directory")
            if any(root.iterdir()):
                raise DatabaseSetupError(
                    "Manifest-backed database creation requires an empty directory"
                )
        else:
            root.mkdir(parents=True)
        manifest = new_manifest(name)
        path = root / MANIFEST_FILENAME
        try:
            write_manifest_atomic(path, manifest)
            return cls._assemble(
                root,
                manifest,
                memory_budget_bytes,
                max_open_handles,
                materialization_limit,
            )
        except BaseException:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @classmethod
    def open(
        cls,
        directory: object,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
    ) -> "Database":
        """Open a managed database solely from its strict persisted manifest."""

        root = Path(directory)
        if not root.is_dir():
            raise DatabaseSetupError("Database root does not exist")
        manifest = read_manifest(root / MANIFEST_FILENAME)
        return cls._assemble(
            root,
            manifest,
            memory_budget_bytes,
            max_open_handles,
            materialization_limit,
        )

    @classmethod
    def _assemble(
        cls,
        root: Path,
        manifest: DatabaseManifest,
        memory_budget_bytes: int,
        max_open_handles: int,
        materialization_limit: int,
    ) -> "Database":
        database = object.__new__(cls)
        database._directory = root.resolve()
        database._manifest_path = database._directory / MANIFEST_FILENAME
        database._manifest = manifest
        database._catalog = Catalog()
        database._environment = QueryEnvironment(database._catalog)
        database._storages: dict[str, HeapFile] = {}
        database._indexes = {}
        database._paths: dict[str, Path] = {}
        database._closed = False
        database._available = True
        database._engine = None
        try:
            for table in manifest.tables:
                database._open_table(table)
            database._engine = SqlEngine(
                database._environment,
                memory_budget_bytes=memory_budget_bytes,
                max_open_handles=max_open_handles,
                materialization_limit=materialization_limit,
                ddl_service=database,
            )
        except BaseException as error:
            try:
                database.close()
            except BaseException as cleanup:
                error.add_note(f"Database open cleanup also failed: {cleanup}")
            raise
        return database

    def _open_table(self, table: ManifestTable) -> None:
        table_path = managed_path(self._directory, table.filename)
        if not table_path.is_file():
            raise DatabaseSetupError(f"Missing managed table file: {table.filename}")
        for index in table.indexes:
            if not index.ready:
                raise DatabaseUnavailableError(
                    f"Managed index {index.name!r} is marked incomplete"
                )
            index_path = managed_path(self._directory, index.filename)
            if not index_path.is_file():
                raise DatabaseSetupError(
                    f"Missing managed index file: {index.filename}"
                )

        self._catalog.register_table(table.metadata)
        storage = HeapFile.open(table_path, table.metadata.schema)
        self._storages[table.name] = storage
        self._paths[table.name] = table_path
        self._environment.register_storage(table.name, storage)
        for persisted in table.indexes:
            metadata = persisted.metadata(self._directory)
            self._catalog.register_index(metadata)
            runtime = open_catalog_index(
                self._catalog,
                metadata.name,
                storage,
            )
            self._indexes[metadata.name] = runtime
            self._paths[metadata.name] = managed_path(
                self._directory,
                persisted.filename,
            )
            self._environment.register_index(metadata.name, runtime)

    def _require_available(self) -> None:
        if self._closed:
            raise DatabaseUnavailableError("Database is closed")
        if not self._available:
            raise DatabaseUnavailableError(
                "Database owner is unavailable until it is closed and reopened"
            )

    def _current_manifest(self) -> DatabaseManifest:
        current = read_manifest(self._manifest_path)
        if current != self._manifest:
            raise DatabaseUnavailableError(
                "Database manifest changed outside the active owner"
            )
        return current

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def identity(self) -> str:
        return self._manifest.identity

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def manifest_path(self) -> Path:
        return self._manifest_path

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def environment(self) -> QueryEnvironment:
        return self._environment

    @property
    def engine(self) -> SqlEngine:
        self._require_available()
        return self._engine

    @property
    def closed(self) -> bool:
        return self._closed

    def table_names(self) -> tuple[str, ...]:
        return tuple(table.name for table in self._catalog.list_tables())

    def storage_for(self, table_name: str) -> HeapFile:
        self._require_available()
        return self._environment.storage_for(table_name)

    def index_for(self, index_name: str):
        self._require_available()
        return self._environment.index_for(index_name)

    def path_for(self, logical_name: str) -> Path:
        self._require_available()
        try:
            return self._paths[logical_name]
        except KeyError as error:
            raise KeyError(f"Unknown managed object: {logical_name!r}") from error

    @staticmethod
    def _validate_definition(table: TableMetadata) -> None:
        if not isinstance(table, TableMetadata):
            raise InvalidTypeError("CREATE requires TableMetadata")
        if not table.schema.columns:
            raise ValidationError("CREATE TABLE requires at least one column")
        for column in table.schema:
            if column.data_type not in {DataType.INTEGER, DataType.VARCHAR}:
                raise ValidationError(
                    "SQL CREATE supports only INTEGER and VARCHAR columns"
                )
            if (
                column.data_type is DataType.VARCHAR
                and table.varchar_length(column.name) is None
            ):
                raise ValidationError(
                    f"SQL-created VARCHAR column {column.name!r} needs a length"
                )

        # Validate unchanged physical header geometry before allocating files.
        OrganizationMetadata(
            organization_type=OrganizationType.HEAP,
            schema=table.schema,
        ).serialize()
        if table.primary_key is not None:
            primary = table.schema.column(table.primary_key)
            BPlusFileHeader(
                index_name=f"__pk__{table.name}",
                table_name=table.name,
                key_column=primary.name,
                key_type=primary.data_type,
                clustered=False,
                allow_duplicate_keys=False,
            ).serialize()

    def validate_create(self, table: TableMetadata) -> None:
        """Revalidate predictable CREATE failures without changing state."""

        self._require_available()
        self._validate_definition(table)
        self._current_manifest()
        if self._catalog.has_table(table.name):
            raise DuplicateError(f"Duplicate table name: {table.name!r}")
        primary_index_name = (
            f"__pk__{table.name}" if table.primary_key is not None else None
        )
        if primary_index_name is not None and self._catalog.has_index(
            primary_index_name
        ):
            raise DuplicateError(f"Duplicate index name: {primary_index_name!r}")

        # Exact manifest-size/shape validation is predictable and precedes I/O.
        dummy_table_id = "0" * 32
        dummy_index_id = "1" * 32
        indexes = ()
        if primary_index_name is not None:
            indexes = (
                ManifestIndex(
                    primary_index_name,
                    dummy_index_id,
                    table.name,
                    table.primary_key,
                    IndexType.BPLUS,
                    True,
                    False,
                    f"i_{dummy_index_id}.bpt",
                    True,
                ),
            )
        candidate = replace(
            self._manifest,
            tables=(
                *self._manifest.tables,
                ManifestTable(
                    table.name,
                    dummy_table_id,
                    f"t_{dummy_table_id}.heap",
                    table,
                    indexes,
                ),
            ),
        )
        encode_manifest(candidate)

    def _allocate_identity(
        self,
        prefix: str,
        suffix: str,
        *,
        reserved: frozenset[str] = frozenset(),
    ) -> tuple[str, str, Path]:
        used = {
            table.identity for table in self._manifest.tables
        } | {
            index.identity
            for table in self._manifest.tables
            for index in table.indexes
        }
        for _ in range(128):
            identity = uuid4().hex
            filename = f"{prefix}_{identity}{suffix}"
            path = managed_path(self._directory, filename)
            if identity not in used and identity not in reserved and not path.exists():
                return identity, filename, path
        raise DatabaseSetupError("Could not allocate a unique managed file identity")

    def _rollback_publication(
        self,
        table_name: str,
        index_name: str | None,
        *,
        table_catalog_registered: bool,
        storage_registered: bool,
        index_catalog_registered: bool,
        index_runtime_registered: bool,
    ) -> list[BaseException]:
        failures: list[BaseException] = []
        if index_name is not None and index_runtime_registered:
            try:
                self._environment.unregister_index(index_name)
            except BaseException as error:
                failures.append(error)
        if index_name is not None and index_catalog_registered:
            try:
                self._catalog.unregister_index(index_name)
            except BaseException as error:
                failures.append(error)
        if storage_registered:
            try:
                self._environment.unregister_storage(table_name)
            except BaseException as error:
                failures.append(error)
        if table_catalog_registered:
            try:
                self._catalog.unregister_table(table_name)
            except BaseException as error:
                failures.append(error)
        self._indexes.pop(index_name, None)
        self._storages.pop(table_name, None)
        self._paths.pop(index_name, None)
        self._paths.pop(table_name, None)
        return failures

    def create_table(self, table: TableMetadata) -> CreatedTable:
        """Create, publish, and atomically register one Heap-backed table."""

        self.validate_create(table)
        table_id, table_file, table_path = self._allocate_identity("t", ".heap")
        primary_index_name = (
            f"__pk__{table.name}" if table.primary_key is not None else None
        )
        index_id = index_file = None
        index_path: Path | None = None
        if primary_index_name is not None:
            index_id, index_file, index_path = self._allocate_identity(
                "i",
                ".bpt",
                reserved=frozenset({table_id}),
            )

        persisted_indexes: tuple[ManifestIndex, ...] = ()
        if primary_index_name is not None:
            persisted_indexes = (
                ManifestIndex(
                    primary_index_name,
                    index_id,
                    table.name,
                    table.primary_key,
                    IndexType.BPLUS,
                    True,
                    False,
                    index_file,
                    True,
                ),
            )
        persisted_table = ManifestTable(
            table.name,
            table_id,
            table_file,
            table,
            persisted_indexes,
        )
        next_manifest = replace(
            self._manifest,
            tables=(*self._manifest.tables, persisted_table),
        )
        encode_manifest(next_manifest)

        storage = None
        runtime_index = None
        table_catalog_registered = False
        storage_registered = False
        index_catalog_registered = False
        index_runtime_registered = False
        try:
            storage = HeapFile.create(table_path, table.schema)
            index_metadata = None
            if primary_index_name is not None:
                temporary_catalog = Catalog()
                temporary_catalog.register_table(table)
                index_metadata = IndexMetadata(
                    primary_index_name,
                    table.name,
                    table.primary_key,
                    IndexType.BPLUS,
                    clustered=False,
                    unique=True,
                    file_path=str(index_path),
                )
                temporary_catalog.register_index(index_metadata)
                runtime_index = build_catalog_index(
                    temporary_catalog,
                    primary_index_name,
                    storage,
                )
            storage.flush()
            if runtime_index is not None:
                runtime_index.flush()
                runtime_index.validate_structure()

            self._catalog.register_table(table)
            table_catalog_registered = True
            self._environment.register_storage(table.name, storage)
            storage_registered = True
            if index_metadata is not None:
                self._catalog.register_index(index_metadata)
                index_catalog_registered = True
                self._environment.register_index(index_metadata.name, runtime_index)
                index_runtime_registered = True
            self._storages[table.name] = storage
            self._paths[table.name] = table_path
            if index_metadata is not None:
                self._indexes[index_metadata.name] = runtime_index
                self._paths[index_metadata.name] = index_path
            write_manifest_atomic(self._manifest_path, next_manifest)
            self._manifest = next_manifest
            return CreatedTable(table.name, primary_index_name)
        except BaseException as error:
            cleanup_failures: list[BaseException] = []
            if table_catalog_registered:
                cleanup_failures.extend(
                    self._rollback_publication(
                        table.name,
                        primary_index_name,
                        table_catalog_registered=table_catalog_registered,
                        storage_registered=storage_registered,
                        index_catalog_registered=index_catalog_registered,
                        index_runtime_registered=index_runtime_registered,
                    )
                )
            for handle in (runtime_index, storage):
                if handle is not None:
                    try:
                        handle.close()
                    except BaseException as cleanup:
                        cleanup_failures.append(cleanup)
            for path in (index_path, table_path):
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except BaseException as cleanup:
                        cleanup_failures.append(cleanup)
            if cleanup_failures:
                self._available = False
                for cleanup in cleanup_failures:
                    error.add_note(
                        f"CREATE cleanup failed: {type(cleanup).__name__}: {cleanup}"
                    )
            raise

    def insert(
        self,
        table_name: str,
        values: Sequence[RecordValue],
    ) -> MutationReport:
        """Validated programmatic write using the same SQL maintenance path."""

        self._require_available()
        table = self._catalog.get_table(table_name)
        record = build_validated_record(table, values)
        storage = self._environment.storage_for(table_name)
        indexes = tuple(
            MaintenanceIndex(
                registered.metadata.name,
                registered.metadata.column_name,
                registered.metadata.unique,
                registered.index,
            )
            for registered in self._environment.require_indexes_for(table_name)
        )
        return MutationService().insert(
            table_name=table_name,
            table_metadata=table,
            storage=storage,
            record=record,
            indexes=indexes,
            storage_may_move_rids=False,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        failures: list[BaseException] = []
        engine = self._engine
        if engine is not None:
            try:
                engine.close()
            except BaseException as error:
                failures.append(error)
        for handle in (*self._indexes.values(), *self._storages.values()):
            try:
                handle.close()
            except BaseException as error:
                failures.append(error)
        self._indexes.clear()
        self._storages.clear()
        if failures:
            raise failures[0]

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False


__all__ = [
    "Database",
    "DatabaseManifestError",
    "DatabaseSetupError",
    "DatabaseUnavailableError",
]
