"""Immutable table and index definitions without physical implementations."""

from dataclasses import dataclass
from enum import Enum

from engine.catalog.schema import Schema


def _validate_name(name: str, label: str) -> None:
    """Apply the same exact-name policy used by Column."""
    if not isinstance(name, str):
        raise TypeError(f"{label} must be a string")
    if not name.strip():
        raise ValueError(f"{label} must not be empty or whitespace-only")


class IndexType(Enum):
    """Declared index strategies, not instantiated index structures."""

    BPLUS = "BPLUS"
    EXTENDIBLE_HASH = "EXTENDIBLE_HASH"


@dataclass(frozen=True, slots=True)
class TableMetadata:
    """A table's name and schema; no records or storage path are owned here."""

    name: str
    schema: Schema

    def __post_init__(self) -> None:
        _validate_name(self.name, "Table name")
        if not isinstance(self.schema, Schema):
            raise TypeError("Table schema must be a Schema object")


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    """A single-column index definition with unresolved named references.

    Catalog registration checks that the table and column exist. The clustered
    flag describes a requested B+ organization; it does not implement one.
    """

    name: str
    table_name: str
    column_name: str
    index_type: IndexType
    clustered: bool = False

    def __post_init__(self) -> None:
        _validate_name(self.name, "Index name")
        _validate_name(self.table_name, "Index table_name")
        _validate_name(self.column_name, "Index column_name")
        if not isinstance(self.index_type, IndexType):
            raise TypeError("Index index_type must be an IndexType member")
        if type(self.clustered) is not bool:
            raise TypeError("Index clustered must be a boolean")
        if self.clustered and self.index_type is not IndexType.BPLUS:
            raise ValueError("Only BPLUS index metadata can be clustered")
