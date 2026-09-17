"""Tasks 7.3-7.4: source spans shared by tokens and AST nodes."""

from dataclasses import FrozenInstanceError, fields

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.query.ast import BoolAnd, Comparison, SelectStatement, SyntaxNode
from engine.query.parser import parse_sql
from engine.query.source import SourceSpan


def test_source_span_is_validated_and_immutable():
    span = SourceSpan(0, 6, 1, 1, 1, 7)
    assert span.position == 1

    with pytest.raises(FrozenInstanceError):
        span.start = 2  # type: ignore[misc]
    with pytest.raises(InvalidTypeError):
        SourceSpan(True, 1, 1, 1, 1, 2)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        SourceSpan(4, 3, 1, 5, 1, 4)


def test_source_span_cover_uses_the_outer_half_open_range():
    first = SourceSpan(2, 5, 1, 3, 1, 6)
    last = SourceSpan(8, 10, 2, 1, 2, 3)

    assert SourceSpan.cover(first, last) == SourceSpan(2, 10, 1, 3, 2, 3)


def test_parser_assigns_spans_to_statement_clauses_and_expressions():
    sql = "SELECT t.id AS chosen FROM things t WHERE a = 1 AND b = 2;"
    statement = parse_sql(sql)

    assert isinstance(statement, SelectStatement)
    assert statement.span is not None
    assert sql[statement.span.start : statement.span.end] == sql
    assert statement.items[0].span is not None
    assert sql[
        statement.items[0].span.start : statement.items[0].span.end
    ] == "t.id AS chosen"
    assert statement.from_table.span is not None
    assert sql[
        statement.from_table.span.start : statement.from_table.span.end
    ] == "things t"
    assert isinstance(statement.where, BoolAnd)
    assert statement.where.span is not None
    assert sql[statement.where.span.start : statement.where.span.end] == "a = 1 AND b = 2"
    assert isinstance(statement.where.left, Comparison)
    assert statement.where.left.left.span is not None
    assert sql[
        statement.where.left.left.span.start : statement.where.left.left.span.end
    ] == "a"


def test_spans_do_not_change_structural_ast_equality():
    first = parse_sql("SELECT * FROM t")
    second = parse_sql("  SELECT * FROM t;")

    assert first == second
    assert first.span != second.span


@pytest.mark.parametrize(
    "sql",
    [
        (
            "SELECT s.id, COUNT(*) AS n FROM students s "
            "JOIN grades g ON s.id = g.student_id "
            "WHERE NOT (g.score < 3 OR g.score > 5) "
            "GROUP BY s.id ORDER BY n DESC;"
        ),
        "INSERT INTO students (id, name) VALUES (1, 'Ana');",
        "DELETE FROM students WHERE id = 1;",
        "DELETE FROM students;",
    ],
)
def test_every_parser_created_syntax_node_has_a_span(sql):
    root = parse_sql(sql)

    def walk(value):
        if isinstance(value, SyntaxNode):
            yield value
            for syntax_field in fields(value):
                if syntax_field.name != "span":
                    yield from walk(getattr(value, syntax_field.name))
        elif isinstance(value, tuple):
            for item in value:
                yield from walk(item)

    nodes = list(walk(root))
    assert nodes
    assert all(node.span is not None for node in nodes)
    assert all(node.span.start < node.span.end for node in nodes if node.span)
