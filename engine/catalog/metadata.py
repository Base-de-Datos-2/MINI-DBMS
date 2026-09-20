"""Immutable table and index definitions without open runtime objects."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from engine.catalog.types import DataType
from engine.catalog.schema import Schema
from engine.errors import InvalidTypeError, ValidationError


# One VARCHAR value stores a four-byte byte-length prefix inside the largest
# payload that can occupy one page slot.  This logical character bound remains
# separate from UTF-8 byte size and complete-record capacity checks.
MAX_DECLARED_VARCHAR_CODEPOINTS = 4_075


def _validate_name(name: str, label: str) -> None:
    """Apply the same exact-name policy used by Column."""
    if not isinstance(name, str):
        raise InvalidTypeError(f"{label} must be a string")
    if not name.strip():
        raise ValidationError(f"{label} must not be empty or whitespace-only")


class IndexType(Enum):
    """Declared index strategies, not instantiated index structures."""

    BPLUS = "BPLUS"
    EXTENDIBLE_HASH = "EXTENDIBLE_HASH"


@dataclass(frozen=True, slots=True)
class ColumnConstraint:
    """Optional logical constraints for one existing physical schema column."""

    column_name: str
    varchar_length: int | None = None
    primary_key: bool = False

    def __post_init__(self) -> None:
        _validate_name(self.column_name, "Constraint column_name")
        if self.varchar_length is not None:
            if type(self.varchar_length) is not int:
                raise InvalidTypeError("VARCHAR length must be an integer")
            if not 1 <= self.varchar_length <= MAX_DECLARED_VARCHAR_CODEPOINTS:
                raise ValidationError(
                    "VARCHAR length must be between 1 and "
                    f"{MAX_DECLARED_VARCHAR_CODEPOINTS}"
                )
        if type(self.primary_key) is not bool:
            raise InvalidTypeError("Primary-key marker must be a boolean")
        if self.varchar_length is None and not self.primary_key:
            raise ValidationError("A column constraint must declare a restriction")


@dataclass(frozen=True, slots=True)
class TableMetadata:
    """Physical schema plus optional backward-compatible logical constraints."""

    name: str
    schema: Schema
    constraints: tuple[ColumnConstraint, ...] = ()

    def __post_init__(self) -> None:
        _validate_name(self.name, "Table name")
        if not isinstance(self.schema, Schema):
            raise InvalidTypeError("Table schema must be a Schema object")
        if isinstance(self.constraints, (str, bytes, bytearray)) or not isinstance(
            self.constraints, Sequence
        ):
            raise InvalidTypeError("Table constraints must be a sequence")

        constraints = tuple(self.constraints)
        names: set[str] = set()
        primary_keys = 0
        for constraint in constraints:
            if not isinstance(constraint, ColumnConstraint):
                raise InvalidTypeError(
                    "Every table constraint must be a ColumnConstraint"
                )
            if constraint.column_name in names:
                raise ValidationError(
                    f"Duplicate constraints for column {constraint.column_name!r}"
                )
            names.add(constraint.column_name)
            try:
                column = self.schema.column(constraint.column_name)
            except KeyError as error:
                raise ValidationError(
                    f"Constraint references unknown column {constraint.column_name!r}"
                ) from error
            if (
                constraint.varchar_length is not None
                and column.data_type is not DataType.VARCHAR
            ):
                raise ValidationError(
                    f"VARCHAR length cannot constrain {column.data_type.value} "
                    f"column {column.name!r}"
                )
            if constraint.primary_key:
                primary_keys += 1
                if column.data_type not in {DataType.INTEGER, DataType.VARCHAR}:
                    raise ValidationError(
                        "A declared primary key must use INTEGER or VARCHAR"
                    )
        if primary_keys > 1:
            raise ValidationError("A table may declare at most one primary key")
        object.__setattr__(self, "constraints", constraints)

    @property
    def primary_key(self) -> str | None:
        """Return the exact primary-key column name, when one is declared."""

        return next(
            (
                constraint.column_name
                for constraint in self.constraints
                if constraint.primary_key
            ),
            None,
        )

    def varchar_length(self, column_name: str) -> int | None:
        """Return one declared character bound; legacy VARCHARs stay unbounded."""

        self.schema.column(column_name)
        return next(
            (
                constraint.varchar_length
                for constraint in self.constraints
                if constraint.column_name == column_name
            ),
            None,
        )


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
    unique: bool = False
    file_path: str | None = None

    def __post_init__(self) -> None:
        _validate_name(self.name, "Index name")
        _validate_name(self.table_name, "Index table_name")
        _validate_name(self.column_name, "Index column_name")
        if not isinstance(self.index_type, IndexType):
            raise InvalidTypeError("Index index_type must be an IndexType member")
        if type(self.clustered) is not bool:
            raise InvalidTypeError("Index clustered must be a boolean")
        if type(self.unique) is not bool:
            raise InvalidTypeError("Index unique must be a boolean")
        if self.file_path is not None:
            _validate_name(self.file_path, "Index file_path")
        if self.clustered and self.index_type is not IndexType.BPLUS:
            raise ValidationError("Only BPLUS index metadata can be clustered")

    @property
    def allow_duplicate_keys(self) -> bool:
        """Translate catalog uniqueness into the index-core convention."""

        return not self.unique

    @property
    def supports_equality(self) -> bool:
        """Both Stage 4/5 index families provide exact-key access."""

        return True

    @property
    def supports_range(self) -> bool:
        """Only B+ metadata advertises ordered range access."""

        return self.index_type is IndexType.BPLUS

    @property
    def supports_ordering(self) -> bool:
        """Hash directory order is not relational key order."""

        return self.index_type is IndexType.BPLUS
