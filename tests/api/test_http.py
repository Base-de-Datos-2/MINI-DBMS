"""Stage 9 Tasks 9.6-9.8 over real HTTP: routes, envelopes and status codes."""

import threading

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.demo import PRESETS
from api.engine_service import EngineService
from tests.api_helpers import details_of, names, open_service, query


def test_health_is_served_even_while_the_engine_is_busy(client, service):
    with service._admitted():
        health = client.get("/api/health")
        tables = client.get("/api/tables")

    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ready"
    assert body["mode"] == "read-only"
    assert body["limits"]["max_preview_rows"] == 500
    assert tables.status_code == 409
    assert tables.json()["error"]["code"] == "ENGINE_BUSY"


def test_every_response_carries_a_request_id_in_body_and_header(client):
    response = query(client, "SELECT id FROM students WHERE id = 1")
    failure = client.get("/api/tables/nope")

    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert failure.json()["error"]["request_id"] == failure.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] != failure.headers["X-Request-ID"]


def test_the_files_panel_lists_tables_then_describes_one(client):
    tables = client.get("/api/tables").json()
    detail = client.get("/api/tables/courses").json()

    assert [table["id"] for table in tables] == [
        "students", "enrollments", "students_big", "courses", "enrollments_big",
    ]
    assert tables[0] == {
        "id": "students", "name": "students", "organization": "HEAP",
        "row_count": 4, "column_count": 4, "index_count": 2,
    }
    assert detail["organization"] == "SEQUENTIAL"
    assert detail["key_column"] == "code"
    assert [column["name"] for column in detail["columns"]] == [
        "code", "title", "credits",
    ]
    assert all(column["nullable"] is False for column in detail["columns"])
    assert detail["indexes"][0]["clustered"] is True


def test_table_json_never_exposes_filesystem_paths(client, prepared_directory):
    text = client.get("/api/tables/students").text + client.get("/api/tables").text

    assert str(prepared_directory) not in text
    assert ".heap" not in text


def test_an_unknown_table_is_a_404_envelope(client):
    response = client.get("/api/tables/nope")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert "nope" in error["message"]


def test_a_successful_query_follows_the_frozen_contract(client):
    body = query(client, "SELECT name FROM students WHERE age > 20 ORDER BY name").json()

    assert set(body) == {
        "request_id", "mode", "statement", "kind", "columns", "rows",
        "returned_rows", "truncated", "truncation_reason", "result_complete",
        "total_rows", "affected_rows", "execution_plan", "plan_status", "metrics",
    }
    assert body["kind"] == "rows"
    assert body["rows"] == [["Ana"], ["Omar"], ["Sol"]]
    assert body["columns"] == [
        {"position": 0, "name": "name", "type": "VARCHAR", "encoding": "string"}
    ]
    assert body["affected_rows"] is None
    assert body["plan_status"] == "execution-observed"


def test_http_rows_match_direct_engine_execution(client, service):
    sql = "SELECT s.name, e.course FROM students s JOIN enrollments e ON s.id = e.student_id"
    body = query(client, sql).json()
    with service._admitted() as engine:
        with engine.execute(sql) as result:
            direct = [list(row.values) for row in result]

    assert sorted(body["rows"]) == sorted(direct)


def test_sql_errors_are_422_with_their_source_location(client):
    response = query(client, "SELEC name FROM students")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "SQL_ERROR"
    assert error["location"]["line"] == 1
    assert error["location"]["column"] == 1


def test_a_disabled_statement_is_403_and_shows_only_its_prepared_plan(client):
    response = query(client, "DELETE FROM enrollments WHERE student_id = 1")

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "STATEMENT_DISABLED"
    assert body["statement"] == "DELETE"
    assert body["plan_status"] == "prepared"
    assert body["execution_plan"]["runtime"] is None


def test_a_busy_engine_is_a_409_envelope(client, service):
    admitted = threading.Event()
    release = threading.Event()

    def hold():
        with service._admitted():
            admitted.set()
            release.wait()

    worker = threading.Thread(target=hold)
    worker.start()
    admitted.wait()
    try:
        response = query(client, "SELECT id FROM students")
    finally:
        release.set()
        worker.join()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ENGINE_BUSY"
    assert query(client, "SELECT id FROM students").status_code == 200


def test_an_oversized_body_is_refused_before_parsing(client):
    response = client.post(
        "/api/query",
        content=b'{"sql": "' + b"a" * 70_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.parametrize(
    "payload",
    [
        {"sql": "SELECT id FROM students", "max_rows": 501},
        {"sql": "SELECT id FROM students", "max_rows": -1},
        {"sql": ""},
        {},
        {"sql": "SELECT id FROM students", "join_strategy": "MERGE"},
        {"sql": "SELECT id FROM students", "unexpected": True},
    ],
)
def test_malformed_requests_are_invalid_request_envelopes(client, payload):
    response = client.post("/api/query", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_an_unexpected_failure_hides_its_details_behind_a_request_id(
    writable_directory, monkeypatch
):
    service = open_service(writable_directory)

    def exploding(request, request_id):
        raise RuntimeError(f"secret detail at {writable_directory}/students.heap")

    monkeypatch.setattr(EngineService, "execute", lambda self, r, i: exploding(r, i))
    try:
        with TestClient(create_app(service), raise_server_exceptions=False) as test_client:
            response = query(test_client, "SELECT id FROM students")
    finally:
        monkeypatch.undo()
        service.close()

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert "secret" not in response.text
    assert str(writable_directory) not in response.text


def test_an_unavailable_engine_is_a_503_envelope(writable_directory):
    service = open_service(writable_directory)
    service._state = "unavailable"
    try:
        with TestClient(create_app(service)) as test_client:
            response = query(test_client, "SELECT id FROM students")
            health = test_client.get("/api/health").json()
    finally:
        service._state = "ready"
        service.close()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ENGINE_UNAVAILABLE"
    assert health["status"] == "unavailable"


def test_presets_are_served_without_their_test_expectations(client):
    presets = client.get("/api/presets").json()

    assert [preset["label"] for preset in presets] == [p.label for p in PRESETS]
    assert all(set(preset) == {"label", "purpose", "sql"} for preset in presets)


def test_a_built_frontend_is_served_beside_the_api(service, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>MINI-DBMS</title>")

    with TestClient(create_app(service, frontend_dir=tmp_path)) as served:
        page = served.get("/")
        api = served.get("/api/health")

    assert page.status_code == 200 and "MINI-DBMS" in page.text
    assert api.json()["status"] == "ready"


def test_the_app_requires_an_engine_service():
    with pytest.raises(TypeError, match="EngineService"):
        create_app("demo")
