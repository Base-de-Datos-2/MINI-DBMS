"""Schema-driven row framing; Page only needs to handle opaque payload bytes."""

from engine.catalog.schema import Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import require_bytes
from engine.storage.record import Record
from engine.storage.value_codec import ValueCodec


class RecordCodec:
    """Concatenate values in schema order, without type tags or stored schema.

    Deserialization requires the matching external Schema. Truncation, trailing
    data and malformed values raise ValidationError. Valid-looking bytes under
    a wrong schema cannot always be detected. Codecs impose no page-size limit.
    """

    @staticmethod
    def serialize(record: Record) -> bytes:
        if not isinstance(record, Record):
            raise InvalidTypeError("record must be a Record")
        # Reuse the model's count/type checks at the serialization boundary.
        checked = Record(record.schema, record.values)
        return b"".join(
            ValueCodec.encode(column.data_type, value)
            for column, value in zip(checked.schema, checked.values)
        )

    @staticmethod
    def deserialize(schema: Schema, payload: bytes) -> Record:
        if not isinstance(schema, Schema):
            raise InvalidTypeError("schema must be a Schema")
        require_bytes(payload)
        values = []
        offset = 0
        for column in schema:
            value, offset = ValueCodec.decode_from(column.data_type, payload, offset)
            values.append(value)
        if offset != len(payload):
            raise ValidationError("Trailing bytes after record")
        return Record(schema, values)
