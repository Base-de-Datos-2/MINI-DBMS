"""Strict primitive encoding, with no schema, page layout, or disk ownership."""

from math import isnan

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import (
    BOOLEAN_STRUCT,
    CANONICAL_NAN_BYTES,
    FLOAT_STRUCT,
    INTEGER_MAX,
    INTEGER_MIN,
    INTEGER_STRUCT,
    STRING_ENCODING,
    UINT32_MAX,
    VARCHAR_LENGTH_STRUCT,
    require_bytes,
)
from engine.storage.record import RecordValue

_VALUE_TYPES = {
    DataType.INTEGER: int,
    DataType.FLOAT: float,
    DataType.BOOLEAN: bool,
    DataType.VARCHAR: str,
}


def _validate_data_type(data_type: DataType) -> None:
    if not isinstance(data_type, DataType):
        raise InvalidTypeError("data_type must be a DataType")


def _end_of(payload: bytes, offset: int, size: int) -> int:
    end = offset + size
    if end > len(payload):
        raise ValidationError(f"Truncated value at byte {offset}: requires {size} bytes")
    return end


class ValueCodec:
    """Stateless v1 codec; wrong types raise InvalidTypeError, bad bytes ValueError.

    Binary validation failures use the domain subclass ValidationError. FLOAT
    preserves signed zero/infinities and canonicalizes NaN on encoding. VARCHAR
    uses a uint32 byte length and strict UTF-8. None/NULL is not supported.
    """

    @staticmethod
    def encode(data_type: DataType, value: RecordValue) -> bytes:
        _validate_data_type(data_type)
        if type(value) is not _VALUE_TYPES[data_type]:
            raise InvalidTypeError(
                f"{data_type.value} requires {_VALUE_TYPES[data_type].__name__}, "
                f"got {type(value).__name__}"
            )
        if data_type is DataType.INTEGER:
            if not INTEGER_MIN <= value <= INTEGER_MAX:
                raise ValidationError("INTEGER is outside the signed 64-bit range")
            return INTEGER_STRUCT.pack(value)
        if data_type is DataType.FLOAT:
            return CANONICAL_NAN_BYTES if isnan(value) else FLOAT_STRUCT.pack(value)
        if data_type is DataType.BOOLEAN:
            return BOOLEAN_STRUCT.pack(int(value))

        try:
            encoded = value.encode(STRING_ENCODING, errors="strict")
        except UnicodeEncodeError as exc:
            raise ValidationError("VARCHAR cannot be encoded as strict UTF-8") from exc
        if len(encoded) > UINT32_MAX:
            raise ValidationError("VARCHAR exceeds the uint32 byte-length limit")
        return VARCHAR_LENGTH_STRUCT.pack(len(encoded)) + encoded

    @staticmethod
    def decode(data_type: DataType, payload: bytes) -> RecordValue:
        """Decode exactly one value; trailing bytes are malformed input."""
        value, end = ValueCodec.decode_from(data_type, payload)
        if end != len(payload):
            raise ValidationError("Trailing bytes after primitive value")
        return value

    @staticmethod
    def decode_from(
        data_type: DataType, payload: bytes, offset: int = 0
    ) -> tuple[RecordValue, int]:
        """Read one framed value and return (value, absolute next offset).

        A valid offset is an exact built-in int in [0, len(payload)]. Remaining
        bytes are checked before unpacking or slicing, including string lengths.
        """
        _validate_data_type(data_type)
        require_bytes(payload)
        if type(offset) is not int:
            raise InvalidTypeError("offset must be a built-in int")
        if not 0 <= offset <= len(payload):
            raise ValidationError("offset is outside the byte buffer")

        if data_type is DataType.INTEGER:
            end = _end_of(payload, offset, INTEGER_STRUCT.size)
            return INTEGER_STRUCT.unpack_from(payload, offset)[0], end
        if data_type is DataType.FLOAT:
            end = _end_of(payload, offset, FLOAT_STRUCT.size)
            return FLOAT_STRUCT.unpack_from(payload, offset)[0], end
        if data_type is DataType.BOOLEAN:
            end = _end_of(payload, offset, BOOLEAN_STRUCT.size)
            value = BOOLEAN_STRUCT.unpack_from(payload, offset)[0]
            if value not in (0, 1):
                raise ValidationError("BOOLEAN byte must be 0 or 1")
            return bool(value), end

        start = _end_of(payload, offset, VARCHAR_LENGTH_STRUCT.size)
        length = VARCHAR_LENGTH_STRUCT.unpack_from(payload, offset)[0]
        end = _end_of(payload, start, length)
        try:
            value = payload[start:end].decode(STRING_ENCODING, errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError("Malformed UTF-8 in VARCHAR") from exc
        return value, end
