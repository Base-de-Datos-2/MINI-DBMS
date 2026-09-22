"""Stage 8 Task 8.5: exact handwritten one-statement control grammar."""

import pytest

from engine.query.ast import (
    BeginTransactionStatement,
    EndTransactionStatement,
    RollbackStatement,
)
from engine.query.errors import SqlSyntaxError, SqlUnsupportedError
from engine.query.parser import parse_sql
from engine.query import QueryEnvironment, SqlEngine
from engine.catalog import Catalog


@pytest.mark.parametrize(
    ("sql", "kind", "lexeme"),
    [
        ("-- before\r\nbEgIn TrAnSaCtIoN; -- after", BeginTransactionStatement,
         "bEgIn TrAnSaCtIoN;"),
        (" end transaction ", EndTransactionStatement, "end transaction"),
        ("/* unsupported */", None, None),
        ("ROLLBACK; -- done", RollbackStatement, "ROLLBACK;"),
    ],
)
def test_control_ast_spans_and_case(sql, kind, lexeme):
    if kind is None:
        with pytest.raises(SqlSyntaxError):
            parse_sql(sql)
        return
    statement = parse_sql(sql)
    assert isinstance(statement, kind)
    assert sql[statement.span.start:statement.span.end] == lexeme


@pytest.mark.parametrize(
    "sql",
    [
        "BEGIN", "BEGIN WORK", "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE",
        "END", "END WORK", "ROLLBACK TRANSACTION", "ROLLBACK TO SAVEPOINT x",
        "COMMIT", "START TRANSACTION", "BEGIN TRANSACTION;;",
        "BEGIN TRANSACTION; INSERT INTO t VALUES (1)",
        "ROLLBACK; SELECT * FROM t",
    ],
)
def test_malformed_or_unsupported_controls_fail_complete_input(sql):
    with pytest.raises(SqlSyntaxError):
        parse_sql(sql)


def test_legacy_sql_engine_refuses_controls_before_planning_or_effects():
    engine = SqlEngine(QueryEnvironment(Catalog()))
    for sql in ("BEGIN TRANSACTION", "END TRANSACTION", "ROLLBACK"):
        with pytest.raises(SqlUnsupportedError, match="database session"):
            engine.prepare(sql)
        with pytest.raises(SqlUnsupportedError, match="database session"):
            engine.execute(sql)
