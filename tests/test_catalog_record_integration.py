"""Integration of the current Stage 1 model, with file I/O forbidden."""

import builtins
import io
import os

import pytest

from engine.catalog import (
    Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata,
)
from engine.storage import RID, Record


def test_catalog_schema_record_and_index_metadata_work_without_disk(monkeypatch):
    def forbid_io(*args, **kwargs):
        pytest.fail("Stage 1 model/catalog operations must not access disk")

    # Patch only during the exercised operations, not pytest's own file handling.
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbid_io)
        patch.setattr(io, "open", forbid_io)
        patch.setattr(os, "open", forbid_io)

        schema = Schema([
            Column("id", DataType.INTEGER),
            Column("name", DataType.VARCHAR),
            Column("score", DataType.FLOAT),
            Column("active", DataType.BOOLEAN),
        ])
        table = TableMetadata("students", schema)
        catalog = Catalog()
        catalog.register_table(table)

        record = Record(catalog.get_table("students").schema, [1, "Ana", 9.5, True])
        rid = RID(page_id=4, slot_id=2)
        rows = {rid: record}  # Test-only mapping; this is not a storage implementation.

        index = IndexMetadata("idx_id", "students", "id", IndexType.BPLUS, True)
        catalog.register_index(index)

        assert catalog.get_table("students").schema is record.schema
        assert rows[RID(4, 2)]["name"] == "Ana"
        assert rows[RID(4, 2)]["active"] is True
        assert catalog.get_index("idx_id") is index
        assert catalog.get_indexes("students") == (index,)
        assert table.schema.column(index.column_name).data_type is DataType.INTEGER

        with pytest.raises(TypeError):
            Record(schema, [True, "Ana", 9.5, True])
        with pytest.raises(KeyError):
            catalog.register_index(
                IndexMetadata("bad", "students", "missing", IndexType.BPLUS)
            )
        assert catalog.get_indexes("students") == (index,)
        assert rows[rid] is record
