"""Catalog registration, reference integrity, and safe metadata queries."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata


@pytest.fixture
def table():
    return TableMetadata("students", Schema([
        Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR),
    ]))


@pytest.fixture
def catalog(table):
    catalog = Catalog()
    catalog.register_table(table)
    return catalog


def test_new_catalog_is_empty():
    catalog = Catalog()
    assert catalog.list_tables() == ()
    assert catalog.has_table("students") is False


def test_register_and_query_tables_preserves_order(catalog, table):
    other = TableMetadata("courses", Schema([]))
    catalog.register_table(other)
    assert catalog.has_table("students") is True
    assert catalog.get_table("students") is table
    assert catalog.list_tables() == (table, other)


def test_duplicate_table_does_not_replace_metadata(catalog, table):
    with pytest.raises(ValueError, match="Duplicate table name"):
        catalog.register_table(TableMetadata("students", Schema([])))
    with pytest.raises(ValueError, match="Duplicate table name"):
        catalog.register_table(table)
    assert catalog.list_tables() == (table,)
    assert catalog.get_table("students") is table


@pytest.mark.parametrize("name", ["missing", "Students", " students ", ""])
def test_unknown_table_queries(catalog, name):
    assert catalog.has_table(name) is False
    with pytest.raises(KeyError, match="Unknown table"):
        catalog.get_table(name)
    with pytest.raises(KeyError, match="Unknown table"):
        catalog.get_indexes(name)


@pytest.mark.parametrize("name", [None, 0, True, [], b"students"])
def test_lookup_requires_string_names(catalog, name):
    for query in (catalog.has_table, catalog.get_table, catalog.get_indexes, catalog.get_index):
        with pytest.raises(TypeError, match="name must be a string"):
            query(name)


@pytest.mark.parametrize("value", [None, "students", {}, Schema([])])
def test_register_table_requires_metadata(catalog, table, value):
    with pytest.raises(TypeError, match="TableMetadata object"):
        catalog.register_table(value)
    assert catalog.list_tables() == (table,)


def test_existing_table_with_no_indexes_returns_empty_tuple(catalog):
    assert catalog.get_indexes("students") == ()


def test_register_and_query_indexes_filters_table_and_preserves_order(catalog):
    catalog.register_table(TableMetadata("courses", Schema([Column("id", DataType.INTEGER)])))
    first = IndexMetadata("idx_name", "students", "name", IndexType.BPLUS)
    other = IndexMetadata("idx_courses", "courses", "id", IndexType.BPLUS)
    second = IndexMetadata("idx_id", "students", "id", IndexType.EXTENDIBLE_HASH)
    for index in (first, other, second):
        catalog.register_index(index)
    assert catalog.get_index("idx_id") is second
    assert catalog.get_indexes("students") == (first, second)
    assert catalog.get_indexes("courses") == (other,)


def test_duplicate_index_names_are_catalog_wide(catalog, table):
    catalog.register_table(TableMetadata("courses", table.schema))
    original = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    catalog.register_index(original)
    for duplicate in (original, IndexMetadata("idx", "courses", "name", IndexType.BPLUS)):
        with pytest.raises(ValueError, match="Duplicate index name"):
            catalog.register_index(duplicate)
    assert catalog.get_index("idx") is original
    assert catalog.get_indexes("students") == (original,)
    assert catalog.get_indexes("courses") == ()


@pytest.mark.parametrize("name", ["missing", "IDX", " idx ", ""])
def test_unknown_index_queries(catalog, name):
    catalog.register_index(IndexMetadata("idx", "students", "id", IndexType.BPLUS))
    with pytest.raises(KeyError, match="Unknown index"):
        catalog.get_index(name)


@pytest.mark.parametrize("value", [None, "idx", {}, TableMetadata("empty", Schema([]))])
def test_register_index_requires_metadata(catalog, value):
    with pytest.raises(TypeError, match="IndexMetadata object"):
        catalog.register_index(value)
    assert catalog.get_indexes("students") == ()


@pytest.mark.parametrize(
    ("table_name", "column_name", "message"),
    [("missing", "id", "Unknown table"), ("Students", "id", "Unknown table"),
     ("students", "missing", "Unknown column"), ("students", "ID", "Unknown column")],
)
def test_invalid_reference_does_not_reserve_index_name(catalog, table_name, column_name, message):
    with pytest.raises(KeyError, match=message):
        catalog.register_index(IndexMetadata("idx", table_name, column_name, IndexType.BPLUS))
    assert catalog.get_indexes("students") == ()
    with pytest.raises(KeyError, match="Unknown index"):
        catalog.get_index("idx")
    valid = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    catalog.register_index(valid)
    assert catalog.get_index("idx") is valid


def test_index_reference_checks_the_target_table_schema(catalog):
    catalog.register_table(TableMetadata("courses", Schema([Column("code", DataType.INTEGER)])))
    with pytest.raises(KeyError, match="Unknown column"):
        catalog.register_index(IndexMetadata("idx", "courses", "id", IndexType.BPLUS))
    assert catalog.get_indexes("courses") == ()


def test_only_one_clustered_definition_is_allowed_per_table(catalog, table):
    first = IndexMetadata("clustered_id", "students", "id", IndexType.BPLUS, True)
    catalog.register_index(first)
    with pytest.raises(ValueError, match="already has a clustered index"):
        catalog.register_index(IndexMetadata("clustered_name", "students", "name", IndexType.BPLUS, True))
    assert catalog.get_indexes("students") == (first,)
    with pytest.raises(KeyError):
        catalog.get_index("clustered_name")

    # A failed registration must not prevent reusing its name on another table.
    catalog.register_table(TableMetadata("courses", table.schema))
    other = IndexMetadata("clustered_name", "courses", "name", IndexType.BPLUS, True)
    catalog.register_index(other)
    assert catalog.get_indexes("courses") == (other,)


def test_clustered_unclustered_and_hash_metadata_can_coexist(catalog):
    indexes = (
        IndexMetadata("clustered", "students", "id", IndexType.BPLUS, True),
        IndexMetadata("unclustered", "students", "id", IndexType.BPLUS),
        IndexMetadata("hash", "students", "id", IndexType.EXTENDIBLE_HASH),
    )
    for index in indexes:
        catalog.register_index(index)
    assert catalog.get_indexes("students") == indexes


def test_index_file_paths_are_unique_without_registering_runtime_objects(catalog):
    first = IndexMetadata(
        "first", "students", "id", IndexType.BPLUS,
        file_path="data/shared.idx",
    )
    catalog.register_index(first)
    with pytest.raises(ValueError, match="Duplicate index file path"):
        catalog.register_index(
            IndexMetadata(
                "second", "students", "name", IndexType.BPLUS,
                file_path="data/shared.idx",
            )
        )
    assert catalog.get_index("first") is first
    assert not hasattr(catalog, "_runtime_indexes")


def test_names_are_case_sensitive_and_table_index_namespaces_are_separate(catalog, table):
    catalog.register_table(TableMetadata("Students", table.schema))
    first = IndexMetadata("students", "students", "id", IndexType.BPLUS)
    second = IndexMetadata("Students", "Students", "id", IndexType.BPLUS)
    catalog.register_index(first)
    catalog.register_index(second)
    assert catalog.get_indexes("students") == (first,)
    assert catalog.get_indexes("Students") == (second,)
    assert catalog.get_table("students") is table


def test_query_results_cannot_mutate_catalog_state(catalog, table):
    tables_snapshot = catalog.list_tables()
    index = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    catalog.register_index(index)
    indexes_snapshot = catalog.get_indexes("students")
    with pytest.raises(TypeError):
        tables_snapshot[0] = TableMetadata("other", Schema([]))
    with pytest.raises(FrozenInstanceError):
        catalog.get_table("students").name = "other"
    with pytest.raises(FrozenInstanceError):
        catalog.get_index("idx").column_name = "missing"
    with pytest.raises(TypeError):
        indexes_snapshot[0] = index

    catalog.register_table(TableMetadata("courses", Schema([])))
    catalog.register_index(IndexMetadata("idx_name", "students", "name", IndexType.BPLUS))
    assert tables_snapshot == (table,)
    assert indexes_snapshot == (index,)
    assert len(catalog.list_tables()) == 2
    assert len(catalog.get_indexes("students")) == 2


def test_catalog_instances_do_not_share_state(catalog, table):
    index = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    catalog.register_index(index)
    other = Catalog()
    assert other.list_tables() == ()
    other.register_table(table)
    assert other.get_indexes("students") == ()
    other.register_index(index)
    assert other.get_index("idx") is index
