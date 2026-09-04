"""Task 4.28: catalog metadata to separately owned B+ runtimes."""

import pytest

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import DuplicateError, InvalidTypeError, SchemaError, ValidationError
from engine.indexes import (
    ClusteredBPlusIndex,
    UnclusteredBPlusIndex,
    build_catalog_bplus,
    open_catalog_bplus,
)
from engine.storage import HeapFile, PagedSequentialFile, Record


SCHEMA = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)


def registered_catalog(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    catalog.register_index(
        IndexMetadata(
            "idx_heap_id",
            "people",
            "id",
            IndexType.BPLUS,
            file_path=str(tmp_path / "heap.idx"),
        )
    )
    catalog.register_index(
        IndexMetadata(
            "idx_ordered_id",
            "people",
            "id",
            IndexType.BPLUS,
            clustered=True,
            file_path=str(tmp_path / "ordered.idx"),
        )
    )
    return catalog


def test_catalog_factory_builds_both_modalities_but_stores_only_metadata(tmp_path):
    catalog = registered_catalog(tmp_path)
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, [2, "B"]))
        with build_catalog_bplus(catalog, "idx_heap_id", heap) as runtime:
            assert isinstance(runtime, UnclusteredBPlusIndex)
            assert [record["id"] for _, record in runtime.range_records()] == [2]
            assert catalog.get_index("idx_heap_id").file_path.endswith("heap.idx")

    with PagedSequentialFile.create(
        tmp_path / "people.seq", SCHEMA, "id"
    ) as sequential:
        sequential.insert(Record(SCHEMA, [1, "A"]))
        with build_catalog_bplus(catalog, "idx_ordered_id", sequential) as runtime:
            assert isinstance(runtime, ClusteredBPlusIndex)
            assert [record["id"] for _, record in runtime.range_records()] == [1]
    assert not hasattr(catalog, "_runtime_indexes")


def test_catalog_factory_reopens_using_metadata_and_fresh_runtime_objects(tmp_path):
    catalog = registered_catalog(tmp_path)
    heap_path = tmp_path / "people.heap"
    with HeapFile.create(heap_path, SCHEMA) as heap:
        heap.insert(Record(SCHEMA, [7, "Ada"]))
        build_catalog_bplus(catalog, "idx_heap_id", heap).close()

    with HeapFile.open(heap_path, SCHEMA) as heap:
        with open_catalog_bplus(catalog, "idx_heap_id", heap) as runtime:
            assert [record["name"] for _, record in runtime.search_records(7)] == [
                "Ada"
            ]


def test_catalog_factory_validates_type_path_storage_and_schema(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    catalog.register_index(
        IndexMetadata("hash", "people", "id", IndexType.EXTENDIBLE_HASH)
    )
    catalog.register_index(
        IndexMetadata("missing_path", "people", "id", IndexType.BPLUS)
    )
    catalog.register_index(
        IndexMetadata(
            "clustered", "people", "id", IndexType.BPLUS,
            clustered=True, file_path=str(tmp_path / "clustered.idx"),
        )
    )
    catalog.register_index(
        IndexMetadata(
            "schema_check", "people", "id", IndexType.BPLUS,
            file_path=str(tmp_path / "schema-check.idx"),
        )
    )
    other_schema = Schema([Column("id", DataType.INTEGER)])
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        with pytest.raises(ValidationError, match="not a BPLUS"):
            build_catalog_bplus(catalog, "hash", heap)
        with pytest.raises(ValidationError, match="requires file_path"):
            build_catalog_bplus(catalog, "missing_path", heap)
        with pytest.raises(InvalidTypeError, match="PagedSequentialFile"):
            build_catalog_bplus(catalog, "clustered", heap)
        with HeapFile.create(tmp_path / "other.heap", other_schema) as heap:
            with pytest.raises(SchemaError, match="catalog table schema"):
                build_catalog_bplus(catalog, "schema_check", heap)


def test_unique_catalog_definition_rejects_duplicate_storage_build(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    catalog.register_index(
        IndexMetadata(
            "unique_id", "people", "id", IndexType.BPLUS,
            unique=True, file_path=str(tmp_path / "unique.idx"),
        )
    )
    with HeapFile.create(tmp_path / "people.heap", SCHEMA) as heap:
        heap.insert(Record(SCHEMA, [1, "A"]))
        heap.insert(Record(SCHEMA, [1, "B"]))
        with pytest.raises(DuplicateError):
            build_catalog_bplus(catalog, "unique_id", heap)


def test_catalog_still_rejects_a_second_clustered_definition(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("people", SCHEMA))
    catalog.register_index(
        IndexMetadata(
            "first", "people", "id", IndexType.BPLUS,
            clustered=True, file_path=str(tmp_path / "first.idx"),
        )
    )
    with pytest.raises(DuplicateError, match="already has a clustered index"):
        catalog.register_index(
            IndexMetadata(
                "second", "people", "name", IndexType.BPLUS,
                clustered=True, file_path=str(tmp_path / "second.idx"),
            )
        )
