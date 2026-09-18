"""Tasks 7.28-7.29: restart, external paths, budgets, and cleanup."""

from collections import Counter

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
from engine.indexes.index_catalog import build_catalog_index, open_catalog_index
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.join import MINIMUM_JOIN_BUDGET_BYTES
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.operators.temp_files import TemporaryWorkspace
from engine.operators.temp_stream import TemporaryRowWriter
from engine.query import (
    JoinPlanningStrategy,
    PhysicalPlanningOptions,
    QueryEnvironment,
    ResultState,
    SqlEngine,
    run_sql,
)
from engine.storage import HeapFile, Record


def _values(result):
    return tuple(record.values for record in result.rows)


def _track_workspaces(monkeypatch):
    directories = []
    original = TemporaryWorkspace.__init__

    def track(workspace, *args, **kwargs):
        original(workspace, *args, **kwargs)
        directories.append(workspace.directory)

    monkeypatch.setattr(TemporaryWorkspace, "__init__", track)
    return directories


def test_public_sort_forces_two_merge_passes_and_cleans_after_early_close(
    tmp_path,
    monkeypatch,
):
    schema = Schema(
        [
            Column("id", DataType.INTEGER),
            Column("payload", DataType.VARCHAR),
        ]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("wide_rows", schema))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "wide.heap", schema)
    environment.register_storage("wide_rows", storage)
    for number in range(600):
        storage.insert(
            Record(schema, [number, f"{number:04d}" + "x" * 500])
        )
    directories = _track_workspaces(monkeypatch)
    small_options = PhysicalPlanningOptions(
        sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        sort_max_fan_in=MINIMUM_FAN_IN,
    )
    try:
        engine = SqlEngine(environment, planning_options=small_options)
        partial = engine.execute(
            "SELECT id FROM wide_rows ORDER BY payload DESC"
        )
        assert partial.fetchmany(1)[0].values == (599,)
        report = partial.report.runtime
        sort = next(node for node in report.operators if node.name == "ExternalSort")
        details = dict(sort.details)
        assert int(details["initial_runs"]) > int(details["fan_in"])
        assert int(details["merge_passes"]) >= 2
        assert report.temporary_pages_read > 0
        assert report.temporary_pages_written > 0
        assert report.bytes_spilled > 0
        assert report.peak_reserved_bytes <= report.memory_budget_bytes
        assert report.peak_open_handles <= engine.max_open_handles
        assert any(directory.exists() for directory in directories)

        context = partial._plan.context
        partial.close()
        assert partial.state is ResultState.CLOSED
        assert context.closed is True
        assert partial.report.runtime.live_temporary_bytes == 0
        assert all(not directory.exists() for directory in directories)

        small = _values(
            run_sql(
                environment,
                "SELECT id FROM wide_rows ORDER BY payload DESC",
                planning_options=small_options,
            )
        )
        large = _values(
            run_sql(
                environment,
                "SELECT id FROM wide_rows ORDER BY payload DESC",
                memory_budget_bytes=512 * 4096,
                planning_options=PhysicalPlanningOptions(
                    sort_memory_budget_bytes=512 * 4096,
                    sort_max_fan_in=8,
                ),
            )
        )
        expected = tuple((number,) for number in range(599, -1, -1))
        assert small == large == expected
        assert storage.record_count == 600
        assert all(not directory.exists() for directory in directories)
    finally:
        storage.close()


def test_public_grouping_spills_and_is_budget_invariant(tmp_path):
    schema = Schema(
        [
            Column("bucket", DataType.VARCHAR),
            Column("amount", DataType.INTEGER),
        ]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("sales", schema))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "sales.heap", schema)
    environment.register_storage("sales", storage)
    for number in range(900):
        storage.insert(
            Record(schema, [f"r{number % 300}", number % 17])
        )
    sql = (
        "SELECT bucket, COUNT(*) AS n, SUM(amount) AS total, "
        "AVG(amount) AS mean, MIN(amount) AS lo, MAX(amount) AS hi "
        "FROM sales GROUP BY bucket"
    )
    small_options = PhysicalPlanningOptions(
        group_memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        group_partition_count=2,
    )
    try:
        small_result = run_sql(
            environment,
            sql,
            planning_options=small_options,
        )
        small = Counter(_values(small_result))
        group = next(
            node for node in small_result.report.runtime.operators
            if node.name == "ExternalHashGroup"
        )
        details = dict(group.details)
        assert len(small) == 300
        assert sum(row[1] for row in small.elements()) == 900
        assert int(details["partitions"]) > 0
        assert int(details["repartitions"]) > 0
        assert small_result.report.runtime.temporary_pages_written > 0
        assert small_result.report.runtime.bytes_spilled > 0

        large = Counter(
            _values(
                run_sql(
                    environment,
                    sql,
                    memory_budget_bytes=512 * 4096,
                    planning_options=PhysicalPlanningOptions(
                        group_memory_budget_bytes=512 * 4096,
                        group_partition_count=2,
                    ),
                )
            )
        )
        assert small == large
        assert storage.record_count == 900
    finally:
        storage.close()


def test_public_grace_join_spills_falls_back_and_matches_other_budgets(tmp_path):
    side = Schema(
        [
            Column("id", DataType.INTEGER),
            Column("payload", DataType.VARCHAR),
        ]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("left_rows", side))
    catalog.register_table(TableMetadata("right_rows", side))
    environment = QueryEnvironment(catalog)
    left = HeapFile.create(tmp_path / "left.heap", side)
    right = HeapFile.create(tmp_path / "right.heap", side)
    environment.register_storage("left_rows", left)
    environment.register_storage("right_rows", right)
    for number in range(120):
        left.insert(Record(side, [number, "l" * 600]))
        right.insert(Record(side, [number, "r" * 600]))
    sql = (
        "SELECT l.id, r.id FROM left_rows AS l "
        "JOIN right_rows AS r ON l.id = r.id"
    )
    try:
        small_result = run_sql(
            environment,
            sql,
            planning_options=PhysicalPlanningOptions(
                join_strategy=JoinPlanningStrategy.GRACE_HASH,
                join_memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES,
                join_partition_count=2,
                join_max_level=1,
            ),
        )
        small = Counter(_values(small_result))
        join = next(
            node for node in small_result.report.runtime.operators
            if node.name == "GraceHashJoin"
        )
        details = dict(join.details)
        assert len(small) == 120
        assert int(details["partition_pairs"]) > 0
        assert int(details["build_overflows"]) > 0
        assert int(details["nested_loop_fallbacks"]) > 0
        assert small_result.report.runtime.temporary_pages_read > 0
        assert small_result.report.runtime.bytes_spilled > 0

        large = Counter(
            _values(
                run_sql(
                    environment,
                    sql,
                    memory_budget_bytes=512 * 4096,
                    planning_options=PhysicalPlanningOptions(
                        join_strategy=JoinPlanningStrategy.GRACE_HASH,
                        join_memory_budget_bytes=512 * 4096,
                        join_partition_count=2,
                    ),
                )
            )
        )
        assert small == large == Counter({(number, number): 1 for number in range(120)})
        assert left.record_count == right.record_count == 120
    finally:
        right.close()
        left.close()


def test_fresh_managers_execute_index_group_sort_and_join_after_restart(tmp_path):
    students_schema = Schema(
        [
            Column("id", DataType.INTEGER),
            Column("career", DataType.VARCHAR),
            Column("age", DataType.INTEGER),
        ]
    )
    enrollments_schema = Schema(
        [
            Column("student_id", DataType.INTEGER),
            Column("course", DataType.VARCHAR),
        ]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", students_schema))
    catalog.register_table(TableMetadata("enrollments", enrollments_schema))
    metadata = IndexMetadata(
        "students_id_hash",
        "students",
        "id",
        IndexType.EXTENDIBLE_HASH,
        unique=True,
        file_path=str(tmp_path / "students_id.hash"),
    )
    catalog.register_index(metadata)
    students_path = tmp_path / "students.heap"
    enrollments_path = tmp_path / "enrollments.heap"
    students = HeapFile.create(students_path, students_schema)
    enrollments = HeapFile.create(enrollments_path, enrollments_schema)
    for row in ((1, "CS", 22), (2, "EE", 19), (3, "CS", 24)):
        students.insert(Record(students_schema, row))
    for row in ((1, "DB2"), (1, "OS"), (3, "DB2")):
        enrollments.insert(Record(enrollments_schema, row))
    index = build_catalog_index(catalog, metadata.name, students)
    index.close()
    enrollments.close()
    students.close()

    reopened_students = HeapFile.open(students_path, students_schema)
    reopened_enrollments = HeapFile.open(enrollments_path, enrollments_schema)
    reopened_index = open_catalog_index(catalog, metadata.name, reopened_students)
    environment = QueryEnvironment(catalog)
    environment.register_storage("students", reopened_students)
    environment.register_storage("enrollments", reopened_enrollments)
    environment.register_index(metadata.name, reopened_index)
    try:
        engine = SqlEngine(environment)
        assert _values(
            engine.execute("SELECT career FROM students WHERE id = 3")
        ) == (("CS",),)
        assert _values(
            engine.execute(
                "SELECT career, COUNT(*) AS n FROM students "
                "GROUP BY career ORDER BY career"
            )
        ) == (("CS", 2), ("EE", 1))
        assert Counter(
            _values(
                engine.execute(
                    "SELECT s.id, e.course FROM students AS s "
                    "JOIN enrollments AS e ON s.id = e.student_id"
                )
            )
        ) == Counter({(1, "DB2"): 1, (1, "OS"): 1, (3, "DB2"): 1})
        assert reopened_students.record_count == 3
        assert reopened_enrollments.record_count == 3
    finally:
        reopened_index.close()
        reopened_enrollments.close()
        reopened_students.close()


def test_temporary_writer_failure_through_sql_cleans_every_owned_resource(
    tmp_path,
    monkeypatch,
):
    schema = Schema(
        [
            Column("id", DataType.INTEGER),
            Column("payload", DataType.VARCHAR),
        ]
    )
    catalog = Catalog()
    catalog.register_table(TableMetadata("wide_rows", schema))
    environment = QueryEnvironment(catalog)
    storage = HeapFile.create(tmp_path / "wide.heap", schema)
    environment.register_storage("wide_rows", storage)
    for number in range(100):
        storage.insert(Record(schema, [number, "x" * 500]))
    directories = _track_workspaces(monkeypatch)
    original_write = TemporaryRowWriter.write
    failed = False

    def fail_once(writer, record):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected SQL temporary-write failure")
        return original_write(writer, record)

    monkeypatch.setattr(TemporaryRowWriter, "write", fail_once)
    try:
        result = SqlEngine(
            environment,
            planning_options=PhysicalPlanningOptions(
                sort_memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
                sort_max_fan_in=MINIMUM_FAN_IN,
            ),
        ).execute("SELECT id FROM wide_rows ORDER BY payload")

        with pytest.raises(OSError, match="temporary-write failure"):
            next(result)

        assert result.state is ResultState.FAILED
        assert isinstance(result.error, OSError)
        assert result._plan.context is None
        assert result.report.runtime.live_temporary_bytes == 0
        assert all(not directory.exists() for directory in directories)
        assert storage.record_count == 100
    finally:
        storage.close()
