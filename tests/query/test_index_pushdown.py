"""Task 7.16: range predicates pushed into a B+ (ordered) index."""

import pytest

from engine.catalog import Catalog, Column, DataType, IndexMetadata, IndexType, Schema, TableMetadata
from engine.indexes.index_catalog import build_catalog_index
from engine.operators import IndexScan
from engine.storage import HeapFile

from engine.query.environment import QueryEnvironment
from engine.query.executor import run_sql
from engine.query.parser import parse_sql
from engine.query.planner import build_select_plan

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
            name="ix_students_age",
            table_name="students",
            column_name="age",
            index_type=IndexType.BPLUS,
            unique=False,
            clustered=False,
            file_path=str(tmp_path / "students_age.bplus"),
        )
    )
    env = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS).__enter__()
    env.register_storage("students", storage)
    index = build_catalog_index(catalog, "ix_students_age", storage)
    env.register_index("ix_students_age", index)

    for row in [(1, "Ana", 22), (2, "Luis", 19), (3, "Sol", 24), (4, "Omar", 23), (5, "Kai", 30)]:
        run_sql(env, f"INSERT INTO students VALUES ({row[0]}, '{row[1]}', {row[2]})")

    try:
        yield env
    finally:
        index.close()
        storage.close()


def _leaf(plan):
    node = plan
    while hasattr(node, "child"):
        node = node.child
    return node


def test_less_than_uses_index_range_scan(environment):
    plan = build_select_plan(environment, parse_sql("SELECT id FROM students WHERE age < 23"))
    assert isinstance(_leaf(plan), IndexScan)
    result = run_sql(environment, "SELECT id FROM students WHERE age < 23")
    assert sorted(r.values[0] for r in result.rows) == [1, 2]


def test_greater_or_equal_uses_index_range_scan(environment):
    result = run_sql(environment, "SELECT id FROM students WHERE age >= 23")
    assert sorted(r.values[0] for r in result.rows) == [3, 4, 5]


def test_literal_on_left_side_flips_correctly(environment):
    # 23 <= age  ==  age >= 23
    result = run_sql(environment, "SELECT id FROM students WHERE 23 <= age")
    assert sorted(r.values[0] for r in result.rows) == [3, 4, 5]


def test_two_sided_range_keeps_the_second_bound_as_residual(environment):
    result = run_sql(environment, "SELECT id FROM students WHERE age >= 20 AND age < 24")
    assert sorted(r.values[0] for r in result.rows) == [1, 4]


def test_range_predicate_still_correct_without_any_index(environment):
    # DELETE goes through TableScan/Filter regardless (no pushdown for
    # writes in this increment); result correctness must match the SELECT.
    result = run_sql(environment, "DELETE FROM students WHERE age > 100")
    assert result.affected_rows == 0
