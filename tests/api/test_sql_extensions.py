"""SQL DDL/DML extensions are persisted and coordinated by the demo owner."""
from fastapi.testclient import TestClient
from api.app import create_app
from api.database import Database
from api.engine_service import EngineService
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


def query(http, sql):
    return http.post('/api/query', json={'sql': sql})


def test_create_index_update_drop_and_persistence(tmp_path):
    root = tmp_path / 'demo'
    prepare(root)
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            assert query(http, 'CREATE TABLE sqlx (id INTEGER PRIMARY KEY, name VARCHAR(40), score FLOAT)').status_code == 200
            assert query(http, "INSERT INTO sqlx VALUES (1, 'Ana', 2.0)").status_code == 200
            assert query(http, "INSERT INTO sqlx VALUES (2, 'Luis', 3.0)").status_code == 200
            created = query(http, 'CREATE INDEX ix_score ON sqlx (score)')
            assert created.status_code == 200, created.text
            updated = query(http, "UPDATE sqlx SET score = 4.0, name = 'Bea' WHERE id = 2")
            assert updated.status_code == 200, updated.text
            assert updated.json()['affected_rows'] == 1
            assert query(http, 'SELECT * FROM sqlx ORDER BY id').json()['rows'] == [
                [1, 'Ana', 2.0], [2, 'Bea', 4.0]
            ]
    finally:
        service.close()

    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            assert query(http, 'SELECT * FROM sqlx ORDER BY id').json()['rows'] == [
                [1, 'Ana', 2.0], [2, 'Bea', 4.0]
            ]
            assert any(index.name == 'ix_score' for index in service._database.describe_table('sqlx').indexes)
            dropped_index = query(http, 'DROP INDEX ix_score')
            assert dropped_index.status_code == 200, dropped_index.text
            dropped_table = query(http, 'DROP TABLE sqlx')
            assert dropped_table.status_code == 200, dropped_table.text
            assert 'sqlx' not in service.health()['tables']
    finally:
        service.close()
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        assert 'sqlx' not in service.health()['tables']
    finally:
        service.close()


def test_unique_index_and_update_constraint_are_enforced(tmp_path):
    root = tmp_path / 'demo'
    prepare(root)
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            assert query(http, 'CREATE TABLE uq (id INTEGER PRIMARY KEY, code INTEGER)').status_code == 200
            assert query(http, 'INSERT INTO uq VALUES (1, 10)').status_code == 200
            assert query(http, 'INSERT INTO uq VALUES (2, 20)').status_code == 200
            assert query(http, 'CREATE UNIQUE INDEX uq_code ON uq (code)').status_code == 200
            assert query(http, 'UPDATE uq SET code = 10 WHERE id = 2').status_code >= 400
            assert query(http, 'SELECT * FROM uq ORDER BY id').json()['rows'] == [[1, 10], [2, 20]]
            assert query(http, 'DROP INDEX __pk__uq').status_code >= 400
    finally:
        service.close()


def test_update_rebuilds_spatial_index_and_keeps_coordinates_queryable(tmp_path):
    from scripts.setup_lima import prepare_lima
    from api.database import Database
    from engine.spatial.geometry import Point
    from scripts.setup_spatial import SPATIAL_DATABASE

    root = tmp_path / 'lima'
    prepare_lima(root)
    service = EngineService(Database.open(SPATIAL_DATABASE, root), allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            updated = query(http, "UPDATE lugares_lima SET nombre = 'Museo actualizado' WHERE id = 13")
            assert updated.status_code == 200, updated.text
            assert updated.json()['affected_rows'] == 1
            row = query(http, 'SELECT * FROM lugares_lima WHERE id = 13')
            assert row.status_code == 200 and row.json()['rows'][0][1] == 'Museo actualizado'
            nearest = http.post('/api/spatial/query', json={
                'table': 'lugares_lima', 'kind': 'knn',
                'center': [-12.0463851, -77.0427655], 'k': 1,
            })
            assert nearest.status_code == 200, nearest.text
            assert nearest.json()['matches'][0]['record']['nombre'] == 'Museo actualizado'
    finally:
        service.close()
