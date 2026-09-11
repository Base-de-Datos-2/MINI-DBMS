"""Stage 5.16–5.21: deletion, page ownership, independent validation and restart."""

from dataclasses import replace
import json
import subprocess
import sys

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError, ValidationError
from engine.indexes import (
    ExtendibleHashIndex, HashBucket, HashCodec, HashDirectory,
    HashDirectoryPage, HashHeaderPageIO,
)
from engine.storage import Page, RID
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE


ARGS = dict(index_name="idx", table_name="t", key_column="k", key_type=DataType.VARCHAR)


def key(number):
    return f"{number}:" + "x" * 230


@pytest.fixture
def routing(monkeypatch):
    monkeypatch.setattr(HashCodec, "hash_key", staticmethod(
        lambda key_type, value: int(value.partition(":")[0])))


def grow(index, depth=2):
    entries = []
    number = 0
    while index.global_depth < depth:
        association = (key(number), RID(number, 0))
        index.insert(*association)
        entries.append(association)
        number += 1 << (depth-1)
    return entries


@pytest.mark.parametrize("corruption", ["depth", "counter"])
def test_delete_rejects_invalid_metadata_before_writing(tmp_path, corruption):
    path = tmp_path / "delete.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        value, rid = key(1), RID(1, 0)
        index.insert(value, rid)
        bucket_id = index._lookup_bucket_page_id(HashCodec.hash_key(DataType.VARCHAR, value))
        if corruption == "depth":
            bucket = index._buckets.read_bucket(bucket_id)
            index._buckets.write_bucket(HashBucket(
                bucket_id, DataType.VARCHAR, index.global_depth+1, bucket.entries))
        else:
            index._write_header(replace(index.header, association_count=0))
        before = path.read_bytes()
        writes = index.pages_written
        with pytest.raises(ValidationError):
            index.delete(value, rid)
        assert index.pages_written == writes
        assert path.read_bytes() == before
        assert index._buckets.read_bucket(bucket_id).contains(value, rid)


@pytest.mark.parametrize("deep", [False, True])
@pytest.mark.parametrize("change", ["valid-mismatch", "bad-magic"])
def test_validator_reads_persisted_header_not_only_cached_copy(tmp_path, deep, change):
    path = tmp_path / "header.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        if change == "valid-mismatch":
            HashHeaderPageIO.write(index._manager, replace(index.header, index_name="altered"))
        else:
            payload = index.header.serialize().replace(b"MINIDB_EHASH", b"BROKEN_HASH!")
            page = Page(0)
            page.insert(payload)
            index._manager.write_page(page)
        before = path.read_bytes()
        with pytest.raises(ValidationError, match="page 0"):
            index.validate_structure(deep=deep)
        assert path.read_bytes() == before


def test_validator_revalidates_invalid_in_memory_header(tmp_path):
    with ExtendibleHashIndex.create(tmp_path / "cached.hash", **ARGS) as index:
        original = index.header.hash_width
        object.__setattr__(index._header, "hash_width", 32)
        try:
            with pytest.raises(ValidationError):
                index.validate_structure()
        finally:
            object.__setattr__(index._header, "hash_width", original)


def test_creation_preserves_typed_allocation_and_write_events(tmp_path):
    with ExtendibleHashIndex.create(tmp_path / "counts.hash", **ARGS) as index:
        metrics = index.metrics
        assert metrics.directory_page_allocations == 1
        assert metrics.bucket_page_allocations == 2
        assert metrics.directory_page_writes == 1
        assert metrics.bucket_page_writes == 2
        assert metrics.bucket_page_frees == 0
        assert index.pages_allocated == 4  # also metadata page 0
        assert index.pages_written == 8  # 4 empty frames + 4 initialized pages
        assert index.pages_read == 4  # header, directory and both buckets


@pytest.mark.parametrize("kind", ["directory", "bucket"])
@pytest.mark.parametrize("corrupt_frame", [False, True])
def test_typed_reads_count_physical_transfers_even_for_corrupt_frames(tmp_path, kind, corrupt_frame):
    path = tmp_path / "frames.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        if kind == "directory":
            io, read = index._directories, index._directories.read_page
            page_id = index.header.directory_first_page_id
        else:
            io, read = index._buckets, index._buckets.read_bucket
            page_id = index.directory_entries[0]
        if corrupt_frame:
            # Corrupt the outer Page identity, before the hash codec can run.
            with path.open("r+b", buffering=0) as physical:
                physical.seek(FILE_HEADER_SIZE + page_id * PAGE_SIZE)
                physical.write((page_id + 100).to_bytes(4, "little"))
        else:
            page_id = index.allocated_page_count  # no transfer is attempted
        index.reset_counters()
        with pytest.raises((ValidationError, InvalidReferenceError)):
            read(page_id)
        assert index.pages_read == int(corrupt_frame)
        assert io.pages_read == index.pages_read
        assert index.pages_written == 0


def test_validator_is_independent_and_reads_each_owned_page_once(tmp_path, routing, monkeypatch):
    with ExtendibleHashIndex.create(tmp_path / "independent.hash", **ARGS) as index:
        entries = grow(index, 10)
        def forbidden_lookup(*args, **kwargs):
            pytest.fail("The structural validator must not call point lookup")
        monkeypatch.setattr(index, "search", forbidden_lookup)
        monkeypatch.setattr(index, "_lookup_bucket_page_id", forbidden_lookup)
        index.reset_counters()
        report = index.validate_structure()
        assert report.association_count == len(entries)
        assert index.pages_read == index.allocated_page_count
        assert index.metrics.directory_page_reads == report.directory_page_count
        assert index.metrics.bucket_page_reads == report.bucket_count
        assert index.pages_written == index.pages_allocated == 0


def test_empty_buckets_reuse_capacity_without_freeing_or_shrinking(tmp_path, routing):
    path = tmp_path / "empty.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        entries = grow(index, 10)
        topology = index.directory_entries
        pages = index.allocated_page_count
        size = index.file_size
        depths = {page_id: index._buckets.read_bucket(page_id).local_depth
                  for page_id in set(topology)}
        for association in entries:
            index.delete(*association)
            index.validate_structure()
        assert index.entry_count == 0
        assert index.directory_entries == topology
        assert index.global_depth == 10
        assert index.allocated_page_count == pages
        assert index.file_size == size
        assert index.metrics.bucket_page_frees == 0
        assert index.metrics.bucket_merges == index.metrics.directory_shrinks == 0
    with ExtendibleHashIndex.open(path) as reopened:
        assert reopened.directory_entries == topology
        assert {page_id: reopened._buckets.read_bucket(page_id).local_depth
                for page_id in set(topology)} == depths
        reopened.reset_counters()
        reopened.insert(*entries[0])
        assert reopened.pages_allocated == 0
        assert reopened.pages_written == 2
        assert reopened.metrics.bucket_page_writes == 1
        assert reopened.metrics.directory_page_writes == 0
        assert reopened.file_size == size
        reopened.validate_structure()


def test_delete_exact_pair_io_and_missing_pair_leave_topology_unchanged(tmp_path, routing):
    path = tmp_path / "exact.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        entries = grow(index)
        value, first = entries[0]
        other = RID(900, 0)
        index.insert(value, other)
        topology = index.directory_entries
        index.reset_counters()
        assert index.delete(value, first) is None
        assert index.pages_read == 2
        assert index.pages_written == 2
        assert index.metrics.bucket_page_writes == 1
        assert index.metrics.directory_page_writes == 0
        assert index.pages_allocated == 0
        assert list(index.search(value)) == [other]
        assert index.directory_entries == topology
        before = path.read_bytes()
        for pair in [(value, first), (value, RID(901, 0)), (key(999), first)]:
            with pytest.raises(InvalidReferenceError):
                index.delete(*pair)
            assert path.read_bytes() == before
        index.validate_structure()
    with ExtendibleHashIndex.open(path) as reopened:
        assert list(reopened.search(value)) == [other]
        reopened.delete(value, other)
        assert list(reopened.search(value)) == []
        reopened.validate_structure()


@pytest.mark.parametrize("corruption,match", [
    ("pattern", "aliases"), ("alias-count", "alias count"),
    ("depth", "local depth"), ("placement", "wrong bucket"),
    ("unique", "duplicate keys"), ("total", "association count"),
    ("bucket-count", "bucket count"), ("overlap", "overlap"),
    ("out-of-range", "range"), ("wrong-type", "signature"),
    ("orphan", "orphan"),
])
def test_independent_validator_rejects_each_structural_corruption(tmp_path, routing, corruption, match):
    path = tmp_path / f"{corruption}.hash"
    with ExtendibleHashIndex.create(path, allow_duplicate_keys=False, **ARGS) as index:
        entries = grow(index)
        directory, directory_pages = index._read_directory()
        a, b, c, _ = directory.entries  # b has aliases 1,3; a/c each have one
        if corruption == "pattern":
            index._write_directory_pages(index._directories,
                HashDirectory(2, [a, c, b, b]), directory_pages)
        elif corruption == "alias-count":
            index._write_directory_pages(index._directories,
                HashDirectory(2, [a, a, c, b]), directory_pages)
        elif corruption == "depth":
            bucket = index._buckets.read_bucket(a)
            index._buckets.write_bucket(bucket.replace_entries(bucket.entries, local_depth=3))
        elif corruption == "placement":
            index._buckets.write_bucket(HashBucket(b, DataType.VARCHAR, 1, [entries[0]]))
            index._write_header(replace(index.header, association_count=index.entry_count+1))
        elif corruption == "unique":
            value, _ = entries[0]
            bucket = index._buckets.read_bucket(a)
            index._buckets.write_bucket(bucket.insert(value, RID(999, 0)))
            index._write_header(replace(index.header, association_count=index.entry_count+1))
        elif corruption == "total":
            index._write_header(replace(index.header, association_count=index.entry_count+1))
        elif corruption == "bucket-count":
            index._write_header(replace(index.header, bucket_count=2))
        elif corruption == "overlap":
            index._write_directory_pages(index._directories,
                HashDirectory(2, [directory_pages[0], b, c, b]), directory_pages)
        elif corruption == "out-of-range":
            index._write_directory_pages(index._directories,
                HashDirectory(2, [index.allocated_page_count, b, c, b]), directory_pages)
        elif corruption == "wrong-type":
            index._directories.write_page(a, HashDirectoryPage(0, [a, b, c, b]))
        elif corruption == "orphan":
            index._manager.allocate_page()
            index._write_header(replace(index.header,
                index_page_count=index._manager.allocated_page_count-1))
        before = path.read_bytes()
        writes = index.pages_written
        with pytest.raises(ValidationError, match=match):
            index.validate_structure()
        assert path.read_bytes() == before
        assert index.pages_written == writes
    with pytest.raises(ValidationError):
        ExtendibleHashIndex.open(path)


@pytest.mark.parametrize("mode", ["cycle", "ordinal", "truncated-chain"])
def test_validator_rejects_corrupt_multipage_links(tmp_path, routing, mode):
    path = tmp_path / "chain.hash"
    with ExtendibleHashIndex.create(path, **ARGS) as index:
        grow(index, 10)
        _, pages = index._read_directory()
        first = index._directories.read_page(pages[0])
        if mode == "cycle":
            changed = HashDirectoryPage(0, first.bucket_page_ids, next_page_id=pages[0])
        elif mode == "ordinal":
            changed = HashDirectoryPage(1, first.bucket_page_ids, next_page_id=pages[1])
        else:
            changed = HashDirectoryPage(0, first.bucket_page_ids)
        index._directories.write_page(pages[0], changed)
        before = path.read_bytes()
        with pytest.raises(ValidationError):
            index.validate_structure()
        assert path.read_bytes() == before
    with pytest.raises(ValidationError):
        ExtendibleHashIndex.open(path)


def test_shallow_validation_omits_key_uniqueness_but_deep_checks_it(tmp_path):
    with ExtendibleHashIndex.create(tmp_path / "shallow.hash", allow_duplicate_keys=False, **ARGS) as index:
        value = key(1)
        index.insert(value, RID(1, 0))
        target = index._lookup_bucket_page_id(HashCodec.hash_key(DataType.VARCHAR, value))
        bucket = index._buckets.read_bucket(target)
        index._buckets.write_bucket(bucket.insert(value, RID(2, 0)))
        index._write_header(replace(index.header, association_count=2))
        assert index.validate_structure(deep=False).association_count == 2
        with pytest.raises(ValidationError, match="duplicate keys"):
            index.validate_structure()


def test_restart_in_three_distinct_processes_continues_growth_and_deletion(tmp_path):
    path = tmp_path / "process.hash"
    # The controlled hash is reinstalled independently in every process. No
    # index, directory, bucket or PageManager survives a phase boundary.
    script = '''
import json, sys
from engine.catalog import DataType
from engine.indexes import ExtendibleHashIndex, HashCodec
from engine.storage import RID
HashCodec.hash_key = staticmethod(lambda kind, value: int(value.partition(":")[0]))
def key(n): return str(n) + ":" + "x" * 230
path, phase = sys.argv[1], int(sys.argv[2])
if phase == 0:
    index = ExtendibleHashIndex.create(path, index_name="idx", table_name="t",
        key_column="k", key_type=DataType.VARCHAR)
    for n in range(20):
        index.insert(key(n*512), RID(n, 0))
        index.validate_structure()
    assert index.global_depth == 10
elif phase == 1:
    index = ExtendibleHashIndex.open(path)
    for n in range(20): assert list(index.search(key(n*512))) == [RID(n, 0)]
    for n in range(0,20,2):
        index.delete(key(n*512), RID(n, 0))
        index.validate_structure()
    pages = index.allocated_page_count
    index.reset_counters()
    for n in range(20,80):
        index.insert(key(n*512), RID(n, 0))
        index.validate_structure()
    assert index.allocated_page_count > pages
    assert index.pages_allocated > 0
    assert index.metrics.bucket_page_allocations > 0
else:
    index = ExtendibleHashIndex.open(path)
    for n in range(80):
        expected = [] if n < 20 and n % 2 == 0 else [RID(n, 0)]
        assert list(index.search(key(n*512))) == expected
    assert index.entry_count == 70
report = index.validate_structure()
print(json.dumps([report.global_depth, report.association_count]))
index.flush()
index.close()
'''
    results = []
    for phase in range(3):
        result = subprocess.run([sys.executable, "-I", "-c", script, str(path), str(phase)],
            check=True, capture_output=True, text=True, timeout=45)
        results.append(json.loads(result.stdout))
    assert results[0] == [10, 20]
    assert results[1][0] > results[0][0]
    assert results[1] == results[2]
