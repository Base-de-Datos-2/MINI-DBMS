"""Record persistence with fresh managers/schemas and no retained writer objects."""

import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidReferenceError, ValidationError
from engine.storage import FileHeader, PageManager, Record, RecordCodec, RID
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_HEADER_SIZE, PAGE_SIZE, SLOT_SIZE


def external_schema():
    return Schema([
        Column("id", DataType.INTEGER), Column("score", DataType.FLOAT),
        Column("active", DataType.BOOLEAN), Column("name", DataType.VARCHAR),
    ])


def write_one_record(path, values):
    # All model/page/manager objects belong to this call and are not returned.
    schema = external_schema()
    with PageManager.create(path) as manager:
        page_id = manager.allocate_page()
        page = manager.read_page(page_id)
        slot_id = page.insert(RecordCodec.serialize(Record(schema, values)))
        manager.write_page(page)
        manager.flush()
    return page_id, slot_id


@pytest.mark.parametrize("values", [
    (1, 3.5, True, ""),
    (-(2**63), -0.0, False, "Lucía 李 😀\x00fin"),
    (2**63 - 1, float("inf"), True, "positive infinity"),
    (-2, -float("inf"), False, "negative infinity"),
    (0, float("nan"), True, "not a number"),
    (10, 5e-324, False, "subnormal"),
])
def test_record_survives_close_and_reopen_with_external_schema(values, tmp_path):
    path = tmp_path / "records.db"
    page_id, slot_id = write_one_record(path, values)
    schema = external_schema()
    with PageManager.open(path) as manager:
        assert manager.header == FileHeader(allocated_page_count=1)
        recovered = RecordCodec.deserialize(schema, manager.read_page(page_id).read(slot_id))
        assert recovered.schema is schema
        assert recovered.values[0] == values[0]
        assert recovered.values[2:] == values[2:]
        assert tuple(map(type, recovered.values)) == (int, float, bool, str)
        if math.isnan(values[1]):
            assert math.isnan(recovered["score"])
        else:
            assert recovered["score"].hex() == values[1].hex()  # Includes signed zero.
        assert manager.pages_read == 1
        assert manager.pages_written == manager.pages_allocated == 0


def write_multiple_pages(path, compact):
    schema = external_schema()
    with PageManager.create(path) as manager:
        for page_id in range(4):
            assert manager.allocate_page() == page_id
            page = manager.read_page(page_id)
            for slot_id in range(3):
                values = (page_id * 10 + slot_id, slot_id + 0.25, slot_id != 1,
                          f"página {page_id} / registro {slot_id} 😀")
                assert page.insert(RecordCodec.serialize(Record(schema, values))) == slot_id
            for slot_id in ((0, 1, 2) if page_id == 3 else (1,)):
                page.delete(slot_id)
            if compact:
                page.compact()
            manager.write_page(page)


@pytest.mark.parametrize("compact", [False, True])
def test_multiple_pages_deleted_slots_and_rewrites_survive_new_managers(compact, tmp_path):
    path = tmp_path / "records.db"
    write_multiple_pages(path, compact)
    with PageManager.open(path) as reopened:
        schema = external_schema()
        assert reopened.allocated_page_count == 4
        for page_id in (3, 0, 2, 1):
            page = reopened.read_page(page_id)
            assert page.slot_count == 3
            assert page.active_record_count == (0 if page_id == 3 else 2)
            live_bytes = 0
            for slot_id in range(3):
                if page_id == 3 or slot_id == 1:
                    with pytest.raises(InvalidReferenceError, match="free/deleted"):
                        page.read(slot_id)
                    with pytest.raises(InvalidReferenceError):
                        page.delete(slot_id)
                else:
                    payload = page.read(slot_id)
                    live_bytes += len(payload)
                    recovered = RecordCodec.deserialize(schema, payload)
                    assert recovered.values == (
                        page_id * 10 + slot_id, slot_id + 0.25, slot_id != 1,
                        f"página {page_id} / registro {slot_id} 😀",
                    )
            available = PAGE_SIZE - PAGE_HEADER_SIZE - 3 * SLOT_SIZE - live_bytes
            if compact:
                assert page.free_space() == available
            else:
                assert page.free_space() < available
        # A fully deleted page keeps its directory but can reclaim all payload bytes.
        page = reopened.read_page(3)
        page.compact()
        assert page.slot_count == 3
        replacement = Record(schema, (999, 9.5, True, "reutilizado"))
        assert page.insert(RecordCodec.serialize(replacement)) == 0
        reopened.write_page(page)
        assert reopened.allocate_page() == 4
    # No reader relies on the previous reader's Page, Record or Schema objects.
    del reopened, page, replacement, recovered, schema
    with PageManager.open(path) as again:
        assert again.allocated_page_count == 5
        row = RecordCodec.deserialize(external_schema(), again.read_page(3).read(0))
        assert row.values == (999, 9.5, True, "reutilizado")
        assert again.read_page(4).slot_count == 0
        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            again.read_page(3).read(1)


def test_compaction_after_reopen_recovers_capacity_and_preserves_live_rid(tmp_path):
    path = tmp_path / "records.db"

    def write():
        schema = Schema([Column("text", DataType.VARCHAR)])
        with PageManager.create(path) as manager:
            page = manager.read_page(manager.allocate_page())
            page.insert(RecordCodec.serialize(Record(schema, ["removed" * 300])))
            page.insert(RecordCodec.serialize(Record(schema, ["alive" * 300])))
            page.delete(0)
            manager.write_page(page)

    write()
    with PageManager.open(path) as manager:
        schema = Schema([Column("text", DataType.VARCHAR)])
        page = manager.read_page(0)
        live_rid = RID(0, 1)
        payload = RecordCodec.serialize(Record(schema, ["replacement" * 200]))
        with pytest.raises(ValidationError, match="Insufficient"):
            page.insert(payload)
        before = page.slots[live_rid.slot_id].offset
        page.compact()
        assert page.slots[live_rid.slot_id].offset != before
        assert RecordCodec.deserialize(schema, page.read(live_rid.slot_id))["text"] == "alive" * 300
        assert page.insert(payload) == 0
        manager.write_page(page)
    del manager, page, schema
    with PageManager.open(path) as manager:
        schema = Schema([Column("text", DataType.VARCHAR)])
        page = manager.read_page(0)
        assert RecordCodec.deserialize(schema, page.read(1))["text"] == "alive" * 300
        assert RecordCodec.deserialize(schema, page.read(0))["text"] == "replacement" * 200


@pytest.mark.parametrize("compact", [False, True])
def test_empty_schema_record_stays_distinct_from_deleted_slot_on_disk(compact, tmp_path):
    path = tmp_path / "records.db"
    with PageManager.create(path) as manager:
        page = manager.read_page(manager.allocate_page())
        for _ in range(3):
            page.insert(RecordCodec.serialize(Record(Schema([]), [])))
        page.delete(1)
        if compact:
            page.compact()
        manager.write_page(page)
    del page, manager
    with PageManager.open(path) as manager:
        page = manager.read_page(0)
        assert (page.slot_count, page.active_record_count) == (3, 2)
        for slot_id in (0, 2):
            assert RecordCodec.deserialize(Schema([]), page.read(slot_id)).values == ()
        with pytest.raises(InvalidReferenceError, match="free/deleted"):
            page.read(1)


@pytest.mark.parametrize("text", ["x" * (MAX_RECORD_SIZE - 4), "é" * 2037 + "x"])
def test_maximum_sized_serialized_record_persists_and_next_byte_is_rejected(text, tmp_path):
    path = tmp_path / "records.db"
    with PageManager.create(path) as manager:
        schema = Schema([Column("text", DataType.VARCHAR)])
        payload = RecordCodec.serialize(Record(schema, [text]))
        assert len(payload) == MAX_RECORD_SIZE
        page = manager.read_page(manager.allocate_page())
        page.insert(payload)
        manager.write_page(page)
        empty = manager.read_page(manager.allocate_page())
        before = path.read_bytes()
        with pytest.raises(ValidationError, match="exceeds page capacity"):
            empty.insert(RecordCodec.serialize(Record(schema, [text + "x"])))
        assert empty.slot_count == 0
        assert path.read_bytes() == before
    del page, empty, schema, payload, manager
    with PageManager.open(path) as manager:
        schema = Schema([Column("text", DataType.VARCHAR)])
        page = manager.read_page(0)
        assert page.free_space() == 0
        assert RecordCodec.deserialize(schema, page.read(0))["text"] == text
        assert manager.read_page(1).slot_count == 0
