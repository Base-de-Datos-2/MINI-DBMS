"""Ordering, lookup, validation, and immutability of relational schemas."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import Column, DataType, Schema


@pytest.fixture
def columns():
    return [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("active", DataType.BOOLEAN),
    ]


@pytest.fixture
def schema(columns):
    return Schema(columns)


def test_schema_preserves_column_order(schema, columns):
    assert schema.columns == tuple(columns)
    assert len(schema) == 3
    assert list(schema) == columns


def test_schema_accepts_tuple_input(columns):
    assert Schema(tuple(columns)).columns == tuple(columns)


@pytest.mark.parametrize(("name", "position"), [("id", 0), ("name", 1), ("active", 2)])
def test_schema_lookup_by_name_and_position(schema, columns, name, position):
    assert schema.column(name) is columns[position]
    assert schema.column(position) is columns[position]
    assert schema.index_of(name) == position


def test_schema_rejects_non_adjacent_duplicate_names():
    with pytest.raises(ValueError, match="Duplicate column name: 'id'"):
        Schema([
            Column("id", DataType.INTEGER),
            Column("name", DataType.VARCHAR),
            Column("id", DataType.FLOAT),
        ])


def test_schema_rejects_repeated_column_object(columns):
    with pytest.raises(ValueError, match="Duplicate column name"):
        Schema([columns[0], columns[0]])


def test_schema_names_are_exact_and_case_sensitive():
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("ID", DataType.FLOAT),
        Column(" id ", DataType.VARCHAR),
    ])
    assert schema.index_of("id") == 0
    assert schema.index_of("ID") == 1
    assert schema.index_of(" id ") == 2
    with pytest.raises(KeyError, match="Unknown column"):
        schema.column("Id")


@pytest.mark.parametrize("name", ["missing", "", "NAME", " name "])
def test_schema_reports_unknown_column(schema, name):
    with pytest.raises(KeyError, match="Unknown column"):
        schema.column(name)
    with pytest.raises(KeyError, match="Unknown column"):
        schema.index_of(name)


@pytest.mark.parametrize("position", [-1, -3, 3, 100])
def test_schema_rejects_out_of_range_positions(schema, position):
    with pytest.raises(IndexError, match="Column position out of range"):
        schema.column(position)


@pytest.mark.parametrize("selector", [None, 1.0, True, False, [], slice(0, 1)])
def test_schema_rejects_invalid_selectors(schema, selector):
    with pytest.raises(TypeError, match="Column selector"):
        schema.column(selector)


@pytest.mark.parametrize("name", [None, 0, True, [], b"id"])
def test_schema_index_of_requires_a_string(schema, name):
    with pytest.raises(TypeError, match="Column name"):
        schema.index_of(name)


@pytest.mark.parametrize("entry", [None, "id", DataType.INTEGER, 1, {"name": "id"}])
def test_schema_rejects_non_column_entries(columns, entry):
    with pytest.raises(TypeError, match="Every schema entry"):
        Schema([columns[0], entry])


@pytest.mark.parametrize("value", [None, 1, "id", "", b"id", bytearray(), {}, set()])
def test_schema_requires_a_sequence_of_columns(value):
    with pytest.raises(TypeError, match="sequence of Column objects"):
        Schema(value)


def test_schema_copies_input_sequence(schema, columns):
    original = tuple(columns)
    columns.reverse()
    columns[0] = Column("other", DataType.FLOAT)
    columns.append(Column("extra", DataType.VARCHAR))
    assert schema.columns == original
    assert schema.index_of("id") == 0
    assert len(schema) == 3


def test_schema_columns_cannot_be_reassigned(schema):
    with pytest.raises(FrozenInstanceError):
        schema.columns = ()


def test_schema_columns_cannot_be_mutated(schema):
    with pytest.raises(TypeError):
        schema.columns[0] = Column("other", DataType.FLOAT)
    with pytest.raises(FrozenInstanceError):
        schema.column(0).name = "other"


def test_empty_schema_is_supported():
    schema = Schema([])
    assert len(schema) == 0
    assert schema.columns == ()
    assert list(schema) == []
    with pytest.raises(KeyError):
        schema.column("id")
    with pytest.raises(IndexError):
        schema.column(0)


def test_schema_equality_uses_ordered_column_definitions(columns):
    assert Schema(columns) == Schema(list(columns))
    assert Schema(columns) != Schema(list(reversed(columns)))
    assert Schema(columns) != Schema([Column("id", DataType.FLOAT)])
