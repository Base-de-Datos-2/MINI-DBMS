"""Stage 5.6/5.7: byte-capacity buckets with complete key comparisons."""

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError, ValidationError
from engine.indexes import HashBucket, HashBucketCodec
from engine.storage import RID
from engine.storage.binary import MAX_RECORD_SIZE


@pytest.mark.parametrize(
    ("key_type", "entries"),
    [
        (DataType.INTEGER, [(1, RID(2, 3)), (-1, RID(4, 5))]),
        (DataType.FLOAT, [(1.5, RID(2, 3)), (float("inf"), RID(4, 5))]),
        (DataType.BOOLEAN, [(False, RID(2, 3)), (True, RID(4, 5))]),
        (DataType.VARCHAR, [("", RID(2, 3)), ("á😀", RID(4, 5))]),
    ],
)
def test_bucket_round_trip_for_every_key_type(key_type, entries):
    bucket = HashBucket(7, key_type, 2, entries)
    payload = HashBucketCodec.serialize(bucket)
    assert len(payload) == MAX_RECORD_SIZE
    assert HashBucketCodec.deserialize(key_type, payload) == bucket


def test_bucket_find_insert_duplicate_and_exact_delete():
    bucket = HashBucket(4, DataType.INTEGER, 1, [(9, RID(2, 0))])
    updated = bucket.insert(9, RID(1, 0))
    assert updated.find(9) == [RID(1, 0), RID(2, 0)]
    assert updated.insert(9, RID(1, 0)) is updated
    assert updated.delete(9, RID(1, 0)).find(9) == [RID(2, 0)]
    with pytest.raises(InvalidReferenceError):
        updated.delete(9, RID(99, 0))


def test_bucket_capacity_uses_serialized_bytes():
    bucket = HashBucket(4, DataType.VARCHAR, 1)
    number = 0
    key = ("x" * 250) + f"{number:05d}"
    while bucket.can_fit(key, RID(number, 0)):
        # Keep every key at the exact 255-byte canonical boundary.
        bucket = bucket.insert(key, RID(number, 0))
        number += 1
        key = ("x" * 250) + f"{number:05d}"
    assert bucket.entry_count > 0
    with pytest.raises(ValidationError, match="exceed"):
        bucket.insert(key, RID(number, 0))


def test_bucket_codec_rejects_corrupted_used_bytes_and_padding():
    payload = bytearray(
        HashBucketCodec.serialize(
            HashBucket(4, DataType.INTEGER, 1, [(9, RID(1, 2))])
        )
    )
    payload[-1] = 1
    with pytest.raises(ValidationError, match="trailing"):
        HashBucketCodec.deserialize(DataType.INTEGER, bytes(payload))
