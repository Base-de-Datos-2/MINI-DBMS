"""SQL-to-published-text adapter acceptance with controlled in-memory doubles."""
from dataclasses import dataclass
from types import SimpleNamespace
import pytest

from api.text_sql import is_text_statement, run_text_sql
from engine.catalog import Column, DataType, Schema
from engine.query.parser import parse_sql
from engine.query.errors import SqlBindingError


@dataclass
class Hit:
    rid: int
    score: float


@dataclass
class FakeReport:
    access: str
    elapsed_seconds: float


class FakeRecord:
    def __init__(self, values):
        self.values = values
    def __getitem__(self, name):
        return self.values[name]


class FakeDatabase:
    def __init__(self):
        self._tables = {'documentos': object()}
        self._schema = Schema([Column('id', DataType.INTEGER), Column('contenido', DataType.VARCHAR)])
        self._catalog = SimpleNamespace(get_table=lambda name: SimpleNamespace(schema=self._schema))
        self._text_indexes = {'documentos': SimpleNamespace(id_column='id', text_column='contenido')}
        self._storages = {'documentos': SimpleNamespace(read=lambda rid: FakeRecord(
            {1: {'id': 1, 'contenido': 'base'}, 2: {'id': 2, 'contenido': 'base de datos'}}[rid]))}
        self.calls = []
    def text_search(self, table, column, query, *, model, order, limit, use_indexes, session):
        self.calls.append((table, column, query, model, order, limit, use_indexes, session))
        hits = (Hit(2, 0.9), Hit(1, 0.2))
        if order in ('score_asc', 'id_asc'):
            hits = hits[::-1]
        if limit is not None:
            hits = hits[:limit]
        return SimpleNamespace(hits=hits, report=FakeReport(access='TextIndex' if use_indexes else 'TextScan', elapsed_seconds=.01))


def run(sql, **options):
    db = FakeDatabase()
    parsed = parse_sql(sql)
    assert is_text_statement(parsed)
    body = run_text_sql(db, parsed, source=sql, session='reader',
                        use_indexes=options.get('use_indexes', True), max_rows=options.get('max_rows', 10))
    return db, body


def test_assignment_first_example():
    db, body = run("SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;")
    assert [col['name'] for col in body['columns']] == ['id', 'contenido']
    assert body['rows'] == [[2, 'base de datos'], [1, 'base']]
    assert db.calls[0][3:6] == ('TF_IDF', 'score_desc', 10)


def test_assignment_second_example():
    db, body = run("SELECT *, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'machine learning') USING BM25 ORDER BY relevancia DESC;")
    assert [c['name'] for c in body['columns']] == ['id', 'contenido', 'relevancia']
    assert body['rows'] == [[2, 'base de datos', .9], [1, 'base', .2]]
    assert body['columns'][-1]['type'] == 'FLOAT'


def test_ascending_before_limit_and_scan():
    db, body = run("SELECT id, SCORE() r FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY r LIMIT 1", use_indexes=False)
    assert body['rows'] == [[1, .2]]
    assert db.calls[0][4:7] == ('score_asc', 1, False)


def test_explain_does_not_execute():
    db, body = run("EXPLAIN SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25")
    assert db.calls == []
    assert body['explanation']['model'] == 'BM25'
    assert body['execution_plan']['prepared']['root']['name'] == 'TextRank'


def test_explain_analyze_executes_once():
    db, body = run("EXPLAIN ANALYZE SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 1")
    assert len(db.calls) == 1
    assert body['explanation']['rows_returned'] == 1


def test_preview_truncation():
    _, body = run("SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25", max_rows=1)
    assert body['truncated'] and body['total_rows'] is None and body['returned_rows'] == 1


@pytest.mark.parametrize('sql', [
    "SELECT SCORE() FROM documentos",
    "SELECT id FROM documentos USING BM25",
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING bogus",
    "SELECT id FROM documentos WHERE MATCH(id, 'base') USING BM25",
    "SELECT SCORE() AS id, id FROM documentos WHERE MATCH(contenido, 'base') USING BM25",
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY contenido",
])
def test_invalid_semantics(sql):
    with pytest.raises(SqlBindingError):
        run(sql)
