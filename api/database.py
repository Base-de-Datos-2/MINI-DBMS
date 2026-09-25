"""Open a declared database and own every permanent file handle it needs.

The engine deliberately borrows storage and index handles: a
``QueryEnvironment`` never opens, closes, builds or mutates them. Something
therefore has to own them for as long as the server runs, and this module is
that owner. It opens or creates files **only** through the engine's public
constructors and catalog index factories; it contains no storage, indexing,
planning or execution logic of its own.

This is the explicit legacy, definition-driven open mode retained for the
Stage 9 demo. Tables are declared in Python: :meth:`Database.create` builds and
seeds them once, offline, while :meth:`Database.open` reopens only the declared
files and refuses a missing or partial directory. It neither infers nor writes
the Stage 7 database manifest, and its ``SqlEngine`` intentionally has no DDL
service, so SQL CREATE is rejected. New manifest-backed databases use
``engine.database.Database``.

Tables created from the Files panel (:meth:`Database.create_gui_table`) are the
one addition: their definitions persist in ``gui_tables.json`` (see
:mod:`api.gui_tables`) and are reopened after the declared ones. They are built
with the same public storage constructors and catalog index factories, under
the Stage 8 schema lock of the default session.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import DuplicateError, ValidationError
from engine.indexes import build_catalog_index, open_catalog_index
from engine.operators.context import DEFAULT_BUDGET_BYTES, DEFAULT_MAX_OPEN_HANDLES
from engine.query import QueryEnvironment, SqlEngine
from engine.storage import HeapFile, PagedSequentialFile, Record
from engine.transactions.ownership import DirectoryLease, claim_directory
from engine.transactions.resources import TableFiles
from engine.transactions.session import SessionCoordinator, SqlSession
from engine.transactions.errors import TransactionUnavailableError
from engine.transactions.runtime import TableRuntime
from engine.transactions.undo import UndoLimits, UndoStore

from .gui_tables import (
    GuiIndex,
    GuiTable,
    RegistryError,
    new_identity,
    read_registry,
    write_registry,
)
from .table_import import MAX_INDEXES, CsvError, DefinitionError, check_identifier


class DatabaseSetupError(ValidationError):
    """The declared database files are missing or incomplete."""


HEAP = "HEAP"
SEQUENTIAL = "SEQUENTIAL"

_TABLE_SUFFIX = {HEAP: ".heap", SEQUENTIAL: ".seq"}
_INDEX_SUFFIX = {IndexType.BPLUS: ".bpt", IndexType.EXTENDIBLE_HASH: ".hsh"}


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    """One single-column index declared over a table."""

    name: str
    column: str
    index_type: IndexType
    unique: bool = False
    clustered: bool = False


@dataclass(frozen=True, slots=True)
class TableDefinition:
    """One table: its schema, physical organization, indexes and seed rows.

    ``rows`` is only consulted when the table file does not exist yet. It is a
    callable so a large seed is generated lazily and streamed into storage.
    """

    name: str
    schema: Schema
    organization: str = HEAP
    key_column: str | None = None
    indexes: tuple[IndexDefinition, ...] = ()
    rows: Callable[[], Iterable[Sequence[object]]] | None = None

    def __post_init__(self) -> None:
        if self.organization not in _TABLE_SUFFIX:
            raise ValidationError(
                f"Table {self.name!r} organization must be HEAP or SEQUENTIAL"
            )
        if self.organization == SEQUENTIAL and self.key_column is None:
            raise ValidationError(
                f"Sequential table {self.name!r} needs a key column"
            )
        for index in self.indexes:
            if index.clustered and (
                self.organization != SEQUENTIAL
                or index.column != self.key_column
                or index.index_type is not IndexType.BPLUS
            ):
                raise ValidationError(
                    f"Clustered index {index.name!r} must be a B+ index on the "
                    f"key column of a sequential table"
                )


@dataclass(frozen=True, slots=True)
class DatabaseDefinition:
    """A named set of tables the server opens as one database."""

    name: str
    tables: tuple[TableDefinition, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class IndexSummary:
    """Structure the Files panel shows for one index."""

    name: str
    column: str
    index_type: str
    unique: bool
    clustered: bool
    supports_range: bool
    entry_count: int | None
    file_bytes: int


@dataclass(frozen=True, slots=True)
class TableSummary:
    """Structure the Files panel shows for one table."""

    name: str
    organization: str
    key_column: str | None
    columns: tuple[tuple[str, str], ...]
    row_count: int
    data_pages: int
    file_bytes: int
    indexes: tuple[IndexSummary, ...]
    #: ``demo`` for declared fixtures, ``csv`` or ``empty`` for GUI tables.
    origin: str = "demo"
    source_filename: str | None = None


@dataclass(frozen=True, slots=True)
class NewIndex:
    """One index requested for a GUI table; its name is generated."""

    column: str
    index_type: IndexType
    unique: bool = False


@dataclass(frozen=True, slots=True)
class NewTable:
    """A GUI table definition, validated by :meth:`Database.create_gui_table`."""

    name: str
    columns: tuple[tuple[str, DataType], ...]
    organization: str = HEAP
    key_column: str | None = None
    indexes: tuple[NewIndex, ...] = ()


class Database:
    """Own the storages and indexes of one declared database.

    Instances come from :meth:`open`. Closing releases every index before the
    storage it resolves against, and attempts every release even when one
    fails.
    """

    __slots__ = (
        "_definition",
        "_directory",
        "_catalog",
        "_environment",
        "_engine",
        "_storages",
        "_indexes",
        "_paths",
        "_closed",
        "_available",
        "_coordinator",
        "_owner_lease",
        "_tables",
        "_gui_tables",
    )

    def __init__(self) -> None:
        raise TypeError("Use Database.open() to open a database")

    @classmethod
    def create(
        cls,
        definition: DatabaseDefinition,
        directory: object,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        undo_limits: UndoLimits = UndoLimits(),
    ) -> "Database":
        """Create, seed and index every declared table in an empty location."""

        if not isinstance(definition, DatabaseDefinition):
            raise TypeError("definition must be a DatabaseDefinition")
        root = Path(directory).resolve()
        lease = claim_directory(root)
        try:
            root.mkdir(parents=True, exist_ok=True)
            UndoStore.require_clean(root)
            existing = [path.name for path in cls._declared_paths(definition, root)
                        if path.exists()]
            if read_registry(root):
                existing.append("gui_tables.json")
            if existing:
                raise DatabaseSetupError(
                    f"{root} already holds database files ({', '.join(existing)}); "
                    "reset it explicitly instead of creating over them"
                )
            return cls._assemble(
                definition, root, True, memory_budget_bytes, max_open_handles, lease,
                undo_limits, (),
            )
        except BaseException:
            lease.release()
            raise

    @classmethod
    def open(
        cls,
        definition: DatabaseDefinition,
        directory: object,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        undo_limits: UndoLimits = UndoLimits(),
    ) -> "Database":
        """Reopen an existing database; never create, seed or rebuild files."""

        if not isinstance(definition, DatabaseDefinition):
            raise TypeError("definition must be a DatabaseDefinition")
        root = Path(directory).resolve()
        lease = claim_directory(root)
        try:
            UndoStore.require_clean(root)
            missing = [path.name for path in cls._declared_paths(definition, root)
                       if not path.is_file()]
            if missing:
                raise DatabaseSetupError(
                    f"{root} is not a prepared database: missing {', '.join(missing)}"
                )
            try:
                gui_tables = read_registry(root)
            except RegistryError as error:
                raise DatabaseSetupError(str(error)) from None
            declared = {table.name for table in definition.tables}
            for gui in gui_tables:
                if gui.name in declared:
                    raise DatabaseSetupError(
                        f"gui_tables.json redeclares the fixture table {gui.name!r}"
                    )
                absent = [name for name in cls._gui_filenames(gui)
                          if not (root / name).is_file()]
                if absent:
                    raise DatabaseSetupError(
                        f"GUI table {gui.name!r} is missing {', '.join(absent)}"
                    )
            return cls._assemble(
                definition, root, False, memory_budget_bytes, max_open_handles, lease,
                undo_limits, gui_tables,
            )
        except BaseException:
            lease.release()
            raise

    @staticmethod
    def _declared_paths(definition: DatabaseDefinition, root: Path) -> list[Path]:
        paths = []
        for table in definition.tables:
            paths.append(root / f"{table.name}{_TABLE_SUFFIX[table.organization]}")
            for index in table.indexes:
                paths.append(root / f"{index.name}{_INDEX_SUFFIX[index.index_type]}")
        return paths

    @staticmethod
    def _gui_filenames(gui: GuiTable) -> list[str]:
        return [gui.filename, *(index.filename for index in gui.indexes)]

    @staticmethod
    def _gui_definition(gui: GuiTable) -> TableDefinition:
        return TableDefinition(
            name=gui.name,
            schema=Schema([Column(name, data_type) for name, data_type in gui.columns]),
            organization=gui.organization,
            key_column=gui.key_column,
            indexes=tuple(
                IndexDefinition(
                    index.name, index.column, index.index_type,
                    unique=index.unique, clustered=index.clustered,
                )
                for index in gui.indexes
            ),
        )

    @classmethod
    def _assemble(
        cls,
        definition: DatabaseDefinition,
        root: Path,
        create: bool,
        memory_budget_bytes: int,
        max_open_handles: int,
        lease: DirectoryLease,
        undo_limits: UndoLimits,
        gui_tables: tuple[GuiTable, ...],
    ) -> "Database":
        if not isinstance(definition, DatabaseDefinition):
            raise TypeError("definition must be a DatabaseDefinition")
        database = object.__new__(cls)
        database._definition = definition
        database._directory = root
        database._catalog = Catalog()
        database._environment = QueryEnvironment(database._catalog)
        database._storages = {}
        database._indexes = {}
        database._paths = {}
        database._closed = False
        database._available = True
        database._coordinator = None
        database._owner_lease = lease
        database._tables = {}
        database._gui_tables = {}
        try:
            for table in definition.tables:
                database._open_table(
                    table,
                    create,
                    root / f"{table.name}{_TABLE_SUFFIX[table.organization]}",
                    {
                        index.name: root / f"{index.name}{_INDEX_SUFFIX[index.index_type]}"
                        for index in table.indexes
                    },
                )
            for gui in gui_tables:
                database._open_table(
                    cls._gui_definition(gui),
                    False,
                    root / gui.filename,
                    {index.name: root / index.filename for index in gui.indexes},
                )
                database._gui_tables[gui.name] = gui
            database._engine = SqlEngine(
                database._environment,
                memory_budget_bytes=memory_budget_bytes,
                max_open_handles=max_open_handles,
            )
            database._coordinator = SessionCoordinator(
                database_identity=str(root),
                environment=database._environment,
                table_files=tuple(
                    database._table_files(table) for table in database._tables.values()
                ),
                engine_factory=lambda: SqlEngine(
                    database._environment,
                    memory_budget_bytes=memory_budget_bytes,
                    max_open_handles=max_open_handles,
                ),
                default_engine=database._engine,
                root=database._directory,
                runtime=TableRuntime(
                    database._catalog, database._environment,
                    database._storages, database._indexes,
                ),
                quarantine_owner=lambda: setattr(database, "_available", False),
                undo_limits=undo_limits,
            )
        except BaseException:
            database.close()
            raise
        return database

    def _table_files(self, table: TableDefinition) -> TableFiles:
        gui = self._gui_tables.get(table.name)
        return TableFiles(
            table.name,
            table.name if gui is None else gui.identity,
            self._paths[table.name],
            tuple((index.name, self._paths[index.name]) for index in table.indexes),
        )

    def _open_table(
        self,
        table: TableDefinition,
        create: bool,
        path: Path,
        index_paths: dict[str, Path],
    ) -> None:
        self._catalog.register_table(TableMetadata(table.name, table.schema))
        created = create
        if table.organization == HEAP:
            storage = (
                HeapFile.create(path, table.schema)
                if created
                else HeapFile.open(path, table.schema)
            )
        else:
            # A clustered B+ index must share the file's duplicate policy, so a
            # unique clustered key makes the sequential file reject duplicates.
            unique_key = any(
                index.clustered and index.unique for index in table.indexes
            )
            storage = (
                PagedSequentialFile.create(
                    path,
                    table.schema,
                    table.key_column,
                    allow_duplicate_keys=not unique_key,
                )
                if created
                else PagedSequentialFile.open(path, table.schema)
            )
        self._storages[table.name] = storage
        self._paths[table.name] = path
        self._tables[table.name] = table
        self._environment.register_storage(table.name, storage)
        if created and table.rows is not None:
            for values in table.rows():
                storage.insert(Record(table.schema, list(values)))

        for index in table.indexes:
            index_path = index_paths[index.name]
            metadata = IndexMetadata(
                index.name,
                table.name,
                index.column,
                index.index_type,
                clustered=index.clustered,
                unique=index.unique,
                file_path=str(index_path),
            )
            self._catalog.register_index(metadata)
            # A new table's index is built from its seeded rows; an existing
            # index is reopened, and the adapter verifies it still covers storage.
            runtime = (
                build_catalog_index(self._catalog, index.name, storage)
                if created
                else open_catalog_index(self._catalog, index.name, storage)
            )
            self._indexes[index.name] = runtime
            self._paths[index.name] = index_path
            self._environment.register_index(index.name, runtime)

    @property
    def name(self) -> str:
        """Return the declared database name."""

        return self._definition.name

    @property
    def directory(self) -> Path:
        """Return the directory holding every table and index file."""

        return self._directory

    @property
    def catalog(self) -> Catalog:
        """Return the in-memory catalog describing the open database."""

        return self._catalog

    @property
    def engine(self) -> SqlEngine:
        """Return the single-session SQL engine over this database."""
        if not self._available:
            raise TransactionUnavailableError("Database owner is quarantined")
        return self._engine

    @property
    def session_coordinator(self) -> SessionCoordinator:
        return self._coordinator

    def open_session(self) -> SqlSession:
        """Open an independent transaction-aware SQL session."""

        if self._closed or not self._available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        return self._coordinator.open_session()

    @property
    def available(self) -> bool:
        """Report whether the owner can still accept work (not quarantined)."""

        return not self._closed and self._available

    @property
    def closed(self) -> bool:
        """Report whether every handle has been released."""

        return self._closed

    def table_names(self) -> tuple[str, ...]:
        """Return the declared tables, then the GUI tables in creation order."""

        with self._coordinator.metadata.read():
            return tuple(self._tables)

    def table_name_for_identity(self, identity: str) -> str:
        """Map a lock-resource identity back to its table name, never a path.

        Declared fixtures use their name as identity; GUI tables use the
        opaque identity of their files. Reads no metadata gate, so session
        status stays available while a GUI CREATE holds it.
        """

        for gui in tuple(self._gui_tables.values()):
            if gui.identity == identity:
                return gui.name
        return identity

    def resource_names(self, resources) -> list[str]:
        """Table names behind engine resource labels (``table:<id>``, ``<id>``)."""

        names = set()
        for resource in resources:
            label = resource.removeprefix("table:")
            if label != "schema":
                names.add(self.table_name_for_identity(label))
        return sorted(names)

    def describe_table(self, name: str) -> TableSummary:
        """Summarize one table and its indexes for the Files panel."""

        with self._coordinator.metadata.read():
            metadata = self._catalog.get_table(name)
            definition = self._tables[name]
            gui = self._gui_tables.get(name)
            storage = self._storages[name]
            indexes = []
            # Catalog.get_indexes returns only this table's definitions.
            for index_metadata in self._catalog.get_indexes(name):
                runtime = self._indexes[index_metadata.name]
                entry_count = getattr(runtime, "entry_count", None)
                indexes.append(
                    IndexSummary(
                        name=index_metadata.name,
                        column=index_metadata.column_name,
                        index_type=index_metadata.index_type.value,
                        unique=index_metadata.unique,
                        clustered=index_metadata.clustered,
                        supports_range=index_metadata.supports_range,
                        entry_count=entry_count if isinstance(entry_count, int) else None,
                        file_bytes=_file_bytes(self._paths[index_metadata.name]),
                    )
                )
            return TableSummary(
                name=metadata.name,
                organization=definition.organization,
                key_column=definition.key_column,
                columns=tuple(
                    (column.name, column.data_type.value) for column in metadata.schema
                ),
                row_count=storage.record_count,
                data_pages=storage.data_page_count,
                file_bytes=_file_bytes(self._paths[name]),
                indexes=tuple(indexes),
                origin="demo" if gui is None else gui.origin,
                source_filename=None if gui is None else gui.source_filename,
            )

    def create_gui_table(
        self,
        spec: NewTable,
        rows: Sequence[Sequence[object]] = (),
        *,
        lines: Sequence[int] | None = None,
        origin: str = "empty",
        source_filename: str | None = None,
        session: SqlSession | None = None,
    ) -> TableSummary:
        """Create, load and index one Files-panel table, then publish it.

        It runs as standalone DDL of ``session`` (the default session when
        omitted), so the Stage 8 schema lock and metadata gate exclude every
        statement while files are built.
        Rows go through the chosen storage and each index is then built from
        that storage, exactly as for the declared fixtures. The table becomes
        durable only when ``gui_tables.json`` is atomically rewritten; every
        earlier failure unregisters it and deletes the files it created.
        ``lines`` maps each row to its CSV line for error messages.
        """

        if self._closed or not self._available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        if lines is not None and len(lines) != len(rows):
            raise ValueError("lines must align with rows")
        runner = self._coordinator.default_session if session is None else session
        runner.run_schema_change(
            lambda: self._build_gui_table(spec, rows, lines, origin, source_filename)
        )
        return self.describe_table(spec.name)

    def _validated_gui_table(
        self, spec: NewTable, loaded_rows: int, origin: str, source_filename: str | None,
    ) -> GuiTable:
        name = check_identifier(spec.name, "la tabla")
        if self._catalog.has_table(name):
            raise DuplicateError(f"Ya existe una tabla llamada {name!r}.")
        if not spec.columns:
            raise DefinitionError("La tabla necesita al menos una columna.")
        columns = []
        for column_name, data_type in spec.columns:
            check_identifier(column_name, "columna")
            if not isinstance(data_type, DataType):
                raise DefinitionError(f"Tipo inválido para la columna {column_name!r}.")
            if any(column_name == seen for seen, _ in columns):
                raise DefinitionError(f"La columna {column_name!r} está repetida.")
            columns.append((column_name, data_type))
        column_names = {column_name for column_name, _ in columns}

        if spec.organization == SEQUENTIAL:
            if spec.key_column not in column_names:
                raise DefinitionError(
                    "Un Paged Sequential File necesita una columna clave de la tabla."
                )
        elif spec.organization == HEAP:
            if spec.key_column is not None:
                raise DefinitionError("La columna clave solo aplica a Paged Sequential File.")
        else:
            raise DefinitionError("La organización debe ser HEAP o SEQUENTIAL.")

        if len(spec.indexes) > MAX_INDEXES:
            raise DefinitionError(f"Se admiten como máximo {MAX_INDEXES} índices por tabla.")
        indexes: list[GuiIndex] = []
        requested: set[tuple[str, IndexType]] = set()
        taken = {metadata.name for metadata in self._catalog.list_indexes()}
        for index in spec.indexes:
            if index.column not in column_names:
                raise DefinitionError(f"El índice usa la columna inexistente {index.column!r}.")
            if (index.column, index.index_type) in requested:
                raise DefinitionError(
                    f"Hay dos índices del mismo tipo sobre {index.column!r}."
                )
            requested.add((index.column, index.index_type))
            clustered = False
            if spec.organization == SEQUENTIAL:
                if index.index_type is not IndexType.BPLUS or index.column != spec.key_column:
                    raise DefinitionError(
                        "Un Paged Sequential File solo admite el índice B+ clustered "
                        "sobre su columna clave; Hash extensible y los B+ "
                        "unclustered requieren Heap File."
                    )
                clustered = True
            suffix = "bplus" if index.index_type is IndexType.BPLUS else "hash"
            base = f"{name}_{index.column}_{suffix}"
            index_name, counter = base, 2
            while index_name in taken:
                index_name, counter = f"{base}_{counter}", counter + 1
            taken.add(index_name)
            indexes.append(
                GuiIndex(
                    index_name, new_identity(), index.column, index.index_type,
                    unique=index.unique, clustered=clustered,
                )
            )
        return GuiTable(
            name=name,
            identity=new_identity(),
            organization=spec.organization,
            key_column=spec.key_column,
            columns=tuple(columns),
            indexes=tuple(indexes),
            origin=origin,
            source_filename=source_filename,
            loaded_rows=loaded_rows,
        )

    def _build_gui_table(
        self,
        spec: NewTable,
        rows: Sequence[Sequence[object]],
        lines: Sequence[int] | None,
        origin: str,
        source_filename: str | None,
    ) -> None:
        gui = self._validated_gui_table(spec, len(rows), origin, source_filename)
        definition = self._gui_definition(gui)
        schema = definition.schema
        table_path = self._directory / gui.filename
        index_paths = {index.name: self._directory / index.filename for index in gui.indexes}
        created_files = [table_path, *index_paths.values()]
        if any(path.exists() for path in created_files):
            raise DatabaseSetupError("A fresh GUI file identity already exists on disk")

        storage = None
        runtimes: dict[str, object] = {}
        catalog_indexes: list[str] = []
        environment_indexes: list[str] = []
        published: dict[str, bool] = {}
        try:
            if gui.organization == HEAP:
                storage = HeapFile.create(table_path, schema)
            else:
                storage = PagedSequentialFile.create(
                    table_path, schema, gui.key_column,
                    allow_duplicate_keys=not any(
                        index.clustered and index.unique for index in gui.indexes
                    ),
                )
            ordered = list(zip(lines if lines is not None else [None] * len(rows), rows))
            if gui.organization == SEQUENTIAL:
                # Loading in key order is the usual bulk load; the file itself
                # still places every record by its key.
                position = [column.name for column in schema].index(gui.key_column)
                ordered.sort(key=lambda pair: pair[1][position])
            for line, values in ordered:
                try:
                    storage.insert(Record(schema, list(values)))
                except ValidationError as error:
                    raise CsvError(
                        f"El motor rechazó la fila: {_message(error)}", line=line,
                    ) from None

            # Build every index against a private Catalog first, so the live
            # Catalog never holds a half-built table.
            staging = Catalog()
            staging.register_table(TableMetadata(gui.name, schema))
            index_metadata = {}
            for index in definition.indexes:
                metadata = IndexMetadata(
                    index.name, gui.name, index.column, index.index_type,
                    clustered=index.clustered, unique=index.unique,
                    file_path=str(index_paths[index.name]),
                )
                staging.register_index(metadata)
                index_metadata[index.name] = metadata
                try:
                    runtimes[index.name] = build_catalog_index(staging, index.name, storage)
                except ValidationError as error:
                    raise DefinitionError(
                        f"No se pudo construir el índice {index.name!r}: {_message(error)}"
                    ) from None
            storage.flush()
            for runtime in runtimes.values():
                runtime.flush()

            self._catalog.register_table(TableMetadata(gui.name, schema))
            published["catalog"] = True
            self._environment.register_storage(gui.name, storage)
            published["storage"] = True
            self._storages[gui.name] = storage
            self._paths[gui.name] = table_path
            self._tables[gui.name] = definition
            self._gui_tables[gui.name] = gui
            for index in definition.indexes:
                self._catalog.register_index(index_metadata[index.name])
                catalog_indexes.append(index.name)
                self._environment.register_index(index.name, runtimes[index.name])
                environment_indexes.append(index.name)
                self._indexes[index.name] = runtimes[index.name]
                self._paths[index.name] = index_paths[index.name]
            self._coordinator.resources.register(self._table_files(definition))
            published["resource"] = True
            write_registry(self._directory, tuple(self._gui_tables.values()))
        except BaseException as error:
            failures = self._unpublish_gui_table(
                gui.name, catalog_indexes, environment_indexes, published,
                storage, runtimes, created_files,
            )
            if failures:
                # Shared state could not be restored: stop accepting work.
                self._available = False
                for failure in failures:
                    error.add_note(
                        f"GUI CREATE cleanup failed: {type(failure).__name__}: {failure}"
                    )
            raise

    def _unpublish_gui_table(
        self, name, catalog_indexes, environment_indexes, published,
        storage, runtimes, created_files,
    ) -> list[BaseException]:
        failures: list[BaseException] = []

        def attempt(action) -> None:
            try:
                action()
            except BaseException as failure:  # noqa: BLE001 - reported by caller
                failures.append(failure)

        if published.get("resource"):
            attempt(lambda: self._coordinator.resources.unregister(name))
        for index_name in reversed(environment_indexes):
            attempt(lambda index_name=index_name: self._environment.unregister_index(index_name))
        for index_name in reversed(catalog_indexes):
            attempt(lambda index_name=index_name: self._catalog.unregister_index(index_name))
            self._indexes.pop(index_name, None)
            self._paths.pop(index_name, None)
        if published.get("storage"):
            attempt(lambda: self._environment.unregister_storage(name))
        if published.get("catalog"):
            attempt(lambda: self._catalog.unregister_table(name))
        for registry in (self._storages, self._paths, self._tables, self._gui_tables):
            registry.pop(name, None)
        for handle in (*runtimes.values(), storage):
            if handle is not None:
                attempt(handle.close)
        for path in created_files:
            attempt(lambda path=path: path.unlink(missing_ok=True))
        return failures

    def close(self) -> None:
        """Release every index, then every storage; safe to call twice."""

        if self._closed:
            return
        coordinator = self._coordinator
        if coordinator is not None:
            coordinator.close()
        self._close_handles()

    def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """Cooperatively cancel sessions before releasing shared handles."""

        if self._closed:
            return
        coordinator = self._coordinator
        if coordinator is not None:
            coordinator.shutdown(timeout_seconds=timeout_seconds)
        self._close_handles()

    def _close_handles(self) -> None:
        self._closed = True
        failures: list[BaseException] = []
        engine = getattr(self, "_engine", None)
        if engine is not None:
            try:
                engine.close()
            except BaseException as error:  # noqa: BLE001 - reported below
                failures.append(error)
        for handle in list(self._indexes.values()) + list(self._storages.values()):
            try:
                handle.close()
            except BaseException as error:  # noqa: BLE001 - reported below
                failures.append(error)
        self._indexes.clear()
        self._storages.clear()
        self._owner_lease.release()
        if failures:
            raise failures[0]

    def __enter__(self) -> "Database":
        """Return this database for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release every handle on every exit path."""

        self.close()


def _message(error: BaseException) -> str:
    """Return an engine error message without Python's KeyError quoting."""

    if isinstance(error, KeyError) and error.args:
        return str(error.args[0])
    return str(error)


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0
