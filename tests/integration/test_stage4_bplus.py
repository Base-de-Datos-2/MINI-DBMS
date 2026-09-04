"""Task 4.30: Stage 4 generic, clustered, and unclustered integration."""

from contextlib import closing

from engine.catalog import Column, DataType, Schema
from engine.indexes import BPlusTree, ClusteredBPlusIndex, UnclusteredBPlusIndex
from engine.storage import HeapFile, PagedSequentialFile, Record, RID


SCHEMA = Schema(
    [Column("key", DataType.VARCHAR), Column("payload", DataType.VARCHAR)]
)


def logical_rows(storage):
    with closing(storage.scan()) as rows:
        return [(record["key"], record["payload"]) for _, record in rows]


def test_stage4_end_to_end_modalities_growth_reduction_restart_and_equivalence(
    tmp_path,
):
    heap_path = tmp_path / "items.heap"
    sequential_path = tmp_path / "items.seq"
    unclustered_path = tmp_path / "items-unclustered.idx"
    clustered_path = tmp_path / "items-clustered.idx"
    direct_path = tmp_path / "direct.idx"
    records = [
        Record(SCHEMA, [f"{number:04d}", f"value-{number}"])
        for number in reversed(range(145))
    ]

    with HeapFile.create(heap_path, SCHEMA) as heap, PagedSequentialFile.create(
        sequential_path, SCHEMA, "key"
    ) as sequential:
        for record in records:
            heap.insert(record)
            sequential.insert(record)

        with UnclusteredBPlusIndex.build(
            unclustered_path,
            heap=heap,
            index_name="idx_items_heap_key",
            table_name="items",
            key_column="key",
        ) as unclustered, ClusteredBPlusIndex.build(
            clustered_path,
            sequential=sequential,
            index_name="idx_items_seq_key",
            table_name="items",
            key_column="key",
        ) as clustered, BPlusTree.create(
            direct_path,
            index_name="idx_direct",
            table_name="direct",
            key_column="key",
            key_type=DataType.VARCHAR,
        ) as direct:
            direct.insert("b", RID(9, 2))
            direct.insert("a", RID(9, 1))
            assert list(direct.range_search()) == [RID(9, 1), RID(9, 2)]

            assert unclustered.tree.height >= 3
            assert clustered.tree.height >= 3
            assert logical_rows(heap) != logical_rows(sequential)
            expected = sorted(logical_rows(heap))
            assert logical_rows(sequential) == expected
            assert [
                (record["key"], record["payload"])
                for _, record in unclustered.range_records()
            ] == expected
            assert [
                (record["key"], record["payload"])
                for _, record in clustered.range_records()
            ] == expected

            for number in range(130):
                key = f"{number:04d}"
                unclustered.delete_record(next(unclustered.search(key)))
                clustered.delete_record(next(clustered.search(key)))
            clustered.reorganize()
            assert unclustered.tree.height < 3
            assert clustered.tree.height < 3
            unclustered.insert_record(Record(SCHEMA, ["9999", "new"]))
            clustered.insert_record(Record(SCHEMA, ["9999", "new"]))
            assert unclustered.validate_structure().entry_count == 16
            assert clustered.validate_structure().entry_count == 16

    fresh_schema = Schema(list(SCHEMA.columns))
    with HeapFile.open(heap_path, fresh_schema) as heap, PagedSequentialFile.open(
        sequential_path, fresh_schema, "key"
    ) as sequential, UnclusteredBPlusIndex.open(
        unclustered_path,
        heap=heap,
        index_name="idx_items_heap_key",
        table_name="items",
        key_column="key",
    ) as unclustered, ClusteredBPlusIndex.open(
        clustered_path,
        sequential=sequential,
        index_name="idx_items_seq_key",
        table_name="items",
        key_column="key",
    ) as clustered:
        expected = sorted(logical_rows(heap))
        assert logical_rows(sequential) == expected
        assert [record.values for _, record in unclustered.range_records()] == [
            record.values for _, record in clustered.range_records()
        ]
        assert expected[-1] == ("9999", "new")
        unclustered.validate_structure()
        clustered.validate_structure()

    with BPlusTree.open(direct_path) as direct:
        assert list(direct.search("a")) == [RID(9, 1)]
