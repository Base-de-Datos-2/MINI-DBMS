"""One deterministic key contract for the Paged Sequential organization."""

from __future__ import annotations

import math
from collections.abc import Sequence

from engine.catalog import DataType, Schema
from engine.errors import InvalidTypeError, SchemaError, ValidationError

from .record import Record, RecordValue


_KEY_TYPES = {
    DataType.INTEGER: int,
    DataType.FLOAT: float,
    DataType.BOOLEAN: bool,
    DataType.VARCHAR: str,
}


class SequentialOrdering:
    """Extract and compare values from one exact schema column.

    Ordering is ascending Python value order within the configured DataType.
    Strings therefore use Unicode code-point order and booleans use
    ``False < True``. NaN is rejected because it has no total ordering;
    infinities are valid FLOAT keys.
    """

    def __init__(self, schema: Schema, key_column: str) -> None:
        if not isinstance(schema, Schema):
            raise InvalidTypeError("schema must be a Schema")
        if type(key_column) is not str:
            raise InvalidTypeError("key_column must be a string")
        try:
            column = schema.column(key_column)
        except KeyError as exc:
            raise SchemaError(
                f"Sequential key column {key_column!r} is not in the schema"
            ) from exc
        if column.data_type not in _KEY_TYPES:
            raise ValidationError(
                f"Unsupported sequential key type: {column.data_type!r}"
            )
        self._schema = schema
        self._key_column = key_column
        self._data_type = column.data_type
        self._python_type = _KEY_TYPES[column.data_type]

    @property
    def schema(self) -> Schema:
        return self._schema

    @property
    def key_column(self) -> str:
        return self._key_column

    @property
    def data_type(self) -> DataType:
        return self._data_type

    def validate_key(self, key: object) -> RecordValue:
        if type(key) is not self._python_type:
            raise InvalidTypeError(
                f"Sequential key {self._key_column!r} requires "
                f"{self._data_type.value} ({self._python_type.__name__}), "
                f"got {type(key).__name__}"
            )
        if self._data_type is DataType.FLOAT and math.isnan(key):
            raise ValidationError("NaN is not a sequential ordering key")
        return key

    def extract(self, record: object) -> RecordValue:
        if not isinstance(record, Record):
            raise InvalidTypeError("Sequential ordering requires a Record")
        if record.schema != self._schema:
            raise SchemaError("Record schema differs from sequential schema")
        return self.validate_key(record[self._key_column])

    def compare(self, left: object, right: object) -> int:
        """Return -1, 0, or 1 using the single configured total order."""

        checked_left = self.validate_key(left)
        checked_right = self.validate_key(right)
        return (checked_left > checked_right) - (checked_left < checked_right)

    def insertion_position(
        self,
        existing_keys: Sequence[RecordValue],
        key: object,
    ) -> int:
        """Return the stable position after every existing equal key."""

        if isinstance(existing_keys, (str, bytes, bytearray)) or not isinstance(
            existing_keys, Sequence
        ):
            raise InvalidTypeError("existing_keys must be a sequence")
        checked_key = self.validate_key(key)
        previous = None
        has_previous = False
        for position, existing in enumerate(existing_keys):
            checked_existing = self.validate_key(existing)
            if has_previous and self.compare(previous, checked_existing) > 0:
                raise ValidationError("existing_keys must be nondecreasing")
            if self.compare(checked_existing, checked_key) > 0:
                return position
            previous = checked_existing
            has_previous = True
        return len(existing_keys)
