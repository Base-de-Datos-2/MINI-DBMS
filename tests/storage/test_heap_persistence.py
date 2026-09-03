from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError
from engine.storage import HeapFile, Record, RID


def _new_schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )


def _record(schema, identifier, character, length=3000):
    return Record(schema, [identifier, character * length])


def test_heap_full_restart_reuse_and_continue_scenario(tmp_path):
    path = tmp_path / "restart.heap"
    write_schema = _new_schema()
    original_records = [
        _record(write_schema, identifier, chr(65 + identifier))
        for identifier in range(5)
    ]

    with HeapFile.create(path, write_schema) as writer:
        original_rids = [writer.insert(record) for record in original_records]
        assert original_rids == [RID(page_id, 0) for page_id in range(1, 6)]
        writer.delete(original_rids[1])
        writer.delete(original_rids[3])
        first_replacement = _record(write_schema, 10, "R", length=2800)
        reused_rid = writer.insert(first_replacement)

        assert reused_rid == original_rids[1]
        assert writer.data_page_count == 5
        assert writer.record_count == 4
        assert writer.deleted_record_count == 1
        writer.flush()

    del writer, write_schema, original_records, first_replacement

    read_schema = _new_schema()
    with HeapFile.open(path, read_schema) as first_reader:
        assert first_reader.schema == read_schema
        assert first_reader.allocated_page_count == 6
        assert first_reader.data_page_count == 5
        assert first_reader.record_count == 4
        assert first_reader.deleted_record_count == 1
        assert first_reader.pages_read == 6  # Metadata page plus five data pages.

        assert first_reader.read(original_rids[0]).values[0] == 0
        assert first_reader.read(original_rids[1]).values[0] == 10
        assert first_reader.read(original_rids[2]).values[0] == 2
        assert first_reader.read(original_rids[4]).values[0] == 4
        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            first_reader.read(original_rids[3])

        scanned_ids = [record.values[0] for _, record in first_reader.scan()]
        assert scanned_ids == [0, 10, 2, 4]

        first_reader.reset_counters()
        second_replacement = _record(read_schema, 11, "S", length=2900)
        second_reused_rid = first_reader.insert(second_replacement)
        assert second_reused_rid == original_rids[3]
        assert first_reader.pages_allocated == 0
        assert first_reader.pages_read == 1
        assert first_reader.pages_written == 2
        assert first_reader.record_count == 5
        assert first_reader.deleted_record_count == 0

    del first_reader, read_schema, second_replacement

    final_schema = _new_schema()
    with HeapFile.open(path, final_schema) as final_reader:
        expected_ids = [0, 10, 2, 11, 4]
        assert [record.values[0] for _, record in final_reader.scan()] == expected_ids
        assert final_reader.read(original_rids[1]).values[0] == 10
        assert final_reader.read(original_rids[3]).values[0] == 11
        assert final_reader.record_count == 5
        assert final_reader.deleted_record_count == 0
        assert final_reader.data_page_count == 5
        assert final_reader.allocated_page_count == 6


def test_reopen_rebuilds_capacity_and_avoids_unnecessary_allocation(tmp_path):
    path = tmp_path / "rebuild.heap"
    schema = _new_schema()
    with HeapFile.create(path, schema) as writer:
        first = writer.insert(_record(schema, 1, "A"))
        second = writer.insert(_record(schema, 2, "B"))
        writer.delete(first)
        assert second == RID(2, 0)

    reopened_schema = _new_schema()
    with HeapFile.open(path, reopened_schema) as reopened:
        assert reopened.free_space_snapshot[0][0] == 1
        pages_before = reopened.allocated_page_count
        replacement = _record(reopened_schema, 3, "C", length=2500)

        rid = reopened.insert(replacement)

        assert rid == first
        assert reopened.allocated_page_count == pages_before
        assert reopened.read(rid) == replacement
        assert reopened.read(second).values[0] == 2


def test_deleted_rid_remains_deleted_and_double_delete_fails_after_reopen(tmp_path):
    path = tmp_path / "deleted.heap"
    schema = _new_schema()
    with HeapFile.create(path, schema) as writer:
        deleted_rid = writer.insert(_record(schema, 1, "D", length=100))
        writer.delete(deleted_rid)

    with HeapFile.open(path, _new_schema()) as reader:
        for operation in (reader.read, reader.delete):
            with pytest.raises(InvalidReferenceError, match="free/deleted"):
                operation(deleted_rid)
        assert reader.record_count == 0
        assert reader.deleted_record_count == 1


def test_independent_scans_after_reopen_are_fresh_and_closable(tmp_path):
    path = tmp_path / "scans.heap"
    schema = _new_schema()
    with HeapFile.create(path, schema) as writer:
        expected = [
            (writer.insert(_record(schema, identifier, "X", length=100)), identifier)
            for identifier in range(4)
        ]

    with HeapFile.open(path, _new_schema()) as reader:
        with closing(reader.scan()) as first, closing(reader.scan()) as second:
            first_pair = next(first)
            second_pair = next(second)
            assert first_pair == second_pair
            assert [(rid, record.values[0]) for rid, record in [first_pair, *first]] == expected
            assert [(rid, record.values[0]) for rid, record in [second_pair, *second]] == expected
        assert not reader.closed
