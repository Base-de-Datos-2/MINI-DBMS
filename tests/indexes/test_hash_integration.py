"""Stage 5 Increment E: Heap builds, maintenance, Catalog, and metrics."""

from contextlib import closing

import pytest

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import DuplicateError, InvalidReferenceError, ValidationError
from engine.indexes import (
    ExtendibleHashIndex,
    HashCodec,
    HashHeaderPageIO,
    UnclusteredHashIndex,
    build_and_register_catalog_hash,
    build_catalog_index,
    drop_catalog_index,
    open_catalog_hash,
    open_catalog_index,
)
from engine.storage import HeapFile, PageManager, RID, Record


SCHEMA = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)


def test_build_from_heap_indexes_only_active_multipage_rows_and_metrics(tmp_path):
    heap_path = tmp_path / "people.heap"
    index_path = tmp_path / "people.hash"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        records = [
            Record(SCHEMA, [number % 5, f"person-{number}-" + "x" * 900])
            for number in range(20)
        ]
        rids = [heap.insert(record) for record in records]
        deleted = {rids[2], rids[11]}
        for rid in deleted:
            heap.delete(rid)
        reads_before = heap.pages_read

        index = ExtendibleHashIndex.build_from_storage(
            index_path,
            storage=heap,
            index_name="idx_people_id_hash",
            table_name="people",
            key_column="id",
        )
        try:
            expected = [
                rid
                for rid, record in zip(rids, records)
                if rid not in deleted and record["id"] == 3
            ]
            assert list(index.search(3)) == sorted(expected)
            assert index.entry_count == heap.record_count == 18
            assert index.build_metrics.associations_indexed == 18
            assert index.build_metrics.storage_pages_read == (
                heap.pages_read - reads_before
            )
            assert index.build_metrics.index_file_size == index.file_size
            assert index.validate_structure().association_count == 18
        finally:
            index.close()

    with ExtendibleHashIndex.open(index_path) as reopened:
        assert reopened.build_metrics is None
        assert reopened.validate_structure().association_count == 18


def test_failed_unique_build_is_incomplete_and_not_catalog_visible(tmp_path):
    index_path = tmp_path / "unique.hash"
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    metadata = IndexMetadata(
        "idx_unique",
        "people",
        "id",
        IndexType.EXTENDIBLE_HASH,
        unique=True,
        file_path=str(index_path),
    )
    with HeapFile.create(tmp_path / "duplicates.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, [1, "first"]))
        heap.insert(Record(SCHEMA, [1, "second"]))
        with pytest.raises(DuplicateError):
            build_and_register_catalog_hash(catalog, metadata, heap)
        with pytest.raises(InvalidReferenceError):
            catalog.get_index("idx_unique")

    with PageManager.open(index_path) as manager:
        assert not HashHeaderPageIO.read(manager).build_complete
    with pytest.raises(ValidationError, match="build is incomplete"):
        ExtendibleHashIndex.open(index_path)


def test_successful_build_publishes_catalog_only_after_validation(tmp_path):
    heap_path = tmp_path / "published.heap"
    index_path = tmp_path / "published.hash"
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    metadata = IndexMetadata(
        "idx_published",
        "people",
        "name",
        IndexType.EXTENDIBLE_HASH,
        file_path=str(index_path),
    )
    with HeapFile.create(heap_path, SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, [1, "variable-length-key"]))
        runtime = build_and_register_catalog_hash(catalog, metadata, heap)
        assert catalog.get_index("idx_published") == metadata
        assert list(runtime.search("variable-length-key")) == [rid]
        runtime.close()
        with open_catalog_hash(catalog, "idx_published", heap) as reopened:
            assert list(reopened.search("variable-length-key")) == [rid]
            reopened.validate_structure()


def test_unclustered_hash_maintains_insert_delete_update_and_rebuild(tmp_path):
    heap_path = tmp_path / "people.heap"
    index_path = tmp_path / "people.hash"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        original = heap.insert(Record(SCHEMA, [1, "Ada"]))
        with UnclusteredHashIndex.build(
            index_path,
            heap=heap,
            index_name="idx_people_id_hash",
            table_name="people",
            key_column="id",
            allow_duplicate_keys=False,
        ) as runtime:
            inserted = runtime.insert_record(Record(SCHEMA, [2, "Grace"]))
            assert [record["name"] for _, record in runtime.search_records(2)] == [
                "Grace"
            ]
            updated = runtime.update_record(inserted, Record(SCHEMA, [3, "Hopper"]))
            assert updated != inserted or heap.read(updated)["id"] == 3
            assert list(runtime.search(2)) == []
            assert [record["name"] for _, record in runtime.search_records(3)] == [
                "Hopper"
            ]
            runtime.delete_record(original)
            assert list(runtime.search(1)) == []
            assert runtime.validate_structure().association_count == 1

            # A direct Heap insertion is intentionally outside maintenance; an
            # atomic rebuild consumes the current source of truth and repairs it.
            external = heap.insert(Record(SCHEMA, [4, "Barbara"]))
            with pytest.raises(ValidationError, match="entry count"):
                runtime.validate_structure()
            metrics = runtime.rebuild()
            assert metrics.associations_indexed == 2
            assert external in runtime.search(4)
            runtime.validate_structure()

    with HeapFile.open(heap_path, SCHEMA) as heap:
        with UnclusteredHashIndex.open(
            index_path,
            heap=heap,
            index_name="idx_people_id_hash",
            table_name="people",
            key_column="id",
            allow_duplicate_keys=False,
        ) as reopened:
            assert [record["name"] for _, record in reopened.search_records(3)] == [
                "Hopper"
            ]
            reopened.validate_structure()


def test_search_records_detects_a_stale_rid(tmp_path):
    with HeapFile.create(tmp_path / "stale.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, [7, "Ada"]))
        with UnclusteredHashIndex.build(
            tmp_path / "stale.hash",
            heap=heap,
            index_name="idx",
            table_name="people",
            key_column="id",
        ) as runtime:
            heap.delete(rid)
            with pytest.raises(InvalidReferenceError):
                list(runtime.search_records(7))


def test_unique_update_same_key_and_duplicate_failure_preserve_consistency(tmp_path):
    with HeapFile.create(tmp_path / "updates.heap", SCHEMA) as heap:
        first = heap.insert(Record(SCHEMA, [1, "old name"]))
        second = heap.insert(Record(SCHEMA, [2, "occupied"]))
        with UnclusteredHashIndex.build(
            tmp_path / "updates.hash",
            heap=heap,
            index_name="idx",
            table_name="people",
            key_column="id",
            allow_duplicate_keys=False,
        ) as runtime:
            replacement = runtime.update_record(
                first, Record(SCHEMA, [1, "new name"])
            )
            assert [record["name"] for _, record in runtime.search_records(1)] == [
                "new name"
            ]
            with pytest.raises(DuplicateError):
                runtime.update_record(replacement, Record(SCHEMA, [2, "conflict"]))
            assert [record["name"] for _, record in runtime.search_records(1)] == [
                "new name"
            ]
            assert list(runtime.search(2)) == [second]
            runtime.validate_structure()


def test_catalog_dispatch_capabilities_reopen_and_drop(tmp_path):
    heap_path = tmp_path / "people.heap"
    index_path = tmp_path / "people.hash"
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    metadata = IndexMetadata(
        "idx_hash",
        "people",
        "id",
        IndexType.EXTENDIBLE_HASH,
        file_path=str(index_path),
    )
    catalog.register_index(metadata)
    assert metadata.supports_equality
    assert not metadata.supports_range
    assert not metadata.supports_ordering

    with HeapFile.create(heap_path, SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, [8, "Edsger"]))
        runtime = build_catalog_index(catalog, "idx_hash", heap)
        assert isinstance(runtime, UnclusteredHashIndex)
        assert list(runtime.search(8)) == [rid]
        runtime.close()

    with HeapFile.open(heap_path, SCHEMA) as heap:
        runtime = open_catalog_index(catalog, "idx_hash", heap)
        assert list(runtime.search(8)) == [rid]
        runtime.close()
    drop_catalog_index(catalog, "idx_hash")
    assert not index_path.exists()
    with pytest.raises(InvalidReferenceError):
        catalog.get_index("idx_hash")


def test_catalog_drop_validates_physical_identity_before_unlinking(tmp_path):
    unrelated_path = tmp_path / "unrelated.hash"
    ExtendibleHashIndex.create(
        unrelated_path,
        index_name="different",
        table_name="people",
        key_column="id",
        key_type=DataType.INTEGER,
    ).close()
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    catalog.register_index(
        IndexMetadata(
            "expected",
            "people",
            "id",
            IndexType.EXTENDIBLE_HASH,
            file_path=str(unrelated_path),
        )
    )
    with pytest.raises(ValidationError, match="index_name"):
        drop_catalog_index(catalog, "expected")
    assert unrelated_path.exists()
    assert catalog.get_index("expected").file_path == str(unrelated_path)


def test_hash_metrics_separate_typed_io_and_logical_events(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "metrics.hash",
        index_name="idx",
        table_name="people",
        key_column="id",
        key_type=DataType.INTEGER,
    ) as index:
        index.insert(1, RID(1, 0))
        index.reset_counters()
        with closing(index.search(1)) as matches:
            assert list(matches) == [RID(1, 0)]
        metrics = index.metrics
        assert metrics.directory_page_reads == 1
        assert metrics.bucket_page_reads == 1
        assert metrics.associations_inspected == 1
        assert metrics.current_global_depth == index.global_depth
        assert metrics.current_live_bucket_count == index.bucket_count
        assert metrics.allocated_index_pages == index.header.index_page_count
        assert metrics.allocated_index_bytes == index.file_size
        assert metrics.bucket_page_frees == 0
        assert metrics.bucket_merges == 0
        assert metrics.directory_shrinks == 0


def test_hash_metrics_count_committed_splits_doublings_and_allocations(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "structural-metrics.hash",
        index_name="idx",
        table_name="people",
        key_column="name",
        key_type=DataType.VARCHAR,
    ) as index:
        index.reset_counters()
        candidate = 0
        # Large keys make the byte-capacity boundary small while selecting one
        # initial suffix forces the educational split path deterministically.
        while index.global_depth == 1:
            key = f"{candidate:04d}-" + "x" * 220
            if HashCodec.hash_key(DataType.VARCHAR, key) & 1 == 0:
                index.insert(key, RID(candidate, 0))
            candidate += 1
        metrics = index.metrics
        assert metrics.bucket_splits >= 1
        assert metrics.directory_doublings >= 1
        assert metrics.bucket_page_allocations >= 1
        assert metrics.bucket_page_writes >= 2
        assert metrics.directory_page_writes >= 1
