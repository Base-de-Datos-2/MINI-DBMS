"""Public HTTP acceptance of Block 4B/5 using real sealed SPIMI/Heap files."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.database import Database
from api.engine_service import EngineService
from engine.text import TextIndex
from tests.text.test_sealing import DEFINITION, create_sealed_database


def _publish(root):
    create_sealed_database(root)
    with TextIndex.open(root / 'text_index') as index:
        entry = dict(table='documentos', column='contenido',
                     collection_id=index.collection_id, generation=index.generation,
                     directory='text_index')
    (root / 'text_tables.json').write_text(json.dumps({'version': 1, 'collections': [entry]}), encoding='utf-8')


def _sql(client, statement, **options):
    response = client.post('/api/query', json={'sql': statement, **options})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('model', ['BM25', 'TF_IDF'])
@pytest.mark.parametrize('indexed', [True, False])
def test_http_sql_real_reopen_and_explain(tmp_path, model, indexed):
    _publish(tmp_path)
    sql = ("SELECT *, SCORE() AS relevancia FROM documentos "
           "WHERE MATCH(contenido, 'base datos') USING " + model +
           " ORDER BY relevancia DESC LIMIT 3")
    snapshots = []
    for _ in range(2):
        service = EngineService(Database.open(DEFINITION, tmp_path))
        try:
            with TestClient(create_app(service)) as client:
                result = _sql(client, sql, use_indexes=indexed)
                assert result['rows']
                assert [r[-1] for r in result['rows']] == sorted((r[-1] for r in result['rows']), reverse=True)
                assert result['execution_plan']['runtime']['name'] == ('TextIndexScan' if indexed else 'TextScan')
                prepared = _sql(client, 'EXPLAIN ' + sql, use_indexes=indexed)
                assert prepared['rows'] == []
                assert prepared['execution_plan']['prepared']['root']['children'][0]['name'] == ('TextIndexScan' if indexed else 'TextScan')
                analyzed = _sql(client, 'EXPLAIN ANALYZE ' + sql, use_indexes=indexed)
                assert analyzed['plan_status'] == 'execution-observed'
                snapshots.append(result['rows'])
        finally:
            service.close()
    assert snapshots[0] == snapshots[1]


def test_http_text_panel_endpoint_matches_sql_and_two_sessions(tmp_path):
    _publish(tmp_path)
    service = EngineService(Database.open(DEFINITION, tmp_path), allow_writes=True)
    try:
        with TestClient(create_app(service)) as client:
            published = client.get('/api/text/tables')
            assert published.status_code == 200, published.text
            assert any(c['table'] == 'documentos' for c in published.json())
            request = dict(table='documentos', column='contenido', query='base datos', model='BM25', limit=3)
            answer = client.post('/api/text/query', json=request)
            assert answer.status_code == 200, answer.text
            assert answer.json()['rows']
            assert answer.json()['model'] == 'BM25'
            assert answer.json()['plan']['operator']
            # A second reader can execute the same published collection concurrently.
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(client.post, '/api/text/query', json=request) for _ in range(2)]
                responses = [future.result() for future in futures]
            assert all(r.status_code == 200 for r in responses)
            assert responses[0].json()['rows'] == responses[1].json()['rows']
            # Sealed tables reject writes while the unrelated mutable table is writable.
            blocked = client.post('/api/query', json={'sql': "INSERT INTO documentos VALUES (999, 'forbidden')"})
            assert blocked.status_code >= 400
            assert _sql(client, "INSERT INTO mutable VALUES (2, 'allowed')")['affected_rows'] == 1
    finally:
        service.close()


def test_http_required_assignment_first_query(tmp_path):
    _publish(tmp_path)
    service = EngineService(Database.open(DEFINITION, tmp_path))
    try:
        with TestClient(create_app(service)) as client:
            response = _sql(client, "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10")
            assert [c['name'] for c in response['columns']] == ['id', 'contenido']
            assert response['statement'] == 'SELECT'
    finally:
        service.close()
