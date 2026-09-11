"""Stage 5.22–5.27 regression and end-to-end acceptance evidence."""

from pathlib import Path
from dataclasses import replace
import random

import pytest

from engine.catalog import Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata
from engine.errors import DuplicateError, InvalidReferenceError, InvalidTypeError, SchemaError, ValidationError
from engine.indexes import (
    ExtendibleHashIndex, HashCodec, HashHeaderPageIO, UnclusteredHashIndex,
    build_and_register_catalog_hash, open_catalog_index, drop_catalog_index,
)
from engine.storage import HeapFile, PageManager, Record


SCHEMA = Schema([Column("k", DataType.VARCHAR), Column("value", DataType.INTEGER)])


def definition(path, unique=False):
    return IndexMetadata("idx", "t", "k", IndexType.EXTENDIBLE_HASH,
                         unique=unique, file_path=str(path))


def catalog():
    result = Catalog()
    result.register_table(TableMetadata("t", SCHEMA))
    return result


def build(heap, path, unique=False):
    return UnclusteredHashIndex.build(path, heap=heap, index_name="idx",
        table_name="t", key_column="k", allow_duplicate_keys=not unique)


@pytest.mark.parametrize("operation", ["insert", "delete", "update"])
@pytest.mark.parametrize("marker_fails", [False, True])
def test_failed_rollback_marks_incomplete_or_closes_without_hiding_errors(tmp_path, monkeypatch, operation, marker_fails):
    path = tmp_path / "failure.hash"
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, ["old", 1]))
        runtime = build(heap, path)
        core = runtime.index
        def fail_index(*args):
            raise ValueError("index failure")
        def fail_heap(*args):
            raise OSError("heap failure")
        def fail_marker():
            raise OSError("marker failure")
        with monkeypatch.context() as faults:
            faults.setattr(core, "insert", fail_index)
            faults.setattr(heap, "delete", fail_heap)
            if marker_fails:
                faults.setattr(core, "mark_incomplete", fail_marker)
            with pytest.raises(BaseExceptionGroup) as caught:
                if operation == "insert":
                    runtime.insert_record(Record(SCHEMA, ["new", 2]))
                elif operation == "delete":
                    runtime.delete_record(rid)
                else:
                    runtime.update_record(rid, Record(SCHEMA, ["new", 2]))
            messages = [str(exc) for exc in caught.value.exceptions]
            assert any("index failure" in message for message in messages)
            assert any("heap failure" in message for message in messages)
            if marker_fails:
                assert "marker failure" in messages
                assert runtime.closed
            else:
                assert not core.header.build_complete
                with pytest.raises(ValidationError, match="incomplete"):
                    list(runtime.search("old"))
        runtime.close()
        with pytest.raises(ValidationError):
            UnclusteredHashIndex.open(path, heap=heap)


@pytest.mark.parametrize("method", ["search", "search_records"])
def test_adapter_rejects_recycled_rid_for_another_key(tmp_path, method):
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        old = heap.insert(Record(SCHEMA, ["old", 1]))
        with build(heap, tmp_path / "index.hash") as runtime:
            heap.delete(old)
            assert heap.insert(Record(SCHEMA, ["new", 2])) == old
            with pytest.raises(InvalidReferenceError, match="does not match"):
                list(getattr(runtime, method)("old"))
            with pytest.raises(ValidationError):
                runtime.validate_structure()
            runtime.rebuild()
            assert list(runtime.search("old")) == []
            assert list(runtime.search("new")) == [old]
            runtime.validate_structure()


def test_build_flushes_before_catalog_publication(tmp_path, monkeypatch):
    path = tmp_path / "build.hash"
    registry = catalog()
    events = []
    flush = ExtendibleHashIndex.flush
    register = registry.register_index
    def observe_flush(index):
        flush(index)
        events.append("flush")
    def observe_register(metadata):
        assert events == ["flush"]
        register(metadata)
        events.append("register")
    monkeypatch.setattr(ExtendibleHashIndex, "flush", observe_flush)
    monkeypatch.setattr(registry, "register_index", observe_register)
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, ["x", 1]))
        with build_and_register_catalog_hash(registry, definition(path), heap) as runtime:
            assert events == ["flush", "register"]
            assert runtime.build_metrics.index_pages_written == runtime.index.pages_written


def test_build_flush_failure_is_not_published(tmp_path, monkeypatch):
    path = tmp_path / "build.hash"
    registry = catalog()
    def fail_flush(index):
        raise OSError("flush failure")
    monkeypatch.setattr(ExtendibleHashIndex, "flush", fail_flush)
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        with pytest.raises(OSError, match="flush failure"):
            build_and_register_catalog_hash(registry, definition(path), heap)
        assert registry.list_indexes() == ()
    with PageManager.open(path) as manager:
        assert not HashHeaderPageIO.read(manager).build_complete


@pytest.mark.parametrize("unique", [False, True])
def test_heap_catalog_differential_restart_growth_and_rebuild(tmp_path, monkeypatch, unique):
    # Test-only controlled hash forces multiple directory pages cheaply.
    monkeypatch.setattr(HashCodec, "hash_key", staticmethod(
        lambda kind, key: int(key.split(":")[0]) * 512))
    def key(n):
        return f"{n}:" + "x" * (215 + n % 20)
    path, source = tmp_path / "index.hash", tmp_path / "source.heap"
    metadata = definition(path, unique)
    heap = HeapFile.create(source, SCHEMA)
    expected = {}
    for n in range(36):
        record = Record(SCHEMA, [key(n), n])
        expected[heap.insert(record)] = record
    deleted = next(iter(expected))
    heap.delete(deleted)
    del expected[deleted]
    runtime = build_and_register_catalog_hash(catalog(), metadata, heap)
    rng = random.Random(52227)
    try:
        assert runtime.index.header.directory_page_count > 1
        for step in range(48):
            if step % 3 == 0:
                rid = rng.choice(list(expected))
                runtime.delete_record(rid)
                del expected[rid]
            elif step % 3 == 1:
                rid = rng.choice(list(expected))
                row = Record(SCHEMA, [key(100 + step), step])
                replacement = runtime.update_record(rid, row)
                del expected[rid]
                expected[replacement] = row
            else:
                row = Record(SCHEMA, [key(200 + step) if unique else key(1), step])
                expected[runtime.insert_record(row)] = row
            assert dict(heap.scan()) == expected
            runtime.validate_structure()
            for value in {r["k"] for r in expected.values()} | {key(999)}:
                assert set(runtime.search(value)) == {rid for rid, row in expected.items() if row["k"] == value}
            if step % 12 == 11:
                runtime.flush()
                runtime.close()
                heap.close()
                # No Catalog, metadata, schema, storage or runtime is reused.
                del runtime, heap
                fresh_schema = Schema([Column("k", DataType.VARCHAR), Column("value", DataType.INTEGER)])
                registry = Catalog()
                registry.register_table(TableMetadata("t", fresh_schema))
                registry.register_index(definition(path, unique))
                heap = HeapFile.open(source, fresh_schema)
                runtime = open_catalog_index(registry, "idx", heap)
                runtime.validate_structure()
        before = dict(heap.scan())
        metrics = runtime.rebuild()
        assert metrics.associations_indexed == len(before)
        assert metrics.index_pages_allocated > 0
        assert metrics.index_file_size == path.stat().st_size
        assert dict(heap.scan()) == before
        runtime.validate_structure()
    finally:
        runtime.close()
        heap.close()


def test_catalog_registration_failure_removes_only_completed_new_index(tmp_path, monkeypatch):
    path = tmp_path / "index.hash"
    registry = catalog()
    def fail_register(metadata):
        raise DuplicateError("publication failure")
    monkeypatch.setattr(registry, "register_index", fail_register)
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, ["x", 1]))
        with pytest.raises(DuplicateError, match="publication"):
            build_and_register_catalog_hash(registry, definition(path), heap)
        assert not path.exists()
        assert heap.read(rid)["k"] == "x"
        assert registry.list_indexes() == ()


def test_failed_drop_keeps_catalog_definition(tmp_path, monkeypatch):
    path = tmp_path / "index.hash"
    registry = catalog()
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        build_and_register_catalog_hash(registry, definition(path), heap).close()
        unlink = Path.unlink
        def fail_unlink(target, *args, **kwargs):
            if target == path:
                raise PermissionError("busy index")
            return unlink(target, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(PermissionError, match="busy"):
            drop_catalog_index(registry, "idx")
        assert registry.get_index("idx") == definition(path)
        assert path.exists()


@pytest.mark.parametrize("issue", ["table", "column", "type", "path", "schema", "name"])
def test_catalog_rejects_bad_definition_before_creating_file(tmp_path, issue):
    path = tmp_path / "never.hash"
    registry = catalog()
    metadata = definition(path)
    if issue == "table":
        metadata = replace(metadata, table_name="missing")
    elif issue == "column":
        metadata = replace(metadata, column_name="missing")
    elif issue == "type":
        metadata = replace(metadata, index_type=IndexType.BPLUS)
    elif issue == "path":
        metadata = replace(metadata, file_path=None)
    elif issue == "name":
        registry.register_index(metadata)
    schema = Schema([Column("different", DataType.INTEGER)]) if issue == "schema" else SCHEMA
    with HeapFile.create(tmp_path / "source.heap", schema) as heap:
        previous = registry.list_indexes()
        with pytest.raises((ValidationError, InvalidReferenceError, KeyError, InvalidTypeError, SchemaError)):
            build_and_register_catalog_hash(registry, metadata, heap)
        assert not path.exists()
        assert registry.list_indexes() == previous


@pytest.mark.parametrize("operation", ["insert", "delete"])
def test_successful_rollback_preserves_complete_usable_index(tmp_path, monkeypatch, operation):
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, ["old", 1]))
        with build(heap, tmp_path / "index.hash", unique=True) as runtime:
            if operation == "insert":
                with pytest.raises(DuplicateError):
                    runtime.insert_record(Record(SCHEMA, ["old", 2]))
            else:
                with monkeypatch.context() as faults:
                    def fail_delete(rid):
                        raise OSError("heap rejected deletion")
                    faults.setattr(heap, "delete", fail_delete)
                    with pytest.raises(OSError):
                        runtime.delete_record(rid)
            assert runtime.index.header.build_complete
            assert list(runtime.search("old")) == [rid]
            assert heap.record_count == 1
            runtime.validate_structure()


def test_incomplete_adapter_can_rebuild_and_resume(tmp_path):
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        with build(heap, tmp_path / "index.hash") as runtime:
            runtime.index.mark_incomplete()
            with pytest.raises(ValidationError, match="incomplete"):
                runtime.insert_record(Record(SCHEMA, ["new", 1]))
            runtime.rebuild()
            rid = runtime.insert_record(Record(SCHEMA, ["new", 1]))
            assert list(runtime.search("new")) == [rid]
            runtime.validate_structure()


def test_failed_rebuild_preserves_original_and_cleans_candidate(tmp_path):
    path = tmp_path / "index.hash"
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, ["old", 1]))
        with build(heap, path, unique=True) as runtime:
            files = set(tmp_path.iterdir())
            before = path.read_bytes()
            extra = heap.insert(Record(SCHEMA, ["old", 2]))
            with pytest.raises(DuplicateError):
                runtime.rebuild()
            assert path.read_bytes() == before
            assert set(tmp_path.iterdir()) == files
            heap.delete(extra)
            runtime.validate_structure()


def test_metric_snapshot_reset_reopen_and_build_scopes(tmp_path):
    path = tmp_path / "index.hash"
    with HeapFile.create(tmp_path / "source.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, ["x", 1]))
        with build(heap, path) as runtime:
            core = runtime.index
            build_metrics = core.build_metrics
            assert build_metrics.elapsed_seconds >= 0
            assert build_metrics.storage_pages_read > 0
            assert build_metrics.index_pages_allocated == core.pages_allocated
            assert build_metrics.index_pages_written == core.pages_written
            snapshot = core.metrics
            core.reset_counters()
            assert snapshot.bucket_page_allocations > 0
            assert core.metrics.bucket_page_allocations == 0
            list(core.search("x"))
            assert core.pages_read == 2
            with pytest.raises(InvalidReferenceError):
                core.delete("absent", rid)
            assert core.pages_read == 4
            assert core.pages_written == 0
            assert core.build_metrics is build_metrics
        with UnclusteredHashIndex.open(path, heap=heap) as reopened:
            assert reopened.build_metrics is None
            assert reopened.index.pages_read > 0  # validation, not cache hits
            assert reopened.index.pages_allocated == 0
