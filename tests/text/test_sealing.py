"""Block 4A: persistent policy, no mutation/undo effects and compatible reopen."""

from contextlib import ExitStack, contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from api.database import Database, DatabaseDefinition, NewIndex, NewTable
from engine.catalog import Catalog, Column, DataType, IndexType, Schema, TableMetadata
from engine.errors import ReadOnlyError, ValidationError
from engine.indexes import UnclusteredBPlusIndex, UnclusteredHashIndex
from engine.maintenance.service import MutationService, MaintenanceIndex
from engine.query.environment import QueryEnvironment
from engine.query.executor import SqlEngine
from engine.query.parser import parse_sql
from engine.storage import FileHeader, HeapFile, PageManager, Record, StorageSeal
from engine.storage.binary import FILE_HEADER_STRUCT, FILE_MAGIC, PAGE_SIZE, SEALED_FORMAT_VERSION
from engine.text import TextIndex, build_spimi, search_text, seal_text_collection
from engine.transactions.model import TransactionId
from engine.transactions.resources import TableFiles
from engine.transactions.undo import UndoStore


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("contenido", DataType.VARCHAR)])
TABLE = TableMetadata("documentos", SCHEMA)
ROWS = [(30, "base base datos"), (7, "base"), (11, "datos índice"), (90, "")]
DEFINITION = DatabaseDefinition("sealed_test")


def fingerprint(paths):
    return {str(path): sha256(Path(path).read_bytes()).hexdigest() for path in paths}


@contextmanager
def collection(root, *, secondary=True):
    with ExitStack() as stack:
        heap = stack.enter_context(HeapFile.create(root / "documents.heap", SCHEMA))
        for row in ROWS:
            heap.insert(Record(SCHEMA, row))
        indexes = []
        if secondary:
            for kind, filename in ((UnclusteredBPlusIndex, "id.bpt"), (UnclusteredHashIndex, "id.hsh")):
                indexes.append(stack.enter_context(kind.build(root / filename, heap=heap,
                    index_name=filename, table_name="documentos", key_column="id")))
        build_spimi(root / "text_index", heap, TABLE, collection_id="seal-test")
        index = stack.enter_context(TextIndex.open(root / "text_index"))
        yield heap, index, indexes


def create_sealed_database(root):
    with Database.create(DEFINITION, root) as database:
        database.create_gui_table(NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR)),
            indexes=(NewIndex("id", IndexType.BPLUS, name="doc_bplus"),
                     NewIndex("id", IndexType.EXTENDIBLE_HASH, name="doc_hash"))), ROWS)
        database.create_gui_table(NewTable("mutable", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR))), [(1, "original")])
        files = database.session_coordinator.resources.table_files("documentos")
    with ExitStack() as stack:
        heap = stack.enter_context(HeapFile.open(files.base, SCHEMA))
        indexes = []
        for name, path in files.indexes:
            kind = UnclusteredBPlusIndex if name == "doc_bplus" else UnclusteredHashIndex
            indexes.append(stack.enter_context(kind.open(path, heap=heap)))
        build_spimi(root / "text_index", heap, TABLE, collection_id="managed-seal-test")
        index = stack.enter_context(TextIndex.open(root / "text_index"))
        seal_text_collection(heap, index, secondary_indexes=indexes)
    return files


def test_v1_files_stay_identical_and_mutable_until_explicit_seal(tmp_path):
    with collection(tmp_path, secondary=False) as (heap, index, _):
        heap.flush()
        path = tmp_path / "documents.heap"
        before = path.read_bytes()
        assert FileHeader.deserialize(before[:20]).version == 1
        assert not heap.read_only and heap.seal_descriptor is None
        with HeapFile.open(path, SCHEMA) as reopened:
            assert not reopened.read_only
        assert path.read_bytes() == before
        extra = heap.insert(Record(SCHEMA, [100, "mutable"]))
        heap.delete(extra)
        assert heap.record_count == 4


def test_seal_preserves_rows_rids_scores_and_freezes_secondary_files(tmp_path):
    with collection(tmp_path) as (heap, index, secondary):
        before = list(heap.scan())
        rankings = {model: search_text(index, "base datos", model=model, limit=2).hits for model in ("TF_IDF", "BM25")}
        descriptor = seal_text_collection(heap, index, secondary_indexes=secondary)
        assert descriptor == StorageSeal(index.collection_id, index.generation)
        assert heap.read_only and heap.seal_descriptor == descriptor
        assert all(item.read_only for item in secondary)
        assert list(heap.scan()) == before
        assert FileHeader.deserialize((tmp_path / "documents.heap").read_bytes()[:20]).version == SEALED_FORMAT_VERSION == 2
        for model, expected in rankings.items():
            assert search_text(index, "base datos", model=model, limit=2, storage=heap).hits == expected
            assert search_text(index, "base datos", model=model, limit=2, storage=heap, use_indexes=False).hits == expected


@pytest.mark.parametrize("route", ["heap_insert", "heap_delete", "maintenance_insert", "maintenance_delete",
    "page_write", "page_allocate", "page_replace", "bplus_insert", "bplus_delete", "bplus_insert_record",
    "bplus_delete_record", "bplus_rebuild", "bplus_incomplete", "tree_insert", "tree_delete", "tree_rebuild",
    "hash_insert", "hash_delete", "hash_insert_record", "hash_delete_record", "hash_update", "hash_rebuild",
    "hash_incomplete", "hash_core_insert", "hash_core_delete", "hash_core_rebuild"])
def test_mutation_routes_refuse_before_any_file_or_row_change(tmp_path, route, monkeypatch):
    with collection(tmp_path) as (heap, index, secondary):
        seal_text_collection(heap, index, secondary_indexes=secondary)
        bplus, hashing = secondary
        rid, record = next(heap.scan())
        paths = [path for path in tmp_path.rglob("*") if path.is_file()]
        before = fingerprint(paths)
        service = MutationService()
        def fail(*args, **kwargs):
            raise AssertionError("read-only rejection must not attempt index repair")
        monkeypatch.setattr(MutationService, "_repair_indexes", fail)
        def targets():
            yield rid, record
        actions = {
            "heap_insert": lambda: heap.insert(Record(SCHEMA, [100, "new"])),
            "heap_delete": lambda: heap.delete(rid),
            "maintenance_insert": lambda: service.insert(table_name="documentos", storage=heap,
                record=Record(SCHEMA, [100, "new"]), indexes=(), storage_may_move_rids=False),
            "maintenance_delete": lambda: service.delete(table_name="documentos", storage=heap,
                indexes=(), targets=targets(), target_count=1, spool_bytes=0),
            "bplus_insert": lambda: bplus.insert(record["id"], rid),
            "bplus_delete": lambda: bplus.delete(record["id"], rid),
            "bplus_insert_record": lambda: bplus.insert_record(Record(SCHEMA, [100, "new"])),
            "bplus_delete_record": lambda: bplus.delete_record(rid),
            "bplus_rebuild": bplus.rebuild, "bplus_incomplete": bplus.mark_incomplete,
            "tree_insert": lambda: bplus.tree.insert(record["id"], rid),
            "tree_delete": lambda: bplus.tree.delete(record["id"], rid),
            "tree_rebuild": lambda: bplus.tree.rebuild_from_storage(heap),
            "hash_insert": lambda: hashing.insert(record["id"], rid),
            "hash_delete": lambda: hashing.delete(record["id"], rid),
            "hash_insert_record": lambda: hashing.insert_record(Record(SCHEMA, [100, "new"])),
            "hash_delete_record": lambda: hashing.delete_record(rid),
            "hash_update": lambda: hashing.update_record(rid, Record(SCHEMA, [100, "new"])),
            "hash_rebuild": hashing.rebuild, "hash_incomplete": hashing.mark_incomplete,
            "hash_core_insert": lambda: hashing.index.insert(record["id"], rid),
            "hash_core_delete": lambda: hashing.index.delete(record["id"], rid),
            "hash_core_rebuild": lambda: hashing.index.rebuild_from_storage(heap),
        }
        if route.startswith("page_"):
            with PageManager.open(tmp_path / "documents.heap") as pages:
                page = pages.read_page(1)
                action = {"page_write": lambda: pages.write_page(page), "page_allocate": pages.allocate_page,
                    "page_replace": lambda: pages.commit_replacement(pages.temporary_replacement_path())}[route]
                with pytest.raises(ReadOnlyError):
                    action()
                assert pages.pages_written == pages.pages_allocated == 0
        else:
            with pytest.raises(ReadOnlyError):
                actions[route]()
        assert heap.record_count == 4 and fingerprint(paths) == before
        assert search_text(index, "base datos", model="BM25", limit=1).hits[0].doc_id == 30


def test_preexisting_alias_handles_observe_persisted_seal(tmp_path):
    with collection(tmp_path) as (heap, index, secondary):
        with HeapFile.open(tmp_path / "documents.heap") as alias:
            with PageManager.open(tmp_path / "id.bpt") as pages:
                page = pages.read_page(0)
                seal_text_collection(heap, index, secondary_indexes=secondary)
                with pytest.raises(ReadOnlyError):
                    alias.insert(Record(SCHEMA, [99, "x"]))
                with pytest.raises(ReadOnlyError):
                    pages.write_page(page)
                assert alias.seal_descriptor == heap.seal_descriptor


@pytest.mark.parametrize("header_version,metadata_sealed", [(1, True), (2, False)])
def test_mixed_sealing_states_fail_closed_on_storage_open(tmp_path, header_version, metadata_sealed):
    with collection(tmp_path, secondary=False) as (heap, index, _):
        if metadata_sealed:
            seal_text_collection(heap, index)
    path = tmp_path / "documents.heap"
    payload = bytearray(path.read_bytes())
    magic, version, size, count = FILE_HEADER_STRUCT.unpack(payload[:20])
    payload[:20] = FILE_HEADER_STRUCT.pack(magic, header_version, size, count)
    path.write_bytes(payload)
    with pytest.raises(ValidationError, match="Inconsistent"):
        HeapFile.open(path)


def test_generation_binding_rejects_another_index_even_for_identical_rows(tmp_path):
    with collection(tmp_path, secondary=False) as (heap, index, _):
        build_spimi(tmp_path / "second", heap, TABLE, collection_id=index.collection_id)
        with TextIndex.open(tmp_path / "second") as other:
            seal_text_collection(heap, index)
            with pytest.raises(ValidationError, match="different text collection"):
                other.verify_storage(heap)
            for use_indexes in (True, False):
                with pytest.raises(ValidationError, match="different text collection"):
                    search_text(other, "base", model="BM25", storage=heap, use_indexes=use_indexes)


def test_sql_engine_without_sessions_rejects_before_delete_spooling(tmp_path, monkeypatch):
    from engine.query import executor
    with collection(tmp_path, secondary=False) as (heap, index, _):
        seal_text_collection(heap, index)
        catalog = Catalog()
        catalog.register_table(TABLE)
        environment = QueryEnvironment(catalog)
        environment.register_storage("documentos", heap)
        engine = SqlEngine(environment)
        def forbidden(*args, **kwargs):
            raise AssertionError("sealed DELETE must not create a target spool")
        monkeypatch.setattr(executor, "DeleteTargetSpool", forbidden)
        try:
            for sql in ("INSERT INTO documentos VALUES (99, 'new')", "DELETE FROM documentos WHERE id = 30"):
                with pytest.raises(ReadOnlyError):
                    engine.execute(sql)
            assert environment.storage_for("documentos") is heap
        finally:
            engine.close()


@pytest.mark.parametrize("route", ["sql_insert", "sql_delete", "run_write", "programmatic_write",
    "create_index", "drop_index", "drop_table", "update", "import"])
def test_owner_routes_reject_without_undo_capture_restore_or_callbacks(tmp_path, monkeypatch, route):
    files = create_sealed_database(tmp_path)
    with Database.open(DEFINITION, tmp_path) as database:
        session = database.open_session()
        completion = database.session_coordinator.completion
        def forbidden(*args, **kwargs):
            raise AssertionError("sealed mutation must reject before undo/callback effects")
        monkeypatch.setattr(completion.undo, "capture", forbidden)
        monkeypatch.setattr(completion.undo, "restore", forbidden)
        monkeypatch.setattr(completion.runtime, "flush", forbidden)
        paths = [*files.physical_files, *(tmp_path / "text_index").iterdir(), tmp_path / "gui_tables.json"]
        before = fingerprint(paths)
        if route == "run_write":
            session.execute("BEGIN TRANSACTION")
        actions = {
            "sql_insert": lambda: session.execute("INSERT INTO documentos VALUES (99, 'new')"),
            "sql_delete": lambda: database.engine.execute("DELETE FROM documentos WHERE id = 30"),
            "run_write": lambda: session.run_write("documentos", forbidden),
            "programmatic_write": lambda: session.run_programmatic_write("documentos", forbidden),
            "create_index": lambda: database.create_sql_index("new_index", "documentos", "id"),
            "drop_index": lambda: database.drop_sql_index("doc_bplus"),
            "drop_table": lambda: database.drop_sql_table("documentos"),
            "update": lambda: database.update_sql_table(parse_sql("UPDATE documentos SET contenido = 'new' WHERE id = 30")),
            "import": lambda: database.create_gui_table(NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR))), [(99, "new")]),
        }
        with pytest.raises(ReadOnlyError):
            actions[route]()
        assert fingerprint(paths) == before and database.available
        with database.engine.execute("SELECT id FROM documentos ORDER BY id") as result:
            assert [row["id"] for row in result] == [7, 11, 30, 90]
        session.close()


def test_rejected_sealed_write_rolls_back_prior_mutable_work_only(tmp_path, monkeypatch):
    files = create_sealed_database(tmp_path)
    with Database.open(DEFINITION, tmp_path) as database:
        completion = database.session_coordinator.completion
        events = []
        capture, restore = completion.undo.capture, completion.undo.restore
        def captured(tx, files):
            events.append(("capture", files.name))
            return capture(tx, files)
        def restored(image, files):
            events.append(("restore", files.name))
            return restore(image, files)
        monkeypatch.setattr(completion.undo, "capture", captured)
        monkeypatch.setattr(completion.undo, "restore", restored)
        before = fingerprint(files.physical_files)
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.execute("INSERT INTO mutable VALUES (2, 'undo me')")
            with pytest.raises(ReadOnlyError):
                session.execute("DELETE FROM documentos WHERE id = 30")
            assert session.active_transaction is None
        assert events == [("capture", "mutable"), ("restore", "mutable")]
        with database.engine.execute("SELECT id FROM mutable ORDER BY id") as result:
            assert [row["id"] for row in result] == [1]
        assert fingerprint(files.physical_files) == before and database.available


def test_online_publication_is_rejected_across_alias_handles_and_active_undo(tmp_path):
    with Database.create(DEFINITION, tmp_path) as database:
        database.create_gui_table(NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR))), ROWS)
        files = database.session_coordinator.resources.table_files("documentos")
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.execute("INSERT INTO documentos VALUES (99, 'mutable image')")
            with HeapFile.open(files.base) as alias:
                before = fingerprint([files.base])
                with pytest.raises(ValidationError, match="offline-only"):
                    alias.seal(collection_id="bad", generation="bad")
                assert fingerprint([files.base]) == before and not alias.read_only
            session.execute("ROLLBACK")
    with HeapFile.open(files.base) as heap:
        heap.seal(collection_id="offline", generation="allowed-after-close")
        assert heap.read_only


def test_raw_undo_cannot_restore_a_preseal_image_or_capture_a_sealed_file(tmp_path):
    with collection(tmp_path, secondary=False) as (heap, index, _):
        files = TableFiles("documentos", "identity", tmp_path / "documents.heap")
        store = UndoStore(tmp_path)
        image = store.capture(TransactionId(1), files)
        seal_text_collection(heap, index)
        before = fingerprint([files.base])
        with pytest.raises(ReadOnlyError):
            store.restore(image, files)
        with pytest.raises(ReadOnlyError):
            store.capture(TransactionId(2), files)
        assert fingerprint([files.base]) == before
        assert store.discard(TransactionId(1)) == ()


def test_internal_runtime_reopen_retains_seal_and_indexes(tmp_path):
    files = create_sealed_database(tmp_path)
    with Database.open(DEFINITION, tmp_path) as database:
        runtime = database.session_coordinator.completion.runtime
        runtime.close_table(files)
        runtime.reopen(files)
        storage = database._environment.storage_for("documentos")
        assert storage.read_only and storage.seal_descriptor.collection_id == "managed-seal-test"
        with pytest.raises(ReadOnlyError):
            database.engine.execute("INSERT INTO documentos VALUES (99, 'new')")
        assert all(database._environment.index_for(name).read_only for name, _ in files.indexes)


def test_published_registry_is_not_opened_partially_by_unready_owners(tmp_path):
    from engine.database import Database as ManagedDatabase
    create_sealed_database(tmp_path)
    (tmp_path / "text_tables.json").write_text("{}", encoding="utf-8")
    for open_owner in (lambda: Database.open(DEFINITION, tmp_path), lambda: ManagedDatabase.open(tmp_path)):
        with pytest.raises(ValueError, match="[Tt]ext|[Pp]ublished"):
            open_owner()


def test_sealed_collection_reopens_in_fresh_process_with_same_scores_and_rejection(tmp_path):
    files = create_sealed_database(tmp_path)
    script = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])  # API is repository-local, not an installed engine package.
from api.database import Database, DatabaseDefinition
from engine.errors import ReadOnlyError
from engine.text import TextIndex, search_text
with Database.open(DatabaseDefinition('sealed_test'), Path(sys.argv[1])) as database:
    storage = database._environment.storage_for('documentos')
    with TextIndex.open(Path(sys.argv[1]) / 'text_index') as index:
        indexed = search_text(index, 'base datos', model='BM25', limit=2, storage=storage)
        scanned = search_text(index, 'base datos', model='BM25', limit=2, storage=storage, use_indexes=False)
        assert indexed.hits == scanned.hits
        for sql in ("INSERT INTO documentos VALUES (99, 'new')", 'DELETE FROM documentos WHERE id = 30'):
            try:
                database.engine.execute(sql)
            except ReadOnlyError:
                continue
            raise AssertionError('sealed write succeeded')
        print(json.dumps({'ids': [h.doc_id for h in indexed.hits], 'read_only': storage.read_only}))
"""
    process = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tmp_path), str(Path(__file__).resolve().parents[2])],
        cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {"ids": [30, 7], "read_only": True}


@pytest.mark.parametrize("failure", ["validate", "capacity", "duplicate_secondary"])
def test_seal_preflight_failure_preserves_every_original_file(tmp_path, monkeypatch, failure):
    with collection(tmp_path) as (heap, index, secondary):
        paths = [p for p in tmp_path.rglob("*") if p.is_file()]
        before = fingerprint(paths)
        if failure == "validate":
            def fail():
                raise ValidationError("injected text validation failure")
            monkeypatch.setattr(index, "validate", fail)
        elif failure == "capacity":
            monkeypatch.setattr(index, "collection_id", "x" * 4096)
        else:
            secondary.append(secondary[0])
        with pytest.raises(ValidationError):
            seal_text_collection(heap, index, secondary_indexes=secondary)
        assert not heap.read_only and fingerprint(paths) == before


def test_failed_heap_seal_closes_handle_and_reopens_fail_closed(tmp_path, monkeypatch):
    with collection(tmp_path, secondary=False) as (heap, index, _):
        manager = heap._manager
        write = manager._write_at
        payload_before = (tmp_path / "documents.heap").read_bytes()[20 + PAGE_SIZE:]
        def fail_header(offset, payload):
            if offset == 0:
                raise OSError("injected seal header failure")
            return write(offset, payload)
        monkeypatch.setattr(manager, "_write_at", fail_header)
        with pytest.raises(OSError, match="seal header"):
            seal_text_collection(heap, index)
        assert heap.closed
        assert (tmp_path / "documents.heap").read_bytes()[20 + PAGE_SIZE:] == payload_before
        with pytest.raises(ValidationError, match="Inconsistent"):
            HeapFile.open(tmp_path / "documents.heap")


def test_partial_secondary_sealing_is_rejected_on_reopen(tmp_path, monkeypatch):
    with collection(tmp_path) as (heap, index, secondary):
        def fail_header(*args):
            raise OSError("injected secondary seal failure")
        monkeypatch.setattr(secondary[1].index._manager, "_write_at", fail_header)
        before = fingerprint([tmp_path / "documents.heap"])
        with pytest.raises(OSError, match="secondary seal"):
            seal_text_collection(heap, index, secondary_indexes=secondary)
        assert not heap.read_only and secondary[0].read_only
        assert fingerprint([tmp_path / "documents.heap"]) == before
        with pytest.raises(ValidationError, match="policies disagree"):
            UnclusteredBPlusIndex.open(tmp_path / "id.bpt", heap=heap)


def test_raw_catalog_drop_cannot_unlink_a_sealed_secondary(tmp_path):
    from engine.catalog import IndexMetadata
    from engine.indexes import drop_catalog_index
    with collection(tmp_path) as (heap, index, secondary):
        seal_text_collection(heap, index, secondary_indexes=secondary)
        catalog = Catalog()
        catalog.register_table(TABLE)
        path = tmp_path / "id.bpt"
        catalog.register_index(IndexMetadata("id.bpt", "documentos", "id", IndexType.BPLUS, file_path=str(path)))
        before = path.read_bytes()
        with pytest.raises(ReadOnlyError):
            drop_catalog_index(catalog, "id.bpt")
        assert path.read_bytes() == before and catalog.has_index("id.bpt")


def test_alternative_manifest_owner_rejects_a_sealed_table(tmp_path):
    from engine.database import Database as ManagedDatabase
    with ManagedDatabase.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE documentos (id INTEGER, contenido VARCHAR(100))")
        for doc_id, text in ROWS:
            database.engine.execute(f"INSERT INTO documentos VALUES ({doc_id}, '{text}')")
        path = database.path_for("documentos")
    with HeapFile.open(path) as heap:
        build_spimi(tmp_path / "text_index", heap, TABLE, collection_id="unsupported-owner")
        with TextIndex.open(tmp_path / "text_index") as index:
            seal_text_collection(heap, index)
    with pytest.raises(ValidationError, match="text-capable"):
        ManagedDatabase.open(tmp_path)


def test_http_allow_writes_does_not_bypass_seal_and_mutable_rollback_survives(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import create_app
    from api.engine_service import EngineService
    files = create_sealed_database(tmp_path)
    database = Database.open(DEFINITION, tmp_path)
    before = fingerprint(files.physical_files)
    capture = database.session_coordinator.completion.undo.capture
    captured = []
    def record_capture(tx, table_files):
        assert table_files.name != "documentos", "sealed table reached undo capture"
        captured.append(table_files.name)
        return capture(tx, table_files)
    monkeypatch.setattr(database.session_coordinator.completion.undo, "capture", record_capture)
    service = EngineService(database, allow_writes=True)
    try:
        with TestClient(create_app(service)) as http:
            for sql in ("INSERT INTO documentos VALUES (99, 'new')", "DELETE FROM documentos WHERE id = 30",
                        "UPDATE documentos SET contenido = 'new' WHERE id = 30",
                        "CREATE INDEX new_idx ON documentos (id)", "DROP INDEX doc_bplus", "DROP TABLE documentos"):
                response = http.post("/api/query", json={"sql": sql})
                assert response.status_code == 422, response.text
                assert response.json()["error"]["code"] == "EXECUTION_REFUSED"
            assert captured == [] and fingerprint(files.physical_files) == before
            assert http.post("/api/query", json={"sql": "INSERT INTO mutable VALUES (2, 'allowed')"}).status_code == 200
            token = http.post("/api/sessions").json()["token"]
            headers = {"X-Session-Token": token}
            for sql in ("BEGIN TRANSACTION", "INSERT INTO mutable VALUES (3, 'undo me')"):
                response = http.post("/api/query", json={"sql": sql}, headers=headers)
                assert response.status_code == 200, response.text
            denied = http.post("/api/query", json={"sql": "DELETE FROM documentos WHERE id = 30"}, headers=headers)
            assert denied.status_code == 422
            result = http.post("/api/query", json={"sql": "SELECT id FROM mutable ORDER BY id"})
            assert result.status_code == 200 and result.json()["rows"] == [[1], [2]]
            assert fingerprint(files.physical_files) == before
    finally:
        service.close()


def test_owner_claim_waits_for_complete_seal_publication(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from engine.transactions.ownership import claim_directory
    with collection(tmp_path, secondary=False) as (heap, index, _):
        metadata_written, finish = Event(), Event()
        owner_attempted, owner_acquired = Event(), Event()
        write = heap._manager._write_at
        def delayed(offset, payload):
            write(offset, payload)
            if offset == 20:
                metadata_written.set()
                assert finish.wait(10), "publication test did not release the writer"
        monkeypatch.setattr(heap._manager, "_write_at", delayed)
        def open_after_claim():
            owner_attempted.set()
            lease = claim_directory(tmp_path)
            try:
                owner_acquired.set()
                with HeapFile.open(tmp_path / "documents.heap") as reopened:
                    return reopened.read_only and reopened.seal_descriptor == heap.seal_descriptor
            finally:
                lease.release()
        with ThreadPoolExecutor(max_workers=2) as pool:
            publisher = pool.submit(seal_text_collection, heap, index)
            try:
                assert metadata_written.wait(10)
                owner = pool.submit(open_after_claim)
                assert owner_attempted.wait(10)
                assert not owner_acquired.wait(0.1)
            finally:
                finish.set()
            publisher.result(timeout=15)
            assert owner.result(timeout=15)
