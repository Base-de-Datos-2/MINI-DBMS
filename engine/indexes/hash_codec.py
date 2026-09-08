"""Canonical typed-key hashing and directory-bit extraction."""

from __future__ import annotations

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.record import RecordValue

from .bplus_codec import BPlusKeyCodec
from .hash_binary import HASH_UINT64_MAX, HASH_WIDTH


class HashCodec:
    """Type-tag canonical B+ scalar bytes and apply FNV-1a 64-bit."""

    FNV_OFFSET_BASIS = 0xCBF29CE484222325
    FNV_PRIME = 0x100000001B3
    # The one-byte type tag makes INTEGER 0 distinct from FLOAT 0.0 even though
    # their Stage 2 payload bytes happen to be identical.
    TYPE_TAGS = {
        DataType.INTEGER: b"\x01",
        DataType.FLOAT: b"\x02",
        DataType.BOOLEAN: b"\x03",
        DataType.VARCHAR: b"\x04",
    }

    @staticmethod
    def encode_key(data_type: DataType, key: object) -> bytes:
        # Stage 4 already established exact type, NaN, int64 and UTF-8 rules;
        # reusing them prevents two incompatible scalar payload formats.
        checked = BPlusKeyCodec.validate(data_type, key)
        # Python equality treats both signed zeros as the same FLOAT key. Hash
        # bytes must therefore canonicalize them to positive zero.
        if data_type is DataType.FLOAT and checked == 0.0:
            checked = 0.0
        return HashCodec.TYPE_TAGS[data_type] + BPlusKeyCodec.encode(
            data_type, checked
        )

    @staticmethod
    def decode_key(data_type: DataType, payload: bytes) -> RecordValue:
        if not isinstance(data_type, DataType):
            raise InvalidTypeError("Hash key data_type must be a DataType")
        if type(payload) is not bytes:
            raise InvalidTypeError("Encoded hash key must be immutable bytes")
        expected_tag = HashCodec.TYPE_TAGS[data_type]
        if not payload.startswith(expected_tag):
            raise ValidationError("Encoded hash key has an incompatible type tag")
        return BPlusKeyCodec.decode(data_type, payload[1:])

    @staticmethod
    def hash_bytes(payload: bytes) -> int:
        if type(payload) is not bytes:
            raise InvalidTypeError("Hash input must be immutable bytes")
        value = HashCodec.FNV_OFFSET_BASIS
        for byte in payload:
            value ^= byte
            value = (value * HashCodec.FNV_PRIME) & HASH_UINT64_MAX
        return value

    @staticmethod
    def hash_key(data_type: DataType, key: object) -> int:
        return HashCodec.hash_bytes(HashCodec.encode_key(data_type, key))

    @staticmethod
    def directory_index(hash_value: object, global_depth: object) -> int:
        if type(hash_value) is not int:
            raise InvalidTypeError("hash_value must be a built-in int")
        if not 0 <= hash_value <= HASH_UINT64_MAX:
            raise ValidationError("hash_value must be an unsigned 64-bit integer")
        if type(global_depth) is not int:
            raise InvalidTypeError("global_depth must be a built-in int")
        if not 0 <= global_depth <= HASH_WIDTH:
            raise ValidationError(
                f"global_depth must be between 0 and {HASH_WIDTH}"
            )
        # The persisted convention selects the global-depth least-significant
        # bits. Depth zero therefore addresses the single directory entry.
        return hash_value & ((1 << global_depth) - 1)
