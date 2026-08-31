"""Record framing remains schema-driven and independent from page capacity."""

import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import Record, RecordCodec


@pytest.fixture
def schema():
    return Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("score", DataType.FLOAT),
        Column("active", DataType.BOOLEAN),
    ])


def test_mixed_record_has_expected_bytes_and_reuses_supplied_schema(schema):
    original = Record(schema, [1, "Ana", 1.5, True])
    expected = bytes.fromhex(
        "0100000000000000 03000000416e61 000000000000f83f 01"
    )
    assert RecordCodec.serialize(original) == expected
    recovered = RecordCodec.deserialize(schema, expected)
    assert recovered == original
    assert recovered is not original
    assert recovered.schema is schema
    assert recovered["name"] == "Ana"
    assert recovered.values == (1, "Ana", 1.5, True)
    assert recovered["active"] is True


@pytest.mark.parametrize(
    "values",
    [
        [-(2**63), "área 東京😀", -0.0, False],
        [2**63 - 1, "", float("inf"), True],
        [-1, "a\x00b", float("-inf"), False],
    ],
)
def test_mixed_records_round_trip_boundaries(schema, values):
    original = Record(schema, values)
    recovered = RecordCodec.deserialize(schema, RecordCodec.serialize(original))
    assert recovered == original
    assert math.copysign(1.0, recovered["score"]) == math.copysign(1.0, values[2])


def test_nan_round_trip_uses_nan_semantics_not_record_equality(schema):
    original = Record(schema, [1, "", float("nan"), False])
    payload = RecordCodec.serialize(original)
    recovered = RecordCodec.deserialize(schema, payload)
    assert math.isnan(recovered["score"])
    assert RecordCodec.serialize(recovered) == payload


def test_empty_record_encodes_to_no_bytes():
    schema = Schema([])
    assert RecordCodec.serialize(Record(schema, [])) == b""
    assert RecordCodec.deserialize(schema, b"") == Record(schema, [])
    with pytest.raises(ValidationError, match="Trailing"):
        RecordCodec.deserialize(schema, b"\x00")


def test_encoding_follows_schema_order_not_name_sorting():
    schema = Schema([Column("z", DataType.BOOLEAN), Column("a", DataType.INTEGER)])
    record = Record(schema, [True, 2])
    assert RecordCodec.serialize(record) == bytes.fromhex("01 0200000000000000")
    assert RecordCodec.deserialize(schema, RecordCodec.serialize(record)) == record


def test_codec_does_not_impose_page_capacity():
    schema = Schema([Column("text", DataType.VARCHAR)])
    record = Record(schema, ["😀" * 2000])
    payload = RecordCodec.serialize(record)
    assert len(payload) == 8004
    assert RecordCodec.deserialize(schema, payload) == record


def test_logical_record_still_accepts_ints_that_cannot_be_persisted():
    schema = Schema([Column("id", DataType.INTEGER)])
    record = Record(schema, [2**100])
    assert record["id"] == 2**100
    with pytest.raises(ValidationError, match="64-bit"):
        RecordCodec.serialize(record)
    assert record["id"] == 2**100


def test_logical_string_with_surrogate_is_rejected_only_at_encoding_boundary():
    schema = Schema([Column("text", DataType.VARCHAR)])
    record = Record(schema, ["\ud800"])
    with pytest.raises(ValidationError, match="UTF-8"):
        RecordCodec.serialize(record)


@pytest.mark.parametrize("value", [None, [], (), {}, "record", b"", 1])
def test_serialize_requires_a_record(value):
    with pytest.raises(InvalidTypeError):
        RecordCodec.serialize(value)


@pytest.mark.parametrize("schema", [None, [], (), {}, "schema", 1])
def test_deserialize_requires_a_schema(schema):
    with pytest.raises(InvalidTypeError):
        RecordCodec.deserialize(schema, b"")


@pytest.mark.parametrize("payload", [None, "", [], 0, bytearray(), memoryview(b"")])
def test_deserialize_requires_bytes_even_with_an_empty_schema(payload):
    with pytest.raises(InvalidTypeError):
        RecordCodec.deserialize(Schema([]), payload)


def test_all_truncated_prefixes_of_a_record_are_rejected(schema):
    payload = RecordCodec.serialize(Record(schema, [7, "á😀", -2.5, True]))
    for length in range(len(payload)):
        with pytest.raises(ValidationError, match="Truncated"):
            RecordCodec.deserialize(schema, payload[:length])


@pytest.mark.parametrize("extra", [b"\x00", bytes(8), b"trailing"])
def test_trailing_record_bytes_are_rejected(schema, extra):
    payload = RecordCodec.serialize(Record(schema, [1, "", 1.0, False]))
    with pytest.raises(ValidationError, match="Trailing"):
        RecordCodec.deserialize(schema, payload + extra)


def test_corrupt_boolean_is_rejected_inside_mixed_record(schema):
    payload = RecordCodec.serialize(Record(schema, [1, "", 1.0, False]))
    with pytest.raises(ValidationError, match="BOOLEAN"):
        RecordCodec.deserialize(schema, payload[:-1] + b"\xff")


@pytest.mark.parametrize(
    "bad_string",
    [b"\xff\xff\xff\xff", b"\x01\x00\x00\x00\xff", b"\x02\x00\x00\x00\xc0\x80"],
)
def test_corrupt_string_after_an_integer_is_rejected(bad_string):
    schema = Schema([Column("id", DataType.INTEGER), Column("text", DataType.VARCHAR)])
    with pytest.raises(ValidationError):
        RecordCodec.deserialize(schema, bytes(8) + bad_string)


def test_schema_column_count_mismatch_is_detected():
    schema = Schema([Column("id", DataType.INTEGER)])
    payload = RecordCodec.serialize(Record(schema, [1]))
    with pytest.raises(ValidationError, match="Trailing"):
        RecordCodec.deserialize(Schema([]), payload)
    with pytest.raises(ValidationError, match="Truncated"):
        RecordCodec.deserialize(Schema([*schema, Column("other", DataType.INTEGER)]), payload)


@pytest.mark.parametrize("values", [(), (1,), (1, "Ana", 1.5, True, 9)])
def test_serialize_rechecks_record_count_at_boundary(schema, values):
    record = Record(schema, [1, "Ana", 1.5, True])
    # Deliberately bypass immutability to test the defensive serialization boundary.
    object.__setattr__(record, "values", values)
    with pytest.raises(ValidationError, match="Record requires"):
        RecordCodec.serialize(record)


def test_serialize_rechecks_record_types_at_boundary(schema):
    record = Record(schema, [1, "Ana", 1.5, True])
    object.__setattr__(record, "values", (True, "Ana", 1.5, True))
    with pytest.raises(InvalidTypeError):
        RecordCodec.serialize(record)
