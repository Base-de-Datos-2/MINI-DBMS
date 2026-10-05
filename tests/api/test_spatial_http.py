from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.database import Database
from api.engine_service import EngineService
from api.schemas import MAX_RESPONSE_BYTES
from api.serialization import encoded_size
from benchmarks.spatial.datasets import FIXTURE_POLYGON
from engine.spatial.metadata import CONVENTIONS, ORIGIN
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


@pytest.fixture
def client(tmp_path):
    directory = tmp_path / "spatial"
    prepare(directory)
    database = Database.open(SPATIAL_DATABASE, directory)
    service = EngineService(database, allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            yield http, service
    finally:
        service.close()


def query(client, sql, token=None, **options):
    headers = {} if token is None else {"X-Session-Token": token}
    return client.post("/api/query", json={"sql": sql, **options}, headers=headers)


def test_spatial_metadata_matches_catalog_and_does_not_mutate_conventions(client):
    http, service = client
    response = http.get("/api/spatial/tables")
    assert response.status_code == 200
    tables = response.json()
    assert {table["table"] for table in tables} == {"tiendas", "restaurantes"}
    for table in tables:
        assert table["row_count"] == service.describe_table(table["table"])["row_count"]
        assert table["location_column"] == "ubicacion"
        assert table["id_column"] == "id"
        assert table["latitude_column"] == "latitud"
        assert table["longitude_column"] == "longitud"
        assert table["conventions"] == CONVENTIONS
    service.list_spatial_tables()[0]["conventions"]["origin"][0] = 0
    assert http.get("/api/spatial/tables").json()[0]["conventions"]["origin"] == list(ORIGIN)


def test_spatial_large_identity_has_the_same_lossless_encoding_as_sql(client):
    http, _ = client
    identity = 9007199254740993
    inserted = query(http, f"INSERT INTO tiendas VALUES ({identity}, 'Identidad grande', {ORIGIN[0]}, {ORIGIN[1]})")
    assert inserted.status_code == 200
    sql = query(http, f"SELECT id FROM tiendas WHERE id = {identity}").json()
    response = http.post("/api/spatial/query", json={"table": "tiendas", "kind": "knn", "center": ORIGIN, "k": 20})
    assert response.status_code == 200
    match = next(hit for hit in response.json()["matches"] if hit["id"] == str(identity))
    assert match["record"]["id"] == sql["rows"][0][0] == str(identity)


def test_finished_spatial_request_returns_an_idle_session(client):
    http, _ = client
    token = http.post("/api/sessions").json()["token"]
    response = http.post("/api/spatial/query", json={"table": "tiendas", "kind": "knn", "center": ORIGIN, "k": 2},
                         headers={"X-Session-Token": token})
    assert response.status_code == 200
    assert response.json()["session"]["busy"] is False
    assert response.json()["session"]["state"] == "IDLE"
    assert response.json()["session"]["transaction"] is None


def test_spatial_sql_parameters_and_measured_plans_use_existing_query_route(client):
    http, _ = client
    sql = "SELECT id FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 2"
    indexed = query(http, sql, parameters={"mi_ubicacion": ORIGIN})
    scanned = query(http, sql, parameters={"mi_ubicacion": ORIGIN}, use_indexes=False)
    assert indexed.status_code == scanned.status_code == 200
    assert indexed.json()["rows"] == scanned.json()["rows"] == [[1], [2]]
    assert "SpatialIndexScan" in str(indexed.json()["execution_plan"])
    assert "SpatialIndexScan" not in str(scanned.json()["execution_plan"])
    assert "SpatialScan" in str(scanned.json()["execution_plan"])
    assert query(http, sql).json()["error"]["code"] == "SQL_ERROR"
    assert query(http, "SELECT id FROM tiendas LIMIT 1").status_code == 200


@pytest.mark.parametrize("kind,geometry", [
    ("radius", {"center": ORIGIN, "radius": 5000}),
    ("knn", {"center": ORIGIN, "k": 5}),
    ("polygon", {"vertices": FIXTURE_POLYGON}),
])
def test_spatial_routes_return_matching_records_coordinates_and_real_statistics(client, kind, geometry):
    http, _ = client
    payload = {"table": "tiendas", "kind": kind, **geometry}
    indexed = http.post("/api/spatial/query", json=payload)
    scanned = http.post("/api/spatial/query", json={**payload, "use_indexes": False})
    assert indexed.status_code == scanned.status_code == 200
    body = indexed.json()
    assert body["matches"] == scanned.json()["matches"]
    assert body["stats"]["access"] == "RTree"
    assert scanned.json()["stats"]["access"] == "SpatialScan"
    assert body["stats"]["base_records_read"] == len(body["matches"])
    assert body["request_id"] == indexed.headers["X-Request-ID"]
    assert all(match["id"] == match["record"]["id"] and match["latitude"] == match["record"]["latitud"]
               for match in body["matches"])
    preview = http.post("/api/spatial/query", json={**payload, "max_rows": 1}).json()
    assert len(preview["matches"]) == 1
    assert preview["truncated"] is True


@pytest.mark.parametrize("geometry", [
    {"kind": "knn"}, {"kind": "radius", "center": ORIGIN},
    {"kind": "knn", "center": [-77, -12]}, {"kind": "polygon", "vertices": [[-12, -77]] * 3},
])
def test_spatial_validation_is_controlled_and_leaves_service_usable(client, geometry):
    http, _ = client
    response = http.post("/api/spatial/query", json={"table": "tiendas", **geometry})
    assert response.status_code == 422
    assert "error" in response.json()
    assert query(http, "SELECT COUNT(*) AS n FROM tiendas").status_code == 200


def test_spatial_reader_waits_for_writer_then_observes_commit_without_global_guard(client):
    http, service = client
    writer = http.post("/api/sessions").json()["token"]
    reader = http.post("/api/sessions").json()["token"]
    assert query(http, "BEGIN TRANSACTION", writer).status_code == 200
    assert query(http, "DELETE FROM tiendas WHERE id = 1", writer).status_code == 200
    payload = {"table": "tiendas", "kind": "radius", "center": ORIGIN, "radius": 0, "inclusive": True}
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(http.post, "/api/spatial/query", json=payload, headers={"X-Session-Token": reader})
        deadline = monotonic() + 3
        while monotonic() < deadline:
            if any(event.action == "wait" for event in service._database.session_coordinator.trace().events):
                break
            sleep(.01)
        assert not future.done()
        assert query(http, "END TRANSACTION", writer).status_code == 200
        response = future.result(timeout=3)
    assert response.status_code == 200
    assert [match["id"] for match in response.json()["matches"]] == [2]
    for token in (writer, reader):
        assert http.delete("/api/session", headers={"X-Session-Token": token}).status_code == 200


def test_spatial_response_byte_cap_keeps_values_and_exact_total():
    value = "x" * 3500
    body = {"matches": [{"id": number, "record": {"nombre": value}} for number in range(500)],
            "total_rows": 500, "returned_rows": 500, "truncated": False}
    result = EngineService._fit(body)
    assert encoded_size(result) <= MAX_RESPONSE_BYTES
    assert result["returned_rows"] == len(result["matches"]) < 500
    assert result["total_rows"] == 500 and result["truncated"] is True
    assert all(match["record"]["nombre"] == value for match in result["matches"])


def test_bad_point_parameter_aborts_explicit_group_and_restores_indexes(client):
    http, _ = client
    token = http.post("/api/sessions").json()["token"]
    assert query(http, "BEGIN TRANSACTION", token).status_code == 200
    assert query(http, "DELETE FROM tiendas WHERE id = 1", token).status_code == 200
    sql = "SELECT id FROM tiendas ORDER BY distancia(ubicacion, missing) LIMIT 2"
    response = query(http, sql, token)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["group_aborted"] is True
    assert query(http, "SELECT id FROM tiendas WHERE id = 1", token).json()["rows"] == [[1]]
