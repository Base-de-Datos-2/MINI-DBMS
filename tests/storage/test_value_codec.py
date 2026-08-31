"""Primitive golden bytes, strict scalar types and defensive framing."""

import math
import struct
import sys

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import ValueCodec


@pytest.mark.parametrize(
    ("data_type", "value", "hex_bytes"),
    [
        (DataType.INTEGER, 0, "0000000000000000"),
        (DataType.INTEGER, 1, "0100000000000000"),
        (DataType.INTEGER, -1, "ffffffffffffffff"),
        (DataType.INTEGER, -(2**63), "0000000000000080"),
        (DataType.INTEGER, 2**63 - 1, "ffffffffffffff7f"),
        (DataType.FLOAT, 1.5, "000000000000f83f"),
        (DataType.FLOAT, -2.5, "00000000000004c0"),
        (DataType.FLOAT, 0.0, "0000000000000000"),
        (DataType.FLOAT, -0.0, "0000000000000080"),
        (DataType.FLOAT, math.inf, "000000000000f07f"),
        (DataType.FLOAT, -math.inf, "000000000000f0ff"),
        (DataType.FLOAT, sys.float_info.max, "ffffffffffffef7f"),
        (DataType.FLOAT, 5e-324, "0100000000000000"),
        (DataType.BOOLEAN, False, "00"),
        (DataType.BOOLEAN, True, "01"),
        (DataType.VARCHAR, "", "00000000"),
        (DataType.VARCHAR, "Ana", "03000000416e61"),
        (DataType.VARCHAR, "á😀", "06000000c3a1f09f9880"),
        (DataType.VARCHAR, "a\x00b", "03000000610062"),
    ],
)
def test_primitive_golden_bytes_and_round_trip(data_type, value, hex_bytes):
    payload = bytes.fromhex(hex_bytes)
    assert ValueCodec.encode(data_type, value) == payload
    decoded = ValueCodec.decode(data_type, payload)
    assert decoded == value
    assert type(decoded) is type(value)
    if data_type is DataType.FLOAT:
        assert math.copysign(1.0, decoded) == math.copysign(1.0, value)


@pytest.mark.parametrize("value", [-(2**63) - 1, 2**63, -(2**100), 2**100])
def test_integer_rejects_values_outside_int64(value):
    with pytest.raises(ValidationError, match="64-bit"):
        ValueCodec.encode(DataType.INTEGER, value)


@pytest.mark.parametrize(
    "hex_bytes",
    ["000000000000f87f", "010000000000f07f", "ffffffffffffffff", "010000000000f8ff"],
)
def test_nan_patterns_decode_and_encode_to_canonical_quiet_nan(hex_bytes):
    decoded = ValueCodec.decode(DataType.FLOAT, bytes.fromhex(hex_bytes))
    assert math.isnan(decoded)
    assert ValueCodec.encode(DataType.FLOAT, decoded) == bytes.fromhex("000000000000f87f")
    assert ValueCodec.encode(DataType.FLOAT, float("nan")) == bytes.fromhex("000000000000f87f")


@pytest.mark.parametrize(
    "value", ["área 東京", "e\u0301", "😀" * 2000, "x" * 65536],
    ids=["unicode", "combining", "larger_than_page", "long_ascii"],
)
def test_unicode_and_long_strings_use_byte_lengths(value):
    payload = ValueCodec.encode(DataType.VARCHAR, value)
    assert int.from_bytes(payload[:4], "little") == len(value.encode("utf-8"))
    assert ValueCodec.decode(DataType.VARCHAR, payload) == value


@pytest.mark.parametrize("value", ["\ud800", "\udfff", "a\ud800b"])
def test_lone_surrogates_are_not_encodable(value):
    with pytest.raises(ValidationError, match="UTF-8") as error:
        ValueCodec.encode(DataType.VARCHAR, value)
    assert isinstance(error.value.__cause__, UnicodeEncodeError)


@pytest.mark.parametrize("body", [b"\xff", b"\xc3", b"\xc0\x80", b"\xed\xa0\x80", b"\xf4\x90\x80\x80"])
def test_invalid_utf8_is_wrapped_in_a_domain_error(body):
    payload = struct.pack("<I", len(body)) + body
    with pytest.raises(ValidationError, match="UTF-8") as error:
        ValueCodec.decode(DataType.VARCHAR, payload)
    assert isinstance(error.value.__cause__, UnicodeDecodeError)


@pytest.mark.parametrize("byte", [2, 3, 127, 128, 255])
def test_non_boolean_byte_is_rejected(byte):
    with pytest.raises(ValidationError, match="BOOLEAN"):
        ValueCodec.decode(DataType.BOOLEAN, bytes([byte]))


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        (DataType.INTEGER, True), (DataType.INTEGER, 1.0), (DataType.INTEGER, "1"),
        (DataType.FLOAT, 1), (DataType.FLOAT, True), (DataType.FLOAT, "1.0"),
        (DataType.BOOLEAN, 0), (DataType.BOOLEAN, 1), (DataType.BOOLEAN, "true"),
        (DataType.VARCHAR, b"text"), (DataType.VARCHAR, 1),
    ] + [(data_type, None) for data_type in DataType],
)
def test_no_implicit_conversions_or_null(data_type, value):
    with pytest.raises(InvalidTypeError):
        ValueCodec.encode(data_type, value)


@pytest.mark.parametrize(
    ("data_type", "base", "value"),
    [(DataType.INTEGER, int, 1), (DataType.FLOAT, float, 1.0), (DataType.VARCHAR, str, "a")],
)
def test_scalar_subclasses_are_rejected(data_type, base, value):
    custom_type = type("CustomScalar", (base,), {})
    with pytest.raises(InvalidTypeError):
        ValueCodec.encode(data_type, custom_type(value))


@pytest.mark.parametrize("data_type", [None, "INTEGER", 1, True, [], {}])
def test_invalid_data_type_is_rejected_before_dispatch(data_type):
    with pytest.raises(InvalidTypeError):
        ValueCodec.encode(data_type, 1)
    with pytest.raises(InvalidTypeError):
        ValueCodec.decode(data_type, bytes(8))


@pytest.mark.parametrize("payload", [None, "", [], 8, bytearray(8), memoryview(bytes(8))])
def test_decode_requires_immutable_bytes(payload):
    with pytest.raises(InvalidTypeError):
        ValueCodec.decode(DataType.INTEGER, payload)


@pytest.mark.parametrize(
    ("data_type", "payload"),
    [(DataType.INTEGER, bytes(8)), (DataType.FLOAT, bytes(8)),
     (DataType.BOOLEAN, b"\x01"), (DataType.VARCHAR, b"\x02\x00\x00\x00ab")],
)
def test_every_truncated_prefix_is_rejected(data_type, payload):
    for length in range(len(payload)):
        with pytest.raises(ValidationError, match="Truncated"):
            ValueCodec.decode(data_type, payload[:length])


@pytest.mark.parametrize("payload", [b"\xff\xff\xff\xff", b"\xff\xff\xff\xffabc", b"\x05\x00\x00\x00ab"])
def test_varchar_length_is_checked_before_reading_body(payload):
    with pytest.raises(ValidationError, match="Truncated"):
        ValueCodec.decode(DataType.VARCHAR, payload)


@pytest.mark.parametrize(
    ("data_type", "value"),
    [(DataType.INTEGER, -2), (DataType.FLOAT, 1.25), (DataType.BOOLEAN, True),
     (DataType.VARCHAR, "á"), (DataType.VARCHAR, "")],
)
def test_decode_from_respects_offset_and_leaves_remaining_data(data_type, value):
    encoded = ValueCodec.encode(data_type, value)
    buffer = b"prefix" + encoded + b"tail"
    recovered, end = ValueCodec.decode_from(data_type, buffer, 6)
    assert recovered == value
    assert type(recovered) is type(value)
    assert end == 6 + len(encoded)
    assert buffer[end:] == b"tail"
    with pytest.raises(ValidationError, match="Trailing"):
        ValueCodec.decode(data_type, encoded + b"tail")


@pytest.mark.parametrize("offset", [-1, 9, 2**100])
def test_decode_from_rejects_out_of_buffer_offsets(offset):
    with pytest.raises(ValidationError, match="offset"):
        ValueCodec.decode_from(DataType.INTEGER, bytes(8), offset)


@pytest.mark.parametrize("offset", [True, False, 0.0, "0", None])
def test_decode_from_requires_an_integer_offset(offset):
    with pytest.raises(InvalidTypeError):
        ValueCodec.decode_from(DataType.INTEGER, bytes(8), offset)


def test_offset_at_end_is_valid_position_but_has_no_complete_value():
    with pytest.raises(ValidationError, match="Truncated"):
        ValueCodec.decode_from(DataType.INTEGER, bytes(8), 8)


def test_varchar_uint32_encoding_limit_without_allocating_gigabytes(monkeypatch):
    # Exercise the length guard using a small local test limit only.
    monkeypatch.setattr("engine.storage.value_codec.UINT32_MAX", 3)
    assert ValueCodec.encode(DataType.VARCHAR, "abc") == b"\x03\x00\x00\x00abc"
    with pytest.raises(ValidationError, match="uint32"):
        ValueCodec.encode(DataType.VARCHAR, "áá")
