"""Stage 7 Task 7.32: CREATE/EXPLAIN syntax and newline diagnostics."""

from dataclasses import fields

import pytest

from engine.catalog import Catalog
from engine.query.ast import (
    ColumnDefinition,
    CreateTableStatement,
    ExplainStatement,
    SelectStatement,
    SyntaxNode,
    TypeSpecification,
)
from engine.query.environment import QueryEnvironment
from engine.query.errors import (
    SqlLexicalError,
    SqlSyntaxError,
    SqlUnknownTableError,
    SqlUnsupportedError,
)
from engine.query.executor import SqlEngine
from engine.query.lexer import TokenType, tokenize
from engine.query.parser import parse_sql


CREATE_ALUMNOS = """-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);"""

ALUMNOS_SUBMISSIONS = (
    CREATE_ALUMNOS,
    """-- 1
SELECT * FROM alumnos
WHERE nombre = 'Pérez, Juan';""",
    """-- 2
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;""",
    """-- 3
SELECT * FROM alumnos
WHERE id = 999;""",
    """-- 4
EXPLAIN
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;""",
    """-- 5
EXPLAIN ANALYZE
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;""",
)


def _walk_syntax(value):
    if isinstance(value, SyntaxNode):
        yield value
        for syntax_field in fields(value):
            if syntax_field.name != "span":
                yield from _walk_syntax(getattr(value, syntax_field.name))
    elif isinstance(value, tuple):
        for item in value:
            yield from _walk_syntax(item)


def test_extension_keywords_are_whole_tokens_and_prefixes_remain_identifiers():
    tokens = tokenize(
        "CREATE TABLE t (id INT PRIMARY KEY, value VARCHAR(3)); "
        "EXPLAIN ANALYZE SELECTED integer_value primary_key"
    )

    keywords = [token.value for token in tokens if token.type is TokenType.KEYWORD]
    assert keywords == [
        "CREATE", "TABLE", "INT", "PRIMARY", "KEY", "VARCHAR",
        "EXPLAIN", "ANALYZE",
    ]
    identifiers = [
        token.value for token in tokens if token.type is TokenType.IDENTIFIER
    ]
    assert identifiers == ["t", "id", "value", "SELECTED", "integer_value", "primary_key"]


def test_create_table_ast_normalizes_types_and_preserves_order_and_spans():
    statement = parse_sql(CREATE_ALUMNOS)

    assert statement == CreateTableStatement(
        "alumnos",
        (
            ColumnDefinition("id", TypeSpecification("INTEGER"), True),
            ColumnDefinition("nombre", TypeSpecification("VARCHAR", 100)),
            ColumnDefinition("carrera_id", TypeSpecification("INTEGER")),
            ColumnDefinition("nota", TypeSpecification("INTEGER")),
        ),
    )
    assert statement.span is not None
    assert CREATE_ALUMNOS[statement.span.start : statement.span.end].startswith(
        "CREATE TABLE"
    )
    assert CREATE_ALUMNOS[statement.span.start : statement.span.end].endswith(";")
    assert CREATE_ALUMNOS[
        statement.columns[0].span.start : statement.columns[0].span.end
    ] == "id INT PRIMARY KEY"
    assert CREATE_ALUMNOS[
        statement.columns[1].data_type.span.start
        : statement.columns[1].data_type.span.end
    ] == "VARCHAR(100)"


def test_create_keywords_are_case_insensitive_but_names_keep_source_case():
    statement = parse_sql(
        "cReAtE tAbLe Alumnos (Id integer primary key, Nombre varchar(7))"
    )

    assert statement.table == "Alumnos"
    assert [column.name for column in statement.columns] == ["Id", "Nombre"]
    assert statement.columns[0].data_type.name == "INTEGER"
    assert statement.columns[1].data_type == TypeSpecification("VARCHAR", 7)


def test_new_keywords_remain_usable_in_existing_identifier_positions():
    statement = parse_sql(
        "SELECT l.key AS primary, analyze FROM left_rows AS l "
        "JOIN right_rows AS r ON l.key = r.key"
    )

    assert statement.items[0].expr.name == "key"
    assert statement.items[0].alias == "primary"
    assert statement.items[1].expr.name == "analyze"
    assert statement.join.on.left.name == "key"
    assert statement.join.on.right.name == "key"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_line_comments_and_source_spans_support_every_newline_style(newline):
    source = f"-- comentario{newline}SELECT * FROM alumnos"
    statement = parse_sql(source)

    assert isinstance(statement, SelectStatement)
    assert statement.span.start_line == 2
    assert statement.span.start_column == 1
    assert statement.from_table.span.start_line == 2


def test_comment_at_eof_and_comment_markers_inside_strings_are_distinct():
    statement = parse_sql(
        "SELECT * FROM alumnos WHERE nombre = 'A; -- B'; -- final"
    )
    only_eof = tokenize("-- comment without newline")

    assert statement.where.right.value == "A; -- B"
    assert len(only_eof) == 1 and only_eof[0].type is TokenType.EOF


def test_cr_only_diagnostic_has_the_correct_line_column_and_excerpt():
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql("-- first\rCREATE TABLE t (\rid INT,\r)")

    error = excinfo.value
    assert (error.line, error.column) == (4, 1)
    assert error.offending == ")"
    assert error.context == ")"


def test_explain_wrappers_keep_the_select_child_and_semicolon_ownership():
    plain_sql = "EXPLAIN\nSELECT * FROM alumnos WHERE id = 999;"
    analyze_sql = (
        "EXPLAIN ANALYZE SELECT * FROM alumnos "
        "WHERE nota >= 14 ORDER BY id;"
    )
    plain = parse_sql(plain_sql)
    analyzed = parse_sql(analyze_sql)

    assert isinstance(plain, ExplainStatement) and plain.analyze is False
    assert isinstance(analyzed, ExplainStatement) and analyzed.analyze is True
    assert isinstance(plain.select, SelectStatement)
    assert plain_sql[plain.select.span.start : plain.select.span.end].endswith("999")
    assert plain_sql[plain.span.start : plain.span.end].endswith(";")
    assert analyze_sql[analyzed.select.span.start : analyzed.select.span.end].endswith(
        "id"
    )


@pytest.mark.parametrize("sql", ALUMNOS_SUBMISSIONS)
def test_every_required_alumnos_submission_parses_as_one_statement(sql):
    statement = parse_sql(sql)

    assert isinstance(statement, (CreateTableStatement, SelectStatement, ExplainStatement))
    nodes = tuple(_walk_syntax(statement))
    assert nodes and all(node.span is not None for node in nodes)
    assert all(node.span.start < node.span.end for node in nodes)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t ()",
        "CREATE TABLE t (id)",
        "CREATE TABLE t (id INT,)",
        "CREATE TABLE t (name VARCHAR)",
        "CREATE TABLE t (name VARCHAR())",
        "CREATE TABLE t (name VARCHAR(0))",
        "CREATE TABLE t (name VARCHAR(-1))",
        "CREATE TABLE t (name VARCHAR(1.5))",
        "CREATE TABLE t (id INT PRIMARY)",
        "CREATE TABLE t (id INT KEY)",
    ],
)
def test_malformed_create_forms_have_controlled_located_syntax_errors(sql):
    with pytest.raises(SqlSyntaxError) as excinfo:
        parse_sql(sql)
    assert excinfo.value.span is not None
    assert excinfo.value.offending is not None


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE INDEX idx ON t (id)",
        "CREATE TABLE t (id TEXT)",
        "CREATE TABLE t (id INT, PRIMARY KEY (id))",
        "EXPLAIN INSERT INTO t VALUES (1)",
        "EXPLAIN ANALYZE DELETE FROM t",
        "EXPLAIN CREATE TABLE t (id INT)",
        "EXPLAIN EXPLAIN SELECT * FROM t",
    ],
)
def test_unsupported_ddl_and_explain_children_are_classified_without_fallback(sql):
    with pytest.raises(SqlUnsupportedError) as excinfo:
        parse_sql(sql)
    assert excinfo.value.span is not None


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (id INT); SELECT * FROM t",
        "EXPLAIN SELECT * FROM t; DELETE FROM t",
        "EXPLAIN ANALYZE SELECT * FROM t; SELECT * FROM t",
    ],
)
def test_extension_statements_reject_a_second_statement(sql):
    with pytest.raises(SqlSyntaxError, match="Only one SQL statement"):
        parse_sql(sql)


def test_empty_comment_only_and_block_comment_inputs_remain_controlled():
    for source in ("", "-- comment", "-- comment\r", "-- comment\r\n"):
        with pytest.raises(SqlSyntaxError) as excinfo:
            parse_sql(source)
        assert excinfo.value.offending == "<EOF>"

    with pytest.raises(SqlLexicalError):
        parse_sql("/* unsupported */ CREATE TABLE t (id INT)")


def test_engine_rejects_create_without_a_manifest_backed_service():
    engine = SqlEngine(QueryEnvironment(Catalog()))
    try:
        with pytest.raises(SqlUnsupportedError, match="manifest-backed"):
            engine.prepare("CREATE TABLE t (id INT)")
        with pytest.raises(SqlUnsupportedError, match="manifest-backed"):
            engine.execute("CREATE TABLE t (id INT)")
        assert engine.active_result is None
    finally:
        engine.close()


@pytest.mark.parametrize(
    "sql",
    [
        "EXPLAIN SELECT * FROM missing",
        "EXPLAIN ANALYZE SELECT * FROM missing",
    ],
)
def test_explain_reaches_semantic_binding_and_reports_unknown_tables(sql):
    engine = SqlEngine(QueryEnvironment(Catalog()))
    try:
        with pytest.raises(SqlUnknownTableError):
            engine.prepare(sql)
        with pytest.raises(SqlUnknownTableError):
            engine.execute(sql)
        assert engine.active_result is None
    finally:
        engine.close()
