import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.storage import Record, SequentialOrdering


@pytest.mark.parametrize(
    ("data_type", "values"),
    [
        (DataType.INTEGER, [-2, 0, 7]),
        (DataType.FLOAT, [float("-inf"), -0.0, 3.5, float("inf")]),
        (DataType.BOOLEAN, [False, True]),
        (DataType.VARCHAR, ["A", "a", "á", "😀"]),
    ],
)
def test_extract_and_compare_every_adopted_key_type(data_type, values, no_file_io):
    schema = Schema([Column("key", data_type), Column("label", DataType.VARCHAR)])
    ordering = SequentialOrdering(schema, "key")

    with no_file_io():
        extracted = [ordering.extract(Record(schema, [value, "row"])) for value in values]
        comparisons = [
            ordering.compare(left, right)
            for left, right in zip(values, values[1:])
        ]

    assert extracted == values
    assert comparisons == [-1] * (len(values) - 1)
    assert ordering.schema == schema
    assert ordering.key_column == "key"
    assert ordering.data_type is data_type


def test_comparator_is_reflexive_antisymmetric_and_transitive():
    schema = Schema([Column("id", DataType.INTEGER)])
    ordering = SequentialOrdering(schema, "id")

    for value in (-4, 0, 9):
        assert ordering.compare(value, value) == 0
    assert ordering.compare(-4, 0) == -ordering.compare(0, -4) == -1
    assert ordering.compare(-4, 0) < 0
    assert ordering.compare(0, 9) < 0
    assert ordering.compare(-4, 9) < 0


def test_stable_insertion_position_is_after_all_equal_keys():
    schema = Schema([Column("id", DataType.INTEGER)])
    ordering = SequentialOrdering(schema, "id")

    assert ordering.insertion_position([], 2) == 0
    assert ordering.insertion_position([2, 2], 2) == 2
    assert ordering.insertion_position([1, 2, 2, 4], 2) == 3
    assert ordering.insertion_position([1, 2, 2, 4], 0) == 0
    assert ordering.insertion_position([1, 2, 2, 4], 5) == 4


def test_ordering_rejects_unknown_column_record_schema_and_invalid_sequences():
    schema = Schema([Column("id", DataType.INTEGER)])
    with pytest.raises(SchemaError, match="not in the schema"):
        SequentialOrdering(schema, "missing")
    with pytest.raises(InvalidTypeError):
        SequentialOrdering([], "id")
    with pytest.raises(InvalidTypeError):
        SequentialOrdering(schema, 0)

    ordering = SequentialOrdering(schema, "id")
    with pytest.raises(InvalidTypeError):
        ordering.extract([1])
    with pytest.raises(SchemaError):
        ordering.extract(Record(Schema([Column("other", DataType.INTEGER)]), [1]))
    with pytest.raises(InvalidTypeError):
        ordering.insertion_position("123", 2)
    with pytest.raises(ValidationError, match="nondecreasing"):
        ordering.insertion_position([2, 1], 3)


@pytest.mark.parametrize(
    ("data_type", "invalid"),
    [
        (DataType.INTEGER, True),
        (DataType.INTEGER, 1.0),
        (DataType.FLOAT, 1),
        (DataType.BOOLEAN, 1),
        (DataType.VARCHAR, b"text"),
    ],
)
def test_ordering_rejects_mixed_or_coerced_key_types(data_type, invalid):
    schema = Schema([Column("key", data_type)])
    ordering = SequentialOrdering(schema, "key")

    with pytest.raises(InvalidTypeError):
        ordering.validate_key(invalid)
    with pytest.raises(InvalidTypeError):
        ordering.compare(invalid, invalid)


def test_float_ordering_rejects_nan_but_accepts_infinities():
    schema = Schema([Column("key", DataType.FLOAT)])
    ordering = SequentialOrdering(schema, "key")

    with pytest.raises(ValidationError, match="NaN"):
        ordering.validate_key(float("nan"))
    with pytest.raises(ValidationError, match="NaN"):
        ordering.extract(Record(schema, [float("nan")]))
    assert ordering.compare(float("-inf"), float("inf")) < 0
    assert math.isinf(ordering.validate_key(float("inf")))
