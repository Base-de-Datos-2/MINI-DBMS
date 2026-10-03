"""Stage 10 Task 10.2d (extension): Extendible Hash validation reuse.

Decoded buckets and directory pages are reused only while their page bytes
are unchanged, the same rule applied to B+ nodes and storage pages.
"""

from engine.catalog import Column, DataType, Schema
from engine.indexes.hash_bucket import HashBucketCodec
from engine.indexes.unclustered_hash import UnclusteredHashIndex
from engine.storage import HeapFile, Record


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)])


def test_decoded_buckets_are_reused_only_while_their_page_is_unchanged(tmp_path, monkeypatch):
    heap = HeapFile.create(tmp_path / "t.heap", SCHEMA)
    for key in range(1, 300):
        heap.insert(Record(SCHEMA, [key, f"row-{key}"]))
    index = UnclusteredHashIndex.build(
        tmp_path / "t.hsh", heap=heap, index_name="pk", table_name="t", key_column="id",
    )
    calls = []
    original = HashBucketCodec.deserialize

    def counting(key_type, payload):
        calls.append(1)
        return original(key_type, payload)

    monkeypatch.setattr(HashBucketCodec, "deserialize", staticmethod(counting))
    try:
        assert [record["name"] for _, record in index.search_records(42)] == ["row-42"]
        warm = len(calls)
        assert [record["name"] for _, record in index.search_records(42)] == ["row-42"]
        assert len(calls) == warm

        rid = next(iter(index.search(42)))
        index.delete_record(rid)  # rewrites the bucket holding key 42
        assert list(index.search_records(42)) == []
        assert len(calls) > warm
        assert index.validate_structure() is not None
    finally:
        index.close()
        heap.close()
