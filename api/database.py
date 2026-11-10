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
the Stage 7 database manifest. Its DDL service publishes SQL-created tables
through the same durable GUI registry. New manifest-backed databases use
``engine.database.Database``.

Tables created from the Files panel (:meth:`Database.create_gui_table`) are the
one addition: their definitions persist in ``gui_tables.json`` (see
:mod:`api.gui_tables`) and are reopened after the declared ones. They are built
with the same public storage constructors and catalog index factories, under
the Stage 8 schema lock of the selected session (the default session when no
client session is supplied).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from engine.catalog import (
    Catalog,
    ColumnConstraint,
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
from engine.query.ast import (
    BoolAnd, BoolNot, BoolOr, BooleanLiteral, ColumnRef, Comparison,
    FloatLiteral, IntegerLiteral, StringLiteral,
)
from engine.maintenance.validation import validate_record
from engine.query.ddl import CreatedTable
from engine.storage import HeapFile, PagedSequentialFile, Record
from engine.spatial.metadata import SpatialMapping, read_mappings
from engine.spatial.geometry import Metric, Point, Polygon
from engine.spatial.index import SpatialIndex
from engine.text import TextIndex, search_text
from engine.text.registry import read_text_registry
from engine.spatial.lifecycle import SpatialMutationService, SpatialTableRuntime
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
    constraints: tuple[ColumnConstraint, ...] = ()

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
class MultimediaSource:
    """One image or audio collection for ``Database.prepare_multimedia``."""

    table: "NewTable"
    rows: Iterable
    id_column: str
    key_column: str
    modality: object                      # engine.multimedia.Modality
    media_directory: Path
    query_files: tuple = ()
    vocabulary_size: int | None = None
    training_ids: tuple | None = None
    ivf_metrics: tuple | None = None      # None: all three metrics
    hnsw_metrics: tuple | None = None     # None: all three metrics
    hnsw_parameters: object | None = None

    def __post_init__(self):
        from engine.multimedia import HnswParameters, Metric
        for name in ("ivf_metrics", "hnsw_metrics"):
            if getattr(self, name) is None:
                object.__setattr__(self, name, tuple(Metric))
        if self.hnsw_parameters is None:
            object.__setattr__(self, "hnsw_parameters", HnswParameters())


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
    name: str | None = None


@dataclass(frozen=True, slots=True)
class NewTable:
    """A GUI table definition, validated by :meth:`Database.create_gui_table`."""

    name: str
    columns: tuple[tuple[str, DataType], ...]
    organization: str = HEAP
    key_column: str | None = None
    indexes: tuple[NewIndex, ...] = ()
    constraints: tuple[ColumnConstraint, ...] = ()


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
        "_spatial_mappings",
        "_spatial_indexes",
        "_text_indexes",
        "_multimedia",
    )

    def __init__(self) -> None:
        raise TypeError("Use Database.open() to open a database")

    @classmethod
    def prepare_text(
        cls, directory, collections, *, companion_tables=(),
        memory_budget_bytes=8 * 1024 * 1024,
    ):
        """Create NEW text data, then publish offline and verify a fresh owner.

        Each collection is (NewTable, rows, id_column, text_column). Each
        companion is (NewTable, rows) and stays outside the text registry.
        Rows may be one-shot iterables. Existing destinations are refused.
        """
        from contextlib import ExitStack
        from uuid import uuid4
        from engine.text import build_spimi, seal_text_collection
        from engine.text.registry import TextRegistration, publish_text_registry
        collections = tuple(collections)
        companion_tables = tuple(companion_tables)
        if not collections:
            raise ValidationError('At least one text collection is required')
        names = [spec.name for spec, *_ in collections]
        names.extend(spec.name for spec, _ in companion_tables)
        if len(set(names)) != len(names):
            raise DuplicateError('Text collections and companion tables must have distinct names')
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=False)
        snapshots = []
        definition = DatabaseDefinition('text')
        with cls.create(definition, root) as database:
            for new_table, rows in companion_tables:
                database.create_gui_table(new_table, rows, origin='prepared')
            for new_table, rows, id_column, text_column in collections:
                database.create_gui_table(new_table, rows, origin='csv', source_filename='text-source.csv')
                table = database._catalog.get_table(new_table.name)
                if not isinstance(database._storages[table.name], HeapFile):
                    raise ValidationError('Text collections require Heap storage')
                snapshots.append((database._catalog, table, database._table_files(database._tables[table.name]),
                                  id_column, text_column))
        registrations = []
        # No live owner/coordinator exists while engine-level publication runs.
        for catalog, table, files, id_column, text_column in snapshots:
            index_directory = 'text_' + uuid4().hex
            with ExitStack() as stack:
                heap = stack.enter_context(HeapFile.open(files.base, table.schema))
                secondary = [stack.enter_context(open_catalog_index(catalog, name, heap))
                             for name, _ in files.indexes]
                build_spimi(root / index_directory, heap, table, collection_id=uuid4().hex,
                            id_column=id_column, text_column=text_column,
                            memory_budget_bytes=memory_budget_bytes)
                index = stack.enter_context(TextIndex.open(root / index_directory, table=table))
                seal_text_collection(heap, index, secondary_indexes=secondary)
                registrations.append(TextRegistration(table.name, text_column, index.collection_id,
                                                       index.generation, index_directory))
        publish_text_registry(root, tuple(registrations))
        with cls.open(definition, root) as database:
            for registration in registrations:
                database._environment.text_for(registration.table).validate()
        return tuple(registrations)

    @classmethod
    def prepare_multimedia(cls, directory, sources):
        """Create NEW image/audio collections, publish offline, verify a fresh owner.

        Each source is a ``MultimediaSource``. Existing destinations are never
        overwritten; a failed preparation stays unpublished for inspection.
        """
        from contextlib import ExitStack
        from uuid import uuid4
        from engine.multimedia.collection import build_collection
        from engine.multimedia.registry import MultimediaRegistration, publish_multimedia_registry
        from engine.multimedia.sealing import seal_multimedia_collection
        root = Path(directory).resolve()
        root.mkdir(parents=True, exist_ok=False)
        definition = DatabaseDefinition("multimedia")
        snapshots = []
        with cls.create(definition, root) as database:
            for source in sources:
                if not isinstance(source, MultimediaSource):
                    raise TypeError("prepare_multimedia expects MultimediaSource items")
                database.create_gui_table(source.table, source.rows, origin="csv",
                                          source_filename="multimedia-source.csv")
                table = database._catalog.get_table(source.table.name)
                if not isinstance(database._storages[table.name], HeapFile):
                    raise ValidationError("Multimedia collections require Heap storage")
                snapshots.append((database._catalog, table,
                                  database._table_files(database._tables[table.name]), source))
        if not snapshots:
            raise ValidationError("At least one multimedia collection is required")
        registrations = []
        # No live owner/coordinator exists while engine-level publication runs.
        for catalog, table, files, source in snapshots:
            name = "mm_" + uuid4().hex
            with ExitStack() as stack:
                heap = stack.enter_context(HeapFile.open(files.base, table.schema))
                secondary = [stack.enter_context(open_catalog_index(catalog, index_name, heap))
                             for index_name, _ in files.indexes]
                collection = stack.enter_context(build_collection(
                    root / name, heap=heap, schema=table.schema, table=table.name,
                    id_column=source.id_column, key_column=source.key_column, modality=source.modality,
                    media_directory=source.media_directory, query_files=source.query_files,
                    collection_id=uuid4().hex, generation=uuid4().hex,
                    vocabulary_size=source.vocabulary_size, training_ids=source.training_ids,
                    ivf_metrics=source.ivf_metrics, hnsw_metrics=source.hnsw_metrics,
                    hnsw_parameters=source.hnsw_parameters))
                seal_multimedia_collection(heap, collection, secondary_indexes=secondary)
                registrations.append(MultimediaRegistration(
                    table.name, source.key_column, source.modality.value, collection.collection_id,
                    collection.generation, name))
        publish_multimedia_registry(root, tuple(registrations))
        with cls.open(definition, root) as database:
            for registration in registrations:
                if database._environment.multimedia_for(registration.table) is None:
                    raise ValidationError("Published multimedia collection did not reopen")
        return tuple(registrations)

    def _open_multimedia(self, root: Path) -> None:
        """Open published multimedia collections; never builds or repairs one."""
        if not (root / "multimedia_tables.json").is_file():
            return          # numpy and the media stack are only needed for Part 4
        from engine.multimedia.collection import MultimediaCollection
        from engine.multimedia.registry import read_multimedia_registry
        for registration in read_multimedia_registry(root):
            if registration.table not in self._tables:
                raise DatabaseSetupError(f"Unknown published multimedia table {registration.table!r}")
            storage = self._storages[registration.table]
            if not isinstance(storage, HeapFile) or not storage.read_only:
                raise DatabaseSetupError("Published multimedia collections require sealed Heap storage")
            collection = MultimediaCollection.open(root / registration.directory,
                                                   collection_id=registration.collection_id,
                                                   generation=registration.generation)
            try:
                if (collection.table_name != registration.table
                        or collection.key_column != registration.column
                        or collection.modality.value != registration.modality):
                    raise DatabaseSetupError("Published multimedia collection does not match its registry")
                collection.require_compatible_storage(storage)
            except BaseException:
                collection.close()
                raise
            self._multimedia[registration.table] = collection
            self._environment.register_multimedia(registration.table, collection)

    def multimedia_collection(self, table: str):
        """The published collection of ``table`` (for media serving), or None."""
        if not self.available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        return self._multimedia.get(table)

    def multimedia_tables(self) -> tuple[str, ...]:
        return tuple(sorted(self._multimedia))

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
            constraints=gui.constraints,
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
        database._spatial_mappings = {}
        database._spatial_indexes = {}
        database._text_indexes = {}
        database._multimedia = {}
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
            mappings = {mapping.table: mapping for mapping in read_mappings(root)}
            for gui in database._gui_tables.values():
                mapping = database._automatic_spatial_mapping(database._gui_definition(gui))
                if mapping is not None:
                    mappings.setdefault(mapping.table, mapping)
            for mapping in mappings.values():
                try:
                    if database._storages[mapping.table].read_only:
                        raise ValidationError("A sealed text Heap cannot register spatial maintenance")
                    mapping.validate_schema(database._catalog.get_table(mapping.table).schema)
                    if database._tables[mapping.table].organization != HEAP:
                        raise ValidationError("Spatial mappings require stable-RID Heap storage")
                except (ValidationError, KeyError) as error:
                    raise DatabaseSetupError(f"Invalid spatial mapping: {error}") from error
                database._spatial_mappings[mapping.table] = mapping
                database._spatial_indexes[mapping.table] = SpatialIndex.open_or_build(
                    database._storages[mapping.table], mapping, root / mapping.index_filename)
                database._environment.register_spatial(
                    mapping.table, database._spatial_indexes[mapping.table])
            # The registry is an immutable association with already published
            # generations. Never rebuild, repair, or silently skip a bad index.
            for registration in read_text_registry(root):
                if registration.table not in database._tables:
                    raise DatabaseSetupError(f"Unknown published text table {registration.table!r}")
                storage = database._storages[registration.table]
                if not isinstance(storage, HeapFile) or not storage.read_only:
                    raise DatabaseSetupError("Published text collections require sealed Heap storage")
                index = TextIndex.open(
                    root / registration.directory,
                    collection_id=registration.collection_id,
                    generation=registration.generation,
                    table=database._catalog.get_table(registration.table),
                )
                try:
                    if index.text_column != registration.column:
                        raise DatabaseSetupError("Published text column does not match registry")
                    index.require_compatible_storage(storage)
                except BaseException:
                    index.close()
                    raise
                database._text_indexes[registration.table] = index
                database._environment.register_text(registration.table, index)
            database._open_multimedia(root)
            database._engine = SqlEngine(
                database._environment,
                mutation_service=SpatialMutationService(database._spatial_indexes),
                ddl_service=database,
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
                    mutation_service=SpatialMutationService(database._spatial_indexes),
                    ddl_service=database,
                    memory_budget_bytes=memory_budget_bytes,
                    max_open_handles=max_open_handles,
                ),
                default_engine=database._engine,
                root=database._directory,
                runtime=SpatialTableRuntime(
                    database._catalog, database._environment,
                    database._storages, database._indexes,
                    database._spatial_indexes, database._spatial_mappings, root,
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
            tuple((mapping.index_name, self._directory / mapping.index_filename)
                  for mapping in (self._spatial_mappings.get(table.name),) if mapping is not None),
        )

    def _open_table(
        self,
        table: TableDefinition,
        create: bool,
        path: Path,
        index_paths: dict[str, Path],
    ) -> None:
        self._catalog.register_table(TableMetadata(table.name, table.schema, table.constraints))
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

    def text_search(self, table: str, column: str, query: str, *, model: str,
                    order: str = "score_desc", limit: int | None = None,
                    use_indexes: bool = True, session=None, consume=None):
        """Typed, read-only query over a published collection, with session locks."""
        if not self.available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        runner = self._coordinator.default_session if session is None else session
        if not isinstance(runner, SqlSession) or runner._owner is not self._coordinator:
            raise ValidationError("Text session belongs to another owner")
        def read():
            index = self._text_indexes.get(table)
            if index is None or index.text_column != column:
                raise ValidationError("No compatible published text index for table/column")
            result = search_text(index, query, model=model, order=order, limit=limit,
                               use_indexes=use_indexes,
                               storage=self._storages[table])
            # Materializers may read source rows while the session still owns
            # its read/metadata locks and participates in shutdown cancellation.
            return result if consume is None else consume(result)
        return runner.run_programmatic_read(table, read)

    def spatial_mapping_for(self, name: str) -> SpatialMapping | None:
        """Return explicit coordinate metadata; this does not imply an index."""
        if not self.available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        with self._coordinator.metadata.read():
            self._catalog.get_table(name)
            return self._spatial_mappings.get(name)

    def _spatial_read(self, name, action, session):
        if not self.available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        runner = self._coordinator.default_session if session is None else session
        if not isinstance(runner, SqlSession) or runner._owner is not self._coordinator:
            raise ValidationError("Spatial session belongs to another owner")
        def read():
            try:
                index = self._spatial_indexes[name]
            except KeyError as error:
                raise ValidationError(f"Table {name!r} has no spatial mapping/index") from error
            return action(index)
        return runner.run_programmatic_read(name, read)

    def spatial_radius(self, name: str, center: Point, radius: float, *,
                       metric=Metric.HAVERSINE, inclusive=False, use_index=True, session=None):
        """Typed E2 engine entry; E3 will expose spatial SQL and HTTP."""
        return self._spatial_read(name, lambda index: index.radius(
            center, radius, metric=metric, inclusive=inclusive, use_index=use_index), session)

    def spatial_knn(self, name: str, center: Point, k: int, *,
                    metric=Metric.HAVERSINE, use_index=True, session=None):
        return self._spatial_read(name, lambda index: index.knn(
            center, k, metric=metric, use_index=use_index), session)

    def spatial_polygon(self, name: str, polygon: Polygon, *, use_index=True, session=None):
        return self._spatial_read(name, lambda index: index.polygon(polygon, use_index=use_index), session)

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
            collection = self._multimedia.get(name)
            if collection is not None:
                def folder_bytes(path):
                    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
                for method, metrics in collection.methods.items():
                    for metric in metrics if method == "HNSW" else [",".join(metrics)]:
                        folder = "ivf" if method == "IVF" else f"hnsw_{metric}"
                        indexes.append(IndexSummary(
                            name=f"{name}_{folder}", column=collection.key_column,
                            index_type=f"{method} ({metric})", unique=False, clustered=False,
                            supports_range=False, entry_count=collection.size,
                            file_bytes=folder_bytes(collection.directory / folder)))
            text = self._text_indexes.get(name)
            if text is not None:
                registration = next(item for item in read_text_registry(self._directory) if item.table == name)
                directory = self._directory / registration.directory
                indexes.append(IndexSummary(
                    name=f'{name}_spimi', column=text.text_column, index_type='SPIMI',
                    unique=False, clustered=False, supports_range=False,
                    entry_count=text.statistics.document_count,
                    file_bytes=sum(path.stat().st_size for path in directory.iterdir() if path.is_file())))
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

    @staticmethod
    def _automatic_spatial_mapping(table: TableDefinition) -> SpatialMapping | None:
        columns = {column.name: column.data_type for column in table.schema}
        if (table.organization == HEAP and columns.get("id") is DataType.INTEGER
                and columns.get("latitud") is DataType.FLOAT
                and columns.get("longitud") is DataType.FLOAT
                and "ubicacion" not in columns):
            return SpatialMapping(table.name)
        return None

    def _sql_spec(self, table: TableMetadata) -> NewTable:
        indexes = (() if table.primary_key is None else
                   (NewIndex(table.primary_key, IndexType.BPLUS, unique=True,
                             name=f"__pk__{table.name}"),))
        return NewTable(table.name,
                        tuple((c.name, c.data_type) for c in table.schema),
                        indexes=indexes, constraints=table.constraints)

    def validate_create(self, table: TableMetadata) -> None:
        if self._closed or not self._available:
            raise TransactionUnavailableError("Database is closed or quarantined")
        self._validated_gui_table(self._sql_spec(table), 0, "empty", None)

    def create_table(self, table: TableMetadata) -> CreatedTable:
        if not self._coordinator.protected_schema_change_active():
            return self._coordinator.default_session.run_schema_change(
                lambda: self.create_table(table))
        self.validate_create(table)
        self._build_gui_table(self._sql_spec(table), (), None, "empty", None)
        indexes = self._catalog.get_indexes(table.name)
        return CreatedTable(table.name, next((i.name for i in indexes if i.unique), None))

    def create_sql_index(self, name: str, table_name: str, column_name: str, *, unique: bool = False):
        """Create and persist a non-clustered B+ index on a GUI-created table."""
        if not self._coordinator.protected_schema_change_active():
            return self._coordinator.default_session.run_schema_change(
                lambda: self.create_sql_index(name, table_name, column_name, unique=unique))
        if table_name not in self._gui_tables:
            raise ValidationError("CREATE INDEX por SQL solo está habilitado para tablas creadas por SQL o el panel Archivos")
        self._storages[table_name].require_writable()
        name = check_identifier(name, "el índice")
        column_name = check_identifier(column_name, "la columna")
        if type(unique) is not bool:
            raise ValidationError("UNIQUE debe ser booleano")
        if self._catalog.has_index(name):
            raise DuplicateError(f"Ya existe un índice llamado {name!r}.")
        table = self._catalog.get_table(table_name)
        table.schema.column(column_name)
        gui = self._gui_tables[table_name]
        identity = new_identity()
        path = self._directory / f"g_{identity}.bpt"
        metadata = IndexMetadata(name, table_name, column_name, IndexType.BPLUS,
                                 clustered=False, unique=unique, file_path=str(path))
        runtime = None
        registered_catalog = False
        try:
            self._catalog.register_index(metadata)
            registered_catalog = True
            runtime = build_catalog_index(self._catalog, name, self._storages[table_name])
            runtime.flush()
            self._environment.register_index(name, runtime)
            self._indexes[name] = runtime
            self._paths[name] = path
            updated_index = GuiIndex(name, identity, column_name, IndexType.BPLUS, unique, False)
            updated_gui = replace(gui, indexes=(*gui.indexes, updated_index))
            self._gui_tables[table_name] = updated_gui
            self._tables[table_name] = self._gui_definition(updated_gui)
            write_registry(self._directory, tuple(self._gui_tables.values()))
            self._coordinator.resources.unregister(table_name)
            self._coordinator.resources.register(self._table_files(self._tables[table_name]))
            return {"index": name, "table": table_name, "column": column_name, "unique": unique}
        except BaseException:
            self._gui_tables[table_name] = gui
            self._tables[table_name] = self._gui_definition(gui)
            if self._environment.catalog.has_index(name):
                try:
                    self._environment.unregister_index(name)
                except Exception:
                    pass
            self._indexes.pop(name, None)
            self._paths.pop(name, None)
            if runtime is not None:
                try: runtime.close()
                except Exception: pass
            if registered_catalog and self._catalog.has_index(name):
                try: self._catalog.unregister_index(name)
                except Exception: pass
            path.unlink(missing_ok=True)
            raise

    def drop_sql_index(self, name: str):
        """Drop a GUI-created index while preserving the table and its rows."""
        if not self._coordinator.protected_schema_change_active():
            return self._coordinator.default_session.run_schema_change(
                lambda: self.drop_sql_index(name))
        if not self._catalog.has_index(name):
            raise ValidationError(f"No existe el índice {name!r}.")
        metadata = self._catalog.get_index(name)
        self._storages[metadata.table_name].require_writable()
        gui = self._gui_tables.get(metadata.table_name)
        if gui is None or not any(index.name == name for index in gui.indexes):
            raise ValidationError("DROP INDEX por SQL solo puede eliminar índices creados dinámicamente")
        if metadata.unique and metadata.column_name == self._catalog.get_table(metadata.table_name).primary_key:
            raise ValidationError("No se puede eliminar el índice que garantiza la clave primaria")
        path = self._paths[name]
        runtime = self._indexes[name]
        updated_gui = replace(gui, indexes=tuple(item for item in gui.indexes if item.name != name))
        # Publish the registry change first. A crash before in-memory cleanup
        # leaves only an orphan physical file, never a registry pointing at a
        # missing index.
        old_tables = self._gui_tables[gui.name]
        self._gui_tables[gui.name] = updated_gui
        try:
            write_registry(self._directory, tuple(self._gui_tables.values()))
        except BaseException:
            self._gui_tables[gui.name] = old_tables
            raise
        self._tables[gui.name] = self._gui_definition(updated_gui)
        self._environment.unregister_index(name)
        runtime.close()
        self._catalog.unregister_index(name)
        self._indexes.pop(name, None)
        self._paths.pop(name, None)
        self._coordinator.resources.unregister(gui.name)
        self._coordinator.resources.register(self._table_files(self._tables[gui.name]))
        path.unlink(missing_ok=True)
        return {"index": name, "table": gui.name}

    def drop_sql_table(self, name: str):
        """Drop a dynamically-created table and all its owned physical files."""
        if not self._coordinator.protected_schema_change_active():
            return self._coordinator.default_session.run_schema_change(
                lambda: self.drop_sql_table(name))
        gui = self._gui_tables.get(name)
        if gui is None:
            raise ValidationError("DROP TABLE por SQL solo está habilitado para tablas creadas por SQL o el panel Archivos")
        self._storages[name].require_writable()
        files = self._table_files(self._tables[name])
        # Registry publication is the durable DROP point; cleanup after this
        # point may leave harmless orphan files if the process stops abruptly.
        old_gui_tables = tuple(self._gui_tables.values())
        self._gui_tables.pop(name)
        try:
            write_registry(self._directory, tuple(self._gui_tables.values()))
        except BaseException:
            self._gui_tables[name] = gui
            # Restore original order if registry publication failed.
            self._gui_tables = {item.name: item for item in old_gui_tables}
            raise
        self._coordinator.resources.unregister(name)
        spatial = self._spatial_indexes.pop(name, None)
        if spatial is not None:
            self._environment.unregister_spatial(name)
            spatial.close()
        self._spatial_mappings.pop(name, None)
        for index in tuple(self._catalog.get_indexes(name)):
            runtime = self._indexes.pop(index.name, None)
            if runtime is not None:
                self._environment.unregister_index(index.name)
                runtime.close()
            self._catalog.unregister_index(index.name)
            self._paths.pop(index.name, None)
        storage = self._storages.pop(name)
        self._environment.unregister_storage(name)
        storage.close()
        self._catalog.unregister_table(name)
        self._tables.pop(name, None)
        self._gui_tables.pop(name, None)
        self._paths.pop(name, None)
        for path in files.physical_files:
            path.unlink(missing_ok=True)
        for _, path in files.auxiliary:
            path.unlink(missing_ok=True)
        return {"table": name}

    @staticmethod
    def _sql_value(expression, record):
        if isinstance(expression, (IntegerLiteral, FloatLiteral, StringLiteral, BooleanLiteral)):
            return expression.value
        if isinstance(expression, ColumnRef):
            return record[expression.name]
        raise ValidationError("UPDATE solo admite valores literales o referencias a columnas")

    @classmethod
    def _sql_predicate(cls, expression, record):
        if expression is None:
            return True
        if isinstance(expression, BoolAnd):
            return bool(cls._sql_predicate(expression.left, record) and cls._sql_predicate(expression.right, record))
        if isinstance(expression, BoolOr):
            return bool(cls._sql_predicate(expression.left, record) or cls._sql_predicate(expression.right, record))
        if isinstance(expression, BoolNot):
            return not cls._sql_predicate(expression.term, record)
        if isinstance(expression, Comparison):
            left, right = cls._sql_value(expression.left, record), cls._sql_value(expression.right, record)
            try:
                return {"=": lambda: left == right, "<>": lambda: left != right,
                        "<": lambda: left < right, "<=": lambda: left <= right,
                        ">": lambda: left > right, ">=": lambda: left >= right}[expression.operator]()
            except (TypeError, KeyError):
                raise ValidationError("Comparación incompatible en UPDATE") from None
        raise ValidationError("Condición WHERE no admitida para UPDATE")

    def update_sql_table(self, statement):
        """Apply a validated UPDATE and rebuild all affected row-ID associations."""
        if not self._coordinator.protected_schema_change_active():
            return self._coordinator.default_session.run_schema_change(
                lambda: self.update_sql_table(statement))
        table_name = statement.table
        table_meta = self._catalog.get_table(table_name)
        storage = self._storages[table_name]
        storage.require_writable()
        old_rows = list(storage.scan())
        if not old_rows:
            return {"table": table_name, "affected_rows": 0}
        column_positions = {column.name: i for i, column in enumerate(table_meta.schema)}
        assignments = []
        for assignment in statement.assignments:
            if assignment.column not in column_positions:
                raise ValidationError(f"Columna desconocida {assignment.column!r}")
            assignments.append((column_positions[assignment.column], assignment.column, assignment.value))
        new_records = []
        affected = 0
        for _, record in old_rows:
            values = list(record.values)
            if self._sql_predicate(statement.where, record):
                affected += 1
                for position, _, expression in assignments:
                    values[position] = self._sql_value(expression, record)
            new_record = Record(table_meta.schema, values)
            validate_record(table_meta, new_record)
            new_records.append(new_record)
        if affected == 0:
            return {"table": table_name, "affected_rows": 0}
        # Check every declared unique index against the complete post-update image.
        for index in self._catalog.get_indexes(table_name):
            if index.unique:
                seen = set()
                for record in new_records:
                    key = record[index.column_name]
                    if key in seen:
                        raise DuplicateError(f"UPDATE violaría la unicidad del índice {index.name!r}")
                    seen.add(key)
        original_records = [record for _, record in old_rows]
        try:
            for rid, _ in old_rows:
                storage.delete(rid)
            for record in new_records:
                storage.insert(record)
            for index in self._catalog.get_indexes(table_name):
                self._indexes[index.name].rebuild()
                self._indexes[index.name].flush()
            if table_name in self._spatial_indexes:
                self._spatial_indexes[table_name].rebuild()
            storage.flush()
        except BaseException as operation_error:
            try:
                for rid, _ in list(storage.scan()):
                    storage.delete(rid)
                for record in original_records:
                    storage.insert(record)
                for index in self._catalog.get_indexes(table_name):
                    self._indexes[index.name].rebuild()
                    self._indexes[index.name].flush()
                if table_name in self._spatial_indexes:
                    self._spatial_indexes[table_name].rebuild()
                storage.flush()
            except BaseException as restore_error:
                self._available = False
                operation_error.add_note(f"Restauración de UPDATE incompleta: {restore_error}")
            raise
        return {"table": table_name, "affected_rows": affected}

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
        if name in self._storages:
            self._storages[name].require_writable()
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
            base = index.name or f"{name}_{index.column}_{suffix}"
            if index.name is not None and index.name in taken:
                raise DuplicateError(f"Ya existe un índice llamado {index.name!r}.")
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
        TableMetadata(name, Schema([Column(n, t) for n, t in columns]), spec.constraints)
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
            constraints=spec.constraints,
        )

    def _build_gui_table(
        self,
        spec: NewTable,
        rows: Sequence[Sequence[object]],
        lines: Sequence[int] | None,
        origin: str,
        source_filename: str | None,
    ) -> None:
        gui = self._validated_gui_table(spec, len(rows) if isinstance(rows, Sequence) else 0,
                                        origin, source_filename)
        definition = self._gui_definition(gui)
        mapping = self._automatic_spatial_mapping(definition)
        schema = definition.schema
        table_path = self._directory / gui.filename
        index_paths = {index.name: self._directory / index.filename for index in gui.indexes}
        created_files = [table_path, *index_paths.values()]
        if mapping is not None:
            created_files.append(self._directory / mapping.index_filename)
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
            from itertools import repeat
            ordered = zip(lines if lines is not None else repeat(None), rows)
            if gui.organization == SEQUENTIAL:
                # Loading in key order is the usual bulk load; the file itself
                # still places every record by its key.
                position = [column.name for column in schema].index(gui.key_column)
                ordered = sorted(ordered, key=lambda pair: pair[1][position])
            loaded_rows = 0
            for line, values in ordered:
                try:
                    storage.insert(Record(schema, list(values)))
                    loaded_rows += 1
                except ValidationError as error:
                    raise CsvError(
                        f"El motor rechazó la fila: {_message(error)}", line=line,
                    ) from None

            gui = replace(gui, loaded_rows=loaded_rows)
            # Build every index against a private Catalog first, so the live
            # Catalog never holds a half-built table.
            staging = Catalog()
            staging.register_table(TableMetadata(gui.name, schema, gui.constraints))
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

            self._catalog.register_table(TableMetadata(gui.name, schema, gui.constraints))
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
            if mapping is not None:
                self._spatial_mappings[gui.name] = mapping
                published["spatial"] = True
                self._spatial_indexes[gui.name] = SpatialIndex.open_or_build(
                    storage, mapping, self._directory / mapping.index_filename)
                self._environment.register_spatial(gui.name, self._spatial_indexes[gui.name])
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

        if published.get("spatial"):
            attempt(lambda: self._environment.unregister_spatial(name))
            spatial = self._spatial_indexes.pop(name, None)
            self._spatial_mappings.pop(name, None)
            if spatial is not None:
                attempt(spatial.close)
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
        for handle in list(getattr(self, "_multimedia", {}).values()) + list(self._text_indexes.values()) + list(self._spatial_indexes.values()) + list(self._indexes.values()) + list(self._storages.values()):
            try:
                handle.close()
            except BaseException as error:  # noqa: BLE001 - reported below
                failures.append(error)
        self._indexes.clear()
        self._spatial_indexes.clear()
        self._text_indexes.clear()
        if hasattr(self, "_multimedia"):
            self._multimedia.clear()
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
