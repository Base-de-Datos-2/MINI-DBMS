"""Stage 5.8–5.15: lifecycle, routes, split invariants and bounded failures."""

from collections import Counter
from dataclasses import replace

import pytest

from engine.catalog import DataType
from engine.errors import (
    DuplicateError, HashBucketOverflowError, HashDepthLimitError,
    InvalidReferenceError, InvalidTypeError, ValidationError,
)
from engine.indexes import (
    BPlusTree, ExtendibleHashIndex, HashBucket, HashCodec,
)
from engine.indexes.hash_binary import HASH_UINT64_MAX
from engine.storage import PageManager, RID


ARGS = dict(index_name="idx", table_name="t", key_column="k", key_type=DataType.VARCHAR)


def key(number, size=240):
    prefix = f"{number}:"
    return prefix + "x" * (size-len(prefix))


@pytest.fixture
def routed_hash(monkeypatch):
    # The replacement is test-only and stays installed across each reopen.
    monkeypatch.setattr(HashCodec, "hash_key", staticmethod(
        lambda key_type, value: int(value.partition(":")[0])))


def fill_target(index, *, step=2, size=240):
    entries = []
    number = 0
    while True:
        value = key(number, size)
        bucket_id = index.directory_entries[0]
        bucket = index._buckets.read_bucket(bucket_id)
        if not bucket.can_fit(value, RID(number, 0)):
            return entries, (value, RID(number, 0))
        index.insert(value, RID(number, 0))
        entries.append((value, RID(number, 0)))
        number += step


def assert_contents(index, entries):
    report = index.validate_structure()
    assert report.association_count == len(entries)
    expected = {}
    for value, rid in entries:
        expected.setdefault(value, set()).add(rid)
    for value, rids in expected.items():
        assert set(index.search(value)) == rids


@pytest.mark.parametrize("operation", ["search", "insert"])
def test_routed_operations_reject_bucket_depth_above_global(tmp_path, operation):
    with ExtendibleHashIndex.create(tmp_path / "depth.hash", **ARGS) as index:
        value = key(1)
        index.insert(value, RID(1, 0))
        bucket_id = index._lookup_bucket_page_id(HashCodec.hash_key(DataType.VARCHAR, value))
        bucket = index._buckets.read_bucket(bucket_id)
        index._buckets.write_bucket(HashBucket(
            bucket_id, DataType.VARCHAR, index.global_depth+1, bucket.entries))
        writes = index.pages_written
        with pytest.raises(ValidationError, match="local depth"):
            if operation == "search":
                list(index.search(value))
            else:
                index.insert(value, RID(2, 0))
        assert index.pages_written == writes


@pytest.mark.parametrize("unique,value", [(False, 1), (True, 0)])
def test_open_rejects_integer_instead_of_boolean_metadata(tmp_path, unique, value):
    path = tmp_path / "metadata.hash"
    ExtendibleHashIndex.create(path, allow_duplicate_keys=not unique, **ARGS).close()
    with pytest.raises(InvalidTypeError):
        with ExtendibleHashIndex.open(path, allow_duplicate_keys=value):
            pass


def test_counter_limit_does_not_break_exact_pair_idempotence(tmp_path):
    with ExtendibleHashIndex.create(tmp_path / "limit.hash", **ARGS) as index:
        index.insert(key(1), RID(1, 0))
        original = index.header
        # Synthetic boundary: no uint64-sized dataset or corrupt on-disk header.
        index._header = replace(original, association_count=HASH_UINT64_MAX)
        writes = index.pages_written
        try:
            assert index.insert(key(1), RID(1, 0)) is None
            with pytest.raises(ValidationError, match="uint64"):
                index.insert(key(2), RID(2, 0))
            assert index.pages_written == writes
        finally:
            index._header = original
        index.validate_structure()


@pytest.mark.parametrize("depth", [0, 1, 3])
def test_empty_lifecycle_reopens_persisted_nondefault_configuration(tmp_path, depth):
    path = tmp_path / "empty.hash"
    index = ExtendibleHashIndex.create(
        path, initial_global_depth=depth, maximum_global_depth=depth+2,
        allow_duplicate_keys=False, **ARGS)
    index.validate_structure()
    index.flush()
    index.close()
    index.close()
    del index
    with ExtendibleHashIndex.open(path) as reopened:
        assert reopened.header.initial_global_depth == depth
        assert reopened.header.maximum_global_depth == depth+2
        assert not reopened.header.allow_duplicate_keys
        assert reopened.validate_structure().bucket_count == 1 << depth
        assert list(reopened.search("absent")) == []


def test_failed_open_releases_manager_and_preserves_non_hash_file(tmp_path, monkeypatch):
    path = tmp_path / "tree.bplus"
    BPlusTree.create(path, **ARGS).close()
    before = path.read_bytes()
    captured = []
    original_open = PageManager.open
    def capture(path):
        manager = original_open(path)
        captured.append(manager)
        return manager
    monkeypatch.setattr(PageManager, "open", capture)
    with pytest.raises(ValidationError):
        ExtendibleHashIndex.open(path)
    assert captured[0].closed
    assert path.read_bytes() == before


def test_search_generator_is_lazy_closable_and_rejects_closed_index(tmp_path):
    index = ExtendibleHashIndex.create(tmp_path / "generator.hash", **ARGS)
    index.insert(key(1), RID(1, 0))
    index.reset_counters()
    result = index.search(key(1))
    assert index.pages_read == 0
    assert next(result) == RID(1, 0)
    result.close()
    assert not index.closed
    assert index.pages_read == 2
    pending = index.search(key(1))
    index.close()
    with pytest.raises(RuntimeError, match="closed"):
        next(pending)
    for operation in (lambda: index.insert(key(1), RID(1, 0)), index.flush,
                      lambda: index.search(key(1))):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


def test_search_reads_one_selected_bucket_on_multipage_directory(tmp_path, routed_hash, monkeypatch):
    with ExtendibleHashIndex.create(
        tmp_path / "route.hash", initial_global_depth=10, **ARGS) as index:
        value = key(1023)
        index.insert(value, RID(1, 0))
        selected = index.directory_entries[1023]
        original = index._buckets.read_bucket
        def read_selected(page_id):
            assert page_id == selected, "search touched an unrelated bucket"
            return original(page_id)
        monkeypatch.setattr(index._buckets, "read_bucket", read_selected)
        index.reset_counters()
        assert list(index.search(value)) == [RID(1, 0)]
        assert index.metrics.directory_page_reads == 2
        assert index.metrics.bucket_page_reads == 1
        assert index.pages_read == 3


@pytest.mark.parametrize("bad_key,bad_rid", [(None, RID(1, 0)), (True, RID(1, 0)),
    ("x" * 256, RID(1, 0)), ("ok", object()), ("ok", RID(2**32, 0))])
def test_invalid_insert_is_byte_for_byte_unchanged(tmp_path, bad_key, bad_rid):
    path = tmp_path / "invalid.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        index.insert("original", RID(1, 0))
        before = path.read_bytes()
        writes = index.pages_written
        with pytest.raises((InvalidTypeError, ValidationError)):
            index.insert(bad_key, bad_rid)
        assert path.read_bytes() == before
        assert index.pages_written == writes


def test_non_growing_insert_only_writes_target_bucket_and_header(tmp_path, routed_hash, monkeypatch):
    with ExtendibleHashIndex.create(tmp_path / "simple.hash", **ARGS) as index:
        entries = index.directory_entries
        page_ids = []
        write = index._manager.write_page
        def capture(page):
            page_ids.append(page.page_id)
            write(page)
        monkeypatch.setattr(index._manager, "write_page", capture)
        index.insert(key(1), RID(1, 0))
        assert page_ids == [entries[1], 0]
        assert index.directory_entries == entries
        assert index.global_depth == 1
        assert index._buckets.read_bucket(entries[1]).local_depth == 1


def test_split_without_doubling_preserves_all_unrelated_aliases(tmp_path, routed_hash):
    path = tmp_path / "aliases.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        entries, pending = fill_target(index)
        index.insert(*pending)
        entries.append(pending)
        assert index.global_depth == 2
        before = index.directory_entries
        target = before[1]
        number = 1
        while index._buckets.read_bucket(target).can_fit(key(number), RID(number, 0)):
            index.insert(key(number), RID(number, 0))
            entries.append((key(number), RID(number, 0)))
            number += 2
        index.insert(key(number), RID(number, 0))
        entries.append((key(number), RID(number, 0)))
        after = index.directory_entries
        assert index.global_depth == 2
        assert len(before) == len(after)
        assert before[0] == after[0] and before[2] == after[2]
        assert after[1] == target and after[3] != target
        assert index._buckets.read_bucket(after[1]).local_depth == 2
        assert index._buckets.read_bucket(after[3]).local_depth == 2
        assert Counter(after) == {page_id: 1 for page_id in after}
        assert_contents(index, entries)
    with ExtendibleHashIndex.open(path) as reopened:
        assert_contents(reopened, entries)


def test_repeated_splits_reopen_with_empty_sides_and_three_directory_pages(tmp_path, routed_hash):
    path = tmp_path / "skew.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        entries, pending = fill_target(index, step=1024)
        index.insert(*pending)
        entries.append(pending)
        assert index.global_depth == 11
        assert index.header.directory_page_count == 3
        counts = Counter(index.directory_entries)
        empty = 0
        for page_id, aliases in counts.items():
            bucket = index._buckets.read_bucket(page_id)
            assert aliases == 1 << (index.global_depth-bucket.local_depth)
            empty += bucket.entry_count == 0
        assert empty >= 9
        assert_contents(index, entries)
    with ExtendibleHashIndex.open(path) as reopened:
        assert_contents(reopened, entries)


@pytest.mark.parametrize("unique", [False, True])
def test_duplicate_policy_matches_bplus_before_after_split_and_restart(tmp_path, routed_hash, unique):
    path = tmp_path / "duplicates.hash"
    index = ExtendibleHashIndex.create(path, allow_duplicate_keys=not unique, **ARGS)
    try:
        entries, pending = fill_target(index)
        # Exercise the same public matrix on both sides of a structural change.
        for split_done in (False, True):
            victim = None
            if split_done:
                index.insert(*pending)
                assert index.global_depth > 1
                index.close()
                index = ExtendibleHashIndex.open(path)
            value, rid = entries[0]
            with BPlusTree.create(tmp_path / f"oracle-{split_done}.bplus",
                                  allow_duplicate_keys=not unique, **ARGS) as tree:
                tree.insert(value, rid)
                before = path.read_bytes()
                for runtime in (index, tree):
                    runtime.insert(value, rid)
                assert path.read_bytes() == before
                other = RID(99999, 0)
                if unique:
                    for runtime in (index, tree):
                        with pytest.raises(DuplicateError):
                            runtime.insert(value, other)
                    assert path.read_bytes() == before
                else:
                    # Free one different association so the duplicate fits in
                    # the full bucket without altering the policy under test.
                    if not split_done:
                        victim = entries.pop()
                        index.delete(*victim)
                    for runtime in (index, tree):
                        runtime.insert(value, other)
                    assert set(index.search(value)) == set(tree.search(value))
                    for runtime in (index, tree):
                        runtime.delete(value, other)
                for runtime in (index, tree):
                    runtime.delete(value, rid)
                    assert list(runtime.search(value)) == []
                    with pytest.raises(InvalidReferenceError):
                        runtime.delete(value, rid)
                    runtime.insert(value, rid)
                if victim is not None:
                    index.insert(*victim)
                    entries.append(victim)
                index.validate_structure()
    finally:
        index.close()


def test_one_key_many_rids_collision_rejection_is_unchanged_after_restart(tmp_path):
    path = tmp_path / "one-key.hash"
    value = "x" * 255
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        rids = []
        target = index._lookup_bucket_page_id(HashCodec.hash_key(DataType.VARCHAR, value))
        while index._buckets.read_bucket(target).can_fit(value, RID(len(rids), 0)):
            rid = RID(len(rids), 0)
            index.insert(value, rid)
            rids.append(rid)
        before = path.read_bytes()
        with pytest.raises(HashBucketOverflowError):
            index.insert(value, RID(len(rids), 0))
        index.insert(value, rids[0])
        assert path.read_bytes() == before
        assert index.global_depth == 1
    with ExtendibleHashIndex.open(path) as reopened:
        assert set(reopened.search(value)) == set(rids)


def test_repeated_split_depth_limit_is_write_free(tmp_path, routed_hash):
    path = tmp_path / "depth-limit.hash"
    with ExtendibleHashIndex.create(path, maximum_global_depth=10, **ARGS) as index:
        entries, pending = fill_target(index, step=1024)
        before = path.read_bytes()
        metrics = index.structural_metrics
        with pytest.raises(HashDepthLimitError):
            index.insert(*pending)
        assert path.read_bytes() == before
        assert index.structural_metrics.bucket_splits == metrics.bucket_splits
        assert index.structural_metrics.directory_doublings == metrics.directory_doublings
        assert_contents(index, entries)
    with ExtendibleHashIndex.open(path) as reopened:
        assert_contents(reopened, entries)


class FaultingFile:
    """Inject a real write failure below PageManager's fail-closed boundary."""
    def __init__(self, wrapped, fail_at):
        self.wrapped = wrapped
        self.remaining = fail_at

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def write(self, payload):
        self.remaining -= 1
        if self.remaining == 0:
            raise OSError("injected physical write failure")
        return self.wrapped.write(payload)


@pytest.mark.parametrize("fail_at", [1, 4, 7])
def test_failed_creation_closes_and_removes_only_its_new_file(tmp_path, monkeypatch, fail_at):
    path = tmp_path / "create-fault.hash"
    unrelated = tmp_path / "existing.hash"
    ExtendibleHashIndex.create(unrelated, **ARGS).close()
    before = unrelated.read_bytes()
    original = PageManager.create
    captured = []
    def create(path):
        manager = original(path)
        manager._file = FaultingFile(manager._file, fail_at)
        captured.append(manager)
        return manager
    monkeypatch.setattr(PageManager, "create", create)
    with pytest.raises(OSError, match="physical write"):
        ExtendibleHashIndex.create(path, **ARGS)
    assert captured[0].closed
    assert not path.exists()
    assert unrelated.read_bytes() == before


def test_variable_length_split_writes_new_bucket_before_publishing_pointers(tmp_path, routed_hash, monkeypatch):
    path = tmp_path / "variable.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        old_directory = index.directory_entries
        entries = []
        number = 0
        while True:
            value = key(number, size=255 if number % 4 else 23)
            rid = RID(number, 0)
            if not index._buckets.read_bucket(old_directory[0]).can_fit(value, rid):
                break
            index.insert(value, rid)
            entries.append((value, rid))
            number += 2
        allocations = []
        writes = []
        allocate = index._manager.allocate_page
        write = index._manager.write_page
        def record_allocation():
            page_id = allocate()
            allocations.append(page_id)
            return page_id
        def record_write(page):
            writes.append(page.page_id)
            write(page)
        monkeypatch.setattr(index._manager, "allocate_page", record_allocation)
        monkeypatch.setattr(index._manager, "write_page", record_write)
        index.insert(value, rid)
        entries.append((value, rid))
        assert index.global_depth == 2
        assert len(allocations) == 1
        assert writes == [allocations[0], old_directory[0], index.header.directory_first_page_id, 0]
        assert index.directory_entries[1] == index.directory_entries[3] == old_directory[1]
        assert_contents(index, entries)
    with ExtendibleHashIndex.open(path) as reopened:
        assert_contents(reopened, entries)


@pytest.mark.parametrize("fail_at", range(1, 7))
def test_split_physical_failures_never_leave_live_partial_runtime(tmp_path, routed_hash, fail_at):
    path = tmp_path / "fault.hash"
    index = ExtendibleHashIndex.create(path, **ARGS)
    entries, pending = fill_target(index)
    before = path.read_bytes()
    index._manager._file = FaultingFile(index._manager._file, fail_at)
    try:
        with pytest.raises(OSError, match="physical write"):
            index.insert(*pending)
        assert index.closed
        with pytest.raises(RuntimeError, match="closed"):
            list(index.search(entries[0][0]))
    finally:
        index.close()
    if fail_at == 1:
        assert path.read_bytes() == before
        with ExtendibleHashIndex.open(path) as reopened:
            assert_contents(reopened, entries)
    else:
        # Without WAL, incomplete multi-page writes require detection/rebuild,
        # not an assertion that an OS failure rolled the bytes back.
        with pytest.raises(ValidationError):
            ExtendibleHashIndex.open(path)
