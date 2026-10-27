"""SQL-created demo tables share persistent storage, locks and spatial lifecycle."""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from api.database import Database
from api.engine_service import EngineService
from scripts.setup_spatial import SPATIAL_DATABASE, prepare

DDL = "CREATE TABLE locales (id INTEGER PRIMARY KEY, nombre VARCHAR(40), latitud FLOAT, longitud FLOAT)"

def query(http, sql, **options):
    return http.post('/api/query', json={'sql': sql, **options})

def test_sql_create_insert_spatial_rollback_delete_and_reopen(tmp_path):
    root = tmp_path / 'demo'
    prepare(root)
    for reopen in (False, True):
        service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
        try:
            with TestClient(create_app(service)) as http:
                if not reopen:
                    response = query(http, DDL)
                    assert response.status_code == 200, response.text
                    assert response.json()['kind'] == 'definition'
                    assert 'locales' in http.get('/api/health').json()['tables']
                    assert query(http, "INSERT INTO locales VALUES (1, 'Centro', -12.0464, -77.0428)").status_code == 200
                    token = http.post('/api/sessions').json()['token']
                    headers = {'X-Session-Token': token}
                    for sql in ('BEGIN TRANSACTION', "INSERT INTO locales VALUES (2, 'Temporal', -12.05, -77.04)", 'ROLLBACK'):
                        response = http.post('/api/query', json={'sql': sql}, headers=headers)
                        assert response.status_code == 200, response.text
                assert 'locales' in {t['table'] for t in http.get('/api/spatial/tables').json()}
                for kind, extra in (
                    ('radius', {'center': [-12.0464, -77.0428], 'radius': 1000}),
                    ('knn', {'center': [-12.0464, -77.0428], 'k': 10}),
                    ('polygon', {'vertices': [[-12.06,-77.06],[-12.06,-77.02],[-12.03,-77.02],[-12.03,-77.06]]}),
                ):
                    response = http.post('/api/spatial/query', json={'table': 'locales', 'kind': kind, **extra})
                    assert response.status_code == 200, response.text
                    assert [p['id'] for p in response.json()['matches']] == [1]
                for sql in (
                    'SELECT * FROM locales WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 1000',
                    'SELECT * FROM locales ORDER BY distancia(ubicacion, POINT(-12.0464, -77.0428)) LIMIT 5',
                ):
                    response = query(http, sql)
                    assert response.status_code == 200, response.text
                    assert response.json()['rows'] == [[1, 'Centro', -12.0464, -77.0428]]
                assert query(http, "INSERT INTO locales VALUES (1, 'Repetido', -12.0464, -77.0428)").status_code != 200
                assert query(http, "INSERT INTO locales VALUES (3, '" + 'a'*41 + "', -12.0464, -77.0428)").status_code != 200
                assert query(http, "INSERT INTO locales VALUES (3, 'Fuera', 0.0, 0.0)").status_code != 200
                if reopen:
                    assert query(http, 'DELETE FROM locales WHERE id = 1').status_code == 200
                    assert http.post('/api/spatial/query', json={'table':'locales', 'kind':'knn', 'center':[-12.0464,-77.0428], 'k':10}).json()['matches'] == []
        finally:
            service.close()


def test_sql_create_policy_errors_and_nonspatial_types(tmp_path):
    root = tmp_path / 'demo'
    prepare(root)
    for writes in (False, True):
        service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=writes)
        try:
            with TestClient(create_app(service)) as http:
                response = query(http, 'CREATE TABLE pruebas (id INT PRIMARY KEY, valor FLOAT, activo BOOLEAN)')
                if not writes:
                    assert response.status_code == 403
                    continue
                assert response.status_code == 200, response.text
                assert query(http, 'INSERT INTO pruebas VALUES (1, 2.5, TRUE)').status_code == 200
                assert query(http, 'SELECT * FROM pruebas').json()['rows'] == [[1, 2.5, True]]
                assert query(http, 'CREATE TABLE pruebas (id INT)').status_code != 200
                assert query(http, 'CREATE TABLE mal (id INT, id INT)').status_code != 200
                assert query(http, 'CREATE TABLE claves (a INT PRIMARY KEY, b INT PRIMARY KEY)').status_code != 200
                assert 'pruebas' not in {t['table'] for t in http.get('/api/spatial/tables').json()}
        finally:
            service.close()


def test_failed_spatial_import_is_not_published(tmp_path):
    from api.database import NewTable
    from engine.catalog import DataType
    from engine.errors import ValidationError
    root = tmp_path / 'demo'
    prepare(root)
    with Database.open(SPATIAL_DATABASE, root) as db:
        spec = NewTable('invalidos', (('id',DataType.INTEGER), ('latitud',DataType.FLOAT), ('longitud',DataType.FLOAT)))
        with pytest.raises(ValidationError):
            db.create_gui_table(spec, [(1,0.0,0.0)])
        assert 'invalidos' not in db.table_names()
        with pytest.raises(KeyError):
            db.spatial_mapping_for('invalidos')
    with Database.open(SPATIAL_DATABASE, root) as db:
        assert 'invalidos' not in db.table_names()


def test_registry_failure_cleans_table_and_spatial_files(tmp_path, monkeypatch):
    import api.database as owner
    from api.schemas import QueryRequest
    root = tmp_path / 'demo'
    prepare(root)
    before = {p.name for p in root.iterdir()}
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        def refuse(*args):
            raise OSError('injected registry failure')
        with monkeypatch.context() as patch:
            patch.setattr(owner, 'write_registry', refuse)
            with pytest.raises(OSError, match='injected'):
                service.execute(QueryRequest(sql=DDL), 'failure')
        assert 'locales' not in service.health()['tables']
        assert 'locales' not in {t['table'] for t in service.list_spatial_tables()}
        assert {p.name for p in root.iterdir()} == before
        response = service.execute(QueryRequest(sql=DDL), 'retry')
        assert response['kind'] == 'definition'
    finally:
        service.close()


def test_explicit_transaction_create_does_not_publish(tmp_path):
    root = tmp_path / 'demo'
    prepare(root)
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            token = http.post('/api/sessions').json()['token']
            headers = {'X-Session-Token': token}
            assert http.post('/api/query', json={'sql':'BEGIN TRANSACTION'}, headers=headers).status_code == 200
            assert http.post('/api/query', json={'sql':DDL}, headers=headers).status_code != 200
            assert 'locales' not in http.get('/api/health').json()['tables']
    finally:
        service.close()
