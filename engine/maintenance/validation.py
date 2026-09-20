"""Shared logical and physical validation for ordinary database writes."""

from __future__ import annotations

from collections.abc import Sequence

from engine.catalog import DataType, TableMetadata
from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.indexes import BPlusKeyCodec
from engine.storage import Record, RecordCodec
from engine.storage.binary import MAX_RECORD_SIZE
from engine.storage.record import RecordValue


def validate_record(table: TableMetadata, record: Record) -> bytes:
    """Validate one row against logical constraints and its unchanged codec."""

    if not isinstance(table, TableMetadata):
        raise InvalidTypeError("Record validation requires TableMetadata")
    if not isinstance(record, Record):
        raise InvalidTypeError("Record validation requires a Record")
    if record.schema != table.schema:
        raise SchemaError("Record schema differs from table metadata")

    for column, value in zip(table.schema, record.values):
        if column.data_type is DataType.VARCHAR:
            declared = table.varchar_length(column.name)
            if declared is not None and len(value) > declared:
                raise ValidationError(
                    f"Column {column.name!r} exceeds its declared VARCHAR({declared}) "
                    "character limit"
                )

    primary_key = table.primary_key
    if primary_key is not None:
        column = table.schema.column(primary_key)
        BPlusKeyCodec.validate(column.data_type, record[primary_key])

    payload = RecordCodec.serialize(record)
    if len(payload) > MAX_RECORD_SIZE:
        raise ValidationError(
            f"Record payload exceeds page capacity of {MAX_RECORD_SIZE} bytes"
        )
    return payload


def build_validated_record(
    table: TableMetadata,
    values: Sequence[RecordValue],
) -> Record:
    """Construct and fully validate one ordered row for a table."""

    if not isinstance(table, TableMetadata):
        raise InvalidTypeError("Record validation requires TableMetadata")
    record = Record(table.schema, values)
    validate_record(table, record)
    return record


__all__ = ["build_validated_record", "validate_record"]
