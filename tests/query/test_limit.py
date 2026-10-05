import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.query import QueryEnvironment, SqlEngine
from engine.query.errors import SqlSyntaxError
from engine.query.parser import parse_sql
from engine.storage import HeapFile, Record


@pytest.fixture
def engine(tmp_path):
    schema = Schema([Column("id", DataType.INTEGER), Column("kind", DataType.INTEGER)])
    catalog = Catalog()
    catalog.register_table(TableMetadata("items", schema))
    environment = QueryEnvironment(catalog)
    with HeapFile.create(tmp_path / "items.heap", schema) as storage:
        environment.register_storage("items", storage)
        for row in [(3, 1), (1, 1), (2, 2), (4, 2)]:
            storage.insert(Record(schema, row))
        yield SqlEngine(environment)


@pytest.mark.parametrize("limit,expected", [(0, []), (1, [(1,)]), (9, [(1,), (2,), (3,), (4,)])])
def test_limit_after_sort_and_projection(engine, limit, expected):
    query = engine.prepare(f"SELECT id FROM items ORDER BY id LIMIT {limit}")
    assert query.describe().name == "Limit"
    for _ in range(2):
        assert [row.values for row in query.execute().fetchall(limit=20)] == expected


def test_filter_and_group_are_applied_before_limit(engine):
    assert [row.values for row in engine.execute(
        "SELECT id FROM items WHERE kind = 2 ORDER BY id DESC LIMIT 1"
    ).fetchall(limit=20)] == [(4,)]
    assert [row.values for row in engine.execute(
        "SELECT kind, COUNT(*) AS n FROM items GROUP BY kind ORDER BY kind DESC LIMIT 1"
    ).fetchall(limit=20)] == [(2, 2)]


def test_limit_does_not_read_remaining_rows(engine):
    result = engine.execute("SELECT id FROM items LIMIT 1")
    assert [row.values for row in result.fetchall(limit=20)] == [(3,)]
    scan = next(node for node in result.report.runtime.root.walk() if node.name == "TableScan")
    assert scan.rows_examined == 1


@pytest.mark.parametrize("value", ["-1", "1.5", "'1'", "TRUE", "id"])
def test_invalid_limits_are_rejected(value):
    with pytest.raises(SqlSyntaxError):
        parse_sql(f"SELECT * FROM items LIMIT {value}")
