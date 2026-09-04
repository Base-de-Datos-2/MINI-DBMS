"""Deterministic B+ key and RID encoding, independent from node I/O."""

from __future__ import annotations

import math

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import UINT32_MAX, require_bytes
from engine.storage.record import RecordValue
from engine.storage.rid import RID
from engine.storage.value_codec import ValueCodec

from .bplus_binary import (
    BPLUS_MAX_VARCHAR_KEY_BYTES,
    BPLUS_RID_SIZE,
    BPLUS_RID_STRUCT,
    maximum_encoded_key_size,
)


_KEY_TYPES = {
    DataType.INTEGER: int,
    DataType.FLOAT: float,
    DataType.BOOLEAN: bool,
    DataType.VARCHAR: str,
}


def _validate_data_type(data_type: object) -> DataType:
    if not isinstance(data_type, DataType):
        raise InvalidTypeError("B+ key data_type must be a DataType")
    return data_type


class BPlusKeyCodec:
    """Encode and compare one of the four Stage 1 key types.

    Comparison is logical, never a comparison of little-endian byte strings.
    FLOAT NaN is rejected while infinities and signed zero remain supported.
    VARCHAR keys are limited by their strict UTF-8 byte length, not character
    count, so the node capacity derived from the worst case is always safe.
    """

    @staticmethod
    def validate(data_type: DataType, key: object) -> RecordValue:
        checked_type = _validate_data_type(data_type)
        expected = _KEY_TYPES[checked_type]
        if type(key) is not expected:
            raise InvalidTypeError(
                f"B+ {checked_type.value} key requires {expected.__name__}, "
                f"got {type(key).__name__}"
            )
        if checked_type is DataType.FLOAT and math.isnan(key):
            raise ValidationError("NaN is not a B+ index key")

        # ValueCodec applies the signed-int64 and strict UTF-8 validations.
        encoded = ValueCodec.encode(checked_type, key)
        if (
            checked_type is DataType.VARCHAR
            and len(encoded) - 4 > BPLUS_MAX_VARCHAR_KEY_BYTES
        ):
            raise ValidationError(
                "B+ VARCHAR key exceeds the 255-byte UTF-8 limit"
            )
        if len(encoded) > maximum_encoded_key_size(checked_type):
            raise ValidationError("B+ key exceeds its encoded-size limit")
        return key

    @staticmethod
    def encode(data_type: DataType, key: object) -> bytes:
        checked = BPlusKeyCodec.validate(data_type, key)
        return ValueCodec.encode(data_type, checked)

    @staticmethod
    def decode(data_type: DataType, payload: bytes) -> RecordValue:
        checked_type = _validate_data_type(data_type)
        require_bytes(payload)
        if (
            checked_type is DataType.VARCHAR
            and len(payload) > maximum_encoded_key_size(checked_type)
        ):
            raise ValidationError("B+ key payload exceeds its encoded-size limit")
        key = ValueCodec.decode(checked_type, payload)
        return BPlusKeyCodec.validate(checked_type, key)

    @staticmethod
    def decode_from(
        data_type: DataType,
        payload: bytes,
        offset: int = 0,
    ) -> tuple[RecordValue, int]:
        """Decode one framed key and return its absolute ending offset."""

        checked_type = _validate_data_type(data_type)
        require_bytes(payload)
        if type(offset) is not int:
            raise InvalidTypeError("B+ key offset must be a built-in int")
        if not 0 <= offset <= len(payload):
            raise ValidationError("B+ key offset is outside the byte buffer")
        key, end = ValueCodec.decode_from(checked_type, payload, offset)
        if end - offset > maximum_encoded_key_size(checked_type):
            raise ValidationError("B+ key payload exceeds its encoded-size limit")
        return BPlusKeyCodec.validate(checked_type, key), end

    @staticmethod
    def compare(data_type: DataType, left: object, right: object) -> int:
        checked_left = BPlusKeyCodec.validate(data_type, left)
        checked_right = BPlusKeyCodec.validate(data_type, right)
        return (checked_left > checked_right) - (checked_left < checked_right)

    @staticmethod
    def maximum_encoded_size(data_type: DataType) -> int:
        checked_type = _validate_data_type(data_type)
        return maximum_encoded_key_size(checked_type)


class BPlusRIDCodec:
    """Encode a logical RID into two little-endian uint32 components."""

    SIZE = BPLUS_RID_SIZE

    @staticmethod
    def encode(rid: RID) -> bytes:
        if not isinstance(rid, RID):
            raise InvalidTypeError("B+ leaf value must be a RID")
        for name, value in (("page_id", rid.page_id), ("slot_id", rid.slot_id)):
            if value > UINT32_MAX:
                raise ValidationError(f"RID {name} exceeds the uint32 encoding range")
        return BPLUS_RID_STRUCT.pack(rid.page_id, rid.slot_id)

    @staticmethod
    def decode(payload: bytes) -> RID:
        require_bytes(payload)
        if len(payload) != BPLUS_RID_SIZE:
            raise ValidationError(
                f"Encoded B+ RID requires exactly {BPLUS_RID_SIZE} bytes"
            )
        return RID(*BPLUS_RID_STRUCT.unpack(payload))
