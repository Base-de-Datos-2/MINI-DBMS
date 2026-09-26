"""Tables created from the Files panel: empty definitions and CSV imports.

Every test goes through the public HTTP routes over a disposable demo
database, then checks the result with SQL through the same engine and, where
persistence matters, after a clean reopen.
"""

import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.database import Database, DatabaseSetupError
from api.demo import PRESETS
from api.gui_tables import REGISTRY_FILENAME
from api.schemas import MAX_REQUEST_BYTES
from tests.api_helpers import details_of, open_service, query, small_demo


ALUMNOS_CSV = (
    "Id;Nombre;Carrera;Nota\n"
    "1;Ana;CS;20\n"
    "2;Luis;EE;15\n"
    "3;Sol;CS;18\n"
    "4;Omar;EE;15\n"
)

FIXTURE_TABLES = ["students", "enrollments", "students_big", "courses", "enrollments_big"]


@pytest.fixture
def writable(writable_directory):
    service = open_service(writable_directory, allow_writes=True)
    with TestClient(create_app(service, presets=PRESETS)) as client:
        yield client, service, writable_directory
    service.close()


def reopen(directory):
    return TestClient(create_app(open_service(directory), presets=PRESETS))


def import_alumnos(client, **overrides):
    body = {
        "name": "alumnos",
        "organization": "HEAP",
        "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "nombre", "type": "VARCHAR"},
            {"name": "carrera", "type": "VARCHAR"},
            {"name": "nota", "type": "INTEGER"},
        ],
        "indexes": [{"column": "id", "type": "EXTENDIBLE_HASH", "unique": True}],
        "csv": {"text": ALUMNOS_CSV, "filename": "alumnos.csv"},
        **overrides,
    }
    return client.post("/api/tables", json=body)


def test_creating_tables_is_refused_in_read_only_mode(client):
    response = client.post(
        "/api/tables", json={"name": "t", "columns": [{"name": "x", "type": "INTEGER"}]}
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WRITES_DISABLED"
    assert "t" not in [table["id"] for table in client.get("/api/tables").json()]


def test_preview_infers_types_without_admission_or_writes(client, service):
    with service._admitted():
        response = client.post(
            "/api/import/preview", json={"text": ALUMNOS_CSV, "filename": "alumnos.csv"}
        )

    assert response.status_code == 200
    body = response.json()
    assert [column["type"] for column in body["columns"]] == [
        "INTEGER", "VARCHAR", "VARCHAR", "INTEGER",
    ]
    assert body["row_count"] == 4
    assert body["suggested_table_name"] == "alumnos"


def test_csv_import_loads_rows_builds_the_index_and_is_queryable(writable):
    client, _, _ = writable

    response = import_alumnos(client)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["loaded_rows"] == 4
    table = body["table"]
    assert table["origin"] == "csv"
    assert table["source_filename"] == "alumnos.csv"
    assert table["row_count"] == 4
    assert [index["name"] for index in table["indexes"]] == ["alumnos_id_hash"]
    assert table["indexes"][0]["entry_count"] == 4

    lookup = query(client, "SELECT nombre FROM alumnos WHERE id = 3")
    assert lookup.json()["rows"] == [["Sol"]]
    assert details_of(lookup.json()["execution_plan"]["runtime"]["root"], "IndexScan")[
        "index_name"
    ] == "alumnos_id_hash"
    grouped = query(
        client, "SELECT carrera, COUNT(*) AS n FROM alumnos GROUP BY carrera ORDER BY carrera"
    )
    assert grouped.json()["rows"] == [["CS", 2], ["EE", 2]]


def test_index_counts_stay_per_table_with_several_tables_and_one_index(writable):
    """Regression: one index over four tables must never be shown as four."""

    client, _, directory = writable
    for name in ("t1", "t2", "t3"):
        created = client.post(
            "/api/tables", json={"name": name, "columns": [{"name": "x", "type": "INTEGER"}]}
        )
        assert created.status_code == 201
    assert import_alumnos(client).status_code == 201

    def counts(test_client):
        return {
            table["id"]: table["index_count"]
            for table in test_client.get("/api/tables").json()
        }

    expected = {
        "students": 2, "enrollments": 0, "students_big": 1, "courses": 1,
        "enrollments_big": 0, "t1": 0, "t2": 0, "t3": 0, "alumnos": 1,
    }
    assert counts(client) == expected
    for name in ("t1", "t2", "t3", "alumnos"):
        detail = client.get(f"/api/tables/{name}").json()
        assert len(detail["indexes"]) == expected[name]

    client.app.state.service.close()
    with reopen(directory) as reopened:
        assert counts(reopened) == expected
        reopened.app.state.service.close()


def test_gui_tables_persist_and_reopen_after_the_declared_fixtures(writable):
    client, _, directory = writable
    assert import_alumnos(client).status_code == 201
    sequential = client.post(
        "/api/tables",
        json={
            "name": "cursos",
            "organization": "SEQUENTIAL",
            "key_column": "codigo",
            "columns": [
                {"name": "codigo", "type": "VARCHAR"},
                {"name": "creditos", "type": "INTEGER"},
            ],
            "indexes": [{"column": "codigo", "type": "BPLUS", "unique": True}],
            "csv": {"text": "codigo,creditos\nZ9,3\nA1,4\nM5,5\n"},
        },
    )
    assert sequential.status_code == 201, sequential.json()
    assert sequential.json()["table"]["indexes"][0]["clustered"] is True
    client.app.state.service.close()

    with reopen(directory) as reopened:
        ids = [table["id"] for table in reopened.get("/api/tables").json()]
        assert ids == FIXTURE_TABLES + ["alumnos", "cursos"]
        ordered = query(reopened, "SELECT codigo FROM cursos")
        assert ordered.json()["rows"] == [["A1"], ["M5"], ["Z9"]]
        assert query(reopened, "SELECT nombre FROM alumnos WHERE id = 1").json()[
            "rows"
        ] == [["Ana"]]
        reopened.app.state.service.close()

    registry = json.loads((directory / REGISTRY_FILENAME).read_text(encoding="utf-8"))
    assert [table["name"] for table in registry["tables"]] == ["alumnos", "cursos"]
    # Logical names never become file names.
    assert not any(path.name.startswith("alumnos") for path in directory.iterdir())


def test_an_empty_table_accepts_inserts(writable):
    client, _, _ = writable
    created = client.post(
        "/api/tables",
        json={
            "name": "notas",
            "columns": [{"name": "id", "type": "INTEGER"}, {"name": "ok", "type": "BOOLEAN"}],
            "indexes": [{"column": "id", "type": "BPLUS"}],
        },
    )

    assert created.status_code == 201
    assert created.json()["table"]["origin"] == "empty"
    inserted = query(client, "INSERT INTO notas VALUES (7, TRUE)").json()
    assert inserted["affected_rows"] == 1
    # Stage 8: the command ran as one committed implicit transaction.
    assert inserted["transaction"]["committed"] is True
    assert isinstance(inserted["transaction"]["id"], int)
    assert query(client, "SELECT ok FROM notas WHERE id >= 7").json()["rows"] == [[True]]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"name": "students"}, "TABLE_EXISTS"),
        ({"name": "select"}, "DEFINITION_ERROR"),
        ({"indexes": [{"column": "nope", "type": "BPLUS"}]}, "DEFINITION_ERROR"),
        ({"organization": "SEQUENTIAL", "key_column": "id",
          "indexes": [{"column": "id", "type": "EXTENDIBLE_HASH"}]}, "DEFINITION_ERROR"),
        ({"indexes": [{"column": "carrera", "type": "BPLUS", "unique": True}]},
         "DEFINITION_ERROR"),
        ({"columns": [{"name": "id", "type": "INTEGER"}]}, "DEFINITION_ERROR"),
        ({"csv": {"text": "id;nombre;carrera;nota\n1;Ana;CS;veinte\n"}}, "CSV_ERROR"),
    ],
)
def test_invalid_definitions_create_nothing(writable, overrides, code):
    client, _, directory = writable
    before = sorted(path.name for path in directory.iterdir())

    response = import_alumnos(client, **overrides)

    assert response.status_code in (409, 422)
    assert response.json()["error"]["code"] == code
    assert sorted(path.name for path in directory.iterdir()) == before
    assert [table["id"] for table in client.get("/api/tables").json()] == FIXTURE_TABLES
    # The service keeps working after the refusal.
    assert import_alumnos(client).status_code == 201


def test_csv_errors_point_at_the_line_and_column(writable):
    client, _, _ = writable
    response = import_alumnos(
        client, csv={"text": "id;nombre;carrera;nota\n1;Ana;CS;20\n2;Luis;EE;x\n"}
    )

    assert response.json()["error"]["details"] == {"line": 3, "column": "nota"}


def test_a_busy_engine_refuses_creation_without_side_effects(writable):
    client, service, directory = writable
    before = sorted(path.name for path in directory.iterdir())

    with service._admitted():
        response = import_alumnos(client)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ENGINE_BUSY"
    assert sorted(path.name for path in directory.iterdir()) == before


def test_only_import_routes_accept_large_bodies(writable):
    client, _, _ = writable
    rows = "".join(f"{i};n{i};CS;{i % 20}\n" for i in range(1, 5001))
    text = "id;nombre;carrera;nota\n" + rows
    assert len(text) > MAX_REQUEST_BYTES

    assert client.post("/api/import/preview", json={"text": text}).status_code == 200
    too_big = client.post("/api/query", json={"sql": "SELECT 1 FROM students " + " " * len(text)})
    assert too_big.status_code == 413


def test_a_corrupt_registry_refuses_to_open(writable_directory):
    (writable_directory / REGISTRY_FILENAME).write_text("{no json", encoding="utf-8")

    with pytest.raises(DatabaseSetupError):
        Database.open(small_demo(), writable_directory)


def test_a_registry_whose_files_vanished_refuses_to_open(writable):
    client, _, directory = writable
    assert import_alumnos(client).status_code == 201
    client.app.state.service.close()
    for path in directory.glob("g_*.hsh"):
        path.unlink()

    with pytest.raises(DatabaseSetupError, match="alumnos"):
        Database.open(small_demo(), directory)


def test_a_quarantined_owner_answers_503_instead_of_500(writable):
    client, service, _ = writable
    service._database._available = False

    response = client.get("/api/tables")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ENGINE_UNAVAILABLE"
    assert client.get("/api/health").json()["status"] == "unavailable"
