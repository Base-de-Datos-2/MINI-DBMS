"""Tasks 7.13-7.22: end-to-end SELECT planning and execution against real storage."""

import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.errors import UnknownColumnError, ValidationError
from engine.operators import collect
from engine.storage import HeapFile, Record

from engine.query.environment import QueryEnvironment
from engine.query.parser import parse_sql
from engine.query.planner import build_select_plan

STUDENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
        Column("career", DataType.VARCHAR),
        Column("age", DataType.INTEGER),
    ]
)

ENROLLMENTS = Schema(
    [
        Column("id", DataType.INTEGER),
        Column("student_id", DataType.INTEGER),
        Column("course", DataType.VARCHAR),
    ]
)

STUDENT_ROWS = (
    (1, "Ana", "CS", 22),
    (2, "Luis", "EE", 19),
    (3, "Sol", "CS", 24),
    (4, "Omar", "EE", 23),
)

ENROLLMENT_ROWS = (
    (1, 1, "DB2"),
    (2, 1, "OS"),
    (3, 3, "DB2"),
)


@pytest.fixture
def environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_table(TableMetadata("enrollments", ENROLLMENTS))
    env = QueryEnvironment(catalog)

    students = HeapFile.create(tmp_path / "students.heap", STUDENTS).__enter__()
    for row in STUDENT_ROWS:
        students.insert(Record(STUDENTS, list(row)))
    env.register_storage("students", students)

    enrollments = HeapFile.create(tmp_path / "enrollments.heap", ENROLLMENTS).__enter__()
    for row in ENROLLMENT_ROWS:
        enrollments.insert(Record(ENROLLMENTS, list(row)))
    env.register_storage("enrollments", enrollments)

    yield env
    students.close()
    enrollments.close()


def _run(env, sql_text):
    plan = build_select_plan(env, parse_sql(sql_text))
    rows = collect(plan, limit=1000)
    return plan.output_schema, rows


def test_select_star(environment):
    schema, rows = _run(environment, "SELECT * FROM students")
    assert [c.name for c in schema.columns] == ["id", "name", "career", "age"]
    assert len(rows) == 4


def test_select_columns_with_alias(environment):
    schema, rows = _run(environment, "SELECT name AS n, age FROM students WHERE age >= 22")
    assert [c.name for c in schema.columns] == ["n", "age"]
    assert sorted(r.values for r in rows) == [("Ana", 22), ("Omar", 23), ("Sol", 24)]


def test_where_and_or_not(environment):
    _, rows = _run(
        environment,
        "SELECT id FROM students WHERE (career = 'CS' AND age > 23) OR id = 2",
    )
    ids = sorted(r.values[0] for r in rows)
    assert ids == [2, 3]


def test_join_on_qualified_keys(environment):
    _, rows = _run(
        environment,
        "SELECT s.name, e.course FROM students s "
        "JOIN enrollments e ON s.id = e.student_id "
        "WHERE e.course = 'DB2'",
    )
    names = sorted(r.values[0] for r in rows)
    assert names == ["Ana", "Sol"]


def test_group_by_with_count_and_avg(environment):
    schema, rows = _run(
        environment,
        "SELECT career, COUNT(*) AS n, AVG(age) AS avg_age FROM students "
        "GROUP BY career ORDER BY career ASC",
    )
    assert [c.name for c in schema.columns] == ["career", "n", "avg_age"]
    by_career = {r.values[0]: (r.values[1], r.values[2]) for r in rows}
    assert by_career["CS"] == (2, 23.0)
    assert by_career["EE"] == (2, 21.0)


def test_order_by_desc(environment):
    _, rows = _run(environment, "SELECT id FROM students ORDER BY age DESC")
    assert [r.values[0] for r in rows] == [3, 4, 1, 2]


def test_unknown_column_raises(environment):
    with pytest.raises(UnknownColumnError):
        _run(environment, "SELECT nope FROM students")


def test_group_by_requires_aggregate(environment):
    with pytest.raises(ValidationError):
        _run(environment, "SELECT career FROM students GROUP BY career")


def test_non_grouped_column_outside_group_by_rejected(environment):
    with pytest.raises(ValidationError):
        _run(environment, "SELECT career, name, COUNT(*) FROM students GROUP BY career")


def test_join_without_equality_key_rejected(environment):
    with pytest.raises(ValidationError):
        _run(
            environment,
            "SELECT * FROM students s JOIN enrollments e ON s.age > 0",
        )


def test_public_package_api(environment):
    from engine.query import QueryEnvironment, QueryResult, run_sql

    assert isinstance(environment, QueryEnvironment)
    result = run_sql(environment, "SELECT name FROM students WHERE age >= 22")
    assert isinstance(result, QueryResult)
    assert sorted(r.values[0] for r in result.rows) == ["Ana", "Omar", "Sol"]
