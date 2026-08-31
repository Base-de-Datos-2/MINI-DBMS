"""Standalone metadata validation without requiring registered tables."""

from dataclasses import FrozenInstanceError, fields

import pytest

from engine.catalog import Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata


@pytest.fixture
def schema():
    return Schema([Column("id", DataType.INTEGER)])


def test_table_metadata_preserves_name_and_schema(schema):
    table = TableMetadata("Students", schema)
    assert table.name == "Students"
    assert table.schema is schema
    assert {field.name for field in fields(table)} == {"name", "schema"}


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_table_rejects_blank_name(schema, name):
    with pytest.raises(ValueError, match="Table name"):
        TableMetadata(name, schema)


@pytest.mark.parametrize("name", [None, 1, True, b"table", []])
def test_table_rejects_non_string_name(schema, name):
    with pytest.raises(TypeError, match="Table name"):
        TableMetadata(name, schema)


@pytest.mark.parametrize("invalid_schema", [None, [], {}, "schema", 1])
def test_table_requires_schema(invalid_schema):
    with pytest.raises(TypeError, match="Table schema"):
        TableMetadata("students", invalid_schema)


def test_table_accepts_empty_schema():
    assert len(TableMetadata("empty", Schema([])).schema) == 0


def test_table_metadata_is_immutable(schema):
    table = TableMetadata("students", schema)
    with pytest.raises(FrozenInstanceError):
        table.name = "other"
    with pytest.raises(FrozenInstanceError):
        table.schema = Schema([])
    with pytest.raises(FrozenInstanceError):
        table.schema.column("id").name = "other"


def test_table_equality_uses_name_and_schema(schema):
    assert TableMetadata("students", schema) == TableMetadata("students", Schema(list(schema)))
    assert TableMetadata("students", schema) != TableMetadata("Students", schema)
    assert TableMetadata("students", schema) != TableMetadata("students", Schema([]))


def test_index_types_have_stable_values():
    assert IndexType.BPLUS.value == "BPLUS"
    assert IndexType.EXTENDIBLE_HASH.value == "EXTENDIBLE_HASH"
    assert len(IndexType.__members__) == 2


@pytest.mark.parametrize(
    ("index_type", "clustered"),
    [(IndexType.BPLUS, False), (IndexType.BPLUS, True), (IndexType.EXTENDIBLE_HASH, False)],
)
def test_index_metadata_describes_supported_strategies(index_type, clustered):
    index = IndexMetadata("idx_id", "students", "id", index_type, clustered)
    assert index.name == "idx_id"
    assert index.table_name == "students"
    assert index.column_name == "id"
    assert index.index_type is index_type
    assert index.clustered is clustered
    assert {field.name for field in fields(index)} == {
        "name", "table_name", "column_name", "index_type", "clustered"
    }


def test_index_is_unclustered_by_default():
    assert IndexMetadata("idx", "students", "id", IndexType.BPLUS).clustered is False


@pytest.mark.parametrize("field", ["name", "table_name", "column_name"])
@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_index_rejects_blank_names(field, name):
    arguments = dict(name="idx", table_name="students", column_name="id", index_type=IndexType.BPLUS)
    arguments[field] = name
    with pytest.raises(ValueError, match="must not be empty"):
        IndexMetadata(**arguments)


@pytest.mark.parametrize("field", ["name", "table_name", "column_name"])
@pytest.mark.parametrize("name", [None, 1, True, [], b"id"])
def test_index_rejects_non_string_names(field, name):
    arguments = dict(name="idx", table_name="students", column_name="id", index_type=IndexType.BPLUS)
    arguments[field] = name
    with pytest.raises(TypeError, match="must be a string"):
        IndexMetadata(**arguments)


@pytest.mark.parametrize("index_type", ["BPLUS", "EXTENDIBLE_HASH", None, 1, DataType.INTEGER])
def test_index_rejects_non_enum_strategy(index_type):
    with pytest.raises(TypeError, match="IndexType member"):
        IndexMetadata("idx", "students", "id", index_type)


@pytest.mark.parametrize("clustered", [None, 0, 1, "true", []])
def test_index_requires_boolean_clustered_flag(clustered):
    with pytest.raises(TypeError, match="clustered must be a boolean"):
        IndexMetadata("idx", "students", "id", IndexType.BPLUS, clustered)


def test_extendible_hash_cannot_be_marked_clustered():
    with pytest.raises(ValueError, match="Only BPLUS"):
        IndexMetadata("idx", "students", "id", IndexType.EXTENDIBLE_HASH, True)


def test_metadata_preserves_names_exactly(schema):
    assert TableMetadata(" Students ", schema).name == " Students "
    index = IndexMetadata(" IDX ", " Students ", " ID ", IndexType.BPLUS)
    assert (index.name, index.table_name, index.column_name) == (" IDX ", " Students ", " ID ")


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("name", "other"), ("table_name", "other"), ("column_name", "other"),
     ("index_type", IndexType.EXTENDIBLE_HASH), ("clustered", True)],
)
def test_index_metadata_is_immutable(field, replacement):
    index = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    with pytest.raises(FrozenInstanceError):
        setattr(index, field, replacement)


def test_index_equality_uses_definition():
    index = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    assert index == IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    assert index != IndexMetadata("idx", "students", "id", IndexType.BPLUS, True)
