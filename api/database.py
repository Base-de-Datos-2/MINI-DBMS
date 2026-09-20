"""Open a declared database and own every permanent file handle it needs.

The engine deliberately borrows storage and index handles: a
``QueryEnvironment`` never opens, closes, builds or mutates them. Something
therefore has to own them for as long as the server runs, and this module is
that owner. It opens or creates files **only** through the engine's public
constructors and catalog index factories; it contains no storage, indexing,
planning or execution logic of its own.

The currently executable Stage 7 baseline has no ``CREATE TABLE``, and the
engine ``Catalog`` lives in memory, so tables are declared in Python.
:meth:`Database.create` builds and seeds the declared files once, offline;
:meth:`Database.open` only reopens files that already exist and refuses a
missing or partial directory. Data therefore survives a server restart without
inventing a catalog format, and a page refresh or a query never reseeds
anything. Task 7.31 freezes a future engine-level manifest owner; this adapter
must delegate to that owner when Tasks 7.32–7.40 implement the extension.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from engine.catalog import Catalog, IndexMetadata, IndexType, Schema, TableMetadata
from engine.errors import ValidationError
from engine.indexes import build_catalog_index, open_catalog_index
from engine.operators.context import DEFAULT_BUDGET_BYTES, DEFAULT_MAX_OPEN_HANDLES
from engine.query import QueryEnvironment, SqlEngine
from engine.storage import HeapFile, PagedSequentialFile, Record


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
    ) -> "Database":
        """Create, seed and index every declared table in an empty location."""

        if not isinstance(definition, DatabaseDefinition):
            raise TypeError("definition must be a DatabaseDefinition")
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        existing = [path.name for path in cls._declared_paths(definition, root)
                    if path.exists()]
        if existing:
            raise DatabaseSetupError(
                f"{root} already holds database files ({', '.join(existing)}); "
                "reset it explicitly instead of creating over them"
            )
        return cls._assemble(
            definition, root, True, memory_budget_bytes, max_open_handles
        )

    @classmethod
    def open(
        cls,
        definition: DatabaseDefinition,
        directory: object,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
    ) -> "Database":
        """Reopen an existing database; never create, seed or rebuild files."""

        if not isinstance(definition, DatabaseDefinition):
            raise TypeError("definition must be a DatabaseDefinition")
        root = Path(directory)
        missing = [path.name for path in cls._declared_paths(definition, root)
                   if not path.is_file()]
        if missing:
            raise DatabaseSetupError(
                f"{root} is not a prepared database: missing {', '.join(missing)}"
            )
        return cls._assemble(
            definition, root, False, memory_budget_bytes, max_open_handles
        )

    @staticmethod
    def _declared_paths(definition: DatabaseDefinition, root: Path) -> list[Path]:
        paths = []
        for table in definition.tables:
            paths.append(root / f"{table.name}{_TABLE_SUFFIX[table.organization]}")
            for index in table.indexes:
                paths.append(root / f"{index.name}{_INDEX_SUFFIX[index.index_type]}")
        return paths

    @classmethod
    def _assemble(
        cls,
        definition: DatabaseDefinition,
        root: Path,
        create: bool,
        memory_budget_bytes: int,
        max_open_handles: int,
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
        try:
            for table in definition.tables:
                database._open_table(table, create)
            database._engine = SqlEngine(
                database._environment,
                memory_budget_bytes=memory_budget_bytes,
                max_open_handles=max_open_handles,
            )
        except BaseException:
            database.close()
            raise
        return database

    def _open_table(self, table: TableDefinition, create: bool) -> None:
        self._catalog.register_table(TableMetadata(table.name, table.schema))
        path = self._directory / f"{table.name}{_TABLE_SUFFIX[table.organization]}"
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
        self._environment.register_storage(table.name, storage)
        if created and table.rows is not None:
            for values in table.rows():
                storage.insert(Record(table.schema, list(values)))

        for index in table.indexes:
            index_path = (
                self._directory / f"{index.name}{_INDEX_SUFFIX[index.index_type]}"
            )
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

        return self._engine

    @property
    def closed(self) -> bool:
        """Report whether every handle has been released."""

        return self._closed

    def table_names(self) -> tuple[str, ...]:
        """Return the tables in declaration order."""

        return tuple(table.name for table in self._definition.tables)

    def describe_table(self, name: str) -> TableSummary:
        """Summarize one table and its indexes for the Files panel."""

        metadata = self._catalog.get_table(name)
        definition = next(t for t in self._definition.tables if t.name == name)
        storage = self._storages[name]
        indexes = []
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
        )

    def close(self) -> None:
        """Release every index, then every storage; safe to call twice."""

        if self._closed:
            return
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
        if failures:
            raise failures[0]

    def __enter__(self) -> "Database":
        """Return this database for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release every handle on every exit path."""

        self.close()


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0
