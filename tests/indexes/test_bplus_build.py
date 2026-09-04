"""Task 4.24: incremental B+ construction from Stage 3 storage."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import DuplicateError, UnknownColumnError, ValidationError
from engine.indexes import BPlusHeaderPageIO, BPlusTree
from engine.storage import HeapFile, PageManager, Record


SCHEMA = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)


def build_arguments(heap):
    return {
        "storage": heap,
        "index_name": "idx_people_id",
        "table_name": "people",
        "key_column": "id",
    }


def test_build_empty_storage_persists_complete_empty_index_and_metrics(tmp_path):
    heap_path = tmp_path / "empty.heap"
    index_path = tmp_path / "empty.idx"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        tree = BPlusTree.build_from_storage(index_path, **build_arguments(heap))
        try:
            assert tree.header.build_complete
            assert tree.entry_count == 0
            metrics = tree.build_metrics
            assert metrics.entries_indexed == 0
            assert metrics.elapsed_seconds >= 0
            assert metrics.storage_pages_read == 0
            assert metrics.index_pages_written >= 3
            assert metrics.index_file_size == tree.file_size
            tree.validate_structure()
        finally:
            tree.close()

    with BPlusTree.open(index_path) as reopened:
        assert reopened.header.build_complete
        assert reopened.build_metrics is None
        assert reopened.validate_structure().entry_count == 0


def test_build_indexes_active_multipage_rows_and_skips_deleted_records(tmp_path):
    heap_path = tmp_path / "people.heap"
    index_path = tmp_path / "people.idx"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        records = [
            Record(SCHEMA, [number % 7, f"person-{number}-" + "x" * 900])
            for number in range(20)
        ]
        rids = [heap.insert(record) for record in records]
        deleted = {rids[2], rids[11]}
        for rid in deleted:
            heap.delete(rid)
        reads_before = heap.pages_read

        tree = BPlusTree.build_from_storage(index_path, **build_arguments(heap))
        try:
            expected = [
                rid for rid, record in zip(rids, records)
                if rid not in deleted and record["id"] == 3
            ]
            assert list(tree.search(3)) == sorted(expected)
            assert tree.entry_count == heap.record_count == 18
            assert tree.build_metrics.entries_indexed == 18
            assert tree.build_metrics.storage_pages_read == heap.pages_read - reads_before
            assert tree.build_metrics.storage_pages_read == heap.data_page_count
            tree.validate_structure()
        finally:
            tree.close()

    with HeapFile.open(heap_path) as heap, BPlusTree.open(index_path) as tree:
        with closing(heap.scan()) as rows:
            expected_rids = sorted(rid for rid, _ in rows)
        assert sorted(tree.range_search()) == expected_rids


def test_build_validates_column_before_creating_index_file(tmp_path):
    index_path = tmp_path / "missing-column.idx"
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        arguments = build_arguments(heap)
        arguments["key_column"] = "missing"
        with pytest.raises(UnknownColumnError):
            BPlusTree.build_from_storage(index_path, **arguments)
    assert not index_path.exists()


def test_failed_unique_build_remains_persistently_incomplete(tmp_path):
    index_path = tmp_path / "incomplete.idx"
    with HeapFile.create(tmp_path / "duplicates.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, [1, "first"]))
        heap.insert(Record(SCHEMA, [1, "second"]))
        with pytest.raises(DuplicateError):
            BPlusTree.build_from_storage(
                index_path,
                **build_arguments(heap),
                allow_duplicate_keys=False,
            )

    with PageManager.open(index_path) as manager:
        assert not BPlusHeaderPageIO.read(manager).build_complete
    with pytest.raises(ValidationError, match="build is incomplete"):
        BPlusTree.open(index_path)
