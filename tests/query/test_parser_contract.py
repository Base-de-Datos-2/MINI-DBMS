"""Tasks 7.5-7.7: frozen recursive-descent parser contract and failures."""

import pytest

from engine.query.ast import (
    BoolAnd,
    BoolNot,
    BoolOr,
    BooleanLiteral,
    ColumnRef,
    Comparison,
    FloatLiteral,
    IntegerLiteral,
    StringLiteral,
)
from engine.query.errors import (
    SqlLexicalError,
    SqlLimitError,
    SqlQueryError,
    SqlSyntaxError,
    SqlUnsupportedError,
)
from engine.query.parser import MAX_PARSE_NESTING, parse_sql


def _comparison(name, operator, value):
    return Comparison(ColumnRef(name), operator, IntegerLiteral(value))


def test_boolean_precedence_matches_the_frozen_grammar_exactly():
    statement = parse_sql(
        "SELECT * FROM t WHERE a = 1 OR b = 2 AND NOT c = 3"
    )

    assert statement.where == BoolOr(
        _comparison("a", "=", 1),
        BoolAnd(
            _comparison("b", "=", 2),
            BoolNot(_comparison("c", "=", 3)),
        ),
    )


def test_parentheses_override_boolean_precedence():
    statement = parse_sql(
        "SELECT * FROM t WHERE (a = 1 OR b = 2) AND c = 3"
    )

    assert statement.where == BoolAnd(
        BoolOr(_comparison("a", "=", 1), _comparison("b", "=", 2)),
        _comparison("c", "=", 3),
    )


def test_signed_numbers_are_literals_and_retain_the_sign_in_their_spans():
    sql = "SELECT * FROM t WHERE a = -12 AND b = +2.5"
    statement = parse_sql(sql)

    assert isinstance(statement.where, BoolAnd)
    negative = statement.where.left.right
    positive = statement.where.right.right
    assert negative == IntegerLiteral(-12)
    assert positive == FloatLiteral(2.5)
    assert sql[negative.span.start : negative.span.end] == "-12"
    assert sql[positive.span.start : positive.span.end] == "+2.5"


def test_signed_literals_are_shared_with_insert():
    statement = parse_sql("INSERT INTO t VALUES (-1, +2.5, 'a,b;c', FALSE)")

    assert statement.values == (
        IntegerLiteral(-1),
        FloatLiteral(2.5),
        StringLiteral("a,b;c"),
        BooleanLiteral(False),
    )


def test_insert_preserves_escaped_quotes_and_sql_separators_inside_strings():
    statement = parse_sql("INSERT INTO t VALUES ('O''Brien,;--text')")

    assert statement.values == (StringLiteral("O'Brien,;--text"),)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t WHERE a = -TRUE",
        "SELECT * FROM t WHERE a = +-1",
        "INSERT INTO t VALUES (-'text')",
    ],
)
def test_sign_is_rejected_outside_one_numeric_literal(sql):
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql(sql)
    assert excinfo.value.span is not None


def test_qualified_references_and_adopted_implicit_aliases_are_unambiguous():
    statement = parse_sql(
        "SELECT s.id chosen, s.* FROM students s "
        "JOIN grades g ON s.id = g.student_id"
    )

    assert statement.items[0].expr == ColumnRef("id", "s")
    assert statement.items[0].alias == "chosen"
    assert statement.items[1].expr.relation == "s"
    assert statement.from_table.alias == "s"
    assert statement.join.table.alias == "g"


def test_repeated_boolean_terms_use_loops_instead_of_recursive_descent():
    predicate = " AND ".join(f"c{i} = {i}" for i in range(600))
    statement = parse_sql(f"SELECT * FROM t WHERE {predicate}")

    assert isinstance(statement.where, BoolAnd)


def test_nesting_limit_accepts_the_boundary_for_not_and_parentheses():
    not_sql = "SELECT * FROM t WHERE " + "NOT " * MAX_PARSE_NESTING + "a = 1"
    paren_sql = (
        "SELECT * FROM t WHERE "
        + "(" * MAX_PARSE_NESTING
        + "a = 1"
        + ")" * MAX_PARSE_NESTING
    )

    assert parse_sql(not_sql).where is not None
    assert parse_sql(paren_sql).where is not None


@pytest.mark.parametrize("wrapper", ["NOT {inner}", "({inner})"])
def test_nesting_limit_above_boundary_is_a_controlled_error(wrapper):
    expression = "a = 1"
    for _ in range(MAX_PARSE_NESTING + 1):
        expression = wrapper.format(inner=expression)

    with pytest.raises(SqlLimitError) as excinfo:
        parse_sql(f"SELECT * FROM t WHERE {expression}")
    assert excinfo.value.span is not None
    assert excinfo.value.position > 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT a, FROM t",
        "SELECT a FROM t GROUP BY a,",
        "SELECT a FROM t ORDER BY a,",
        "INSERT INTO t (a,) VALUES (1)",
        "INSERT INTO t VALUES (1,)",
    ],
)
def test_trailing_commas_are_rejected(sql):
    with pytest.raises(SqlSyntaxError):
        parse_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t WHERE",
        "SELECT * FROM a JOIN b",
        "SELECT * FROM a JOIN b ON",
        "SELECT * FROM t WHERE (a = 1",
        "SELECT * FROM t WHERE a =",
    ],
)
def test_required_tokens_and_operands_report_controlled_eof_errors(sql):
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql(sql)
    assert excinfo.value.offending == "<EOF>"
    assert excinfo.value.span is not None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t WHERE a = 1 ORDER BY a WHERE b = 2",
        "SELECT * FROM t WHERE a = 1 WHERE b = 2",
        "SELECT * FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id",
    ],
)
def test_wrong_order_duplicate_clauses_and_extra_join_are_rejected(sql):
    with pytest.raises(SqlSyntaxError, match="Unexpected or duplicate"):
        parse_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(*) FROM t",
        "SELECT COUNT(1) FROM t",
        "SELECT COUNT(t.*) FROM t",
        "SELECT mystery(a) FROM t",
    ],
)
def test_invalid_or_unsupported_aggregate_forms_are_rejected(sql):
    with pytest.raises(SqlSyntaxError):
        parse_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT DISTINCT a FROM t",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.id",
        "SELECT * FROM t LIMIT 1",
        "SELECT * FROM t WHERE a IN (1)",
        "SELECT * FROM t WHERE a IS NULL",
        "SELECT * FROM t WHERE a = 1 UNION SELECT * FROM u",
        "SELECT * FROM (SELECT * FROM t) nested",
        "SELECT * FROM t WHERE EXISTS (SELECT * FROM u)",
    ],
)
def test_recognized_but_unimplemented_sql_is_reported_as_unsupported(sql):
    with pytest.raises(SqlUnsupportedError) as excinfo:
        parse_sql(sql)
    assert excinfo.value.span is not None


def test_chained_comparison_is_explicitly_rejected():
    with pytest.raises(SqlUnsupportedError, match="Chained comparisons"):
        parse_sql("SELECT * FROM t WHERE a < b < c")


def test_bang_inequality_is_normalized_in_the_ast():
    statement = parse_sql("SELECT * FROM t WHERE a != 1")

    assert statement.where.operator == "<>"


def test_insert_values_reject_column_references():
    with pytest.raises(SqlSyntaxError):
        parse_sql("INSERT INTO t VALUES (other_column)")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t SELECT * FROM u",
        "INSERT INTO t VALUES (1), (2)",
        "INSERT INTO t VALUES (1) RETURNING id",
    ],
)
def test_unsupported_insert_variants_are_classified(sql):
    with pytest.raises(SqlUnsupportedError):
        parse_sql(sql)


def test_delete_uses_shared_predicate_parser_and_adopted_whole_table_policy():
    filtered = parse_sql("DELETE FROM t WHERE a = -1 OR b = 2 AND c = 3")
    whole_table = parse_sql("DELETE FROM t")

    assert isinstance(filtered.where, BoolOr)
    assert isinstance(filtered.where.right, BoolAnd)
    assert whole_table.where is None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM t;;",
        "SELECT * FROM t; SELECT * FROM u",
        "SELECT * FROM t SELECT * FROM u",
    ],
)
def test_submission_requires_exactly_one_statement_and_at_most_one_semicolon(sql):
    with pytest.raises(SqlSyntaxError):
        parse_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN TRANSACTION",
        "COMMIT",
        "ROLLBACK",
        "UPDATE t SET a = 1",
    ],
)
def test_unsupported_statement_families_have_a_distinct_error(sql):
    with pytest.raises(SqlUnsupportedError):
        parse_sql(sql)


def test_syntax_error_exposes_expected_offending_span_line_column_and_context():
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql("SELECT * FROM t\nWHERE = 1")

    error = excinfo.value
    assert error.expected == "a literal or column reference"
    assert error.offending == "="
    assert error.span is not None
    assert (error.line, error.column, error.position) == (2, 7, 23)
    assert error.context == "WHERE = 1"
    assert "line 2, column 7" in str(error)


def test_lexical_error_is_eager_and_uses_the_shared_query_error_hierarchy():
    with pytest.raises(SqlLexicalError) as excinfo:
        parse_sql("SELECT * FROM t; $")

    assert isinstance(excinfo.value, SqlQueryError)
    assert excinfo.value.offending == "$"
    assert excinfo.value.span is not None


def test_block_comments_remain_a_located_lexical_error():
    with pytest.raises(SqlLexicalError) as excinfo:
        parse_sql("SELECT * /* unsupported */ FROM t")
    assert excinfo.value.offending == "/"


def test_parser_state_is_fresh_after_success_and_failure():
    assert parse_sql("SELECT * FROM alpha").from_table.name == "alpha"
    with pytest.raises(SqlSyntaxError):
        parse_sql("SELECT FROM")
    assert parse_sql("SELECT * FROM beta;").from_table.name == "beta"
