"""Tasks 4.26-4.27: clustered B+ coordination and RID repair."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import DuplicateError, InvalidReferenceError, ValidationError
from engine.indexes import ClusteredBPlusIndex
from engine.storage import PagedSequentialFile, Record


SCHEMA = Schema(
    [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
)


def row(key, label, size=1100):
    return Record(SCHEMA, [key, label * size])


def test_clustered_build_requires_the_physical_ordering_key_and_duplicate_policy(
    tmp_path,
):
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id", allow_duplicate_keys=False
    ) as sequential:
        with pytest.raises(ValidationError, match="matching ordered storage"):
            ClusteredBPlusIndex.build(
                tmp_path / "wrong-key.idx",
                sequential=sequential,
                index_name="idx_payload",
                table_name="items",
                key_column="payload",
                allow_duplicate_keys=False,
            )
        with pytest.raises(ValidationError, match="duplicate policy"):
            ClusteredBPlusIndex.build(
                tmp_path / "wrong-policy.idx",
                sequential=sequential,
                index_name="idx_id",
                table_name="items",
                key_column="id",
                allow_duplicate_keys=True,
            )


def test_clustered_insert_rebuilds_all_associations_after_sequential_rid_moves(
    tmp_path,
):
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id"
    ) as sequential:
        for key, label in ((20, "B"), (40, "D"), (60, "F")):
            sequential.insert(row(key, label))
        before = {record["id"]: rid for rid, record in sequential.scan()}

        with ClusteredBPlusIndex.build(
            tmp_path / "id.idx",
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ) as index:
            inserted = index.insert_record(row(10, "A"))
            after = {record["id"]: rid for rid, record in sequential.scan()}

            assert inserted == after[10]
            assert after != {**before, 10: inserted}
            assert [record["id"] for _, record in index.range_records()] == [
                10, 20, 40, 60
            ]
            assert list(index.tree.range_search()) == [
                rid for rid, _ in sequential.scan()
            ]
            assert index.build_metrics.entries_indexed == 4
            assert index.validate_structure().entry_count == 4


def test_clustered_delete_and_reorganization_remove_tombstones_and_rebuild_rids(
    tmp_path,
):
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id"
    ) as sequential:
        for key in (4, 1, 3, 2):
            sequential.insert(row(key, str(key)))
        with ClusteredBPlusIndex.build(
            tmp_path / "id.idx",
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ) as index:
            removed_rid = next(index.search(2))
            index.delete_record(removed_rid)
            assert list(index.search(2)) == []
            with pytest.raises(InvalidReferenceError):
                sequential.read(removed_rid)
            assert sequential.deleted_record_count == 1

            metrics = index.reorganize()

            assert sequential.deleted_record_count == 0
            assert [record["id"] for _, record in index.range_records()] == [
                1, 3, 4
            ]
            assert metrics.index.entries_indexed == 3
            assert metrics.storage.pages_written > 0
            assert index.validate_structure().entry_count == 3


def test_clustered_detects_external_rid_changes_and_can_rebuild(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id"
    ) as sequential:
        for key in (20, 40, 60):
            sequential.insert(row(key, str(key)))
        with ClusteredBPlusIndex.build(
            tmp_path / "id.idx",
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ) as index:
            sequential.insert(row(10, "E"))
            with pytest.raises(ValidationError):
                index.validate_structure()

            metrics = index.rebuild()

            assert metrics.entries_indexed == 4
            assert index.validate_structure().entry_count == 4
            assert [record["id"] for _, record in index.range_records()] == [
                10, 20, 40, 60
            ]


def test_clustered_reopens_with_fresh_storage_and_rejects_stale_raw_rid(
    tmp_path,
):
    storage_path = tmp_path / "ordered.db"
    index_path = tmp_path / "id.idx"
    with PagedSequentialFile.create(storage_path, SCHEMA, "id") as sequential:
        for key in (3, 1, 2):
            sequential.insert(row(key, str(key), 20))
        ClusteredBPlusIndex.build(
            index_path,
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ).close()

    with PagedSequentialFile.open(storage_path, SCHEMA, "id") as sequential:
        with ClusteredBPlusIndex.open(
            index_path,
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ) as index:
            with closing(index.search_records(2)) as matches:
                rid, record = next(matches)
            assert record["id"] == 2
            with pytest.raises(InvalidReferenceError, match="does not match"):
                index.insert(1, rid)
            assert index.validate_structure().entry_count == 3
        assert not sequential.closed


def test_failed_unique_precondition_does_not_invalidate_clustered_index(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id", allow_duplicate_keys=False
    ) as sequential:
        sequential.insert(row(1, "first", 20))
        with ClusteredBPlusIndex.build(
            tmp_path / "id.idx",
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
            allow_duplicate_keys=False,
        ) as index:
            with pytest.raises(DuplicateError):
                index.insert_record(row(1, "second", 20))
            assert index.consistent
            assert list(index.search(1))
            assert index.validate_structure().entry_count == 1


def test_failed_post_storage_rebuild_leaves_persistent_incomplete_marker(
    tmp_path, monkeypatch
):
    index_path = tmp_path / "id.idx"
    with PagedSequentialFile.create(
        tmp_path / "ordered.db", SCHEMA, "id"
    ) as sequential:
        sequential.insert(row(2, "B", 20))
        with ClusteredBPlusIndex.build(
            index_path,
            sequential=sequential,
            index_name="idx_items_id",
            table_name="items",
            key_column="id",
        ) as index:
            original_rebuild = index.tree.rebuild_from_storage
            monkeypatch.setattr(
                index.tree,
                "rebuild_from_storage",
                lambda storage: (_ for _ in ()).throw(OSError("injected rebuild")),
            )
            with pytest.raises(OSError, match="injected rebuild"):
                index.insert_record(row(1, "A", 20))
            assert not index.consistent
            with pytest.raises(ValidationError, match="must be rebuilt"):
                list(index.search(1))
            monkeypatch.setattr(index.tree, "rebuild_from_storage", original_rebuild)
            assert index.rebuild().entries_indexed == 2
            assert index.consistent
            assert index.validate_structure().entry_count == 2
