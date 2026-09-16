"""Tasks 7.23-7.25: INSERT/DELETE through run_sql, with real index maintenance."""

import pytest

from engine.catalog import Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata
from engine.errors import UnknownTableError, ValidationError
from engine.indexes.index_catalog import build_catalog_index
from engine.storage import HeapFile, Record

from engine.maintenance import MaintenanceError
from engine.query.environment import QueryEnvironment
from engine.query.executor import run_sql

STUDENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
    ]
)


@pytest.fixture
def environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_index(
        IndexMetadata(
            name="ix_students_id",
            table_name="students",
            column_name="id",
            index_type=IndexType.EXTENDIBLE_HASH,
            unique=True,
            file_path=str(tmp_path / "students_id.hash"),
        )
    )
    env = QueryEnvironment(catalog)

    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS).__enter__()
    env.register_storage("students", storage)

    index = build_catalog_index(catalog, "ix_students_id", storage)
    env.register_index("ix_students_id", index)

    yield env
    storage.close()


def test_insert_with_explicit_columns_and_index_maintenance(environment):
    result = run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")
    assert result.affected_rows == 1

    select = run_sql(environment, "SELECT name FROM students WHERE id = 5")
    assert [r.values[0] for r in select.rows] == ["Kai"]

    index = environment.index_for("ix_students_id")
    rids = list(index.search(5))
    assert len(rids) == 1
    assert environment.storage_for("students").read(rids[0])["name"] == "Kai"


def test_insert_without_column_list_uses_schema_order(environment):
    run_sql(environment, "INSERT INTO students VALUES (7, 'Noa', 30)")
    select = run_sql(environment, "SELECT id, name, age FROM students WHERE id = 7")
    assert select.rows[0].values == (7, "Noa", 30)


def test_insert_rejects_incomplete_column_list(environment):
    with pytest.raises(ValidationError):
        run_sql(environment, "INSERT INTO students (id, name) VALUES (9, 'X')")


def test_delete_with_where_removes_row_and_index_entry(environment):
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")

    result = run_sql(environment, "DELETE FROM students WHERE id = 5")
    assert result.affected_rows == 1

    select = run_sql(environment, "SELECT id FROM students WHERE id = 5")
    assert select.rows == ()

    index = environment.index_for("ix_students_id")
    assert list(index.search(5)) == []


def test_delete_without_where_removes_every_row(environment):
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (1, 'A', 20)")
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (2, 'B', 21)")

    result = run_sql(environment, "DELETE FROM students")
    assert result.affected_rows == 2

    select = run_sql(environment, "SELECT * FROM students")
    assert select.rows == ()


def test_delete_matching_nothing_reports_zero(environment):
    result = run_sql(environment, "DELETE FROM students WHERE id = 999")
    assert result.affected_rows == 0


def test_insert_into_unknown_table_raises(environment):
    with pytest.raises(UnknownTableError):
        run_sql(environment, "INSERT INTO ghosts (id) VALUES (1)")


def test_insert_duplicate_unique_key_rolls_back_the_row(environment):
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")

    with pytest.raises(MaintenanceError):
        run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Other', 40)")

    # The row must not have been left in storage without its index entry.
    result = run_sql(environment, "SELECT name FROM students WHERE id = 5")
    assert [r.values[0] for r in result.rows] == ["Kai"]


def test_select_with_indexed_equality_uses_index_scan(environment):
    from engine.operators import IndexScan

    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (6, 'Eva', 25)")

    from engine.query.parser import parse_sql
    from engine.query.planner import build_select_plan

    plan = build_select_plan(environment, parse_sql("SELECT name FROM students WHERE id = 5"))
    # Walk down to the leaf: Projection -> IndexScan (no Filter needed, the
    # equality term was fully consumed by the index lookup).
    leaf = plan
    while hasattr(leaf, "child"):
        leaf = leaf.child
    assert isinstance(leaf, IndexScan)

    result = run_sql(environment, "SELECT name FROM students WHERE id = 5")
    assert [r.values[0] for r in result.rows] == ["Kai"]


def test_select_indexed_equality_plus_residual_term(environment):
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")
    result = run_sql(environment, "SELECT name FROM students WHERE id = 5 AND age = 999")
    assert result.rows == ()


def test_close_reopen_storage_scan_and_index_agree(environment, tmp_path):
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (5, 'Kai', 21)")
    run_sql(environment, "DELETE FROM students WHERE id = 5")
    run_sql(environment, "INSERT INTO students (id, name, age) VALUES (6, 'Eva', 25)")

    environment.storage_for("students").close()
    environment.index_for("ix_students_id").close()

    reopened_storage = HeapFile.open(tmp_path / "students.heap", STUDENTS).__enter__()
    catalog = environment.catalog
    from engine.indexes.index_catalog import open_catalog_index

    reopened_index = open_catalog_index(catalog, "ix_students_id", reopened_storage)
    try:
        rows = list(reopened_storage.scan())
        assert [record["id"] for _, record in rows] == [6]
        assert list(reopened_index.search(5)) == []
        assert [reopened_storage.read(rid)["id"] for rid in reopened_index.search(6)] == [6]
    finally:
        reopened_storage.close()
        reopened_index.close()
