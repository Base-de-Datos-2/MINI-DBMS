"""Validation and immutability of individual column definitions."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import Column, DataType


@pytest.mark.parametrize("data_type", list(DataType))
def test_create_column_with_each_supported_type(data_type):
    column = Column("value", data_type)
    assert column.name == "value"
    assert column.data_type is data_type


@pytest.mark.parametrize("name", ["", " ", "\t\n", "\u00a0"])
def test_column_rejects_blank_names(name):
    with pytest.raises(ValueError, match="Column name"):
        Column(name, DataType.INTEGER)


@pytest.mark.parametrize("name", [None, 1, True, b"id", []])
def test_column_rejects_non_string_names(name):
    with pytest.raises(TypeError, match="Column name"):
        Column(name, DataType.INTEGER)


@pytest.mark.parametrize("data_type", ["INTEGER", int, None, 1, True])
def test_column_rejects_invalid_types_without_coercion(data_type):
    with pytest.raises(TypeError, match="DataType member"):
        Column("id", data_type)


@pytest.mark.parametrize("name", ["ID", " id ", "nombre completo", "año"])
def test_column_preserves_name_exactly(name):
    assert Column(name, DataType.INTEGER).name == name


@pytest.mark.parametrize(
    ("attribute", "replacement"),
    [("name", "renamed"), ("data_type", DataType.FLOAT)],
)
def test_column_is_immutable(attribute, replacement):
    column = Column("id", DataType.INTEGER)
    with pytest.raises(FrozenInstanceError):
        setattr(column, attribute, replacement)


def test_column_equality_uses_name_and_type():
    assert Column("id", DataType.INTEGER) == Column("id", DataType.INTEGER)
    assert Column("id", DataType.INTEGER) != Column("ID", DataType.INTEGER)
    assert Column("id", DataType.INTEGER) != Column("id", DataType.FLOAT)
