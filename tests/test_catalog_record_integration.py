"""Integration of the current Stage 1 model, with file I/O forbidden."""

from contextlib import closing

import pytest

from engine.catalog import (
    Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata,
)
from engine.errors import (
    DatabaseError, DuplicateError, InvalidReferenceError, InvalidTypeError,
    SchemaError, UnknownColumnError, UnknownTableError,
)
from engine.storage import RID, Record
from tests.doubles import EqualityIndexDouble, OperatorDouble, OrderedIndexDouble, StorageDouble


def test_catalog_schema_record_and_index_metadata_work_without_disk(no_file_io):
    with no_file_io():
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


@pytest.mark.parametrize(
    ("index_class", "index_type"),
    [(EqualityIndexDouble, IndexType.EXTENDIBLE_HASH), (OrderedIndexDouble, IndexType.BPLUS)],
)
def test_model_catalog_and_all_contracts_integrate_without_files(no_file_io, index_class, index_type):
    with no_file_io():
        schema = Schema([Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)])
        catalog = Catalog()
        table = TableMetadata("students", schema)
        catalog.register_table(table)
        metadata = IndexMetadata("idx", "students", "id", index_type)
        catalog.register_index(metadata)
        storage = StorageDouble(catalog.get_table(metadata.table_name).schema)
        index = index_class()
        records = [Record(schema, values) for values in ([2, "Ana"], [1, "Luis"], [2, "Eva"])]
        rids = [storage.insert(record) for record in records]

        # Coordination is test-only: storage/catalog do not secretly maintain indexes.
        assert list(index.search(2)) == []
        with closing(storage.scan()) as rows:
            for rid, record in rows:
                index.insert(record[metadata.column_name], rid)

        def indexed_source():
            with closing(index.search(2)) as matches:
                for rid in matches:
                    yield storage.read(rid)

        operator = OperatorDouble(indexed_source)
        try:
            operator.open()
            actual = []
            while (record := operator.next()) is not None:
                actual.append(record)
            assert set(actual) == {records[0], records[2]}
            assert operator.next() is None
        finally:
            operator.close()
        assert index.searches.active == storage.scans.active == 0

        if isinstance(index, OrderedIndexDouble):
            with closing(index.range_search(1, 2)) as matches:
                assert [storage.read(rid)["id"] for rid in matches] == [1, 2, 2]

        for operation, expected in (
            (lambda: catalog.register_table(table), DuplicateError),
            (lambda: catalog.register_index(metadata), DuplicateError),
            (lambda: catalog.get_table("missing"), UnknownTableError),
            (lambda: catalog.register_index(IndexMetadata("bad", "students", "other", index_type)), UnknownColumnError),
            (lambda: Record(schema, [True, "Ana"]), InvalidTypeError),
            (lambda: storage.insert(Record(Schema([]), [])), SchemaError),
        ):
            with pytest.raises(DatabaseError) as caught:
                operation()
            assert isinstance(caught.value, expected)
        assert catalog.list_tables() == (table,)
        assert catalog.get_indexes("students") == (metadata,)
        assert dict(storage.scan()) == dict(zip(rids, records))

        # Deleting an index pair does not remove its row, and vice versa.
        index.delete(2, rids[0])
        assert storage.read(rids[0]) == records[0]
        storage.delete(rids[0])
        assert list(index.search(2)) == [rids[2]]
        storage.delete(rids[2])  # Deliberate dangling reference to exercise propagation.
        assert list(index.search(2)) == [rids[2]]
        try:
            operator.open()
            with pytest.raises(DatabaseError) as caught:
                operator.next()
            assert isinstance(caught.value, InvalidReferenceError)
            assert isinstance(caught.value, KeyError)
        finally:
            operator.close()
        assert index.searches.active == 0
        index.delete(2, rids[2])
        assert list(index.search(2)) == []
        assert storage.read(rids[1]) == records[1]


@pytest.mark.parametrize("source_kind", ["scan", "index"])
def test_early_operator_close_releases_owned_cursor_not_borrowed_manager(no_file_io, source_kind):
    with no_file_io():
        schema = Schema([Column("id", DataType.INTEGER)])
        storage, index = StorageDouble(schema), EqualityIndexDouble()
        for _ in range(3):
            record = Record(schema, [7])
            index.insert(7, storage.insert(record))

        def source():
            if source_kind == "scan":
                with closing(storage.scan()) as rows:
                    for _, record in rows:
                        yield record
            else:
                with closing(index.search(7)) as matches:
                    for rid in matches:
                        yield storage.read(rid)

        operator = OperatorDouble(source)
        probe = storage.scans if source_kind == "scan" else index.searches
        try:
            operator.open()
            assert operator.next() == Record(schema, [7])
            assert probe.active == probe.yielded == 1
        finally:
            operator.close()
        assert probe.active == 0
        assert probe.opened == probe.closed == 1
        assert len(list(storage.scan())) == len(list(index.search(7))) == 3
