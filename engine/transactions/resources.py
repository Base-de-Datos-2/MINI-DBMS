"""Statement access intents over stable database/table resources.

These are plans for later S/X acquisition. Building one reads metadata only;
it never acquires a logical lock or opens a data cursor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock

from engine.catalog import Catalog
from engine.errors import InvalidTypeError, ValidationError
from engine.query.ast import (
    BeginTransactionStatement,
    CreateTableStatement,
    DeleteStatement,
    EndTransactionStatement,
    ExplainStatement,
    InsertStatement,
    RollbackStatement,
    SelectStatement,
    Statement,
)
from engine.query.environment import QueryEnvironment


class LockMode(Enum):
    S = "S"
    X = "X"


class SchemaMode(Enum):
    NONE = "NONE"
    S = "S"
    X = "X"


@dataclass(frozen=True, slots=True)
class TableFiles:
    name: str
    identity: str
    base: Path
    indexes: tuple[tuple[str, Path], ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.identity:
            raise ValidationError("Table resource names and identities must be nonempty")
        object.__setattr__(self, "base", Path(self.base).resolve())
        object.__setattr__(
            self, "indexes",
            tuple((name, Path(path).resolve()) for name, path in self.indexes),
        )
        names = [name for name, _ in self.indexes]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise ValidationError("Index file names must be unique within a table")
        paths = [self.base, *(path for _, path in self.indexes)]
        if len(paths) != len(set(paths)):
            raise ValidationError("A table's base and index files must be distinct")

    @property
    def physical_files(self) -> tuple[Path, ...]:
        return (self.base, *(path for _, path in self.indexes))


@dataclass(frozen=True, slots=True, order=True)
class TableResource:
    database_identity: str
    table_identity: str


@dataclass(frozen=True, slots=True)
class TableIntent:
    table_name: str
    resource: TableResource
    mode: LockMode
    generation: int
    files: tuple[Path, ...]
    runtime_generation: int = 0


@dataclass(frozen=True, slots=True)
class AccessPlan:
    schema: SchemaMode
    tables: tuple[TableIntent, ...]
    schema_generation: int


class StaleAccessPlanError(ValidationError):
    """A runtime/metadata generation changed after access planning."""


class ResourceCatalog:
    """Owner-local mapping of logical tables and every permanent file.

    Its short mutex makes one metadata snapshot internally consistent. Stage
    8.7/8.15 will place the schema S/X gate around mapping and execution.
    """

    def __init__(
        self,
        database_identity: str,
        catalog: Catalog,
        tables: tuple[TableFiles, ...],
        environment: QueryEnvironment | None = None,
    ) -> None:
        if not database_identity:
            raise ValidationError("Database identity must be nonempty")
        if not isinstance(catalog, Catalog):
            raise InvalidTypeError("ResourceCatalog requires a Catalog")
        self._database_identity = database_identity
        self._catalog = catalog
        if environment is not None and environment.catalog is not catalog:
            raise ValidationError("Runtime environment must borrow the same Catalog")
        self._environment = environment
        self._mutex = RLock()
        self._tables: dict[str, TableFiles] = {}
        self._generations: dict[str, int] = {}
        self._schema_generation = 0
        for table in tables:
            self.register(table)

    @property
    def database_identity(self) -> str:
        return self._database_identity

    def register(self, table: TableFiles) -> None:
        with self._mutex:
            if not isinstance(table, TableFiles):
                raise InvalidTypeError("Registered table files must be TableFiles")
            if table.name in self._tables:
                raise ValidationError(f"Table resource {table.name!r} is already registered")
            if any(item.identity == table.identity for item in self._tables.values()):
                raise ValidationError("Stable table identities must be unique")
            metadata = self._catalog.get_table(table.name)
            index_metadata = self._catalog.get_indexes(metadata.name)
            expected_indexes = tuple(item.name for item in index_metadata)
            if set(expected_indexes) != {name for name, _ in table.indexes}:
                raise ValidationError(
                    f"Table {table.name!r} file set must include every declared index"
                )
            indexed_paths = dict(table.indexes)
            for item in index_metadata:
                if item.file_path is not None and indexed_paths[item.name] != Path(
                    item.file_path
                ).resolve():
                    raise ValidationError(
                        f"Index {item.name!r} file does not match its Catalog path"
                    )
            used = {
                path for existing in self._tables.values()
                for path in existing.physical_files
            }
            if any(path in used for path in table.physical_files):
                raise ValidationError("One permanent file cannot belong to two tables")
            self._tables[table.name] = table
            self._generations[table.name] = 0
            self._schema_generation += 1

    def unregister(self, table_name: str) -> None:
        """Remove a not-yet-published CREATE resource during compensation."""

        with self._mutex:
            if table_name not in self._tables:
                raise ValidationError(f"Unknown table resource {table_name!r}")
            del self._tables[table_name]
            del self._generations[table_name]
            self._schema_generation += 1

    def bump_generation(self, table_name: str) -> int:
        """Invalidate access plans after runtime replacement or restoration."""

        with self._mutex:
            if table_name not in self._tables:
                raise ValidationError(f"Unknown table resource {table_name!r}")
            self._generations[table_name] += 1
            return self._generations[table_name]

    def table_files(self, table_name: str) -> TableFiles:
        with self._mutex:
            try:
                return self._tables[table_name]
            except KeyError as error:
                raise ValidationError(f"Unknown table resource {table_name!r}") from error

    def plan(self, statement: Statement) -> AccessPlan:
        with self._mutex:
            if isinstance(
                statement,
                (BeginTransactionStatement, EndTransactionStatement, RollbackStatement),
            ):
                return AccessPlan(SchemaMode.NONE, (), self._schema_generation)
            if isinstance(statement, CreateTableStatement):
                return AccessPlan(SchemaMode.X, (), self._schema_generation)
            if isinstance(statement, ExplainStatement) and not statement.analyze:
                return AccessPlan(SchemaMode.S, (), self._schema_generation)

            if isinstance(statement, ExplainStatement):
                select = statement.select
            elif isinstance(statement, SelectStatement):
                select = statement
            else:
                select = None

            if select is not None:
                names = {select.from_table.name}
                if select.join is not None:
                    names.add(select.join.table.name)
                mode = LockMode.S
            elif isinstance(statement, (InsertStatement, DeleteStatement)):
                names = {statement.table}
                mode = LockMode.X
            else:
                raise InvalidTypeError("Unsupported statement for resource planning")

            intents: list[TableIntent] = []
            for name in names:
                self._catalog.get_table(name)
                try:
                    files = self._tables[name]
                except KeyError as error:
                    raise ValidationError(
                        f"No stable file resource is registered for {name!r}"
                    ) from error
                intents.append(
                    TableIntent(
                        name,
                        TableResource(self._database_identity, files.identity),
                        mode,
                        self._generations[name],
                        files.physical_files,
                        0 if self._environment is None else self._environment.runtime_generation(name),
                    )
                )
            intents.sort(key=lambda item: item.resource)
            return AccessPlan(SchemaMode.S, tuple(intents), self._schema_generation)

    def validate(self, plan: AccessPlan) -> None:
        with self._mutex:
            if (plan.schema is not SchemaMode.NONE and not plan.tables
                    and plan.schema_generation != self._schema_generation):
                raise StaleAccessPlanError("Schema changed after metadata access planning")
            for intent in plan.tables:
                current = self._tables.get(intent.table_name)
                if (current is None
                        or intent.resource != TableResource(self._database_identity, current.identity)
                        or intent.generation != self._generations[intent.table_name]
                        or intent.files != current.physical_files):
                    raise StaleAccessPlanError(
                        f"Runtime resource for {intent.table_name!r} changed"
                    )
                if (self._environment is not None
                        and intent.runtime_generation != self._environment.runtime_generation(
                            intent.table_name
                        )):
                    raise StaleAccessPlanError(
                        f"Runtime registry for {intent.table_name!r} changed"
                    )
