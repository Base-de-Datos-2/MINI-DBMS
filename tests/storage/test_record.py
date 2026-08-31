"""Strict row typing, ordered values, and schema-based access."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import Column, DataType, Schema
from engine.storage import Record


@pytest.fixture
def schema():
    return Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("score", DataType.FLOAT),
        Column("active", DataType.BOOLEAN),
    ])


def test_record_preserves_schema_and_ordered_values(schema):
    record = Record(schema=schema, values=[1, "Ana", 9.5, True])
    assert record.schema is schema
    assert record.values == (1, "Ana", 9.5, True)
    assert record["id"] == 1
    assert record["name"] == "Ana"
    assert record["score"] == 9.5
    assert record["active"] is True


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        (DataType.INTEGER, 0), (DataType.INTEGER, -10),
        (DataType.INTEGER, 2**100),
        (DataType.FLOAT, 0.0), (DataType.FLOAT, -1.25),
        (DataType.FLOAT, float("inf")), (DataType.FLOAT, float("-inf")),
        (DataType.FLOAT, float("nan")),
        (DataType.BOOLEAN, True), (DataType.BOOLEAN, False),
        (DataType.VARCHAR, ""), (DataType.VARCHAR, "área 東京"),
    ],
)
def test_record_accepts_exact_builtin_types(data_type, value):
    record = Record(Schema([Column("value", data_type)]), (value,))
    assert record["value"] is value
    assert type(record["value"]) is type(value)


@pytest.mark.parametrize(
    ("data_type", "value"),
    [
        (DataType.INTEGER, True), (DataType.INTEGER, False),
        (DataType.INTEGER, 1.0), (DataType.INTEGER, "123"),
        (DataType.FLOAT, 1), (DataType.FLOAT, True), (DataType.FLOAT, "1.5"),
        (DataType.BOOLEAN, 0), (DataType.BOOLEAN, 1), (DataType.BOOLEAN, "true"),
        (DataType.VARCHAR, b"text"), (DataType.VARCHAR, 12),
        (DataType.VARCHAR, []), (DataType.VARCHAR, {}),
    ] + [(data_type, None) for data_type in DataType],
)
def test_record_rejects_incompatible_types_without_conversion(data_type, value):
    with pytest.raises(TypeError, match=f"Column 'value' requires {data_type.value}"):
        Record(Schema([Column("value", data_type)]), [value])


def test_record_rejects_subclasses_of_scalar_types():
    class CustomInteger(int):
        pass

    with pytest.raises(TypeError, match="requires INTEGER"):
        Record(Schema([Column("id", DataType.INTEGER)]), [CustomInteger(1)])


@pytest.mark.parametrize("values", [[], [1], [1, "Ana", 9.5], [1, "Ana", 9.5, True, 5]])
def test_record_rejects_wrong_value_count(schema, values):
    with pytest.raises(ValueError, match="Record requires 4 values"):
        Record(schema, values)


@pytest.mark.parametrize("values", [None, 1, "", "text", b"text", bytearray(), {}, set()])
def test_record_requires_a_sequence(schema, values):
    with pytest.raises(TypeError, match="values must be a sequence"):
        Record(schema, values)


@pytest.mark.parametrize("schema", [None, [], {}, "schema", Column("id", DataType.INTEGER)])
def test_record_requires_a_schema(schema):
    with pytest.raises(TypeError, match="schema must be a Schema"):
        Record(schema, [])


@pytest.mark.parametrize("name", ["missing", "NAME", " name ", ""])
def test_record_reports_unknown_column(schema, name):
    with pytest.raises(KeyError, match="Unknown column"):
        Record(schema, [1, "Ana", 9.5, True])[name]


@pytest.mark.parametrize("selector", [0, -1, True, None, [], slice(0, 1)])
def test_record_access_requires_a_column_name(schema, selector):
    with pytest.raises(TypeError, match="Column name must be a string"):
        Record(schema, [1, "Ana", 9.5, True])[selector]


def test_record_does_not_share_mutable_input(schema):
    values = [1, "Ana", 9.5, True]
    record = Record(schema, values)
    values[0] = "invalid"
    values.clear()
    assert record.values == (1, "Ana", 9.5, True)


def test_record_is_immutable(schema):
    record = Record(schema, [1, "Ana", 9.5, True])
    with pytest.raises(FrozenInstanceError):
        record.values = ()
    with pytest.raises(FrozenInstanceError):
        record.schema = Schema([])
    with pytest.raises(TypeError):
        record.values[0] = 2


def test_empty_record_matches_empty_schema():
    record = Record(Schema([]), [])
    assert record.values == ()
    with pytest.raises(KeyError):
        record["id"]


def test_record_equality_includes_schema_and_values(schema):
    record = Record(schema, [1, "Ana", 9.5, True])
    assert record == Record(Schema(list(schema)), [1, "Ana", 9.5, True])
    assert record != Record(schema, [2, "Ana", 9.5, True])
    assert Record(Schema([Column("id", DataType.INTEGER)]), [1]) != Record(
        Schema([Column("other", DataType.INTEGER)]), [1]
    )
