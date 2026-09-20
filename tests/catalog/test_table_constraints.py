"""Stage 7 Task 7.33 logical table constraints and shared row validation."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import (
    MAX_DECLARED_VARCHAR_CODEPOINTS,
    Column,
    ColumnConstraint,
    DataType,
    Schema,
    TableMetadata,
)
from engine.maintenance.validation import build_validated_record, validate_record
from engine.storage import Record


SCHEMA = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
    ]
)


def test_legacy_metadata_remains_unconstrained_and_constructor_compatible():
    table = TableMetadata("students", SCHEMA)

    assert table.constraints == ()
    assert table.primary_key is None
    assert table.varchar_length("name") is None
    validate_record(table, Record(SCHEMA, [1, "x" * 1000]))


def test_constraints_are_immutable_ordered_and_queryable():
    source = [
        ColumnConstraint("id", primary_key=True),
        ColumnConstraint("name", varchar_length=100),
    ]
    table = TableMetadata("students", SCHEMA, source)
    source.clear()

    assert table.primary_key == "id"
    assert table.varchar_length("name") == 100
    assert [item.column_name for item in table.constraints] == ["id", "name"]
    with pytest.raises(FrozenInstanceError):
        table.constraints[0].primary_key = False


@pytest.mark.parametrize("length", [0, -1, 1.5, True, None])
def test_declared_varchar_length_rejects_invalid_values(length):
    arguments = {"varchar_length": length}
    if length is None:
        arguments["primary_key"] = False
    with pytest.raises((TypeError, ValueError)):
        ColumnConstraint("name", **arguments)


def test_declared_varchar_length_has_the_frozen_maximum():
    assert MAX_DECLARED_VARCHAR_CODEPOINTS == 4075
    assert ColumnConstraint(
        "name", varchar_length=MAX_DECLARED_VARCHAR_CODEPOINTS
    ).varchar_length == MAX_DECLARED_VARCHAR_CODEPOINTS
    with pytest.raises(ValueError, match="between 1 and 4075"):
        ColumnConstraint(
            "name", varchar_length=MAX_DECLARED_VARCHAR_CODEPOINTS + 1
        )


def test_table_rejects_duplicate_unknown_incompatible_and_multiple_constraints():
    with pytest.raises(ValueError, match="Duplicate constraints"):
        TableMetadata(
            "students",
            SCHEMA,
            (
                ColumnConstraint("name", varchar_length=3),
                ColumnConstraint("name", primary_key=True),
            ),
        )
    with pytest.raises(ValueError, match="unknown column"):
        TableMetadata(
            "students",
            SCHEMA,
            (ColumnConstraint("missing", primary_key=True),),
        )
    with pytest.raises(ValueError, match="cannot constrain INTEGER"):
        TableMetadata(
            "students",
            SCHEMA,
            (ColumnConstraint("id", varchar_length=3),),
        )
    with pytest.raises(ValueError, match="at most one primary key"):
        TableMetadata(
            "students",
            SCHEMA,
            (
                ColumnConstraint("id", primary_key=True),
                ColumnConstraint("name", varchar_length=3, primary_key=True),
            ),
        )


def test_shared_validator_counts_code_points_before_physical_utf8_bytes():
    table = TableMetadata(
        "students",
        SCHEMA,
        (
            ColumnConstraint("id", primary_key=True),
            ColumnConstraint("name", varchar_length=3),
        ),
    )

    assert build_validated_record(table, [1, "á😀x"]).values == (1, "á😀x")
    with pytest.raises(ValueError, match=r"VARCHAR\(3\)"):
        build_validated_record(table, [1, "á😀xy"])
    with pytest.raises(TypeError, match="requires INTEGER"):
        build_validated_record(table, [None, "ok"])


def test_primary_varchar_also_obeys_the_existing_bplus_byte_limit():
    schema = Schema([Column("code", DataType.VARCHAR)])
    table = TableMetadata(
        "codes",
        schema,
        (ColumnConstraint("code", varchar_length=200, primary_key=True),),
    )

    with pytest.raises(ValueError, match="255-byte"):
        build_validated_record(table, ["é" * 128])
