"""Tasks 7.21-7.22 and initial 7.26: streaming SQL execution/results."""

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
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes.index_catalog import build_catalog_index
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.query import (
    PhysicalPlanningOptions,
    QueryEnvironment,
    QueryResult,
    ResultKind,
    ResultState,
    SqlEngine,
    StatementKind,
    run_sql,
)
from engine.query.planner import SelectPlanSpec
from engine.storage import HeapFile, Record
from tests.operator_helpers import FailingOpen, RowSource


STUDENTS = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])

ROWS = (
    (1, "Ana", 22),
    (2, "Luis", 19),
    (3, "Sol", 24),
    (4, "Omar", 23),
)


@pytest.fixture
def environment(tmp_path):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    query_environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    query_environment.register_storage("students", storage)
    for row in ROWS:
        storage.insert(Record(STUDENTS, row))
    try:
        yield query_environment, storage
    finally:
        storage.close()


def _values(rows):
    return tuple(row.values for row in rows)


def test_prepare_is_read_only_reusable_and_each_execution_is_fresh(environment):
    env, storage = environment
    engine = SqlEngine(env)
    before = storage.record_count
    prepared = engine.prepare("SELECT name FROM students WHERE age >= 22")

    assert prepared.kind is StatementKind.SELECT
    assert prepared.reusable is True
    assert prepared.describe().name == "Projection"
    assert storage.record_count == before

    first = prepared.execute()
    first_rows = first.fetchall(limit=10)
    first_root = first._plan.root
    second = prepared.execute()
    second_rows = second.fetchall(limit=10)

    assert _values(first_rows) == _values(second_rows) == (
        ("Ana",), ("Sol",), ("Omar",),
    )
    assert second._plan.root is not first_root
    assert first.state is second.state is ResultState.COMPLETE
    assert first.statistics.rows_produced == second.statistics.rows_produced == 3
    assert storage.record_count == before

    third = prepared.execute().open()
    first_context = third._plan.context
    third.close()
    fourth = prepared.execute().open()
    second_context = fourth._plan.context
    fourth.close()
    assert first_context is not second_context
    assert first_context.closed is second_context.closed is True


def test_result_streams_in_bounded_batches_and_closes_early_without_closing_storage(
    environment,
):
    env, storage = environment
    engine = SqlEngine(env)
    result = engine.execute("SELECT id FROM students ORDER BY id")

    assert result.kind is ResultKind.ROWS
    assert result.state is ResultState.CREATED
    assert [column.name for column in result.schema] == ["id"]
    assert result.statistics is None
    assert _values(result.fetchmany(2)) == ((1,), (2,))
    assert result.state is ResultState.OPEN
    assert result.report.rows_delivered == 2
    assert result.report.fully_consumed is False
    assert result.report.runtime.rows_produced == 2

    result.close()

    assert result.state is ResultState.CLOSED
    assert result.partial is True
    assert [column.name for column in result.schema] == ["id"]
    assert result.statistics.live_temporary_bytes == 0
    assert engine.active_result is None
    assert storage.closed is False
    with pytest.raises(RuntimeError, match="closed early"):
        next(result)


def test_empty_and_fully_consumed_results_have_an_unambiguous_complete_state(environment):
    env, _ = environment
    engine = SqlEngine(env)
    empty = engine.execute("SELECT id FROM students WHERE id = 999")

    assert empty.fetchmany(5) == ()
    assert empty.state is ResultState.COMPLETE
    assert empty.fully_consumed is True
    assert empty.rows_delivered == 0
    assert empty.report.runtime.rows_produced == 0

    full = engine.execute("SELECT id FROM students ORDER BY id")
    assert _values(tuple(full)) == ((1,), (2,), (3,), (4,))
    assert full.state is ResultState.COMPLETE
    assert full.closed is True


def test_context_manager_releases_resources_when_the_consumer_raises(environment):
    env, storage = environment
    engine = SqlEngine(env)
    result = engine.execute("SELECT id FROM students")

    with pytest.raises(RuntimeError, match="consumer failed"):
        with result:
            assert next(result).values == (1,)
            raise RuntimeError("consumer failed")

    assert result.state is ResultState.CLOSED
    assert result.partial is True
    assert result.error is None
    assert result.statistics.live_temporary_bytes == 0
    assert engine.active_result is None
    assert storage.closed is False


def test_rows_shortcut_and_fetchall_are_bounded_and_do_not_silently_truncate(
    environment,
):
    env, _ = environment
    result = SqlEngine(env, materialization_limit=2).execute(
        "SELECT id FROM students ORDER BY id"
    )

    with pytest.raises(ValidationError, match="more than the requested 2"):
        _ = result.rows

    assert result.state is ResultState.CLOSED
    assert result.partial is True
    assert result.rows_delivered == 3

    cached = run_sql(env, "SELECT name FROM students WHERE id <= 2")
    assert _values(cached.rows) == (("Ana",), ("Luis",))
    assert cached.rows is cached.rows
    assert cached.state is ResultState.COMPLETE


def test_fetch_validation_does_not_open_the_result(environment):
    env, _ = environment
    result = SqlEngine(env).execute("SELECT id FROM students")

    assert result.fetchmany(0) == ()
    assert result.state is ResultState.CREATED
    with pytest.raises(InvalidTypeError):
        result.fetchmany(True)
    with pytest.raises(ValidationError):
        result.fetchmany(-1)
    with pytest.raises(InvalidTypeError):
        result.fetchall(limit=True)
    result.close()


def test_one_active_result_owns_the_session_and_mutations_execute_once_closed(
    environment,
):
    env, storage = environment
    engine = SqlEngine(env)
    before = storage.record_count
    active = engine.execute("SELECT id FROM students")
    insert = engine.prepare("INSERT INTO students VALUES (9, 'Nia', 20)")

    assert insert.kind is StatementKind.INSERT
    assert insert.schema is None
    assert insert.describe().name == "Insert"
    assert storage.record_count == before
    with pytest.raises(ValidationError, match="active SELECT"):
        insert.execute()

    active.close()
    command = insert.execute()
    assert command.kind is ResultKind.COMMAND
    assert command.affected_rows == 1
    assert command.report.affected_rows == 1
    assert storage.record_count == before + 1

    following = engine.execute("SELECT COUNT(*) AS n FROM students")
    assert _values(following.rows) == ((before + 1,),)


def test_open_failure_is_recorded_and_releases_the_session(environment, monkeypatch):
    env, _ = environment
    engine = SqlEngine(env)
    prepared = engine.prepare("SELECT * FROM students")
    failing = FailingOpen()
    monkeypatch.setattr(SelectPlanSpec, "instantiate", lambda self: failing)
    result = prepared.execute()

    with pytest.raises(ValueError, match="injected open failure"):
        result.open()

    assert result.state is ResultState.FAILED
    assert isinstance(result.error, ValueError)
    assert result.report.error_type == "ValueError"
    assert result.report.runtime is not None
    assert failing.closes == 1
    assert engine.active_result is None


def test_failure_after_partial_delivery_is_not_reported_as_completion(
    environment,
    monkeypatch,
):
    env, _ = environment
    engine = SqlEngine(env)
    prepared = engine.prepare("SELECT * FROM students")
    source = RowSource(
        [Record(STUDENTS, row) for row in ROWS],
        schema=STUDENTS,
        fail_at=1,
    )
    monkeypatch.setattr(SelectPlanSpec, "instantiate", lambda self: source)
    result = prepared.execute()

    assert next(result).values == ROWS[0]
    with pytest.raises(ValueError, match="injected row failure"):
        next(result)

    assert result.state is ResultState.FAILED
    assert result.rows_delivered == 1
    assert result.partial is True
    assert result.fully_consumed is False
    assert result.report.runtime.rows_produced == 1
    assert source.closes == 1
    assert engine.active_result is None


def test_close_failure_is_propagated_after_all_cleanup_is_attempted(
    environment,
    monkeypatch,
):
    class FailingCloseSource(RowSource):
        def _close(self):
            super()._close()
            raise OSError("injected close failure")

    env, _ = environment
    engine = SqlEngine(env)
    prepared = engine.prepare("SELECT * FROM students")
    source = FailingCloseSource([Record(STUDENTS, ROWS[0])], schema=STUDENTS)
    monkeypatch.setattr(SelectPlanSpec, "instantiate", lambda self: source)
    result = prepared.execute()
    assert result.fetchmany(1)[0].values == ROWS[0]

    with pytest.raises(OSError, match="injected close failure"):
        result.close()

    assert result.state is ResultState.FAILED
    assert isinstance(result.error, OSError)
    assert source.closes == 1
    assert result.statistics.live_temporary_bytes == 0
    assert engine.active_result is None


def test_prepared_and_runtime_reports_are_distinct_and_truthful_for_index_scan(
    tmp_path,
):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    metadata = IndexMetadata(
        "students_id_hash",
        "students",
        "id",
        IndexType.EXTENDIBLE_HASH,
        file_path=str(tmp_path / "students_id.hash"),
    )
    catalog.register_index(metadata)
    query_environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "students.heap", STUDENTS)
    query_environment.register_storage("students", storage)
    for row in ROWS:
        storage.insert(Record(STUDENTS, row))
    index = build_catalog_index(catalog, metadata.name, storage)
    query_environment.register_index(metadata.name, index)
    try:
        engine = SqlEngine(query_environment)
        prepared = engine.prepare("SELECT name FROM students WHERE id = 3")
        prepared_nodes = tuple(prepared.describe().walk())
        assert [node.name for node in prepared_nodes] == [
            "Projection", "Filter", "IndexScan",
        ]
        assert dict(prepared_nodes[-1].details)["index"] == metadata.name

        result = prepared.execute()
        assert _values(result.rows) == (("Sol",),)
        runtime = result.report.runtime
        runtime_nodes = runtime.operators
        assert [node.name for node in runtime_nodes] == [
            "Projection", "Filter", "IndexScan",
        ]
        assert dict(runtime_nodes[-1].details)["index_name"] == metadata.name
        assert runtime.index_pages_read > 0
        assert result.report.prepared == prepared.describe()
        assert result.report.fully_consumed is True
    finally:
        index.close()
        storage.close()


def test_index_join_runtime_report_includes_inner_index_io_and_identity(tmp_path):
    enrollments = Schema([
        Column("student_id", DataType.INTEGER),
        Column("course", DataType.VARCHAR),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))
    catalog.register_table(TableMetadata("enrollments", enrollments))
    metadata = IndexMetadata(
        "enrollments_student_hash",
        "enrollments",
        "student_id",
        IndexType.EXTENDIBLE_HASH,
        file_path=str(tmp_path / "enrollments_student.hash"),
    )
    catalog.register_index(metadata)
    query_environment = QueryEnvironment(catalog)
    students = HeapFile.create(tmp_path / "join_students.heap", STUDENTS)
    inner = HeapFile.create(tmp_path / "enrollments.heap", enrollments)
    query_environment.register_storage("students", students)
    query_environment.register_storage("enrollments", inner)
    for row in ROWS:
        students.insert(Record(STUDENTS, row))
    for row in ((1, "DB2"), (1, "OS"), (3, "DB2")):
        inner.insert(Record(enrollments, row))
    index = build_catalog_index(catalog, metadata.name, inner)
    query_environment.register_index(metadata.name, index)
    try:
        result = SqlEngine(query_environment).execute(
            "SELECT s.name, e.course FROM students AS s "
            "JOIN enrollments AS e ON s.id = e.student_id"
        )
        assert sorted(_values(result.rows)) == [
            ("Ana", "DB2"), ("Ana", "OS"), ("Sol", "DB2"),
        ]
        runtime = result.report.runtime
        join = next(
            node for node in runtime.operators
            if node.name == "IndexNestedLoopJoin"
        )

        assert dict(join.details)["index_name"] == metadata.name
        assert runtime.index_pages_read > 0
        assert runtime.base_pages_read > 0
    finally:
        index.close()
        inner.close()
        students.close()


def test_partial_external_sort_report_keeps_measured_spill_evidence(tmp_path):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("payload", DataType.VARCHAR),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("wide_rows", schema))
    query_environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "wide.heap", schema)
    query_environment.register_storage("wide_rows", storage)
    for number in range(400):
        storage.insert(Record(schema, [number, f"{number:04d}" + "x" * 400]))
    try:
        engine = SqlEngine(
            query_environment,
            planning_options=PhysicalPlanningOptions(
                sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
                sort_max_fan_in=MINIMUM_FAN_IN,
            ),
        )
        result = engine.execute(
            "SELECT id FROM wide_rows ORDER BY payload DESC"
        )
        assert result.fetchmany(1)[0].values == (399,)
        report = result.report

        assert report.state is ResultState.OPEN
        assert report.fully_consumed is False
        assert report.rows_delivered == 1
        assert report.runtime.temporary_pages_written > 0
        assert report.runtime.temporary_pages_read > 0
        assert "ExternalSort" in [node.name for node in report.runtime.operators]

        result.close()
        assert result.report.runtime.live_temporary_bytes == 0
        assert result.state is ResultState.CLOSED
    finally:
        storage.close()


@pytest.mark.parametrize(
    "kwargs,error",
    [
        ({"memory_budget_bytes": True}, InvalidTypeError),
        ({"memory_budget_bytes": 1}, ValidationError),
        ({"max_open_handles": 0}, ValidationError),
        ({"materialization_limit": -1}, ValidationError),
        ({"planning_options": object()}, InvalidTypeError),
    ],
)
def test_engine_configuration_is_validated_before_execution(environment, kwargs, error):
    env, _ = environment
    with pytest.raises(error):
        SqlEngine(env, **kwargs)
