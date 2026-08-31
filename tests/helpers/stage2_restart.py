"""Subprocess fixture for Stage 2: fixed pages, not a file-organization algorithm.

The caller supplies a schema declaration on the command line. Only the data
file crosses process boundaries; there is no saved Catalog or pickled model.
"""

import json
import math
import sys

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.errors import InvalidReferenceError
from engine.storage import FileHeader, PageManager, Record, RecordCodec, RID
from engine.storage.binary import PAGE_HEADER_SIZE, PAGE_SIZE, SLOT_SIZE


REPLACEMENT = (999, 9.5, False, "reemplazo 😀")
APPENDED = (400, 4.5, True, "nueva página tras reiniciar")


def original_values(page_id, slot_id):
    return (
        page_id * 10 + slot_id,
        (-0.0, float("inf"), float("nan"))[slot_id],
        slot_id % 2 == 0,
        f"Lucía / 李 / 😀 / {page_id}:{slot_id}\x00" * (slot_id + 1),
    )


def deleted(page_id, slot_id, final):
    return page_id == 2 or (page_id == 0 and slot_id == 1 and not final) or (
        page_id == 1 and slot_id == 0 and final
    )


def expected_values(page_id, slot_id, final):
    if final and page_id == 0 and slot_id == 1:
        return REPLACEMENT
    if page_id == 4:
        return APPENDED
    return original_values(page_id, slot_id)


def write_database(path, schema, compact):
    with PageManager.create(path) as manager:
        for page_id in range(4):
            assert manager.allocate_page() == page_id
            page = manager.read_page(page_id)
            if page_id != 3:
                for slot_id in range(3):
                    row = Record(schema, original_values(page_id, slot_id))
                    assert page.insert(RecordCodec.serialize(row)) == slot_id
                for slot_id in range(3):
                    if deleted(page_id, slot_id, final=False):
                        page.delete(slot_id)
            if compact:
                page.compact()
            manager.write_page(page)
        manager.flush()
    return manager


def verify_database(manager, schema, compact, final):
    count = 5 if final else 4
    assert manager.header == FileHeader(allocated_page_count=count)
    for page_id in reversed(range(count)):
        page = manager.read_page(page_id)
        slots = 0 if page_id == 3 else (1 if page_id == 4 else 3)
        assert page.slot_count == slots
        active_bytes = 0
        live_count = 0
        for slot_id in range(slots):
            rid = RID(page_id, slot_id)
            if deleted(page_id, slot_id, final):
                assert not page.slots[slot_id].is_active
                try:
                    page.read(rid.slot_id)
                except InvalidReferenceError:
                    pass
                else:
                    raise AssertionError(f"Deleted RID was readable: {rid}")
                continue
            payload = page.read(rid.slot_id)
            row = RecordCodec.deserialize(schema, payload)
            expected = expected_values(page_id, slot_id, final)
            assert row.schema is schema
            assert row.values[0] == expected[0]
            assert row.values[2:] == expected[2:]
            assert tuple(map(type, row.values)) == (int, float, bool, str)
            if math.isnan(expected[1]):
                assert math.isnan(row["score"])
            else:
                assert row["score"].hex() == expected[1].hex()
            active_bytes += len(payload)
            live_count += 1
        assert page.active_record_count == live_count
        packed_space = PAGE_SIZE - PAGE_HEADER_SIZE - slots * SLOT_SIZE - active_bytes
        if compact or (final and page_id in (0, 1)) or slots == live_count:
            assert page.free_space() == packed_space
        else:
            assert page.free_space() < packed_space


def read_or_rewrite_database(path, schema, compact, phase):
    with PageManager.open(path) as manager:
        assert manager.pages_read == manager.pages_written == manager.pages_allocated == 0
        verify_database(manager, schema, compact, final=phase == "final")
        if phase == "rewrite":
            page = manager.read_page(0)
            page.compact()
            assert page.insert(RecordCodec.serialize(Record(schema, REPLACEMENT))) == 1
            manager.write_page(page)
            page = manager.read_page(1)
            page.delete(0)
            page.compact()
            manager.write_page(page)
            assert manager.allocate_page() == 4
            page = manager.read_page(4)
            assert page.insert(RecordCodec.serialize(Record(schema, APPENDED))) == 0
            manager.write_page(page)
    return manager


def main():
    phase, path, schema_json, compact_flag = sys.argv[1:]
    if phase not in {"write", "read", "rewrite", "final"}:
        raise ValueError("Unknown fixture phase")
    if compact_flag not in {"yes", "no"}:
        raise ValueError("Unknown fixture compaction flag")
    schema = Schema([Column(name, DataType(type_name)) for name, type_name in json.loads(schema_json)])
    catalog = Catalog()
    assert catalog.list_tables() == ()  # No catalog discovery from opening a page file.
    catalog.register_table(TableMetadata("students", schema))
    schema = catalog.get_table("students").schema
    compact = compact_flag == "yes"
    if phase == "write":
        manager = write_database(path, schema, compact)
    else:
        manager = read_or_rewrite_database(path, schema, compact, phase)
    assert manager.closed
    print(json.dumps({
        "phase": phase, "page_count": manager.allocated_page_count,
        "pages_read": manager.pages_read, "pages_written": manager.pages_written,
        "pages_allocated": manager.pages_allocated,
    }))


if __name__ == "__main__":
    main()
