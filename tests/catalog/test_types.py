"""Tests for the fixed, minimal set of relational type identifiers."""

import pytest

from engine.catalog import DataType


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (DataType.INTEGER, "INTEGER"),
        (DataType.FLOAT, "FLOAT"),
        (DataType.BOOLEAN, "BOOLEAN"),
        (DataType.VARCHAR, "VARCHAR"),
    ],
)
def test_datatype_has_stable_text_value(member, value):
    assert member.value == value
    assert DataType(value) is member


def test_datatype_members_are_distinct_and_complete():
    assert set(DataType) == {
        DataType.INTEGER,
        DataType.FLOAT,
        DataType.BOOLEAN,
        DataType.VARCHAR,
    }
    assert len(DataType.__members__) == 4
    assert DataType.INTEGER != DataType.FLOAT
    assert DataType.INTEGER != "INTEGER"


@pytest.mark.parametrize("value", ["DATE", "integer", " INTEGER ", "", None, 1])
def test_datatype_rejects_unknown_values_without_normalizing(value):
    with pytest.raises(ValueError):
        DataType(value)
