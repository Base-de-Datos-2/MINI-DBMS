"""Stage 2's in-memory binary/page block integrates with Stage 1 without I/O.

This guard remains separate from the complete Stage 2 disk-pipeline tests.
"""

from dataclasses import asdict

import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.errors import DatabaseError, InvalidTypeError, ValidationError
from engine.storage import Page, PageHeader, Record, RecordCodec, RID, ValueCodec
from engine.storage.binary import PAGE_SIZE, validate_page_layout


def test_catalog_records_header_and_geometry_integrate_without_files(no_file_io):
    with no_file_io():
        catalog = Catalog()
        schema = Schema([
            Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
            Column("active", DataType.BOOLEAN),
        ])
        catalog.register_table(TableMetadata("students", schema))
        original = Record(catalog.get_table("students").schema, [3, "Lucía 😀", True])
        payload = RecordCodec.serialize(original)
        offset = PAGE_SIZE - len(payload)
        # Explicit metadata/range example, not insertion or slot allocation.
        header = PageHeader(page_id=7, slot_count=1, free_space_start=17,
                            free_space_end=offset, active_record_count=1)
        reconstructed = PageHeader.deserialize(header.serialize())
        validate_page_layout(**asdict(reconstructed), active_regions=[(offset, len(payload))])
        assert reconstructed.contiguous_free_space == PAGE_SIZE - 17 - len(payload)
        recovered = RecordCodec.deserialize(catalog.get_table("students").schema, payload)
        assert recovered == original
        rid = RID(reconstructed.page_id, 0)
        assert rid == RID(7, 0)  # Still a value, not a validated disk address.
        assert catalog.list_tables() == (TableMetadata("students", schema),)
        assert Catalog().list_tables() == ()  # No implicit catalog persistence.


def test_binary_errors_keep_domain_and_builtin_compatibility_without_files(no_file_io):
    with no_file_io():
        for operation, error_type, builtin_type in (
            (lambda: ValueCodec.encode(DataType.INTEGER, True), InvalidTypeError, TypeError),
            (lambda: ValueCodec.decode(DataType.BOOLEAN, b"\x02"), ValidationError, ValueError),
            (lambda: RecordCodec.deserialize(Schema([]), b"extra"), ValidationError, ValueError),
            (lambda: PageHeader(-1), ValidationError, ValueError),
            (lambda: PageHeader.deserialize(bytes(11)), ValidationError, ValueError),
        ):
            with pytest.raises(error_type) as error:
                operation()
            assert isinstance(error.value, DatabaseError)
            assert isinstance(error.value, builtin_type)


def test_record_codec_and_page_operations_integrate_without_files(no_file_io):
    with no_file_io():
        catalog = Catalog()
        schema = Schema([
            Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
            Column("active", DataType.BOOLEAN),
        ])
        catalog.register_table(TableMetadata("students", schema))
        page = Page(page_id=4)
        originals = [Record(schema, [1, "Ana", True]), Record(schema, [2, "李 😀", False])]

        rids = [RID(page.page_id, page.insert(RecordCodec.serialize(row))) for row in originals]
        assert rids == [RID(4, 0), RID(4, 1)]
        assert [
            RecordCodec.deserialize(schema, page.read(rid.slot_id)) for rid in rids
        ] == originals

        page.delete(rids[0].slot_id)
        with pytest.raises(KeyError, match="free/deleted"):
            page.read(rids[0].slot_id)
        replacement = Record(schema, [3, "Lucía", True])
        replacement_rid = RID(page.page_id, page.insert(RecordCodec.serialize(replacement)))
        assert replacement_rid == rids[0]  # Adopted slot-reuse / no-generation policy.
        assert RecordCodec.deserialize(schema, page.read(replacement_rid.slot_id)) == replacement
        assert RecordCodec.deserialize(schema, page.read(rids[1].slot_id)) == originals[1]
        assert Catalog().list_tables() == ()


def test_empty_schema_record_is_active_and_distinct_from_deleted_slot(no_file_io):
    with no_file_io():
        schema = Schema([])
        page = Page(0)
        slot_id = page.insert(RecordCodec.serialize(Record(schema, [])))
        assert RecordCodec.deserialize(schema, page.read(slot_id)) == Record(schema, [])
        assert page.slots[slot_id].is_active
        page.delete(slot_id)
        assert not page.slots[slot_id].is_active
        with pytest.raises(KeyError, match="free/deleted"):
            page.read(slot_id)
