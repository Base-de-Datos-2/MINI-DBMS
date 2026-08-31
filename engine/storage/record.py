"""Validated relational rows with no knowledge of pages or storage files."""

from collections.abc import Sequence
from dataclasses import dataclass

from engine.catalog.schema import Schema
from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError


RecordValue = int | float | bool | str

_VALUE_TYPES = {
    DataType.INTEGER: int,
    DataType.FLOAT: float,
    DataType.BOOLEAN: bool,
    DataType.VARCHAR: str,
}


@dataclass(frozen=True, slots=True, init=False)
class Record:
    """An immutable row whose values exactly match its schema's Python types.

    No implicit conversion is performed: FLOAT requires float, INTEGER
    requires int (not bool), and None/SQL NULL is not supported yet.
    """

    schema: Schema
    values: tuple[RecordValue, ...]

    def __init__(self, schema: Schema, values: Sequence[RecordValue]) -> None:
        if not isinstance(schema, Schema):
            raise InvalidTypeError("Record schema must be a Schema object")
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(
            values, Sequence
        ):
            raise InvalidTypeError("Record values must be a sequence of scalar values")

        ordered_values = tuple(values)
        if len(ordered_values) != len(schema):
            raise ValidationError(
                f"Record requires {len(schema)} values, got {len(ordered_values)}"
            )

        for column, value in zip(schema, ordered_values):
            expected_type = _VALUE_TYPES[column.data_type]
            if type(value) is not expected_type:
                raise InvalidTypeError(
                    f"Column {column.name!r} requires {column.data_type.value} "
                    f"({expected_type.__name__}), got {type(value).__name__}"
                )

        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "values", ordered_values)

    def __getitem__(self, name: str) -> RecordValue:
        """Return a named value; missing names raise UnknownColumnError (KeyError)."""
        return self.values[self.schema.index_of(name)]
