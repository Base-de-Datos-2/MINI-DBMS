"""4B incremental parser contract tests (not execution acceptance)."""
import pytest
from engine.query.ast import SelectStatement, TextMatch, FunctionCall
from engine.query.parser import parse_sql
from engine.query.errors import SqlSyntaxError

@pytest.mark.parametrize('sql,model', [
    ("SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;", 'TF_IDF'),
    ("SELECT *, SCORE() AS relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;", 'BM25'),
    ("SELECT id FROM documentos d WHERE (MATCH(d.contenido, 'l''árbol')) USING bm25", 'BM25'),
])
def test_accept_textual_syntax(sql, model):
    statement = parse_sql(sql)
    assert isinstance(statement, SelectStatement)
    assert isinstance(statement.where, TextMatch)
    assert statement.text_model == model


def test_score_expression():
    stmt = parse_sql("SELECT SCORE() FROM documentos WHERE MATCH(contenido, 'base') USING BM25")
    assert isinstance(stmt.items[0].expr, FunctionCall)
    assert stmt.items[0].expr.function == 'SCORE'

@pytest.mark.parametrize('sql', [
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base')",
    "SELECT id FROM documentos WHERE MATCH(contenido, 123) USING BM25",
    "SELECT SCORE(1) FROM documentos WHERE MATCH(contenido, 'base') USING BM25",
])
def test_reject_invalid_textual_syntax(sql):
    with pytest.raises(SqlSyntaxError):
        parse_sql(sql)
