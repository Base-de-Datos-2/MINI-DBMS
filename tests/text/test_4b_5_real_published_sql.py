"""End-to-end Block 4B acceptance using a real sealed Heap and SPIMI files.

No fake indexes or in-memory ranking substitutes are involved.
"""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from api.database import Database
from api.text_sql import run_text_sql
from engine.query.parser import parse_sql
from engine.text import TextIndex
from tests.text.test_sealing import DEFINITION, create_sealed_database


def published(tmp_path):
    create_sealed_database(tmp_path)
    with TextIndex.open(tmp_path / 'text_index') as index:
        entry = {'table': 'documentos', 'column': 'contenido',
                 'collection_id': index.collection_id,
                 'generation': index.generation, 'directory': 'text_index'}
    (tmp_path / 'text_tables.json').write_text(json.dumps(
        {'version': 1, 'collections': [entry]}), encoding='utf-8')


def query(db, sql, *, use_indexes=True, max_rows=20, session=None):
    return run_text_sql(db, parse_sql(sql), source=sql, session=session,
                        use_indexes=use_indexes, max_rows=max_rows)


SQL = "SELECT *, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'base datos') USING BM25 ORDER BY relevancia DESC LIMIT 3;"


@pytest.mark.parametrize('model', ['BM25', 'TF_IDF'])
@pytest.mark.parametrize('use_indexes', [True, False])
def test_real_reopen_ranked_sql_and_explain(tmp_path, model, use_indexes):
    published(tmp_path)
    sql = SQL.replace('BM25', model)
    with Database.open(DEFINITION, tmp_path) as db:
        result = query(db, sql, use_indexes=use_indexes)
        assert result['rows']
        assert all(isinstance(row[-1], float) for row in result['rows'])
        assert [row[-1] for row in result['rows']] == sorted(
            (row[-1] for row in result['rows']), reverse=True)
        assert result['execution_plan']['runtime']['name'] == ('TextIndexScan' if use_indexes else 'TextScan')
        assert query(db, 'EXPLAIN ' + sql)['rows'] == []
        assert query(db, 'EXPLAIN ANALYZE ' + sql)['plan_status'] == 'execution-observed'
        expected = result['rows']
    with Database.open(DEFINITION, tmp_path) as db:
        assert query(db, sql, use_indexes=use_indexes)['rows'] == expected
        assert db._storages['documentos'].read_only
        assert not db._storages['mutable'].read_only


def test_two_independent_reader_sessions_same_sealed_generation(tmp_path):
    published(tmp_path)
    with Database.open(DEFINITION, tmp_path) as db:
        # The immutable index can be read concurrently without moving RIDs.
        with db.open_session() as first, db.open_session() as second:
            def read(session):
                return query(db, SQL, session=session)['rows']
            with ThreadPoolExecutor(max_workers=2) as pool:
                left, right = pool.map(read, (first, second))
        assert left == right and left


def test_real_first_assignment_sql_and_preview(tmp_path):
    published(tmp_path)
    with Database.open(DEFINITION, tmp_path) as db:
        sql = "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;"
        result = query(db, sql)
        assert [col['name'] for col in result['columns']] == ['id', 'contenido']
        preview = query(db, SQL, max_rows=1)
        assert len(preview['rows']) == 1
        assert preview['truncated']


def test_explain_access_node_matches_selected_execution_strategy(tmp_path):
    published(tmp_path)
    with Database.open(DEFINITION, tmp_path) as db:
        for indexed, expected in ((True, 'TextIndexScan'), (False, 'TextScan')):
            planned = query(db, 'EXPLAIN ' + SQL, use_indexes=indexed)
            root = planned['execution_plan']['prepared']['root']
            assert root['name'] == 'TextTopK'
            assert root['children'][0]['name'] == expected
            assert root['children'][0]['details'][-1]['value'] == 'BM25'
            observed = query(db, SQL, use_indexes=indexed)
            assert observed['execution_plan']['runtime']['name'] == expected


def test_real_sql_score_ascending_and_id_sort(tmp_path):
    published(tmp_path)
    with Database.open(DEFINITION, tmp_path) as db:
        ascending = query(db, SQL.replace('DESC LIMIT 3', 'ASC LIMIT 3'))
        assert [row[-1] for row in ascending['rows']] == sorted(row[-1] for row in ascending['rows'])
        by_id = query(db, SQL.replace('ORDER BY relevancia DESC', 'ORDER BY id ASC'))
        assert [row[0] for row in by_id['rows']] == sorted(row[0] for row in by_id['rows'])
