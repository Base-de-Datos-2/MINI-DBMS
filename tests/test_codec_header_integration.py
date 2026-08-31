"""Stage 2's initial binary block integrates with Stage 1 without file I/O.

This is NOT the complete Stage 2 persistence test: no Page/manager exists yet.
"""

from dataclasses import asdict

import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.errors import DatabaseError, InvalidTypeError, ValidationError
from engine.storage import PageHeader, Record, RecordCodec, RID, ValueCodec
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
