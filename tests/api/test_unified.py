"""One server, one port: every prepared part mounted under its own prefix."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.database import Database
from api.demo import PRESETS, SPATIAL_PRESETS, TEXT_PRESETS
from api.schemas import MAX_REQUEST_BYTES
from api.unified import PARTS, close_parts, create_unified_app, open_parts
from scripts.setup_all import prepare_all
from scripts.setup_lima import prepare_lima
from scripts.setup_text import prepare as prepare_text
from tests.api_helpers import small_demo


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    """Parts 1-3 prepared; Part 4 deliberately missing."""

    directory = tmp_path_factory.mktemp("todas")
    Database.create(small_demo(), directory / "parte1").close()
    prepare_lima(directory / "parte2")
    prepare_text(directory / "parte3")
    return directory


@pytest.fixture(scope="module")
def parts(root):
    opened = open_parts(root, allow_writes=True)
    yield opened
    assert close_parts(opened) == []


@pytest.fixture(scope="module")
def client(parts):
    with TestClient(create_unified_app(parts)) as test_client:
        yield test_client


def run(client, part, sql, token=None):
    headers = {} if token is None else {"X-Session-Token": token}
    return client.post(f"/{part}/api/query", json={"sql": sql, "max_rows": 500}, headers=headers)


def test_parts_list_every_part_in_tab_order_and_explains_a_missing_one(client):
    listed = client.get("/api/parts").json()
    assert [part["id"] for part in listed] == [spec.id for spec in PARTS]
    ready = {part["id"]: part for part in listed}
    for identifier in ("parte1", "parte2", "parte3"):
        assert ready[identifier]["status"] == "ready"
        assert ready[identifier]["base"] == f"/{identifier}"
    missing = ready["parte4"]
    assert missing["status"] == "missing" and missing["base"] is None
    assert "setup_all.py" in missing["setup"] and missing["problem"]
    assert client.get("/parte4/api/health").status_code == 404


def test_root_health_summarizes_the_parts_for_hosting_checks(client):
    body = client.get("/api/health").json()
    assert body == {"status": "ready", "parts": {"parte1": "ready", "parte2": "ready",
                                                 "parte3": "ready", "parte4": "missing"}}


def test_each_prefix_reaches_its_own_database_and_presets(client):
    expected = {"parte1": ("students", PRESETS), "parte2": ("lugares_lima", SPATIAL_PRESETS),
                "parte3": ("productos", TEXT_PRESETS)}
    for part, (table, presets) in expected.items():
        assert table in client.get(f"/{part}/api/health").json()["tables"]
        assert [p["sql"] for p in client.get(f"/{part}/api/presets").json()] == [p.sql for p in presets]


def test_writes_apply_only_to_the_parts_that_accept_them(client):
    modes = {part["id"]: part["mode"] for part in client.get("/api/parts").json()}
    assert modes == {"parte1": "serialized-writes", "parte2": "serialized-writes",
                     "parte3": "read-only", "parte4": None}


def test_sessions_belong_to_one_part(client):
    token = client.post("/parte1/api/sessions").json()["token"]
    assert run(client, "parte1", "BEGIN TRANSACTION;", token).status_code == 200
    assert client.get("/parte1/api/session", headers={"X-Session-Token": token}).status_code == 200
    # The same token means nothing to another part's engine.
    other = client.get("/parte3/api/session", headers={"X-Session-Token": token})
    assert other.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert run(client, "parte1", "ROLLBACK;", token).status_code == 200


def test_the_csv_import_limit_still_applies_under_a_prefix(client):
    # Larger than ordinary requests but within the import limit: accepted
    # as an import route even though the path starts with /parte1.
    text = "id,nombre\n" + "".join(f"{i},x\n" for i in range(MAX_REQUEST_BYTES // 4))
    response = client.post("/parte1/api/import/preview", json={"text": text, "filename": "big.csv"})
    assert response.json().get("error", {}).get("code") != "REQUEST_TOO_LARGE"


@pytest.mark.parametrize("preset", SPATIAL_PRESETS, ids=[p.label for p in SPATIAL_PRESETS])
def test_every_spatial_preset_runs(client, preset):
    response = run(client, "parte2", preset.sql)
    assert response.status_code == 200, response.json()


def test_spatial_presets_return_the_known_points(client):
    rows = {p.label: run(client, "parte2", p.sql).json()["rows"] for p in SPATIAL_PRESETS[:3]}
    assert [row[0] for row in rows["Radio de 200 m"]] == [1, 2, 3, 4]
    assert len(rows["Radio de 5 km (PDF)"]) == 7
    assert [row[0] for row in rows["k vecinos más cercanos"]] == [1, 2, 3]


@pytest.mark.parametrize("preset", TEXT_PRESETS, ids=[p.label for p in TEXT_PRESETS])
def test_every_text_preset_runs_on_the_text_index(client, preset):
    body = run(client, "parte3", preset.sql).json()
    assert body["execution_plan"]["prepared"]["root"]["name"] == "TextIndexScan"
    if not preset.sql.startswith("EXPLAIN"):
        assert body["rows"]


def test_bm25_and_tf_idf_rank_the_long_product_query_differently(client):
    bm25, tfidf = (run(client, "parte3", p.sql).json()["rows"] for p in TEXT_PRESETS[3:5])
    assert {row[0] for row in bm25} & {row[0] for row in tfidf}
    assert [row[0] for row in bm25] != [row[0] for row in tfidf]


def test_no_part_prepared_opens_nothing(tmp_path):
    parts = open_parts(tmp_path, allow_writes=False)
    assert [part.service for part in parts] == [None] * len(PARTS)


def test_setup_all_never_touches_an_existing_part(tmp_path):
    (tmp_path / "parte1").mkdir()
    outcome = prepare_all(tmp_path, {"parte1", "parte3"})
    assert outcome == {"parte1": "exists", "parte3": "created"}
    assert list((tmp_path / "parte1").iterdir()) == []
    assert (tmp_path / "parte3" / "text_tables.json").is_file()
    assert prepare_all(tmp_path, {"parte3"}) == {"parte3": "exists"}


def test_text_demo_files_hold_the_documented_collections():
    from scripts.setup_text import DEMO_COLLECTIONS, DEMO_DIRECTORY, _csv_rows
    counts = {name: len(list(_csv_rows(DEMO_DIRECTORY / filename, column)))
              for name, column, filename in DEMO_COLLECTIONS}
    assert counts == {"documentos": 36, "articulos": 20, "productos": 1000}
    assert Path(DEMO_DIRECTORY / "ATTRIBUTION.md").is_file()
