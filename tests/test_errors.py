"""Domain classifications and compatibility of the existing validation paths."""

import pytest

from engine.catalog import (
    Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata,
)
from engine.errors import (
    ColumnPositionError, DatabaseError, DuplicateError, InvalidReferenceError,
    InvalidTypeError, SchemaError, UnknownColumnError, UnknownTableError,
    ValidationError,
)
from engine.storage import RID, Record


@pytest.fixture
def schema():
    return Schema([Column("id", DataType.INTEGER)])


@pytest.mark.parametrize(
    ("operation", "domain_error", "builtin_error", "message"),
    [
        (lambda s: Column(None, DataType.INTEGER), InvalidTypeError, TypeError, "Column name"),
        (lambda s: Column("", DataType.INTEGER), SchemaError, ValueError, "Column name"),
        (lambda s: Column("id", "INTEGER"), InvalidTypeError, TypeError, "DataType member"),
        (lambda s: Schema(None), InvalidTypeError, TypeError, "sequence of Column"),
        (lambda s: Schema([None]), InvalidTypeError, TypeError, "Every schema entry"),
        (lambda s: Schema([s.column(0)] * 2), SchemaError, ValueError, "Duplicate column"),
        (lambda s: s.column(True), InvalidTypeError, TypeError, "Column selector"),
        (lambda s: s.column(-1), ColumnPositionError, IndexError, "Column position"),
        (lambda s: s.column("other"), UnknownColumnError, KeyError, "Unknown column"),
        (lambda s: s.index_of(None), InvalidTypeError, TypeError, "Column name"),
        (lambda s: TableMetadata(None, s), InvalidTypeError, TypeError, "Table name"),
        (lambda s: TableMetadata("", s), ValidationError, ValueError, "Table name"),
        (lambda s: TableMetadata("students", None), InvalidTypeError, TypeError, "Table schema"),
        (lambda s: IndexMetadata("idx", None, "id", IndexType.BPLUS), InvalidTypeError, TypeError, "table_name"),
        (lambda s: IndexMetadata("idx", "students", "", IndexType.BPLUS), ValidationError, ValueError, "column_name"),
        (lambda s: IndexMetadata("idx", "students", "id", "BPLUS"), InvalidTypeError, TypeError, "IndexType member"),
        (lambda s: IndexMetadata("idx", "students", "id", IndexType.BPLUS, 1), InvalidTypeError, TypeError, "boolean"),
        (lambda s: IndexMetadata("idx", "students", "id", IndexType.EXTENDIBLE_HASH, True), ValidationError, ValueError, "Only BPLUS"),
        (lambda s: RID(True, 0), InvalidTypeError, TypeError, "page_id"),
        (lambda s: RID(0, -1), ValidationError, ValueError, "slot_id"),
        (lambda s: Record(None, []), InvalidTypeError, TypeError, "Record schema"),
        (lambda s: Record(s, None), InvalidTypeError, TypeError, "sequence"),
        (lambda s: Record(s, []), ValidationError, ValueError, "requires 1 values"),
        (lambda s: Record(s, [True]), InvalidTypeError, TypeError, "requires INTEGER"),
        (lambda s: Record(s, [1])["other"], UnknownColumnError, KeyError, "Unknown column"),
    ],
)
def test_model_validations_are_domain_errors_and_keep_builtin_compatibility(
    schema, operation, domain_error, builtin_error, message,
):
    with pytest.raises(domain_error, match=message) as caught:
        operation(schema)
    assert isinstance(caught.value, DatabaseError)
    assert isinstance(caught.value, builtin_error)


@pytest.mark.parametrize(
    "operation",
    [
        lambda c: c.register_table(None),
        lambda c: c.register_index(None),
        lambda c: c.has_table(None),
        lambda c: c.get_table(None),
        lambda c: c.get_indexes(None),
        lambda c: c.get_index(None),
    ],
)
def test_catalog_argument_types_use_domain_errors(operation):
    catalog = Catalog()
    with pytest.raises(InvalidTypeError) as caught:
        operation(catalog)
    assert isinstance(caught.value, DatabaseError)
    assert isinstance(caught.value, TypeError)
    assert catalog.list_tables() == ()


def test_catalog_reference_errors_keep_messages_and_do_not_reserve_names(schema):
    catalog = Catalog()
    table = TableMetadata("students", schema)
    catalog.register_table(table)

    for lookup in (catalog.get_table, catalog.get_indexes):
        with pytest.raises(UnknownTableError) as caught:
            lookup("missing")
        assert isinstance(caught.value, InvalidReferenceError)
        assert isinstance(caught.value, KeyError)
        assert caught.value.args == ("Unknown table: 'missing'",)

    for table_name, column_name, error in (
        ("missing", "id", UnknownTableError),
        ("students", "missing", UnknownColumnError),
    ):
        with pytest.raises(error):
            catalog.register_index(
                IndexMetadata("idx", table_name, column_name, IndexType.BPLUS)
            )
        assert catalog.get_indexes("students") == ()
        with pytest.raises(InvalidReferenceError) as caught:
            catalog.get_index("idx")
        assert isinstance(caught.value, DatabaseError)
        assert isinstance(caught.value, KeyError)
        assert caught.value.args == ("Unknown index: 'idx'",)

    valid = IndexMetadata("idx", "students", "id", IndexType.BPLUS)
    catalog.register_index(valid)
    assert catalog.get_index("idx") is valid


def test_catalog_duplicates_keep_original_definitions(schema):
    catalog = Catalog()
    table = TableMetadata("students", schema)
    index = IndexMetadata("idx", "students", "id", IndexType.BPLUS, True)
    catalog.register_table(table)
    catalog.register_index(index)

    for operation in (
        lambda: catalog.register_table(TableMetadata("students", Schema([]))),
        lambda: catalog.register_index(IndexMetadata("idx", "students", "id", IndexType.BPLUS)),
        lambda: catalog.register_index(IndexMetadata("other", "students", "id", IndexType.BPLUS, True)),
    ):
        with pytest.raises(DuplicateError) as caught:
            operation()
        assert isinstance(caught.value, DatabaseError)
        assert isinstance(caught.value, ValueError)
        assert catalog.list_tables() == (table,)
        assert catalog.get_indexes("students") == (index,)

    with pytest.raises(InvalidReferenceError):
        catalog.get_index("other")
