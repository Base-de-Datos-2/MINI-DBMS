"""Stage 5 Increment D: exact deletion and independent validation."""

from dataclasses import replace

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.indexes import (
    ExtendibleHashIndex,
    HashBucket,
    HashCodec,
    HashDirectory,
    HashValidationReport,
)
from engine.storage import RID


CREATE_ARGUMENTS = {
    "index_name": "idx_people_id_hash",
    "table_name": "people",
    "key_column": "id",
    "key_type": DataType.INTEGER,
}


def test_delete_exact_pair_preserves_other_rids_and_empty_bucket(tmp_path):
    path = tmp_path / "delete.idx"
    first = RID(1, 0)
    second = RID(2, 0)
    with ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS) as index:
        index.insert(7, first)
        index.insert(7, second)
        index.insert(8, RID(3, 0))

        assert index.delete(7, first) is None
        assert list(index.search(7)) == [second]
        assert index.entry_count == 2
        index.delete(7, second)
        assert list(index.search(7)) == []
        assert list(index.search(8)) == [RID(3, 0)]
        assert index.entry_count == 1

    with ExtendibleHashIndex.open(path, **CREATE_ARGUMENTS) as reopened:
        assert list(reopened.search(7)) == []
        assert list(reopened.search(8)) == [RID(3, 0)]


def test_missing_deletion_is_write_free_and_uses_shared_contract(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "missing.idx", **CREATE_ARGUMENTS
    ) as index:
        index.insert(4, RID(1, 0))
        writes = index.pages_written
        count = index.entry_count
        with pytest.raises(InvalidReferenceError):
            index.delete(4, RID(9, 0))
        with pytest.raises(InvalidReferenceError):
            index.delete(99, RID(1, 0))
        assert index.pages_written == writes
        assert index.entry_count == count


def test_delete_validates_key_rid_and_closed_lifecycle(tmp_path):
    index = ExtendibleHashIndex.create(
        tmp_path / "boundaries.idx", **CREATE_ARGUMENTS
    )
    with pytest.raises(InvalidTypeError):
        index.delete(True, RID(1, 0))
    with pytest.raises(InvalidTypeError):
        index.delete(1, object())
    index.close()
    with pytest.raises(RuntimeError, match="closed"):
        index.delete(1, RID(1, 0))


def test_validator_reports_complete_topology_without_mutation(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "valid.idx", **CREATE_ARGUMENTS
    ) as index:
        for key in range(25):
            index.insert(key, RID(key, 0))
        writes = index.pages_written
        report = index.validate_structure()
        assert isinstance(report, HashValidationReport)
        assert report.global_depth == index.global_depth
        assert report.directory_entry_count == 1 << index.global_depth
        assert report.bucket_count == index.bucket_count
        assert report.association_count == 25
        assert report.orphan_page_count == 0
        assert index.pages_written == writes
        shallow = index.validate_structure(deep=False)
        assert shallow.association_count == 25
        with pytest.raises(InvalidTypeError):
            index.validate_structure(deep=1)


def test_validator_detects_bad_alias_count_with_bucket_context(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "aliases.idx", **CREATE_ARGUMENTS
    ) as index:
        key = 0
        while index.global_depth == 1:
            index.insert(key, RID(key, 0))
            key += 2
        directory, page_ids = index._read_directory()
        counts = {
            page_id: directory.entries.count(page_id)
            for page_id in set(directory.entries)
        }
        aliased = next(page_id for page_id, count in counts.items() if count == 2)
        singleton = next(page_id for page_id, count in counts.items() if count == 1)
        entries = list(directory.entries)
        entries[entries.index(aliased)] = singleton
        corrupted = HashDirectory(
            directory.global_depth,
            entries,
        )
        index._write_directory_pages(index._directories, corrupted, page_ids)
        with pytest.raises(ValidationError, match="alias count"):
            index.validate_structure()


def test_validator_detects_depth_placement_uniqueness_and_orphans(tmp_path):
    # Each corruption gets its own file so one violated invariant cannot mask
    # the diagnostic expected from the next independent case.
    depth_path = tmp_path / "depth.idx"
    with ExtendibleHashIndex.create(depth_path, **CREATE_ARGUMENTS) as index:
        bucket_id = index.directory_entries[0]
        bucket = index._buckets.read_bucket(bucket_id)
        index._buckets.write_bucket(
            HashBucket(bucket_id, DataType.INTEGER, index.global_depth + 1)
        )
        with pytest.raises(ValidationError, match=f"bucket {bucket_id} local depth"):
            index.validate_structure()

    placement_path = tmp_path / "placement.idx"
    with ExtendibleHashIndex.create(placement_path, **CREATE_ARGUMENTS) as index:
        directory, _ = index._read_directory()
        key = next(
            candidate
            for candidate in range(100)
            if directory.lookup_bucket(
                HashCodec.hash_key(DataType.INTEGER, candidate)
            )
            != directory.entries[0]
        )
        bucket_id = directory.entries[0]
        index._buckets.write_bucket(
            HashBucket(
                bucket_id,
                DataType.INTEGER,
                index.global_depth,
                ((key, RID(1, 0)),),
            )
        )
        index._write_header(replace(index._header, association_count=1))
        with pytest.raises(ValidationError, match="wrong bucket"):
            index.validate_structure()

    orphan_path = tmp_path / "orphan.idx"
    with ExtendibleHashIndex.create(orphan_path, **CREATE_ARGUMENTS) as index:
        index._manager.allocate_page()
        index._write_header(
            replace(index._header, index_page_count=index._header.index_page_count + 1)
        )
        with pytest.raises(ValidationError, match="orphan page"):
            index.validate_structure()


def test_delete_from_split_bucket_survives_restart(tmp_path):
    path = tmp_path / "split-delete.idx"
    with ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS) as index:
        # Long strings are not needed: enough integer/RID pairs eventually force
        # at least one split under the exact serialized-byte capacity rule.
        key = 0
        while index.global_depth == 1:
            index.insert(key, RID(key, 0))
            key += 2
        victim = key - 2
        index.delete(victim, RID(victim, 0))
        index.validate_structure()

    with ExtendibleHashIndex.open(path, **CREATE_ARGUMENTS) as reopened:
        assert list(reopened.search(victim)) == []
        assert reopened.validate_structure().association_count == victim // 2
