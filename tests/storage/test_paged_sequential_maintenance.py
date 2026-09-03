from pathlib import Path

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError, InvalidTypeError
from engine.storage import PagedSequentialFile, Record, RecordCodec, RID
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE, SLOT_SIZE


@pytest.fixture
def schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )


def _row(schema, key, label, length=1):
    return Record(schema, [key, label * length])


def test_lazy_delete_marks_slot_updates_counts_and_never_reorganizes(
    tmp_path, schema
):
    path = tmp_path / "ordered.db"
    with PagedSequentialFile.create(
        path,
        schema,
        "id",
        reorganization_threshold=0.0001,
    ) as sequential:
        first = sequential.insert(_row(schema, 1, "A", 1000))
        removed = sequential.insert(_row(schema, 2, "B", 1000))
        last = sequential.insert(_row(schema, 3, "C", 1000))
        page_count = sequential.data_page_count
        file_size = path.stat().st_size
        page_before = sequential._manager.read_page(removed.page_id)
        free_end_before = page_before.header.free_space_end
        sequential.reset_counters()

        sequential.delete(removed)

        assert sequential.record_count == 2
        assert sequential.deleted_record_count == 1
        assert sequential.data_page_count == page_count
        assert sequential.allocated_page_count == page_count + 1
        assert sequential.pages_allocated == 0
        assert sequential.pages_written == 2
        assert path.stat().st_size == file_size
        page_after = sequential._manager.read_page(removed.page_id)
        assert page_after.header.free_space_end == free_end_before
        assert not page_after.slots[removed.slot_id].is_active
        assert sequential.read(first).values[0] == 1
        assert sequential.read(last).values[0] == 3
        assert list(sequential.search(2)) == []
        assert [record.values[0] for _, record in sequential.scan()] == [1, 3]
        assert sequential.should_reorganize()


def test_double_lazy_delete_is_rejected_without_another_write(tmp_path, schema):
    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        rid = sequential.insert(_row(schema, 1, "row"))
        sequential.delete(rid)
        sequential.reset_counters()

        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            sequential.delete(rid)

        assert sequential.record_count == 0
        assert sequential.deleted_record_count == 1
        assert sequential.pages_written == 0


def test_lazy_delete_rejects_invalid_rids_without_writes(tmp_path, schema):
    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        rid = sequential.insert(_row(schema, 1, "row"))
        sequential.reset_counters()

        with pytest.raises(InvalidTypeError):
            sequential.delete((rid.page_id, rid.slot_id))
        with pytest.raises(InvalidReferenceError, match="not a sequential data page"):
            sequential.delete(RID(2, 0))
        with pytest.raises(InvalidReferenceError, match="Unknown slot_id"):
            sequential.delete(RID(1, 99))

        assert sequential.record_count == 1
        assert sequential.deleted_record_count == 0
        assert sequential.pages_written == 0


def test_waste_formula_counts_payload_holes_and_free_slot_entries_only(
    tmp_path, schema
):
    removed = _row(schema, 1, "X", 37)
    retained = _row(schema, 2, "Y", 19)
    removed_payload_size = len(RecordCodec.serialize(removed))
    expected = (removed_payload_size + SLOT_SIZE) / PAGE_SIZE

    path = tmp_path / "ordered.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        assert sequential.wasted_space_ratio() == 0.0
        removed_rid = sequential.insert(removed)
        sequential.insert(retained)
        # Normal unused capacity is not part of the numerator.
        assert sequential.wasted_space_ratio() == 0.0

        sequential.delete(removed_rid)

        assert sequential.wasted_space_ratio() == expected

    with PagedSequentialFile.open(path, schema, "id") as reopened:
        assert reopened.wasted_space_ratio() == expected
        assert reopened.deleted_record_count == 1


def test_threshold_is_strict_and_policy_checks_are_read_only(tmp_path, schema):
    removed = _row(schema, 1, "X", 50)
    boundary = (len(RecordCodec.serialize(removed)) + SLOT_SIZE) / PAGE_SIZE
    path = tmp_path / "boundary.db"
    with PagedSequentialFile.create(
        path,
        schema,
        "id",
        reorganization_threshold=boundary,
    ) as sequential:
        rid = sequential.insert(removed)
        sequential.delete(rid)
        sequential.reset_counters()

        assert sequential.wasted_space_ratio() == boundary
        assert sequential.should_reorganize() is False
        assert list(sequential.search(1)) == []
        assert sequential.pages_written == 0
        assert sequential.pages_allocated == 0

    with PagedSequentialFile.create(
        tmp_path / "above.db",
        schema,
        "id",
        reorganization_threshold=boundary / 2,
    ) as sequential:
        rid = sequential.insert(removed)
        sequential.delete(rid)
        assert sequential.should_reorganize() is True


def test_reorganize_removes_tombstones_and_preserves_order_and_duplicates(
    tmp_path, schema
):
    path = tmp_path / "ordered.db"
    supplied = [
        _row(schema, 4, "D", 900),
        _row(schema, 1, "A", 900),
        _row(schema, 3, "C", 900),
        _row(schema, 2, "B", 900),
        _row(schema, 3, "E", 900),
    ]
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        for record in supplied:
            sequential.insert(record)
        sequential.delete(list(sequential.search(4))[0][0])
        expected = [
            record
            for _, record in sequential.scan()
        ]
        assert [record.values[0] for record in expected] == [1, 2, 3, 3]
        assert sequential.wasted_space_ratio() > 0.0

        sequential.reorganize()

        assert not sequential.closed
        assert sequential.record_count == len(expected)
        assert sequential.deleted_record_count == 0
        assert sequential.wasted_space_ratio() == 0.0
        assert [record for _, record in sequential.scan()] == expected
        assert [record.values[1][0] for _, record in sequential.search(3)] == [
            "C",
            "E",
        ]
        assert not list(path.parent.glob(f".{path.name}.*.replacement"))
        assert path.stat().st_size == (
            FILE_HEADER_SIZE + (sequential.data_page_count + 1) * PAGE_SIZE
        )


def test_reorganize_empty_and_all_deleted_files(tmp_path, schema):
    empty_path = tmp_path / "empty.db"
    with PagedSequentialFile.create(empty_path, schema, "id") as empty:
        empty.reorganize()
        assert empty.record_count == empty.deleted_record_count == 0
        assert empty.data_page_count == 0
        assert empty.wasted_space_ratio() == 0.0

    deleted_path = tmp_path / "deleted.db"
    with PagedSequentialFile.create(deleted_path, schema, "id") as sequential:
        rids = [
            sequential.insert(_row(schema, key, "X", 1500))
            for key in (1, 2, 3)
        ]
        for rid in rids:
            sequential.delete(rid)

        sequential.reorganize()

        assert list(sequential.scan()) == []
        assert sequential.record_count == sequential.deleted_record_count == 0
        assert sequential.data_page_count == 0
        assert sequential.allocated_page_count == 1


def test_reorganization_applies_documented_rid_invalidation_policy(
    tmp_path, schema
):
    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        old_rids = [
            sequential.insert(_row(schema, key, chr(64 + key), 3000))
            for key in (1, 2, 3)
        ]
        second_record = sequential.read(old_rids[1])
        sequential.delete(old_rids[0])

        sequential.reorganize()

        new_matches = list(sequential.search(2))
        assert len(new_matches) == 1
        assert new_matches[0][1] == second_record
        assert new_matches[0][0] != old_rids[1]
        assert sequential.read(old_rids[1]) != second_record
        with pytest.raises(InvalidReferenceError):
            sequential.read(old_rids[2])


def test_failed_candidate_build_leaves_original_open_and_removes_temporary_file(
    tmp_path, schema, monkeypatch
):
    path = tmp_path / "ordered.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        sequential.insert(_row(schema, 1, "row"))
        sequential.flush()
        original = path.read_bytes()

        def fail_build(temporary_path):
            Path(temporary_path).write_bytes(b"incomplete candidate")
            raise OSError("injected candidate failure")

        monkeypatch.setattr(sequential, "_write_compact_replacement", fail_build)
        with pytest.raises(OSError, match="candidate failure"):
            sequential.reorganize()

        assert not sequential.closed
        assert [record.values[0] for _, record in sequential.scan()] == [1]
        assert path.read_bytes() == original
        assert not list(path.parent.glob(f".{path.name}.*.replacement"))


def test_failed_atomic_replace_reopens_unchanged_original(
    tmp_path, schema, monkeypatch
):
    path = tmp_path / "ordered.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        sequential.insert(_row(schema, 2, "B"))
        sequential.insert(_row(schema, 1, "A"))
        sequential.flush()
        original = path.read_bytes()

        def fail_replace(source, destination):
            raise OSError("injected replace failure")

        monkeypatch.setattr(
            "engine.storage.page_manager.os.replace",
            fail_replace,
        )
        with pytest.raises(OSError, match="replace failure"):
            sequential.reorganize()

        assert not sequential.closed
        assert [record.values[0] for _, record in sequential.scan()] == [1, 2]
        sequential.flush()
        assert path.read_bytes() == original
        assert not list(path.parent.glob(f".{path.name}.*.replacement"))


def test_complete_sequential_lifecycle_survives_fresh_restarts(tmp_path, schema):
    path = tmp_path / "restart.db"
    writer = PagedSequentialFile.create(
        path,
        schema,
        "id",
        reorganization_threshold=0.01,
    )
    for key, label in ((8, "H"), (2, "B"), (5, "E"), (5, "F"), (1, "A")):
        writer.insert(_row(schema, key, label, 1200))
    writer.delete(list(writer.search(8))[0][0])
    first_five = next(
        rid
        for rid, record in writer.search(5)
        if record.values[1][0] == "E"
    )
    writer.delete(first_five)
    waste_before_restart = writer.wasted_space_ratio()
    writer.close()
    del writer

    fresh_schema = Schema(list(schema.columns))
    with PagedSequentialFile.open(path, fresh_schema, "id") as first_reader:
        assert first_reader.deleted_record_count == 2
        assert first_reader.wasted_space_ratio() == waste_before_restart
        assert [record.values[0] for _, record in first_reader.scan()] == [1, 2, 5]
        assert len(list(first_reader.search(5))) == 1
        first_reader.insert(_row(fresh_schema, 3, "C", 600))
        assert first_reader.deleted_record_count == 2
        assert first_reader.should_reorganize()
        first_reader.reorganize()
        assert first_reader.deleted_record_count == 0

    final_schema = Schema(list(schema.columns))
    with PagedSequentialFile.open(path, final_schema, "id") as final_reader:
        assert final_reader.key_column == "id"
        assert final_reader.reorganization_threshold == 0.01
        assert final_reader.deleted_record_count == 0
        assert final_reader.wasted_space_ratio() == 0.0
        assert [record.values[0] for _, record in final_reader.scan()] == [1, 2, 3, 5]
        assert len(list(final_reader.search(5))) == 1
