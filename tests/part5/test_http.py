"""Exercise the mounted academic REST routes with real Heap and SPIMI data."""

import asyncio

import httpx2
import pytest
from fastapi.testclient import TestClient

from api.academic_retrieval import retrieve_academic
from api.academic_schema import CHUNK_COLUMNS, PAPER_COLUMNS
from api.database import Database, DatabaseDefinition, NewTable
from api.demo import TEXT_PRESETS
from api.unified import PARTS, close_parts, create_unified_app, open_parts
from engine.catalog import DataType
from engine.text.registry import read_text_registry


PART5 = PARTS[-1]
PAPERS = [(1, "A. Author", 2020, "Graph search", "Graph paper abstract."),
          (2, "B. Author", 2021, "Graph neighbors", "Neighbor paper abstract.")]
CHUNKS = [(1, 1, 1, "graph graph hierarchy layer search"),
          (2, 1, 2, "graph graph search"),
          (3, 2, 1, "graph neighbors")]


def prepare_part5(directory, *, variant=None):
    chunks = CHUNK_COLUMNS if variant != "schema" else (
        *CHUNK_COLUMNS, ("extra", DataType.VARCHAR),
    )
    chunk_rows = CHUNKS if variant != "schema" else [(*row, "extra") for row in CHUNKS]
    id_column = "position" if variant == "registration" else "chunk_id"
    if variant == "registration":
        chunk_rows = CHUNKS[:2]
    Database.prepare_text(
        directory, [(NewTable("chunks", chunks), chunk_rows, id_column, "content")],
        companion_tables=[(NewTable("papers", PAPER_COLUMNS), PAPERS)],
    )


def retrieve(app):
    async def request():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport) as client:
            return await retrieve_academic(
                "graph", base_url="http://testserver/parte5", client=client,
            )
    return asyncio.run(request())


def test_academic_rest_is_read_only_and_survives_reopen(tmp_path):
    academic = tmp_path / "parte5"
    prepare_part5(academic)
    registration = read_text_registry(academic)
    Database.prepare_text(tmp_path / "parte3", [
        (NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR))),
         [(1, "demo text")], "id", "contenido"),
    ])
    parts = open_parts(tmp_path, allow_writes=True)
    try:
        app = create_unified_app(parts)
        with TestClient(app) as client:
            fifth = client.get("/api/parts").json()[4]
            assert (fifth["id"], fifth["base"], fifth["status"], fifth["mode"]) == (
                "parte5", "/parte5", "ready", "read-only",
            )
            health = client.get("/parte5/api/health").json()
            assert set(health["tables"]) == {"papers", "chunks"}
            assert health["mode"] == "read-only"
            [published] = client.get("/parte5/api/text/tables").json()
            assert (published["table"], published["column"], published["id_column"],
                    published["documents"]) == ("chunks", "content", "chunk_id", 3)
            assert client.get("/parte5/api/presets").json() == []
            assert [p["sql"] for p in client.get("/parte3/api/presets").json()] == [
                p.sql for p in TEXT_PRESETS
            ]
            assert [r["table"] for r in client.get("/parte3/api/text/tables").json()] == ["documentos"]
            assert client.get("/parte5/api/tables/papers").json()["origin"] == "prepared"

            for sql in (
                "INSERT INTO papers VALUES (9, 'A', 2000, 'T', 'A');",
                "INSERT INTO chunks VALUES (9, 1, 3, 'new text');",
            ):
                blocked = client.post("/parte5/api/query", json={"sql": sql})
                assert blocked.status_code >= 400
                assert blocked.json()["error"]["code"] == "STATEMENT_DISABLED"

            for source_part, target_part in (("parte3", "parte5"), ("parte5", "parte3")):
                token = client.post(f"/{source_part}/api/sessions").json()["token"]
                headers = {"X-Session-Token": token}
                assert client.get(f"/{source_part}/api/session", headers=headers).status_code == 200
                other = client.get(f"/{target_part}/api/session", headers=headers)
                assert other.json()["error"]["code"] == "SESSION_NOT_FOUND"

            raw = client.post("/parte5/api/text/query", json={
                "table": "chunks", "column": "content", "query": "graph",
                "model": "BM25", "limit": 3, "max_rows": 3, "use_indexes": True,
            }).json()
            assert raw["plan"]["operator"] == "TextIndexScan"
            before = retrieve(app)
            assert before["status"] == "context"
            sources = before["sources"]
            assert [(s["chunk_id"], s["score"]) for s in sources] == [
                (row[0], row[4]) for row in raw["rows"]
            ]
            assert [s["label"] for s in sources] == ["S1", "S2", "S3"]
            for source in sources:
                _, author, year, title, abstract = PAPERS[source["paper_id"] - 1]
                assert (source["authors"], source["year"], source["title"], source["abstract"]) == (
                    author, year, title, abstract,
                )
                assert source["content"] == CHUNKS[source["chunk_id"] - 1][3]
    finally:
        assert close_parts(parts) == []

    reopened = open_parts(tmp_path, allow_writes=False, specs=(PART5,))
    try:
        assert retrieve(create_unified_app(reopened)) == before
        assert read_text_registry(academic) == registration
    finally:
        assert close_parts(reopened) == []


@pytest.mark.parametrize("variant", ["part3", "schema", "registration", "corrupt_registry"])
def test_wrong_data_is_reported_missing_and_owner_is_released(tmp_path, variant):
    directory = tmp_path / "parte5"
    if variant == "part3":
        Database.prepare_text(directory, [
            (NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR))),
             [(1, "text")], "id", "contenido"),
        ])
    else:
        prepare_part5(directory, variant=variant)

    registry_path = directory / "text_tables.json"
    if variant == "corrupt_registry":
        original = registry_path.read_bytes()
        registry_path.write_text("invalid registry", encoding="utf-8")

    parts = open_parts(tmp_path, allow_writes=False, specs=(PART5,))
    try:
        with TestClient(create_unified_app(parts)) as client:
            [missing] = client.get("/api/parts").json()
            assert missing["status"] == "missing"
            assert missing["base"] is None
            assert missing["problem"]
            assert "setup_academic.py" in missing["setup"]
            assert f'--data-dir "{directory.as_posix()}"' in missing["setup"]
    finally:
        assert close_parts(parts) == []
    if variant == "corrupt_registry":
        registry_path.write_bytes(original)
    with Database.open(DatabaseDefinition("text"), directory) as database:
        assert database.table_names()
