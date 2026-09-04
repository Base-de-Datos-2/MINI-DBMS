"""B+ key/RID binary encoding and logical comparison semantics."""

import math
import struct

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import BPlusKeyCodec, BPlusRIDCodec
from engine.storage import RID
from engine.storage.binary import UINT32_MAX


@pytest.mark.parametrize(
    ("data_type", "key", "expected"),
    [
        (DataType.INTEGER, -1, bytes.fromhex("ffffffffffffffff")),
        (DataType.INTEGER, 1, bytes.fromhex("0100000000000000")),
        (DataType.FLOAT, -2.5, bytes.fromhex("00000000000004c0")),
        (DataType.FLOAT, float("inf"), bytes.fromhex("000000000000f07f")),
        (DataType.BOOLEAN, False, b"\x00"),
        (DataType.BOOLEAN, True, b"\x01"),
        (DataType.VARCHAR, "á😀", bytes.fromhex("06000000c3a1f09f9880")),
    ],
)
def test_bplus_key_golden_bytes_and_round_trip(data_type, key, expected):
    assert BPlusKeyCodec.encode(data_type, key) == expected
    recovered = BPlusKeyCodec.decode(data_type, expected)
    assert recovered == key
    assert type(recovered) is type(key)


@pytest.mark.parametrize(
    ("data_type", "wrong"),
    [
        (DataType.INTEGER, True),
        (DataType.INTEGER, 1.0),
        (DataType.FLOAT, 1),
        (DataType.BOOLEAN, 1),
        (DataType.VARCHAR, b"text"),
    ],
)
def test_key_codec_rejects_coercion(data_type, wrong):
    with pytest.raises(InvalidTypeError):
        BPlusKeyCodec.encode(data_type, wrong)


@pytest.mark.parametrize("key", [-(2**63) - 1, 2**63])
def test_integer_key_respects_physical_int64_limit(key):
    with pytest.raises(ValidationError, match="64-bit"):
        BPlusKeyCodec.encode(DataType.INTEGER, key)


def test_varchar_limit_counts_strict_utf8_bytes():
    boundary = "á" * 127 + "a"
    assert len(boundary.encode("utf-8")) == 255
    assert BPlusKeyCodec.decode(
        DataType.VARCHAR,
        BPlusKeyCodec.encode(DataType.VARCHAR, boundary),
    ) == boundary
    with pytest.raises(ValidationError, match="255-byte"):
        BPlusKeyCodec.encode(DataType.VARCHAR, boundary + "a")
    with pytest.raises(ValidationError, match="UTF-8"):
        BPlusKeyCodec.encode(DataType.VARCHAR, "\ud800")


def test_key_codec_rejects_nan_on_encode_decode_and_compare():
    nan = float("nan")
    with pytest.raises(ValidationError, match="NaN"):
        BPlusKeyCodec.encode(DataType.FLOAT, nan)
    with pytest.raises(ValidationError, match="NaN"):
        BPlusKeyCodec.decode(DataType.FLOAT, bytes.fromhex("000000000000f87f"))
    with pytest.raises(ValidationError, match="NaN"):
        BPlusKeyCodec.compare(DataType.FLOAT, 1.0, nan)


def test_key_decode_rejects_truncated_trailing_invalid_and_oversized_payloads():
    with pytest.raises(ValidationError, match="Truncated"):
        BPlusKeyCodec.decode(DataType.INTEGER, b"\x00")
    with pytest.raises(ValidationError, match="Trailing"):
        BPlusKeyCodec.decode(DataType.INTEGER, bytes(9))
    with pytest.raises(ValidationError, match="BOOLEAN"):
        BPlusKeyCodec.decode(DataType.BOOLEAN, b"\x02")
    oversized = struct.pack("<I", 256) + b"x" * 256
    with pytest.raises(ValidationError, match="encoded-size"):
        BPlusKeyCodec.decode(DataType.VARCHAR, oversized)


@pytest.mark.parametrize("data_type", [None, "INTEGER", 1, int])
def test_key_codec_requires_data_type(data_type):
    with pytest.raises(InvalidTypeError):
        BPlusKeyCodec.encode(data_type, 1)


def test_comparator_uses_logical_order_not_little_endian_bytes():
    assert BPlusKeyCodec.encode(DataType.INTEGER, 256) < BPlusKeyCodec.encode(
        DataType.INTEGER, 1
    )
    assert BPlusKeyCodec.compare(DataType.INTEGER, 1, 256) == -1
    assert BPlusKeyCodec.compare(DataType.VARCHAR, "A", "a") == -1
    assert BPlusKeyCodec.compare(DataType.BOOLEAN, False, True) == -1
    assert BPlusKeyCodec.compare(DataType.FLOAT, -math.inf, math.inf) == -1
    assert BPlusKeyCodec.compare(DataType.FLOAT, -0.0, 0.0) == 0


@pytest.mark.parametrize(
    "rid",
    [RID(0, 0), RID(1, 816), RID(UINT32_MAX, UINT32_MAX)],
)
def test_rid_codec_has_deterministic_little_endian_round_trip(rid):
    encoded = BPlusRIDCodec.encode(rid)
    assert len(encoded) == BPlusRIDCodec.SIZE == 8
    assert encoded == struct.pack("<II", rid.page_id, rid.slot_id)
    assert BPlusRIDCodec.decode(encoded) == rid


@pytest.mark.parametrize("rid", [None, (1, 2), [1, 2], "1:2"])
def test_rid_codec_requires_rid(rid):
    with pytest.raises(InvalidTypeError):
        BPlusRIDCodec.encode(rid)


def test_rid_codec_rejects_unencodable_components_and_bad_payloads():
    with pytest.raises(ValidationError, match="uint32"):
        BPlusRIDCodec.encode(RID(UINT32_MAX + 1, 0))
    with pytest.raises(ValidationError, match="exactly 8"):
        BPlusRIDCodec.decode(bytes(7))
    with pytest.raises(InvalidTypeError):
        BPlusRIDCodec.decode(bytearray(8))
