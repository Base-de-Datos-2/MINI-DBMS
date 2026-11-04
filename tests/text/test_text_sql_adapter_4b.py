"""Native binding/execution acceptance, replacing the former fake API adapter."""
from pathlib import Path
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from api.database import Database, DatabaseDefinition
from api.engine_service import EngineService
from api.schemas import QueryRequest
from engine.query.errors import SqlBindingError
from engine.query.planner import StalePlanError
from engine.text import TextIndex
from engine.errors import ValidationError
from engine.transactions.errors import TransactionAbortError
from scripts.setup_text import prepare

FIRST = "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;"
SECOND = "SELECT *, SCORE() as relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;"


@pytest.fixture
def database(tmp_path):
    root = tmp_path / 'database'
    prepare(root)
    with Database.open(DatabaseDefinition('text'), root) as db:
        yield db


def rows(db, sql, **options):
    with db.engine.execute(sql, **options) as result:
        return [row.values for row in result]


def test_both_literal_assignment_queries_execute_natively(database):
    assert rows(database, FIRST)
    answer = rows(database, SECOND)
    assert answer and all(isinstance(row[-1], float) for row in answer)
    assert [r[-1] for r in answer] == sorted((r[-1] for r in answer), reverse=True)


@pytest.mark.parametrize('model', ['TF_IDF', 'BM25'])
@pytest.mark.parametrize('order', ['', 'ORDER BY r DESC', 'ORDER BY r ASC', 'ORDER BY r',
    'ORDER BY id ASC', 'ORDER BY id DESC', 'ORDER BY r DESC, id ASC'])
def test_native_scan_index_and_hidden_id_order_equivalence(database, model, order):
    sql = f"SELECT SCORE() r FROM documentos WHERE MATCH(contenido, 'base datos') USING {model} {order} LIMIT 2"
    assert rows(database, sql, use_indexes=True) == rows(database, sql, use_indexes=False)


def test_prepare_reuse_explain_and_analyze_use_native_operator(database, monkeypatch):
    import engine.text.operators as operators
    real = operators.search_text
    calls = []
    def counted(*args, **kwargs):
        calls.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(operators, 'search_text', counted)
    query = database.engine.prepare(SECOND)
    assert query.describe().name == 'TextIndexScan'
    assert not calls
    database.engine.execute('EXPLAIN ' + SECOND)
    assert not calls
    for _ in range(2):
        with query.execute() as result:
            assert list(result)
    assert len(calls) == 2
    analysis = database.engine.execute('EXPLAIN ANALYZE ' + SECOND)
    assert analysis.statistics.root.name == 'TextIndexScan'
    details = dict(analysis.statistics.root.details)
    assert details['model'] == 'BM25'
    assert details['selection'] == 'ExternalSort'
    assert int(details['candidates_scored']) > 0
    assert len(calls) == 3


@pytest.mark.parametrize('sql', [
    "SELECT SCORE() FROM documentos",
    "SELECT id FROM documentos USING BM25",
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING bogus",
    "SELECT id FROM documentos WHERE MATCH(id, 'base') USING BM25",
    "SELECT SCORE() AS id, id FROM documentos WHERE MATCH(contenido, 'base') USING BM25",
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY contenido",
    "SELECT id FROM documentos WHERE MATCH(contenido, 'base') OR id = 1 USING BM25",
    "SELECT COUNT(*) FROM documentos WHERE MATCH(contenido, 'base') USING BM25",
    "SELECT x.id FROM documentos d WHERE MATCH(d.contenido, 'base') USING BM25",
])
def test_invalid_native_semantics(database, sql):
    with pytest.raises(SqlBindingError):
        database.engine.prepare(sql)


def test_empty_limit_zero_aliases_and_preview(database):
    assert rows(database, FIRST.replace('LIMIT 10', 'LIMIT 0')) == []
    assert rows(database, FIRST.replace('base de datos vectorial', 'zzzzunknown')) == []
    assert rows(database, "SELECT d.id FROM documentos d WHERE MATCH(d.contenido, 'base') USING BM25")
    service = EngineService(database)
    result = service.execute(QueryRequest(sql=FIRST, max_rows=1), 'preview')
    assert result['truncated'] and result['returned_rows'] == 1


def test_stale_native_plan_rejects_replaced_registration(database):
    query = database.engine.prepare(FIRST)
    env = database._environment
    env.unregister_text('documentos')
    with pytest.raises(StalePlanError):
        query._spec.validate()
    # Managed sessions rebind changed generations before execution.
    with pytest.raises(SqlBindingError):
        query.execute()


def test_two_native_sessions_reuse_same_generation(database):
    with database.open_session() as first, database.open_session() as second:
        def read(session):
            with session.execute(SECOND) as result:
                return [row.values for row in result]
        with ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(read, (first, second)))
    assert answers[0] == answers[1] and answers[0]


def test_cancelled_native_text_query_rolls_back_and_releases_session(database, monkeypatch):
    import engine.text.operators as operators
    from engine.operators.context import cancellation_point
    original = operators.search_text
    with database.open_session() as session:
        def cancel(*args, **kwargs):
            session.cancel()
            cancellation_point()
            return original(*args, **kwargs)
        monkeypatch.setattr(operators, 'search_text', cancel)
        with pytest.raises(TransactionAbortError, match='cancelled'):
            with session.execute(FIRST) as result:
                list(result)
        monkeypatch.setattr(operators, 'search_text', original)
        with session.execute(FIRST) as result:
            assert list(result)


def test_publication_is_exclusive_and_survives_fresh_process(tmp_path):
    root = tmp_path / 'published'
    prepare(root)
    before = (root / 'text_tables.json').read_bytes()
    with pytest.raises(FileExistsError):
        prepare(root)
    assert (root / 'text_tables.json').read_bytes() == before
    script = """
import json,sys
from api.database import Database,DatabaseDefinition
with Database.open(DatabaseDefinition('text'),sys.argv[1]) as db:
    output=[]
    for sql in json.loads(sys.argv[2]):
        with db.engine.execute(sql) as result:
            output.append([row.values for row in result])
    print(json.dumps(output))
"""
    result = subprocess.run([sys.executable, '-B', '-c', script, str(root), json.dumps([FIRST, SECOND])],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert all(json.loads(result.stdout))
    with Database.open(DatabaseDefinition('text'), root) as db:
        assert db.describe_table('documentos').indexes[-1].index_type == 'SPIMI'


def test_csv_is_streamed_and_sealed(tmp_path):
    csv = tmp_path / 'docs.csv'
    csv.write_text('id,body\n1,alpha beta\n2,beta gamma\n', encoding='utf-8')
    root = tmp_path / 'csv-db'
    prepare(root, csv_path=csv, table='notes', text_column='body')
    with Database.open(DatabaseDefinition('text'), root) as db:
        assert rows(db, "SELECT id FROM notes WHERE MATCH(body, 'beta') USING BM25 ORDER BY id") == [(1,), (2,)]
        assert db._storages['notes'].read_only


def test_failed_publication_never_exposes_registry(tmp_path, monkeypatch):
    import engine.text
    root = tmp_path / 'failed'
    def fail(*args, **kwargs):
        raise RuntimeError('injected sealing failure')
    monkeypatch.setattr(engine.text, 'seal_text_collection', fail)
    with pytest.raises(RuntimeError, match='injected'):
        prepare(root)
    assert not (root / 'text_tables.json').exists()


def test_partial_open_failure_closes_readers_and_releases_owner(tmp_path, monkeypatch):
    root = tmp_path / 'partial'
    prepare(root)
    registry = root / 'text_tables.json'
    original = registry.read_text()
    payload = json.loads(original)
    payload['collections'][1]['generation'] = 'wrong-generation'
    registry.write_text(json.dumps(payload))
    opened = []
    real = TextIndex.open
    def tracked(*args, **kwargs):
        index = real(*args, **kwargs)
        opened.append(index)
        return index
    monkeypatch.setattr(TextIndex, 'open', tracked)
    with pytest.raises(ValidationError):
        Database.open(DatabaseDefinition('text'), root)
    assert opened and all(index._closed for index in opened)
    registry.write_text(original)
    with Database.open(DatabaseDefinition('text'), root) as db:
        assert rows(db, FIRST)


def test_text_launcher_requires_publication_and_excludes_spatial(tmp_path):
    from api.__main__ import main
    with pytest.raises(SystemExit, match='setup_text.py'):
        main(['--text', '--data-dir', str(tmp_path / 'missing'), '--port', '0'])
    with pytest.raises(SystemExit):
        main(['--text', '--spatial'])


def test_secondary_indexes_are_sealed_by_publication(tmp_path):
    from api.database import NewTable, NewIndex
    from engine.catalog import DataType, IndexType
    from engine.errors import ReadOnlyError
    root = tmp_path / 'secondary'
    spec = NewTable('docs', (('id', DataType.INTEGER), ('body', DataType.VARCHAR)),
                    indexes=(NewIndex('id', IndexType.BPLUS, name='docs_id'),))
    Database.prepare_text(root, [(spec, iter([(1, 'alpha beta'), (2, 'beta')]), 'id', 'body')])
    with Database.open(DatabaseDefinition('text'), root) as db:
        assert db._indexes['docs_id'].read_only
        with pytest.raises(ReadOnlyError):
            db.engine.execute("INSERT INTO docs VALUES (3, 'new')")
        assert rows(db, "SELECT id FROM docs WHERE MATCH(body, 'beta') USING BM25 ORDER BY id") == [(1,), (2,)]


def test_standalone_sql_engine_borrows_text_generation_without_http(database):
    from engine.query import SqlEngine
    engine = SqlEngine(database._environment)
    try:
        with engine.execute(SECOND) as result:
            assert list(result)
    finally:
        engine.close()
    # Closing a consumer must not close the owner's permanent readers.
    assert rows(database, SECOND)
