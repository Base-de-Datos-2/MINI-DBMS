"""Stage 7 Tasks 7.36-7.38: truthful EXPLAIN execution contracts."""

from __future__ import annotations

import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.database import Database
from engine.errors import DatabaseError, UnsupportedAccessError, ValidationError
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.operators.temp_files import TemporaryWorkspace
from engine.query import (
    AnalysisExecutionError,
    ExplanationResult,
    PhysicalPlanningOptions,
    QueryEnvironment,
    ResultKind,
    ResultState,
    SelectPlanSpec,
    SqlEngine,
    SqlSyntaxError,
    SqlUnknownColumnError,
    SqlUnknownTableError,
    SqlUnsupportedError,
    StatementKind,
)
from engine.storage import HeapFile, Record
from tests.operator_helpers import RowSource


ALUMNOS_DDL = """CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
)"""

ALUMNOS_ROWS = (
    (1, "Ana", 10, 16),
    (2, "Luis", 20, 11),
    (3, "Sol", 10, 18),
)


def _seed_alumnos(database: Database) -> None:
    database.engine.execute(ALUMNOS_DDL)
    for row in ALUMNOS_ROWS:
        database.insert("alumnos", row)


def _node_names(descriptor) -> tuple[str, ...]:
    return tuple(node.name for node in descriptor.walk())


def _details(descriptor) -> dict[str, str]:
    return dict(descriptor.details)


def test_plain_explain_describes_the_real_plan_without_instantiating_it(
    tmp_path,
    monkeypatch,
):
    directories = []
    original_workspace_init = TemporaryWorkspace.__init__

    def track_workspace(workspace, *args, **kwargs):
        original_workspace_init(workspace, *args, **kwargs)
        directories.append(workspace.directory)

    monkeypatch.setattr(TemporaryWorkspace, "__init__", track_workspace)

    with Database.create(tmp_path) as database:
        _seed_alumnos(database)
        storage = database.storage_for("alumnos")
        index = database.index_for("__pk__alumnos")
        before = (storage.record_count, index.entry_count)
        prepared = database.engine.prepare(
            "EXPLAIN SELECT * FROM alumnos "
            "WHERE nota >= 14 ORDER BY id"
        )

        def reject_instantiation(_spec):
            raise AssertionError("plain EXPLAIN instantiated a row operator")

        monkeypatch.setattr(SelectPlanSpec, "instantiate", reject_instantiation)
        result = prepared.execute()

        assert isinstance(result, ExplanationResult)
        assert prepared.kind is StatementKind.EXPLAIN
        assert prepared.reusable is True
        assert result.kind is ResultKind.EXPLANATION
        assert result.statement_kind is StatementKind.EXPLAIN
        assert result.state is ResultState.COMPLETE
        assert result.executed is False
        assert result.complete is result.report.complete is True
        assert result.schema is None
        assert result.statistics is None
        assert result.output_rows is None
        assert result.execution_seconds is None
        assert result.planning_seconds >= 0
        assert _node_names(result.plan) == (
            "Projection",
            "ExternalSort",
            "Filter",
            "TableScan",
        )
        assert _details(result.plan.children[0])["keys"] == "alumnos.id ASC"
        assert _details(result.plan.children[0].children[0])["predicate"]
        assert (storage.record_count, index.entry_count) == before
        assert directories == []
        assert database.engine.active_result is None
        assert not hasattr(result, "affected_rows")
        with pytest.raises(UnsupportedAccessError):
            result.fetchall(limit=1)
        with pytest.raises(UnsupportedAccessError):
            iter(result)


def test_plain_explain_uses_the_same_index_policy_and_scan_fallback(tmp_path):
    with Database.create(tmp_path) as database:
        _seed_alumnos(database)

        indexed = database.engine.execute(
            "EXPLAIN SELECT nombre FROM alumnos WHERE id = 2"
        )
        scanned = database.engine.execute(
            "EXPLAIN SELECT nombre FROM alumnos WHERE id = 2",
            use_indexes=False,
        )

        indexed_nodes = tuple(indexed.plan.walk())
        index_scan = next(node for node in indexed_nodes if node.name == "IndexScan")
        assert _details(index_scan)["index"] == "__pk__alumnos"
        assert "TableScan" not in _node_names(indexed.plan)
        assert "TableScan" in _node_names(scanned.plan)
        assert "IndexScan" not in _node_names(scanned.plan)
        assert indexed.statistics is scanned.statistics is None


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("EXPLAIN SELECT * FROM missing", SqlUnknownTableError),
        ("EXPLAIN SELECT missing FROM alumnos", SqlUnknownColumnError),
        ("EXPLAIN ANALYZE INSERT INTO alumnos VALUES (4, 'X', 1, 20)", SqlUnsupportedError),
    ],
)
def test_explain_preserves_semantic_and_unsupported_error_categories(
    tmp_path,
    sql,
    error,
):
    with Database.create(tmp_path) as database:
        _seed_alumnos(database)
        before = database.storage_for("alumnos").record_count

        with pytest.raises(error) as excinfo:
            database.engine.execute(sql)

        assert excinfo.value.span is not None
        assert database.storage_for("alumnos").record_count == before
        assert database.engine.active_result is None


def test_explain_analyze_drains_once_without_retaining_rows_or_honoring_preview_cap(
    tmp_path,
    monkeypatch,
):
    with Database.create(tmp_path, materialization_limit=0) as database:
        _seed_alumnos(database)
        calls = 0
        original_instantiate = SelectPlanSpec.instantiate

        def count_instantiation(spec):
            nonlocal calls
            calls += 1
            return original_instantiate(spec)

        monkeypatch.setattr(SelectPlanSpec, "instantiate", count_instantiation)
        prepared = database.engine.prepare(
            "EXPLAIN ANALYZE SELECT * FROM alumnos "
            "WHERE nota >= 14 ORDER BY id"
        )
        first = prepared.execute()

        assert isinstance(first, ExplanationResult)
        assert prepared.kind is StatementKind.EXPLAIN_ANALYZE
        assert first.kind is ResultKind.EXPLANATION
        assert first.statement_kind is StatementKind.EXPLAIN_ANALYZE
        assert first.executed is True
        assert first.complete is first.report.complete is True
        assert first.state is ResultState.COMPLETE
        assert first.output_rows == 2
        assert first.statistics.rows_produced == 2
        assert first.execution_seconds >= 0
        assert first.statistics.elapsed_seconds >= 0
        assert first.statistics.live_temporary_bytes == 0
        assert calls == 1
        assert database.engine.active_result is None
        with pytest.raises(UnsupportedAccessError):
            first.fetchall(limit=100)

        second = prepared.execute()
        assert calls == 2
        assert second.output_rows == 2
        assert second.statistics.rows_produced == 2
        assert second.statistics.root is not first.statistics.root
        assert database.storage_for("alumnos").record_count == 3


def test_explain_analyze_reports_zero_for_an_empty_complete_execution(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute(ALUMNOS_DDL)
        result = database.engine.execute(
            "EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 14"
        )

        assert result.executed is True
        assert result.report.complete is True
        assert result.output_rows == result.statistics.rows_produced == 0
        assert result.statistics.live_temporary_bytes == 0


def test_explain_analyze_runs_real_external_sort_and_cleans_temporary_files(
    tmp_path,
    monkeypatch,
):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("payload", DataType.VARCHAR),
    ])
    catalog = Catalog()
    catalog.register_table(TableMetadata("wide_rows", schema))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "wide.heap", schema)
    environment.register_storage("wide_rows", storage)
    for number in range(400):
        storage.insert(Record(schema, [number, f"{number:04d}" + "x" * 400]))

    directories = []
    original_workspace_init = TemporaryWorkspace.__init__

    def track_workspace(workspace, *args, **kwargs):
        original_workspace_init(workspace, *args, **kwargs)
        directories.append(workspace.directory)

    monkeypatch.setattr(TemporaryWorkspace, "__init__", track_workspace)
    options = PhysicalPlanningOptions(
        sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        sort_max_fan_in=MINIMUM_FAN_IN,
    )
    try:
        engine = SqlEngine(
            environment,
            materialization_limit=0,
            planning_options=options,
        )
        result = engine.execute(
            "EXPLAIN ANALYZE SELECT id FROM wide_rows ORDER BY payload DESC"
        )
        runtime = result.statistics
        sort = next(node for node in runtime.operators if node.name == "ExternalSort")
        actual = _details(sort)

        assert result.output_rows == 400
        assert runtime.temporary_pages_written > 0
        assert runtime.temporary_pages_read > 0
        assert runtime.bytes_spilled > 0
        assert runtime.peak_live_temporary_bytes > 0
        assert runtime.live_temporary_bytes == 0
        assert int(actual["initial_runs"]) > 1
        assert directories and all(not path.exists() for path in directories)
    finally:
        storage.close()


def test_failed_analysis_reports_partial_work_cleans_and_allows_later_execution(
    tmp_path,
    monkeypatch,
):
    schema = Schema([Column("id", DataType.INTEGER)])
    catalog = Catalog()
    catalog.register_table(TableMetadata("items", schema))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "items.heap", schema)
    environment.register_storage("items", storage)
    storage.insert(Record(schema, [1]))
    storage.insert(Record(schema, [2]))
    engine = SqlEngine(environment)
    source = RowSource(
        [Record(schema, [1]), Record(schema, [2])],
        schema=schema,
        fail_at=1,
    )

    def failing_instantiation(_spec):
        return source

    original_instantiate = SelectPlanSpec.instantiate
    prepared = engine.prepare("EXPLAIN ANALYZE SELECT * FROM items")
    monkeypatch.setattr(SelectPlanSpec, "instantiate", failing_instantiation)
    try:
        with pytest.raises(AnalysisExecutionError) as excinfo:
            prepared.execute()

        failure = excinfo.value
        assert isinstance(failure, DatabaseError)
        assert isinstance(failure.cause, ValueError)
        assert failure.report.state is ResultState.FAILED
        assert failure.report.executed is True
        assert failure.report.complete is False
        assert failure.report.output_rows == 1
        assert failure.report.runtime.rows_produced == 1
        assert failure.report.runtime.live_temporary_bytes == 0
        assert failure.report.error_type == "ValueError"
        assert failure.report.error_message == "injected row failure"
        assert source.opens == source.closes == 1
        assert engine.active_result is None

        monkeypatch.setattr(SelectPlanSpec, "instantiate", original_instantiate)
        later = engine.execute("EXPLAIN ANALYZE SELECT * FROM items")
        assert later.output_rows == 2
        assert later.report.complete is True
    finally:
        storage.close()


def test_explanations_obey_active_stream_and_complete_input_boundaries(tmp_path):
    with Database.create(tmp_path) as database:
        _seed_alumnos(database)
        active = database.engine.execute("SELECT * FROM alumnos")
        assert active.fetchmany(1)

        with pytest.raises(ValidationError, match="active SELECT"):
            database.engine.execute("EXPLAIN SELECT * FROM alumnos")
        active.close()

        explained = database.engine.execute("EXPLAIN SELECT * FROM alumnos")
        assert explained.state is ResultState.COMPLETE
        assert database.engine.active_result is None

        before_tables = database.table_names()
        before_rows = database.storage_for("alumnos").record_count
        with pytest.raises(SqlSyntaxError, match="Only one SQL statement"):
            database.engine.execute(
                "CREATE TABLE extra (id INT); SELECT * FROM alumnos"
            )
        with pytest.raises(SqlSyntaxError, match="Only one SQL statement"):
            database.engine.execute(
                "INSERT INTO alumnos VALUES (4, 'X', 1, 20); "
                "SELECT * FROM alumnos"
            )

        assert database.table_names() == before_tables
        assert database.storage_for("alumnos").record_count == before_rows
        assert database.engine.execute(
            "EXPLAIN ANALYZE SELECT * FROM alumnos WHERE id = 999"
        ).output_rows == 0
