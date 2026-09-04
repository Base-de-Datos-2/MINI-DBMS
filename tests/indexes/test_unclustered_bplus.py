"""Task 4.25: unclustered B+ behavior over an independent HeapFile."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError
from engine.indexes import UnclusteredBPlusIndex
from engine.storage import HeapFile, Record, RID


SCHEMA = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)


def records():
    return [
        Record(SCHEMA, [30, "c"]),
        Record(SCHEMA, [10, "a"]),
        Record(SCHEMA, [20, "b"]),
        Record(SCHEMA, [10, "a2"]),
    ]


def test_unclustered_build_resolves_exact_and_ordered_range_without_reordering_heap(
    tmp_path,
):
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        rids = [heap.insert(record) for record in records()]
        with closing(heap.scan()) as rows:
            assert [record["id"] for _, record in rows] == [30, 10, 20, 10]

        with UnclusteredBPlusIndex.build(
            tmp_path / "id.idx",
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ) as index:
            assert list(index.search(10)) == [rids[1], rids[3]]
            assert [record["name"] for _, record in index.search_records(10)] == [
                "a", "a2"
            ]
            assert [record["id"] for _, record in index.range_records(10, 20)] == [
                10, 10, 20
            ]
            assert index.validate_structure().entry_count == len(rids)
            assert index.build_metrics.entries_indexed == len(rids)
        assert not heap.closed


def test_unclustered_coordinated_insert_and_delete_maintain_heap_and_index(tmp_path):
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        with UnclusteredBPlusIndex.build(
            tmp_path / "id.idx",
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ) as index:
            rid = index.insert_record(Record(SCHEMA, [7, "Ada"]))
            assert index.read(rid)["name"] == "Ada"
            assert list(index.search(7)) == [rid]
            index.delete_record(rid)
            assert list(index.search(7)) == []
            with pytest.raises(InvalidReferenceError):
                heap.read(rid)
            assert index.validate_structure().entry_count == 0


def test_unclustered_raw_association_must_match_live_heap_record(tmp_path):
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        rid = heap.insert(Record(SCHEMA, [8, "row"]))
        with UnclusteredBPlusIndex.build(
            tmp_path / "id.idx",
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ) as index:
            with pytest.raises(InvalidReferenceError, match="does not match"):
                index.insert(9, rid)
            index.delete(8, rid)
            assert heap.read(rid)["id"] == 8


def test_two_unclustered_indexes_share_heap_but_keep_independent_order(tmp_path):
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        rids = [heap.insert(record) for record in records()]
        id_index = UnclusteredBPlusIndex.build(
            tmp_path / "id.idx",
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        )
        name_index = UnclusteredBPlusIndex.build(
            tmp_path / "name.idx",
            heap=heap,
            index_name="idx_people_name",
            table_name="people",
            key_column="name",
        )
        try:
            assert list(id_index.search(10)) == [rids[1], rids[3]]
            assert list(name_index.search("b")) == [rids[2]]
            assert [record["name"] for _, record in name_index.range_records()] == [
                "a", "a2", "b", "c"
            ]
        finally:
            id_index.close()
            name_index.close()
        assert not heap.closed


def test_unclustered_reopens_with_fresh_heap_and_index_objects(tmp_path):
    heap_path = tmp_path / "people.heap"
    index_path = tmp_path / "id.idx"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        expected = [heap.insert(record) for record in records()]
        UnclusteredBPlusIndex.build(
            index_path,
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ).close()

    with HeapFile.open(heap_path) as reopened_heap:
        with UnclusteredBPlusIndex.open(
            index_path,
            heap=reopened_heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ) as reopened_index:
            assert list(reopened_index.range_search()) == [
                expected[1], expected[3], expected[2], expected[0]
            ]
            assert reopened_index.build_metrics is None
            reopened_index.validate_structure()
        assert not reopened_heap.closed


def test_unclustered_detects_external_heap_change_and_can_rebuild(tmp_path):
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        original = heap.insert(Record(SCHEMA, [1, "old"]))
        with UnclusteredBPlusIndex.build(
            tmp_path / "id.idx",
            heap=heap,
            index_name="idx_people_id",
            table_name="people",
            key_column="id",
        ) as index:
            heap.delete(original)
            replacement = heap.insert(Record(SCHEMA, [2, "new"]))
            with pytest.raises((InvalidReferenceError, ValueError)):
                index.validate_structure()

            metrics = index.rebuild()

            assert metrics.entries_indexed == 1
            assert list(index.search(1)) == []
            assert list(index.search(2)) == [replacement]
            assert index.validate_structure().entry_count == 1
