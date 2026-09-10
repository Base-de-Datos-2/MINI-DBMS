"""Regression and format evidence for the review of Stage 5 tasks 5.1–5.7."""

from dataclasses import replace
import json
import os
import random
import struct
import subprocess
import sys

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import (
    ExtendibleHashIndex, HashBucket, HashBucketCodec, HashBucketPageIO,
    HashCodec, HashDirectory, HashDirectoryCodec, HashDirectoryPage,
    HashDirectoryPageIO, HashFileHeader,
)
from engine.indexes.hash_binary import HASH_DIRECTORY_ENTRIES_PER_PAGE
from engine.storage import PageManager, RID
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_SIZE


ARGS = dict(index_name="idx", table_name="t", key_column="k", key_type=DataType.INTEGER)


@pytest.mark.parametrize("changes", [
    dict(directory_page_count=2, index_page_count=4),
    dict(global_depth=10, directory_entry_count=1024),
    dict(bucket_count=3, index_page_count=4),
])
def test_header_rejects_impossible_directory_geometry(changes):
    with pytest.raises(ValidationError):
        replace(HashFileHeader(**ARGS), **changes)


def test_header_rejects_oversized_and_excessively_nested_input():
    payload = HashFileHeader(**ARGS).serialize()
    with pytest.raises(ValidationError):
        HashFileHeader.deserialize(payload + b" " * MAX_RECORD_SIZE)
    with pytest.raises(ValidationError):
        HashFileHeader.deserialize(b"[" * 1100 + b"0" + b"]" * 1100)


@pytest.mark.parametrize("changes", [
    {"hash_algorithm_version": 2}, {"page_size": 2048},
    {"directory_first_page_id": 0}, {"directory_first_page_id": 9},
    {"maximum_global_depth": 0}, {"initial_global_depth": 2},
    {"allow_duplicate_keys": 1}, {"build_complete": "true"},
    {"key_type": "UNKNOWN"}, {"unexpected": 1},
])
def test_persisted_header_rejects_incompatible_fields(changes):
    document = json.loads(HashFileHeader(**ARGS).serialize())
    document.update(changes)
    with pytest.raises((ValidationError, InvalidTypeError)):
        HashFileHeader.deserialize(json.dumps(document).encode())


def test_hash_repeatability_in_fresh_processes_with_distinct_hash_seeds():
    script = '''
import json
from engine.catalog import DataType
from engine.indexes import HashCodec
cases = [(DataType.INTEGER, -(2**63)), (DataType.INTEGER, 2**63-1),
         (DataType.FLOAT, -0.0), (DataType.FLOAT, float("inf")),
         (DataType.BOOLEAN, False), (DataType.BOOLEAN, True),
         (DataType.VARCHAR, ""), (DataType.VARCHAR, "á😀")]
print(json.dumps([(HashCodec.encode_key(t, k).hex(), HashCodec.hash_key(t, k))
                  for t, k in cases]))
'''
    results = []
    for seed in ("1", "42"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
        results.append(subprocess.run(
            [sys.executable, "-c", script], env=env, check=True,
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        ).stdout)
    assert json.loads(results[0]) == json.loads(results[1])


@pytest.mark.parametrize("key_type,key", [
    (DataType.INTEGER, -(2**63)-1), (DataType.INTEGER, 2**63),
    (DataType.INTEGER, True), (DataType.FLOAT, float("nan")),
    (DataType.FLOAT, 1), (DataType.BOOLEAN, 1),
    (DataType.VARCHAR, "é" * 128), (DataType.VARCHAR, "\ud800"),
    *[(kind, None) for kind in DataType],
])
def test_hash_key_boundaries_follow_shared_index_contract(key_type, key):
    with pytest.raises((ValidationError, InvalidTypeError)):
        HashCodec.hash_key(key_type, key)


def test_directory_all_patterns_and_immutable_repeated_doubling():
    original = HashDirectory(0, [7])
    directory = original
    for depth in range(6):
        directory.validate_shape()
        assert len(tuple(directory.iter_entries())) == 1 << depth
        for pattern in range(1 << depth):
            assert directory.get_entry(pattern) == 7
            assert directory.lookup_bucket(pattern | (1 << 40)) == 7
        changed = directory.set_entry((1 << depth)-1, 9)
        assert changed.get_entry((1 << depth)-1) == 9
        assert directory.get_entry((1 << depth)-1) == 7
        directory = directory.double()
    assert original.entries == (7,)


def test_random_directory_spans_three_pages_and_reopens_exactly(tmp_path):
    rng = random.Random(557)
    directory = HashDirectory(11, [rng.choice([2, 4, 6]) for _ in range(2048)])
    path = tmp_path / "directory.pages"
    cap = HASH_DIRECTORY_ENTRIES_PER_PAGE
    page_ids = (1, 3, 5)
    with PageManager.create(path) as manager:
        for _ in range(7):
            manager.allocate_page()
        io = HashDirectoryPageIO(manager)
        for ordinal, page_id in enumerate(page_ids):
            chunk = HashDirectoryPage(
                ordinal, directory.entries[ordinal*cap:(ordinal+1)*cap],
                next_page_id=page_ids[ordinal+1] if ordinal < 2 else None,
            )
            chunk.validate_position(len(directory.entries))
            payload = HashDirectoryCodec.serialize(chunk)
            assert HashDirectoryCodec.serialize(HashDirectoryCodec.deserialize(payload)) == payload
            io.write_page(page_id, chunk)
    with PageManager.open(path) as manager:
        io = HashDirectoryPageIO(manager)
        entries = []
        next_page = page_ids[0]
        while next_page is not None:
            chunk = io.read_page(next_page)
            chunk.validate_position(len(directory.entries))
            entries.extend(chunk.bucket_page_ids)
            next_page = chunk.next_page_id
        assert tuple(entries) == directory.entries
        assert io.pages_read == 3


@pytest.mark.parametrize("page,total", [
    (HashDirectoryPage(1, [2]), 2),
    (HashDirectoryPage(0, [2]), 2),
    (HashDirectoryPage(0, [2] * HASH_DIRECTORY_ENTRIES_PER_PAGE), 1024),
])
def test_directory_context_rejects_bad_ordinal_length_or_missing_link(page, total):
    with pytest.raises(ValidationError):
        page.validate_position(total)


def test_directory_resegmentation_cannot_hide_records_after_validation(tmp_path):
    path = tmp_path / "chunks.hash"
    cap = HASH_DIRECTORY_ENTRIES_PER_PAGE
    key = next(k for k in range(10000)
               if HashCodec.directory_index(HashCodec.hash_key(DataType.INTEGER, k), 10) == cap)
    with ExtendibleHashIndex.create(path, initial_global_depth=10, **ARGS) as index:
        index.insert(key, RID(42, 0))
        assert list(index.search(key)) == [RID(42, 0)]
        directory, pages = index._read_directory()
        index._directories.write_page(pages[0], HashDirectoryPage(
            0, directory.entries[:cap-1], next_page_id=pages[1]))
        index._directories.write_page(pages[1], HashDirectoryPage(
            1, directory.entries[cap-1:]))
        writes = index.pages_written
        for operation in (index.validate_structure, lambda: list(index.search(key))):
            with pytest.raises(ValidationError, match="entry count"):
                operation()
        assert index.pages_written == writes
    with pytest.raises(ValidationError, match="entry count"):
        ExtendibleHashIndex.open(path)


@pytest.mark.parametrize("link", [1, 999])
def test_lookup_rejects_nonterminal_link_on_last_directory_page(tmp_path, link):
    with ExtendibleHashIndex.create(tmp_path / "link.hash", **ARGS) as index:
        directory, pages = index._read_directory()
        index._directories.write_page(pages[0], HashDirectoryPage(
            0, directory.entries, next_page_id=link))
        with pytest.raises(ValidationError):
            list(index.search(1))


def test_bucket_rejects_invalid_rids_before_comparing_them():
    with pytest.raises(InvalidTypeError):
        HashBucket(1, DataType.INTEGER, 0, [(1, object()), (1, object())])


def test_bucket_decoder_rejects_unsorted_persisted_associations():
    payload = HashBucketCodec.serialize(HashBucket(
        1, DataType.INTEGER, 0, [(1, RID(1, 0)), (2, RID(2, 0))]))
    # INTEGER entry = uint16 length + int64 key + two uint32 RID components.
    malformed = payload[:16] + payload[34:52] + payload[16:34] + payload[52:]
    with pytest.raises(ValidationError, match="canonical"):
        HashBucketCodec.deserialize(DataType.INTEGER, malformed)


def test_bucket_decoder_rejects_repeated_association():
    payload = HashBucketCodec.serialize(HashBucket(
        1, DataType.INTEGER, 0, [(1, RID(1, 0)), (2, RID(2, 0))]))
    malformed = payload[:34] + payload[16:34] + payload[52:]
    with pytest.raises(ValidationError, match="duplicate"):
        HashBucketCodec.deserialize(DataType.INTEGER, malformed)


def test_bucket_boolean_payload_rejects_non_boolean_byte():
    payload = bytearray(HashBucketCodec.serialize(HashBucket(
        1, DataType.BOOLEAN, 0, [(True, RID(1, 0))])))
    payload[18] = 2
    with pytest.raises(ValidationError):
        HashBucketCodec.deserialize(DataType.BOOLEAN, bytes(payload))


def test_binary_golden_fixtures_and_exact_physical_page_size(tmp_path):
    bucket = HashBucket(7, DataType.INTEGER, 2, [(1, RID(2, 3))])
    raw_bucket = HashBucketCodec.serialize(bucket)
    expected_bucket = bytes.fromhex(
        "48424b54 01 02 0100 07000000 22000000 "
        "0800 0100000000000000 02000000 03000000")
    assert raw_bucket == expected_bucket + bytes(MAX_RECORD_SIZE-len(expected_bucket))
    directory = HashDirectoryPage(0, [7, 7])
    raw_directory = HashDirectoryCodec.serialize(directory)
    expected_directory = bytes.fromhex(
        "48444952 01 00 0200 00000000 ffffffff 07000000 07000000")
    assert raw_directory == expected_directory + bytes(MAX_RECORD_SIZE-len(expected_directory))
    with PageManager.create(tmp_path / "frames.pages") as manager:
        for _ in range(8):
            manager.allocate_page()
        HashBucketPageIO(manager, DataType.INTEGER).write_bucket(bucket)
        HashDirectoryPageIO(manager).write_page(1, directory)
        assert len(manager.read_page(7).serialize()) == PAGE_SIZE
        assert len(manager.read_page(1).serialize()) == PAGE_SIZE
        with pytest.raises(ValidationError):
            HashBucketPageIO(manager, DataType.INTEGER).read_bucket(1)
        with pytest.raises(ValidationError):
            HashDirectoryPageIO(manager).read_page(7)


@pytest.mark.parametrize("key_type", list(DataType))
def test_seeded_bucket_round_trips_preserve_exact_bytes(key_type):
    rng = random.Random(571)
    for _ in range(30):
        entries = []
        for number in range(rng.randrange(40)):
            key = {
                DataType.INTEGER: rng.randrange(-(2**63), 2**63),
                DataType.FLOAT: rng.choice([-0.0, 0.0, float("inf"), -2.5, 3.25]),
                DataType.BOOLEAN: bool(rng.randrange(2)),
                DataType.VARCHAR: "á😀" * rng.randrange(12),
            }[key_type]
            entries.append((key, RID(number, rng.randrange(10))))
        bucket = HashBucket(7, key_type, rng.randrange(21), entries)
        payload = HashBucketCodec.serialize(bucket)
        decoded = HashBucketCodec.deserialize(key_type, payload)
        assert decoded == bucket
        assert HashBucketCodec.serialize(decoded) == payload


@pytest.mark.parametrize("offset,fmt,value", [
    (4, "B", 2), (5, "B", 65), (6, "H", 2),
    (8, "I", 0), (12, "I", 15), (12, "I", MAX_RECORD_SIZE+1),
    (16, "H", 65535),
])
def test_bucket_codec_rejects_malformed_fields(offset, fmt, value):
    payload = bytearray(HashBucketCodec.serialize(HashBucket(
        1, DataType.INTEGER, 0, [(1, RID(1, 0))])))
    struct.pack_into("<" + fmt, payload, offset, value)
    with pytest.raises(ValidationError):
        HashBucketCodec.deserialize(DataType.INTEGER, bytes(payload))


@pytest.mark.parametrize("offset,fmt,value", [
    (4, "B", 2), (5, "B", 1), (6, "H", 0),
    (6, "H", HASH_DIRECTORY_ENTRIES_PER_PAGE+1),
    (12, "I", 0), (16, "I", 0), (16, "I", 2**32-1),
])
def test_directory_codec_rejects_malformed_fields(offset, fmt, value):
    payload = bytearray(HashDirectoryCodec.serialize(HashDirectoryPage(0, [2])))
    struct.pack_into("<" + fmt, payload, offset, value)
    with pytest.raises(ValidationError):
        HashDirectoryCodec.deserialize(bytes(payload))


@pytest.mark.parametrize("cut", [0, 15, 17, MAX_RECORD_SIZE-1])
def test_page_codecs_reject_truncation(cut):
    directory = HashDirectoryCodec.serialize(HashDirectoryPage(0, [2]))
    bucket = HashBucketCodec.serialize(HashBucket(2, DataType.INTEGER, 0))
    with pytest.raises(ValidationError):
        HashDirectoryCodec.deserialize(directory[:cut])
    with pytest.raises(ValidationError):
        HashBucketCodec.deserialize(DataType.INTEGER, bucket[:cut])
