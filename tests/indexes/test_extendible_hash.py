"""Stage 5 Increments B/C: persistent equality access and dynamic growth."""

import pytest

from engine.catalog import DataType
from engine.errors import (
    DuplicateError,
    HashBucketOverflowError,
    HashDepthLimitError,
    InvalidTypeError,
    ValidationError,
)
from engine.indexes import ExtendibleHashIndex, HashBucket, HashCodec
from engine.storage import RID
from engine.storage.binary import FILE_HEADER_SIZE, MAX_RECORD_SIZE, PAGE_SIZE


CREATE_ARGUMENTS = {
    "index_name": "idx_people_id_hash",
    "table_name": "people",
    "key_column": "id",
    "key_type": DataType.INTEGER,
}


def routed_keys(*, suffix: int, bits: int, count: int, start: int = 0):
    """Choose deterministic integer keys with one requested LSB hash suffix."""

    result = []
    candidate = start
    mask = (1 << bits) - 1
    while len(result) < count:
        if HashCodec.hash_key(DataType.INTEGER, candidate) & mask == suffix:
            result.append(candidate)
        candidate += 1
    return result


def integer_bucket_capacity() -> int:
    """Derive capacity from serialized bytes rather than duplicating a constant."""

    entries = []
    candidate = 0
    while HashBucket.serialized_size_for(
        DataType.INTEGER, (*entries, (candidate, RID(candidate, 0)))
    ) <= MAX_RECORD_SIZE:
        entries.append((candidate, RID(candidate, 0)))
        candidate += 1
    return len(entries)


def insert_keys(index, keys):
    for key in keys:
        index.insert(key, RID(key, 0))


def test_empty_lifecycle_and_restart_use_only_persisted_metadata(tmp_path):
    path = tmp_path / "empty-hash.idx"
    index = ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS)
    assert index.global_depth == 1
    assert index.entry_count == 0
    assert index.bucket_count == 2
    assert len(index.directory_entries) == 2
    assert index.allocated_page_count == 4
    assert index.file_size == FILE_HEADER_SIZE + 4 * PAGE_SIZE
    assert list(index.search(7)) == []
    index.flush()
    index.close()

    with ExtendibleHashIndex.open(path, **CREATE_ARGUMENTS) as reopened:
        assert reopened.header.hash_algorithm == "FNV1A"
        assert reopened.header.bit_selection == "LSB"
        assert reopened.global_depth == 1
        assert list(reopened.search(7)) == []


def test_insertion_without_growth_changes_only_bucket_and_count(tmp_path):
    with ExtendibleHashIndex.create(
        tmp_path / "simple.idx", **CREATE_ARGUMENTS
    ) as index:
        before_directory = index.directory_entries
        before_pages = index.allocated_page_count
        keys = routed_keys(suffix=0, bits=1, count=2)
        index.reset_counters()
        insert_keys(index, keys)
        assert index.directory_entries == before_directory
        assert index.allocated_page_count == before_pages
        assert index.global_depth == 1
        assert index.pages_allocated == 0
        for key in keys:
            assert list(index.search(key)) == [RID(key, 0)]
        assert list(index.search(999_999)) == []


@pytest.mark.parametrize(
    ("key_type", "key"),
    [
        (DataType.INTEGER, -(2**63)),
        (DataType.FLOAT, float("inf")),
        (DataType.BOOLEAN, True),
        (DataType.VARCHAR, "Lucía 😀"),
    ],
)
def test_persistent_index_supports_every_shared_key_type(tmp_path, key_type, key):
    path = tmp_path / f"typed-{key_type.value}.idx"
    arguments = {
        **CREATE_ARGUMENTS,
        "key_type": key_type,
        "key_column": "value",
    }
    with ExtendibleHashIndex.create(path, **arguments) as index:
        index.insert(key, RID(4, 2))
        assert list(index.search(key)) == [RID(4, 2)]
    with ExtendibleHashIndex.open(path, **arguments) as reopened:
        assert list(reopened.search(key)) == [RID(4, 2)]


def test_non_unique_key_returns_distinct_rids_in_deterministic_order(tmp_path):
    path = tmp_path / "duplicates.idx"
    with ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS) as index:
        index.insert(5, RID(9, 0))
        index.insert(5, RID(2, 0))
        assert list(index.search(5)) == [RID(2, 0), RID(9, 0)]


def test_full_key_comparison_survives_deliberate_hash_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(HashCodec, "hash_bytes", staticmethod(lambda payload: 0))
    with ExtendibleHashIndex.create(
        tmp_path / "collision-compare.idx", **CREATE_ARGUMENTS
    ) as index:
        index.insert(1, RID(1, 0))
        index.insert(2, RID(2, 0))
        assert list(index.search(1)) == [RID(1, 0)]
        assert list(index.search(2)) == [RID(2, 0)]
        assert list(index.search(3)) == []


def test_duplicate_pair_is_idempotent_and_unique_policy_is_unchanged(tmp_path):
    path = tmp_path / "unique.idx"
    with ExtendibleHashIndex.create(
        path, **CREATE_ARGUMENTS, allow_duplicate_keys=False
    ) as index:
        index.insert(8, RID(1, 0))
        writes = index.pages_written
        index.insert(8, RID(1, 0))
        assert index.pages_written == writes
        with pytest.raises(DuplicateError):
            index.insert(8, RID(2, 0))
        assert index.entry_count == 1
        assert list(index.search(8)) == [RID(1, 0)]


def test_bucket_split_and_directory_doubling_survive_restart(tmp_path):
    path = tmp_path / "split.idx"
    capacity = integer_bucket_capacity()
    keys = routed_keys(suffix=0, bits=1, count=capacity + 1)
    with ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS) as index:
        insert_keys(index, keys)
        assert index.global_depth == 2
        assert index.bucket_count == 3
        assert len(index.directory_entries) == 4
        assert len(set(index.directory_entries)) == 3
        for key in keys:
            assert list(index.search(key)) == [RID(key, 0)]

    with ExtendibleHashIndex.open(path, **CREATE_ARGUMENTS) as reopened:
        assert reopened.global_depth == 2
        assert reopened.entry_count == capacity + 1
        for key in keys:
            assert list(reopened.search(key)) == [RID(key, 0)]


def test_split_with_local_depth_below_global_depth_keeps_directory_size(tmp_path):
    capacity = integer_bucket_capacity()
    even_bucket = routed_keys(suffix=0, bits=1, count=capacity + 1)
    odd_bucket = routed_keys(
        suffix=1,
        bits=1,
        count=capacity + 1,
        start=even_bucket[-1] + 1,
    )
    with ExtendibleHashIndex.create(
        tmp_path / "aliased-split.idx", **CREATE_ARGUMENTS
    ) as index:
        insert_keys(index, even_bucket)
        assert index.global_depth == 2
        directory_size = len(index.directory_entries)
        bucket_count = index.bucket_count
        insert_keys(index, odd_bucket)
        assert index.global_depth == 2
        assert len(index.directory_entries) == directory_size
        assert index.bucket_count == bucket_count + 1
        assert len(set(index.directory_entries)) == 4


def test_repeated_splits_grow_directory_across_page_boundary(tmp_path):
    capacity = integer_bucket_capacity()
    # Sharing nine low hash bits forces repeated empty-sided splits; bit ten
    # finally separates the associations after the directory reaches D=10.
    keys = routed_keys(suffix=0, bits=9, count=capacity + 1)
    assert {
        (HashCodec.hash_key(DataType.INTEGER, key) >> 9) & 1 for key in keys
    } == {0, 1}
    with ExtendibleHashIndex.create(
        tmp_path / "multipage-directory.idx", **CREATE_ARGUMENTS
    ) as index:
        insert_keys(index, keys)
        assert index.global_depth == 10
        assert len(index.directory_entries) == 1 << 10
        assert index.header.directory_page_count == 2
        assert index.bucket_count == 11
        for key in keys:
            assert list(index.search(key)) == [RID(key, 0)]


def test_unsplittable_full_hash_collision_is_bounded_and_write_free(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(HashCodec, "hash_bytes", staticmethod(lambda payload: 0))
    capacity = integer_bucket_capacity()
    path = tmp_path / "full-collision.idx"
    with ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS) as index:
        insert_keys(index, range(capacity))
        pages = index.allocated_page_count
        writes = index.pages_written
        with pytest.raises(HashBucketOverflowError, match="Full-hash"):
            index.insert(capacity, RID(capacity, 0))
        assert index.allocated_page_count == pages
        assert index.pages_written == writes
        assert index.entry_count == capacity
        assert list(index.search(0)) == [RID(0, 0)]
    # The test hash remains injected for this fresh object, proving that the
    # rejected association did not damage the persisted collision state.
    with ExtendibleHashIndex.open(path, **CREATE_ARGUMENTS) as reopened:
        assert reopened.entry_count == capacity
        assert list(reopened.search(capacity - 1)) == [RID(capacity - 1, 0)]


def test_maximum_depth_rejection_preserves_prior_contents(tmp_path):
    capacity = integer_bucket_capacity()
    keys = routed_keys(suffix=0, bits=1, count=capacity + 1)
    with ExtendibleHashIndex.create(
        tmp_path / "depth-limit.idx",
        **CREATE_ARGUMENTS,
        maximum_global_depth=1,
    ) as index:
        insert_keys(index, keys[:-1])
        pages = index.allocated_page_count
        writes = index.pages_written
        with pytest.raises(HashDepthLimitError, match="maximum"):
            index.insert(keys[-1], RID(keys[-1], 0))
        assert index.allocated_page_count == pages
        assert index.pages_written == writes
        assert index.entry_count == capacity


def test_lifecycle_and_argument_boundaries(tmp_path):
    path = tmp_path / "boundaries.idx"
    index = ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS)
    with pytest.raises(InvalidTypeError):
        index.insert(True, RID(1, 0))
    index.close()
    index.close()
    for operation in (
        lambda: index.search(1),
        lambda: index.insert(1, RID(1, 0)),
        lambda: index.flush(),
        lambda: index.directory_entries,
    ):
        with pytest.raises(RuntimeError, match="closed"):
            operation()
    with pytest.raises(FileExistsError):
        ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS)
    with pytest.raises(FileNotFoundError):
        ExtendibleHashIndex.open(tmp_path / "absent.idx")


def test_failed_initial_creation_removes_its_incomplete_file(tmp_path):
    path = tmp_path / "invalid-create.idx"
    # The invalid persisted name is detected when the final header is built,
    # after physical initialization has begun, exercising cleanup ownership.
    with pytest.raises(ValidationError, match="must not be empty"):
        ExtendibleHashIndex.create(path, **{**CREATE_ARGUMENTS, "index_name": ""})
    assert not path.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("index_name", "other"),
        ("table_name", "other"),
        ("key_column", "other"),
        ("key_type", DataType.VARCHAR),
        ("allow_duplicate_keys", False),
    ],
)
def test_open_rejects_incompatible_external_definition(tmp_path, field, value):
    path = tmp_path / f"mismatch-{field}.idx"
    ExtendibleHashIndex.create(path, **CREATE_ARGUMENTS).close()
    with pytest.raises(ValidationError, match=field):
        ExtendibleHashIndex.open(path, **{field: value})
