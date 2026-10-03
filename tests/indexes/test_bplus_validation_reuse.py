"""Stage 10 Task 10.2d: B+ validation reuse keeps every integrity guarantee.

Decoded nodes are reused only while their page bytes are unchanged, and range
rows are checked against the leaf entry they come from instead of a second
descent. These tests show that stale associations are still rejected.
"""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError
from engine.indexes import UnclusteredBPlusIndex
from engine.indexes.bplus_node_codec import BPlusNodeCodec
from engine.storage import HeapFile, Record


SCHEMA = Schema([Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)])


def build(tmp_path, keys):
    heap = HeapFile.create(tmp_path / "t.heap", SCHEMA)
    rids = {key: heap.insert(Record(SCHEMA, [key, f"row-{key}"])) for key in keys}
    index = UnclusteredBPlusIndex.build(
        tmp_path / "t.idx", heap=heap, index_name="pk", table_name="t", key_column="id",
    )
    return heap, index, rids


def test_range_rows_still_reject_an_association_whose_record_changed_key(tmp_path):
    heap, index, rids = build(tmp_path, range(1, 50))
    try:
        # Bypass the index: free key 20's slot and reuse it for another key.
        heap.delete(rids[20])
        reused = heap.insert(Record(SCHEMA, [999, "intruder"]))
        assert reused == rids[20]
        with pytest.raises(InvalidReferenceError, match="stale"):
            list(index.range_records(10, 30))
        # Ranges that do not touch the stale entry keep working.
        assert [record["id"] for _, record in index.range_records(30, 35)] == list(range(30, 36))
    finally:
        index.close()
        heap.close()


def test_range_entries_pair_each_rid_with_its_leaf_key(tmp_path):
    heap, index, rids = build(tmp_path, [5, 1, 3, 9])
    try:
        with closing(index.tree.range_entries(2, 9)) as entries:
            assert list(entries) == [(3, rids[3]), (5, rids[5]), (9, rids[9])]
        assert list(index.tree.range_search(2, 9)) == [rids[3], rids[5], rids[9]]
    finally:
        index.close()
        heap.close()


def test_decoded_nodes_are_reused_only_while_their_page_is_unchanged(tmp_path, monkeypatch):
    heap, index, _ = build(tmp_path, range(1, 200))
    calls = []
    original = BPlusNodeCodec.deserialize

    def counting(key_type, payload):
        calls.append(1)
        return original(key_type, payload)

    monkeypatch.setattr(BPlusNodeCodec, "deserialize", staticmethod(counting))
    try:
        list(index.search(50))
        warm = len(calls)
        list(index.search(50))
        assert len(calls) == warm  # same pages, same bytes: nothing re-decoded

        index.insert_record(Record(SCHEMA, [50, "dup"]))  # rewrites the leaf
        assert [record["name"] for _, record in index.search_records(50)] == ["row-50", "dup"]
        assert len(calls) > warm  # the changed page was decoded again
        assert index.validate_structure().entry_count == 200
    finally:
        index.close()
        heap.close()
