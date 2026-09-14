"""Task 6.6: typed expression binding and evaluation without SQL or eval."""

import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.operators import (
    And,
    ColumnReference,
    Compare,
    ComparisonOperator,
    Literal,
    Not,
    Or,
    RowLayout,
    column,
    compare_values,
    data_type_of,
    validate_comparable,
)
from engine.storage import Record
from tests.operator_helpers import ENROLLMENTS, STUDENTS


@pytest.fixture
def layout():
    return RowLayout(STUDENTS, relation="students")


def test_literal_types_are_inferred_without_treating_bool_as_int():
    assert data_type_of(True) is DataType.BOOLEAN
    assert data_type_of(1) is DataType.INTEGER
    assert data_type_of(1.0) is DataType.FLOAT
    assert data_type_of("x") is DataType.VARCHAR
    assert Literal(False).data_type is DataType.BOOLEAN
    with pytest.raises(InvalidTypeError):
        data_type_of(None)
    with pytest.raises(InvalidTypeError):
        Literal(None)


def test_comparison_uses_native_ordering_and_treats_signed_zero_as_equal():
    assert compare_values(DataType.INTEGER, 1, 2) == -1
    assert compare_values(DataType.INTEGER, 2, 2) == 0
    assert compare_values(DataType.INTEGER, 3, 2) == 1
    assert compare_values(DataType.FLOAT, -0.0, 0.0) == 0
    assert compare_values(DataType.BOOLEAN, False, True) == -1
    assert compare_values(DataType.VARCHAR, "Z", "a") == -1
    assert compare_values(DataType.VARCHAR, "a", "A") == 1


def test_infinities_are_comparable_while_nan_is_rejected_everywhere():
    assert compare_values(DataType.FLOAT, math.inf, 1.0) == 1
    assert compare_values(DataType.FLOAT, -math.inf, 1.0) == -1
    assert validate_comparable(DataType.FLOAT, math.inf) == math.inf

    with pytest.raises(ValidationError, match="NaN"):
        compare_values(DataType.FLOAT, math.nan, 1.0)
    with pytest.raises(ValidationError, match="NaN"):
        validate_comparable(DataType.FLOAT, math.nan)
    with pytest.raises(ValidationError, match="NaN"):
        Literal(math.nan)


def test_comparison_refuses_mismatched_types_without_implicit_conversion(layout):
    with pytest.raises(ValidationError, match="Cannot compare INTEGER with FLOAT"):
        Compare(column("age"), ComparisonOperator.EQUAL, 20.0).bind(layout)
    with pytest.raises(ValidationError, match="Cannot compare"):
        Compare(column("age"), ComparisonOperator.EQUAL, True).bind(layout)
    with pytest.raises(ValidationError, match="Cannot compare"):
        Compare(column("name"), ComparisonOperator.LESS, 3).bind(layout)
    with pytest.raises(InvalidTypeError):
        Compare(column("age"), ">", 20)


@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        (ComparisonOperator.EQUAL, [False, False, False, False]),
        (ComparisonOperator.NOT_EQUAL, [True, True, True, True]),
        (ComparisonOperator.LESS, [False, True, False, False]),
        (ComparisonOperator.LESS_OR_EQUAL, [False, True, False, False]),
        (ComparisonOperator.GREATER, [True, False, True, True]),
        (ComparisonOperator.GREATER_OR_EQUAL, [True, False, True, True]),
    ],
)
def test_every_approved_operator_evaluates_over_bound_rows(layout, operator, expected):
    predicate = Compare(column("age"), operator, 20).bind(layout)
    rows = [(1, "Ana", "CS", 22), (2, "Luis", "EE", 19), (3, "Sol", "CS", 24),
            (4, "Omar", "EE", 23)]

    assert [predicate.matches(row) for row in rows] == expected


def test_equal_boundary_values_separate_strict_from_inclusive_operators(layout):
    row = (1, "Ana", "CS", 20)

    assert Compare(column("age"), ComparisonOperator.EQUAL, 20).bind(
        layout
    ).matches(row) is True
    assert Compare(column("age"), ComparisonOperator.GREATER, 20).bind(
        layout
    ).matches(row) is False
    assert Compare(column("age"), ComparisonOperator.GREATER_OR_EQUAL, 20).bind(
        layout
    ).matches(row) is True


def test_two_column_comparison_binds_both_sides(layout):
    predicate = Compare(
        column("name"), ComparisonOperator.EQUAL, column("career")
    ).bind(layout)

    assert predicate.matches((1, "CS", "CS", 22)) is True
    assert predicate.matches((1, "Ana", "CS", 22)) is False


def test_nested_boolean_composition_short_circuits_and_negates(layout):
    predicate = And(
        Compare(column("age"), ComparisonOperator.GREATER, 20),
        Or(
            Compare(column("career"), ComparisonOperator.EQUAL, "CS"),
            Not(Compare(column("name"), ComparisonOperator.EQUAL, "Omar")),
        ),
    ).bind(layout)

    assert predicate.matches((1, "Ana", "CS", 22)) is True
    assert predicate.matches((3, "Sol", "CS", 24)) is True
    assert predicate.matches((4, "Omar", "EE", 23)) is False
    assert predicate.matches((2, "Luis", "EE", 19)) is False


def test_boolean_composition_requires_boolean_terms_and_at_least_two(layout):
    with pytest.raises(ValidationError, match="at least two terms"):
        And(Compare(column("age"), ComparisonOperator.EQUAL, 1))
    with pytest.raises(ValidationError, match="must be BOOLEAN"):
        And(Literal(1), Literal(2)).bind(layout)
    with pytest.raises(ValidationError, match="must be BOOLEAN"):
        Or(Literal("a"), Literal("b")).bind(layout)
    with pytest.raises(ValidationError, match="requires a BOOLEAN term"):
        Not(column("age")).bind(layout)


def test_boolean_columns_are_usable_as_predicates_directly():
    schema = Schema([Column("active", DataType.BOOLEAN)])
    layout = RowLayout(schema, relation="flags")
    predicate = column("active").bind(layout)

    assert predicate.matches((True,)) is True
    assert predicate.matches((False,)) is False


def test_a_non_boolean_expression_cannot_be_used_as_a_predicate(layout):
    value = column("age").bind(layout)

    assert value.evaluate((1, "Ana", "CS", 22)) == 22
    with pytest.raises(ValidationError, match="must be BOOLEAN"):
        value.matches((1, "Ana", "CS", 22))


def test_binding_rejects_unknown_and_ambiguous_columns_before_any_row(layout):
    joined = RowLayout.combine(layout, RowLayout(ENROLLMENTS, relation="enrollments"))

    with pytest.raises(UnknownColumnError):
        column("missing").bind(layout)
    with pytest.raises(ValidationError, match="Ambiguous"):
        column("id").bind(joined)

    qualified = column(ColumnReference("id", "enrollments")).bind(joined)
    assert qualified.evaluate((1, "Ana", "CS", 22, 77, 1, "BD2")) == 77


def test_expressions_bind_only_against_a_layout(layout):
    with pytest.raises(InvalidTypeError):
        column("age").bind(STUDENTS)
    with pytest.raises(InvalidTypeError):
        Literal(1).bind(None)


def test_evaluate_record_accepts_records_and_rejects_short_rows(layout):
    predicate = Compare(column("age"), ComparisonOperator.GREATER, 20).bind(layout)
    record = Record(STUDENTS, [1, "Ana", "CS", 22])

    assert predicate.evaluate_record(record) is True
    with pytest.raises(InvalidTypeError):
        predicate.evaluate_record((1, "Ana", "CS", 22))
    with pytest.raises(ValidationError, match="narrower than the layout"):
        predicate.matches((1, "Ana"))


def test_repr_shows_the_expression_without_exposing_sql_text():
    predicate = And(
        Compare(column("age"), ComparisonOperator.GREATER, 20),
        Not(Literal(True)),
    )

    text = repr(predicate)
    assert "Compare" in text and "ColumnValue('age')" in text and "'>'" in text
    assert "SELECT" not in text
