"""Immutable column definitions and ordered relational schemas."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from engine.catalog.types import DataType


@dataclass(frozen=True, slots=True)
class Column:
    """A named logical type; names are preserved exactly, without coercion."""

    name: str
    data_type: DataType

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Column name must be a string")
        if not self.name.strip():
            raise ValueError("Column name must not be empty or whitespace-only")
        if not isinstance(self.data_type, DataType):
            raise TypeError("Column data_type must be a DataType member")


@dataclass(frozen=True, slots=True, init=False)
class Schema:
    """An ordered, immutable sequence of uniquely named columns.

    Empty schemas are allowed. Positions are zero-based and non-negative;
    lookup by name is exact and case-sensitive.
    """

    columns: tuple[Column, ...]

    def __init__(self, columns: Sequence[Column]) -> None:
        if isinstance(columns, (str, bytes, bytearray)) or not isinstance(
            columns, Sequence
        ):
            raise TypeError("Schema columns must be a sequence of Column objects")

        ordered_columns = tuple(columns)
        names: set[str] = set()
        for column in ordered_columns:
            if not isinstance(column, Column):
                raise TypeError("Every schema entry must be a Column object")
            if column.name in names:
                raise ValueError(f"Duplicate column name: {column.name!r}")
            names.add(column.name)

        object.__setattr__(self, "columns", ordered_columns)

    def __len__(self) -> int:
        """Return the number of columns."""
        return len(self.columns)

    def __iter__(self) -> Iterator[Column]:
        """Iterate over columns in declaration order."""
        return iter(self.columns)

    def column(self, name_or_position: str | int) -> Column:
        """Look up a column by exact name or non-negative integer position.

        Raises TypeError for unsupported selectors, KeyError for unknown
        names, and IndexError for positions outside the schema.
        """
        if isinstance(name_or_position, str):
            return self.columns[self.index_of(name_or_position)]
        if isinstance(name_or_position, bool) or not isinstance(
            name_or_position, int
        ):
            raise TypeError("Column selector must be a name or integer position")
        if not 0 <= name_or_position < len(self.columns):
            raise IndexError(f"Column position out of range: {name_or_position}")
        return self.columns[name_or_position]

    def index_of(self, name: str) -> int:
        """Return the zero-based position of an exact column name.

        Raises TypeError for non-string names and KeyError for missing names.
        """
        if not isinstance(name, str):
            raise TypeError("Column name must be a string")
        for position, column in enumerate(self.columns):
            if column.name == name:
                return position
        raise KeyError(f"Unknown column: {name!r}")
