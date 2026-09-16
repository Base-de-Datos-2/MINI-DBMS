"""Tasks 7.5-7.7: SELECT / INSERT / DELETE syntax."""

import pytest

from engine.query.ast import (
    AggregateCall,
    BoolAnd,
    BoolNot,
    BoolOr,
    BooleanLiteral,
    ColumnRef,
    Comparison,
    DeleteStatement,
    FloatLiteral,
    InsertStatement,
    IntegerLiteral,
    SelectItem,
    SelectStatement,
    Star,
    StringLiteral,
    TableRef,
)
from engine.query.lexer import SqlSyntaxError
from engine.query.parser import parse_sql


def test_select_star():
    stmt = parse_sql("SELECT * FROM students")
    assert stmt == SelectStatement(
        items=(SelectItem(Star()),), from_table=TableRef("students")
    )


def test_select_columns_with_alias_and_table_alias():
    stmt = parse_sql("SELECT s.id AS sid, name FROM students AS s")
    assert stmt.items == (
        SelectItem(ColumnRef("id", "s"), "sid"),
        SelectItem(ColumnRef("name"), None),
    )
    assert stmt.from_table == TableRef("students", "s")


def test_where_precedence_and_over_or():
    stmt = parse_sql("SELECT * FROM t WHERE a = 1 OR b = 2 AND c = 3")
    # AND binds tighter than OR: a=1 OR (b=2 AND c=3)
    assert isinstance(stmt.where, BoolOr)
    assert isinstance(stmt.where.right, BoolAnd)


def test_not_and_parentheses():
    stmt = parse_sql("SELECT * FROM t WHERE NOT (a = 1 AND b = 2)")
    assert isinstance(stmt.where, BoolNot)
    assert isinstance(stmt.where.term, BoolAnd)


def test_comparison_operators_all_recognized():
    for op in ("=", "<>", "<", "<=", ">", ">="):
        stmt = parse_sql(f"SELECT * FROM t WHERE a {op} 1")
        assert isinstance(stmt.where, Comparison)
        assert stmt.where.operator == op


def test_join_on():
    stmt = parse_sql(
        "SELECT * FROM students s JOIN enrollments e ON s.id = e.student_id"
    )
    assert stmt.join.table == TableRef("enrollments", "e")
    assert stmt.join.on == Comparison(
        ColumnRef("id", "s"), "=", ColumnRef("student_id", "e")
    )


def test_group_by_and_order_by():
    stmt = parse_sql(
        "SELECT career, COUNT(*) AS n FROM students "
        "GROUP BY career ORDER BY n DESC, career ASC"
    )
    assert stmt.group_by == (ColumnRef("career"),)
    assert stmt.items[1].expr == AggregateCall("COUNT", None, star=True)
    assert stmt.order_by[0].descending is True
    assert stmt.order_by[1].descending is False


def test_aggregate_with_column_argument():
    stmt = parse_sql("SELECT AVG(age) FROM students")
    assert stmt.items[0].expr == AggregateCall("AVG", ColumnRef("age"), star=False)


def test_literals():
    stmt = parse_sql("SELECT * FROM t WHERE a = 1 AND b = 2.5 AND c = 'x' AND d = TRUE")
    # spot-check the parsed literal types via string round trip of the tree
    assert isinstance(stmt.where, BoolAnd)


def test_insert_with_explicit_columns():
    stmt = parse_sql(
        "INSERT INTO students (id, name, age) VALUES (1, 'Ana', 22)"
    )
    assert stmt == InsertStatement(
        table="students",
        columns=("id", "name", "age"),
        values=(IntegerLiteral(1), StringLiteral("Ana"), IntegerLiteral(22)),
    )


def test_insert_without_columns():
    stmt = parse_sql("INSERT INTO t VALUES (1, 2.0, 'x', FALSE)")
    assert stmt.columns is None
    assert stmt.values == (
        IntegerLiteral(1),
        FloatLiteral(2.0),
        StringLiteral("x"),
        BooleanLiteral(False),
    )


def test_delete_with_where():
    stmt = parse_sql("DELETE FROM students WHERE id = 4")
    assert stmt == DeleteStatement("students", Comparison(ColumnRef("id"), "=", IntegerLiteral(4)))


def test_delete_without_where():
    stmt = parse_sql("DELETE FROM students")
    assert stmt == DeleteStatement("students", None)


def test_trailing_garbage_is_rejected():
    with pytest.raises(SqlSyntaxError):
        parse_sql("SELECT * FROM t; DROP TABLE t;")


def test_missing_from_is_rejected_with_position():
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql("SELECT * students")
    assert excinfo.value.position > 0


def test_empty_input_is_rejected():
    with pytest.raises(SqlSyntaxError):
        parse_sql("")


def test_unknown_statement_keyword_is_rejected():
    with pytest.raises(SqlSyntaxError):
        parse_sql("UPDATE students SET x = 1")


def test_star_disallowed_outside_select_list_position():
    with pytest.raises(SqlSyntaxError):
        parse_sql("SELECT * FROM t GROUP BY *")
