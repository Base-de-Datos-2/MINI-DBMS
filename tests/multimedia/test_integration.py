"""Phase 5: owner, sealing, SQL, operators, API and media routes for Part 4."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from api.app import create_app
from api.database import Database, DatabaseDefinition
from api.demo import MULTIMEDIA_PRESETS
from api.engine_service import EngineService
from engine.errors import ReadOnlyError, ValidationError
from engine.multimedia.registry import read_multimedia_registry
from engine.query.errors import SqlBindingError, SqlSyntaxError
from scripts.setup_multimedia import fixture_sources

ROOT = Path(__file__).resolve().parents[2]
DEFINITION = DatabaseDefinition("multimedia")
IMAGE_SQL = "SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10) USING HNSW WITH METRIC=cosine;"
AUDIO_SQL = ("SELECT nombre, artista, SIMILARITY_SCORE() as score FROM canciones "
             "WHERE SIMILAR_TO('audio_query.mp3', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("multimedia") / "db"
    registrations = Database.prepare_multimedia(root, fixture_sources())
    return root, registrations


@pytest.fixture
def database(prepared):
    with Database.open(DEFINITION, prepared[0]) as opened:
        yield opened


def rows(database, sql, use_indexes=True):
    session = database.open_session()
    try:
        result = session.execute(sql, use_indexes=use_indexes)
        return [tuple(row.values) for row in result.rows], result
    finally:
        session.close()


def test_preparation_publishes_sealed_registered_collections(prepared, database):
    root, registrations = prepared
    assert {r.table: r.modality for r in registrations} == {"imagenes": "image", "canciones": "audio"}
    assert read_multimedia_registry(root) == registrations
    for registration in registrations:
        collection = database.multimedia_collection(registration.table)
        assert collection.generation == registration.generation
        assert database._storages[registration.table].read_only


def test_both_assignment_examples_run_through_the_engine(database):
    images, _ = rows(database, IMAGE_SQL)
    assert images[0][2] == "scene_a.png" and len(images) == 8          # k=10 > N=8
    audio, _ = rows(database, AUDIO_SQL)
    assert audio[0][0] == "Acorde grave La-Do#-Mi" and len(audio) == 5
    scores = [row[2] for row in audio]
    assert scores == sorted(scores, reverse=True) and all(score <= 0 for score in scores)


@pytest.mark.parametrize("method", ["IVF", "HNSW"])
@pytest.mark.parametrize("metric", ["euclidean", "dot", "cosine"])
def test_indexes_equal_the_exact_scan_on_the_tiny_collections(database, method, metric):
    sql = (f"SELECT id, SIMILARITY_SCORE() AS s FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=8) "
           f"USING {method} WITH METRIC={metric}")
    indexed, with_index = rows(database, sql, use_indexes=True)
    exact, without = rows(database, sql, use_indexes=False)
    assert indexed == exact
    assert with_index.report.prepared.name == "VectorIndexScan"
    assert without.report.prepared.name == "VectorScan"


def test_limit_applies_after_best_first_selection(database):
    full, _ = rows(database, "SELECT id FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=6) "
                             "USING IVF WITH METRIC=cosine")
    limited, _ = rows(database, "SELECT id FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=6) "
                                "USING IVF WITH METRIC=cosine LIMIT 2")
    assert limited == full[:2] and len(full) == 6
    tie_break, _ = rows(database, "SELECT id, SIMILARITY_SCORE() AS s FROM imagenes WHERE "
                                  "SIMILAR_TO('foto_consulta.jpg', k=6) USING IVF WITH METRIC=cosine "
                                  "ORDER BY s DESC, id ASC")
    assert [row[0] for row in tie_break] == [row[0] for row in full]


@pytest.mark.parametrize("sql, error, message", [
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) USING IVF WITH METRIC=cosine "
     "ORDER BY id", SqlBindingError, "best-first"),
    ("SELECT id, SIMILARITY_SCORE() AS s FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) "
     "USING IVF WITH METRIC=cosine ORDER BY s ASC", SqlBindingError, "best-first"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('audio_query.mp3', k=3) USING IVF WITH METRIC=cosine",
     SqlBindingError, "is audio"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('../model/codebook.npy', k=3) USING IVF WITH METRIC=cosine",
     SqlBindingError, "registered file name"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) USING PQ WITH METRIC=cosine",
     SqlBindingError, "Unknown vector index"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) USING IVF WITH METRIC=manhattan",
     SqlBindingError, "Unknown metric"),
    ("SELECT SIMILARITY_SCORE() FROM imagenes WHERE id = 1", SqlBindingError, "single SIMILAR_TO"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=0) USING IVF WITH METRIC=cosine",
     SqlSyntaxError, "positive integer"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) USING IVF",
     SqlSyntaxError, "WITH METRIC"),
    ("SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) AND id = 1 USING IVF "
     "WITH METRIC=cosine", SqlSyntaxError, "single SIMILAR_TO"),
    ("SELECT COUNT(*) FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=3) USING IVF WITH METRIC=cosine",
     SqlBindingError, "Only columns"),
])
def test_unsupported_forms_fail_clearly(database, sql, error, message):
    with pytest.raises(error, match=message):
        rows(database, sql)


def test_unregistered_keys_fail_at_execution_without_reading_the_filesystem(database):
    with pytest.raises(ValidationError, match="not registered"):
        rows(database, "SELECT * FROM imagenes WHERE SIMILAR_TO('nada.jpg', k=3) USING IVF WITH METRIC=cosine")


def test_explain_and_analyze_report_the_executed_access_path(database):
    session = database.open_session()
    try:
        plan = session.execute("EXPLAIN " + IMAGE_SQL).plan
        details = dict(plan.details)
        assert plan.name == "VectorIndexScan"
        assert details["method"] == "HNSW" and details["metric"] == "cosine"
        analyzed = session.execute("EXPLAIN ANALYZE " + AUDIO_SQL.replace("IVF", "HNSW"))
        runtime = dict(analyzed.report.runtime.root.details)
        assert runtime["executed"] == "HNSW" and int(runtime["evaluations"]) > 0
        assert "extract_ms" in runtime and "ef_search" in runtime
        bypass = session.execute("EXPLAIN " + IMAGE_SQL, use_indexes=False).plan
        assert bypass.name == "VectorScan"
        assert dict(bypass.details)["method"] == "exact scan (requested HNSW)"
    finally:
        session.close()


def test_relational_sql_on_a_published_table_keeps_working(database):
    found, result = rows(database, "SELECT nombre FROM imagenes WHERE id = 2")
    assert found == [("scene b",)]
    assert result.report.prepared.name not in ("VectorScan", "VectorIndexScan")


@pytest.mark.parametrize("sql", [
    "INSERT INTO imagenes VALUES (99, 'nueva', 'scene_a.png')",
    "DELETE FROM canciones WHERE id = 1",
])
def test_published_collections_reject_mutations_before_any_effect(prepared, database, sql):
    before = database._storages["imagenes"].record_count, database._storages["canciones"].record_count
    with pytest.raises(ReadOnlyError):
        rows(database, sql)
    assert (database._storages["imagenes"].record_count,
            database._storages["canciones"].record_count) == before


def test_a_fresh_process_reopens_and_returns_identical_rows(prepared, database):
    expected, _ = rows(database, AUDIO_SQL)
    database.close()
    script = (
        "import json, sys; from pathlib import Path\n"
        "from api.database import Database, DatabaseDefinition\n"
        "with Database.open(DatabaseDefinition('multimedia'), Path(sys.argv[1])) as db:\n"
        "    s = db.open_session(); r = s.execute(sys.argv[2])\n"
        "    print(json.dumps([list(x.values) for x in r.rows])); s.close()\n"
    )
    output = subprocess.run([sys.executable, "-c", script, str(prepared[0]), AUDIO_SQL], cwd=ROOT,
                            check=True, capture_output=True, text=True).stdout
    assert [tuple(row) for row in json.loads(output.strip().splitlines()[-1])] == expected


def test_registry_and_collection_disagreement_refuses_to_open(prepared, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(prepared[0], copy)
    registry = copy / "multimedia_tables.json"
    payload = json.loads(registry.read_text())
    payload["collections"][0]["generation"] = "f" * 32
    registry.write_text(json.dumps(payload))
    with pytest.raises(ValidationError, match="generation"):
        Database.open(DEFINITION, copy).close()


def test_preparation_never_reuses_an_existing_directory(prepared):
    with pytest.raises(FileExistsError):
        Database.prepare_multimedia(prepared[0], fixture_sources())


@pytest.fixture
def client(prepared):
    database = Database.open(DEFINITION, prepared[0])
    service = EngineService(database, allow_writes=True)
    with TestClient(create_app(service, presets=MULTIMEDIA_PRESETS)) as test_client:
        yield test_client
    database.close()


def test_http_lists_collections_and_serves_only_registered_media(client):
    tables = {t["table"]: t for t in client.get("/api/multimedia/tables").json()}
    assert tables["imagenes"]["modality"] == "image" and tables["imagenes"]["queries"] == ["foto_consulta.jpg"]
    assert tables["canciones"]["methods"]["IVF"] == ["cosine", "dot", "euclidean"]
    image = client.get("/api/multimedia/imagenes/media/foto_consulta.jpg")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    gallery = client.get("/api/multimedia/canciones/media/acorde_grave.wav")
    assert gallery.status_code == 200 and gallery.headers["content-type"] == "audio/wav"
    for path in ("/api/multimedia/imagenes/media/..%2Fcollection.json",
                 "/api/multimedia/imagenes/media/audio_query.mp3",
                 "/api/multimedia/imagenes/media/nada.png",
                 "/api/multimedia/otra/media/scene_a.png"):
        assert client.get(path).status_code == 404, path


def test_http_query_and_presets_use_the_engine(client):
    body = client.post("/api/query", json={"sql": AUDIO_SQL}).json()
    assert body["rows"][0][0] == "Acorde grave La-Do#-Mi"
    assert body["execution_plan"]["prepared"]["root"]["name"] == "VectorIndexScan"
    presets = client.get("/api/presets").json()
    assert {preset["sql"] for preset in presets} >= {IMAGE_SQL}
    for preset in presets:
        response = client.post("/api/query", json={"sql": preset["sql"]})
        assert response.status_code == 200, preset["label"]


def test_http_writes_are_refused_even_with_allow_writes(client):
    response = client.post("/api/query", json={"sql": "INSERT INTO imagenes VALUES (50, 'x', 'scene_a.png')"})
    assert response.status_code == 422
    assert "read-only" in json.dumps(response.json()).lower() or "sealed" in json.dumps(response.json()).lower()
