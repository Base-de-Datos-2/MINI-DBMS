"""In-memory registration and lookup of immutable table/index metadata."""

from engine.catalog.metadata import IndexMetadata, TableMetadata
from engine.errors import (
    DuplicateError, InvalidReferenceError, InvalidTypeError, UnknownTableError,
)


class Catalog:
    """An independent, non-persistent catalog with exact, case-sensitive names.

    Table names and index names each have their own catalog-wide namespace.
    Query methods return immutable metadata or tuple snapshots, never the
    internal dictionaries. Thread safety and persistence are not implemented.
    """

    def __init__(self) -> None:
        self._tables: dict[str, TableMetadata] = {}
        self._indexes: dict[str, IndexMetadata] = {}

    def register_table(self, table: TableMetadata) -> None:
        """Register a table, rejecting duplicate names without replacing data."""
        if not isinstance(table, TableMetadata):
            raise InvalidTypeError("Catalog table must be a TableMetadata object")
        if table.name in self._tables:
            raise DuplicateError(f"Duplicate table name: {table.name!r}")
        self._tables[table.name] = table

    def has_table(self, name: str) -> bool:
        """Return whether an exact table name is registered."""
        if not isinstance(name, str):
            raise InvalidTypeError("Table name must be a string")
        return name in self._tables

    def get_table(self, name: str) -> TableMetadata:
        """Resolve an exact name, raising UnknownTableError (a KeyError)."""
        if not self.has_table(name):
            raise UnknownTableError(f"Unknown table: {name!r}")
        return self._tables[name]

    def list_tables(self) -> tuple[TableMetadata, ...]:
        """Return a snapshot in registration order."""
        return tuple(self._tables.values())

    def register_index(self, index: IndexMetadata) -> None:
        """Validate references and register a definition without partial updates.

        Names must be unique across this catalog's indexes. At most one
        clustered B+ definition is allowed per table. No index is built.
        DuplicateError reports either conflict. UnknownTableError and
        UnknownColumnError from reference resolution propagate unchanged.
        """
        if not isinstance(index, IndexMetadata):
            raise InvalidTypeError("Catalog index must be an IndexMetadata object")
        if index.name in self._indexes:
            raise DuplicateError(f"Duplicate index name: {index.name!r}")

        table = self.get_table(index.table_name)
        table.schema.column(index.column_name)
        if index.clustered and any(
            registered.table_name == index.table_name and registered.clustered
            for registered in self._indexes.values()
        ):
            raise DuplicateError(
                f"Table {index.table_name!r} already has a clustered index"
            )

        # Change state only after every validation succeeds.
        self._indexes[index.name] = index

    def get_index(self, name: str) -> IndexMetadata:
        """Resolve an exact index name or raise InvalidReferenceError (KeyError)."""
        if not isinstance(name, str):
            raise InvalidTypeError("Index name must be a string")
        if name not in self._indexes:
            raise InvalidReferenceError(f"Unknown index: {name!r}")
        return self._indexes[name]

    def get_indexes(self, table_name: str) -> tuple[IndexMetadata, ...]:
        """Return a table's definitions in registration order.

        An existing table with no indexes returns an empty tuple; an unknown
        table raises UnknownTableError rather than hiding an invalid reference.
        """
        table = self.get_table(table_name)
        return tuple(
            index for index in self._indexes.values() if index.table_name == table.name
        )
