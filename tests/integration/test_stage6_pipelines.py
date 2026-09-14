"""Stage 6 increment A: manually assembled pipelines over persisted storage.

These scenarios instantiate the acceptance examples of ETAPA_06 section 11
that increment A can already satisfy. Sorting, grouping and joins arrive with
later increments and are not simulated here.
"""

from collections import defaultdict
from contextlib import closing

import pytest

from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.indexes import (
    ClusteredBPlusIndex,
    UnclusteredBPlusIndex,
    UnclusteredHashIndex,
)
from engine.operators import (
    And,
    Avg,
    ColumnReference,
    Count,
    ExternalHashGroup,
    ExternalSort,
    GraceHashJoin,
    JoinSpec,
    NestedLoopJoin,
    SortSpec,
    Sum,
    Compare,
    ComparisonOperator,
    ExecutionContext,
    Filter,
    IndexScan,
    Projection,
    TableScan,
    collect,
    column,
    execute,
    run_plan,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.storage import HeapFile, PagedSequentialFile, Record
from tests.operator_helpers import STUDENTS, STUDENT_ROWS, students


def values(rows):
    return [tuple(row.values) for row in rows]


@pytest.fixture
def database(tmp_path):
    """Build the shared dataset in both organizations plus all three indexes."""

    heap_path = tmp_path / "students.heap"
    sequential_path = tmp_path / "students.seq"
    with HeapFile.create(heap_path, STUDENTS) as heap, PagedSequentialFile.create(
        sequential_path, STUDENTS, "id"
    ) as sequential:
        for record in students(reversed(STUDENT_ROWS)):
            heap.insert(record)
            sequential.insert(record)
        with UnclusteredBPlusIndex.build(
            tmp_path / "students.bpt",
            heap=heap,
            index_name="ix_students_id",
            table_name="students",
            key_column="id",
        ) as bplus, UnclusteredHashIndex.build(
            tmp_path / "students.hsh",
            heap=heap,
            index_name="hx_students_id",
            table_name="students",
            key_column="id",
        ) as hash_index, ClusteredBPlusIndex.build(
            tmp_path / "students.cbt",
            sequential=sequential,
            index_name="cx_students_id",
            table_name="students",
            key_column="id",
        ) as clustered:
            yield {
                "heap": heap,
                "sequential": sequential,
                "bplus": bplus,
                "hash": hash_index,
                "clustered": clustered,
                "paths": (heap_path, sequential_path),
            }


def test_example_a_filtered_projection_runs_over_real_paged_storage(database):
    plan = Projection(
        Filter(
            TableScan(database["heap"], relation="students"),
            Compare(column("age"), ComparisonOperator.GREATER, 20),
        ),
        ["name", "career"],
    )

    with ExecutionContext(memory_budget_bytes=8192, label="example-a") as context:
        rows = collect(plan, context, limit=10)

    assert sorted(values(rows)) == sorted(
        [("Ana", "CS"), ("Sol", "CS"), ("Omar", "EE")]
    )
    assert plan.describe().render().splitlines() == [
        "Projection(columns=name, career)",
        "  Filter(predicate=Compare(ColumnValue('age'), '>', Literal(20)))",
        "    TableScan(relation=students, access=sequential scan)",
    ]


def test_the_reported_plan_names_the_access_path_actually_used(database):
    over_scan = Filter(
        TableScan(database["heap"], relation="students"),
        Compare(column("id"), ComparisonOperator.EQUAL, 3),
    )
    over_hash = IndexScan.equality(database["hash"], 3, relation="students")
    over_bplus = IndexScan.between(database["bplus"], 3, 3, relation="students")

    scan_details = dict(over_scan.describe().children[0].details)
    hash_details = dict(over_hash.describe().details)
    bplus_details = dict(over_bplus.describe().details)

    assert scan_details["access"] == "sequential scan"
    assert hash_details["access"] == "hash equality"
    assert hash_details["index"] == "UnclusteredHashIndex"
    assert bplus_details["access"] == "b+ range"
    assert values(collect(over_scan, limit=5)) == values(collect(over_hash, limit=5))
    assert values(collect(over_hash, limit=5)) == values(collect(over_bplus, limit=5))


def test_plan_report_counts_shared_base_pages_once(database):
    heap = database["heap"]
    before = heap.pages_read
    root = NestedLoopJoin(
        TableScan(heap, relation="left"),
        TableScan(heap, relation="right"),
        JoinSpec.on(("id", "id")),
    )
    rows, report = run_plan(root, limit=10)
    assert len(rows) == 4
    assert report.base_pages_read == heap.pages_read - before > 0
    assert report.base_pages_written == 0
    assert report.temporary_pages_written > 0


@pytest.mark.parametrize("name,access", [("bplus", "tree"), ("hash", "index")])
def test_plan_report_uses_real_index_and_base_counter_deltas(database, name, access):
    heap = database["heap"]
    index = database[name]
    physical_index = getattr(index, access)
    base_before, index_before = heap.pages_read, physical_index.pages_read
    rows, report = run_plan(
        IndexScan.equality(index, 3, relation="students"), limit=5,
    )
    assert len(rows) == 1
    assert report.base_pages_read == heap.pages_read - base_before
    assert report.index_pages_read == physical_index.pages_read - index_before > 0
    assert report.base_pages_written == report.index_pages_written == 0


def test_a_composed_predicate_narrows_both_organizations_identically(database):
    predicate = And(
        Compare(column("career"), ComparisonOperator.EQUAL, "CS"),
        Compare(column("age"), ComparisonOperator.GREATER_OR_EQUAL, 22),
    )

    heap_rows = collect(
        Projection(
            Filter(TableScan(database["heap"], relation="students"), predicate),
            ["id"],
        ),
        limit=10,
    )
    sequential_rows = collect(
        Projection(
            Filter(TableScan(database["sequential"], relation="students"), predicate),
            ["id"],
        ),
        limit=10,
    )

    assert sorted(values(heap_rows)) == [(1,), (3,)]
    assert sorted(values(heap_rows)) == sorted(values(sequential_rows))


def test_only_the_sequential_pipeline_claims_an_ordering(database):
    heap_plan = Projection(
        Filter(
            TableScan(database["heap"], relation="students"),
            Compare(column("age"), ComparisonOperator.GREATER, 0),
        ),
        ["id", "name"],
    )
    sequential_plan = Projection(
        Filter(
            TableScan(database["sequential"], relation="students"),
            Compare(column("age"), ComparisonOperator.GREATER, 0),
        ),
        ["id", "name"],
    )

    assert heap_plan.ordering is None
    assert sequential_plan.ordering == ColumnReference("id", "students")
    assert [row.values[0] for row in collect(sequential_plan, limit=10)] == [
        1,
        2,
        3,
        4,
    ]


def test_example_e_close_everything_reopen_and_rerun_the_same_pipeline(tmp_path):
    heap_path = tmp_path / "rerun.heap"
    index_path = tmp_path / "rerun.bpt"
    with HeapFile.create(heap_path, STUDENTS) as heap:
        for record in students():
            heap.insert(record)
        with UnclusteredBPlusIndex.build(
            index_path,
            heap=heap,
            index_name="ix_rerun",
            table_name="students",
            key_column="id",
        ):
            pass

    def run(budget):
        fresh_schema = Schema(list(STUDENTS.columns))
        with HeapFile.open(heap_path, fresh_schema) as heap:
            with UnclusteredBPlusIndex.open(index_path, heap=heap) as index:
                plan = Projection(
                    Filter(
                        IndexScan.between(index, 2, relation="students"),
                        Compare(column("career"), ComparisonOperator.EQUAL, "EE"),
                    ),
                    ["id", "name"],
                )
                with ExecutionContext(memory_budget_bytes=budget) as context:
                    return values(collect(plan, context, limit=10))

    first = run(8192)
    second = run(64 * 4096)

    assert first == [(2, "Luis"), (4, "Omar")]
    assert first == second


def test_a_pipeline_runs_twice_from_one_plan_object(database):
    plan = Projection(
        Filter(
            TableScan(database["heap"], relation="students"),
            Compare(column("career"), ComparisonOperator.EQUAL, "CS"),
        ),
        ["name"],
    )

    first = values(collect(plan, limit=10))
    second = values(collect(plan, limit=10))

    # The Heap advertises no ordering, so the two runs must agree with each
    # other and as a multiset, not with the order the rows were inserted in.
    assert first == second
    assert sorted(first) == [("Ana",), ("Sol",)]
    assert plan.statistics.runs == 2
    assert plan.statistics.rows_emitted == 4


def test_abandoning_a_pipeline_early_releases_every_owned_cursor(database):
    scan = TableScan(database["heap"], relation="students")
    plan = Projection(Filter(scan, Compare(column("age"), ComparisonOperator.GREATER, 0)), ["name"])

    with closing(execute(plan)) as stream:
        assert next(stream) is not None

    assert scan.state.value == "CLOSED"
    assert database["heap"].closed is False
    assert len(collect(TableScan(database["heap"], relation="students"), limit=10)) == 4


def test_the_catalog_describes_the_table_the_pipeline_reads(database):
    catalog = Catalog()
    catalog.register_table(TableMetadata("students", STUDENTS))

    metadata = catalog.get_table("students")
    plan = TableScan(database["heap"], relation=metadata.name)

    assert plan.output_schema == metadata.schema
    assert plan.layout.relations == ("students",)
    assert len(collect(plan, limit=10)) == 4


def test_execution_context_accounting_survives_a_full_pipeline_run(database):
    plan = Projection(
        Filter(
            TableScan(database["heap"], relation="students"),
            Compare(column("age"), ComparisonOperator.GREATER, 20),
        ),
        ["name"],
    )

    with ExecutionContext(memory_budget_bytes=8192, label="pipeline") as context:
        collect(plan, context, limit=10)

        assert context.reserved_bytes == 0
        assert context.available_bytes == 8192
        assert context.open_handle_count == 0


def test_example_d_forces_real_external_sorting_over_persisted_storage(tmp_path):
    """ETAPA_06 section 11, example D: prove the spill, do not assume it."""

    schema = Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )
    rows = [
        Record(schema, [(number * 7919) % 3000, f"payload-{number:05d}"])
        for number in range(3000)
    ]
    with HeapFile.create(tmp_path / "wide.heap", schema) as heap:
        for record in rows:
            heap.insert(record)
        assert heap.data_page_count > 1

        plan = ExternalSort(
            TableScan(heap, relation="wide"),
            SortSpec.ascending("id"),
            memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
            max_fan_in=MINIMUM_FAN_IN,
        )
        with ExecutionContext(memory_budget_bytes=512 * 4096) as context:
            output = collect(plan, context, limit=3500)

    metrics = plan.metrics
    expected = sorted((tuple(row.values) for row in rows), key=lambda row: row[0])

    assert metrics.initial_runs > plan.fan_in
    assert metrics.merge_passes >= 2
    assert metrics.max_fan_in <= plan.fan_in
    assert metrics.temporary_pages_written > 0
    assert values(output) == expected
    assert sorted(values(output)) == sorted(tuple(row.values) for row in rows)
    assert not plan.describe().details[1][1] == "0"


def test_a_sorted_pipeline_cleans_up_even_when_abandoned_early(database):
    plan = Projection(
        ExternalSort(
            TableScan(database["heap"], relation="students"),
            SortSpec.descending("age"),
            memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        ),
        ["name", "age"],
    )

    with closing(execute(plan)) as stream:
        first = next(stream)
        assert first.values == ("Sol", 24)

    assert database["heap"].closed is False
    assert plan.state.value == "CLOSED"


def test_sorting_a_heap_scan_reproduces_the_sequential_physical_order(database):
    sorted_heap = ExternalSort(
        TableScan(database["heap"], relation="students"),
        SortSpec.ascending("id"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )
    sequential = TableScan(database["sequential"], relation="students")

    assert values(collect(sorted_heap, limit=10)) == values(
        collect(sequential, limit=10)
    )
    assert sorted_heap.ordering == sequential.ordering


def test_example_b_group_then_sort_over_persisted_storage(database):
    """ETAPA_06 section 11, example B: career counts and averages, sorted."""

    plan = ExternalSort(
        ExternalHashGroup(
            TableScan(database["heap"], relation="students"),
            ["career"],
            [Count(), Avg("age")],
        ),
        SortSpec.ascending("career"),
    )

    with ExecutionContext(memory_budget_bytes=512 * 4096) as context:
        rows = collect(plan, context, limit=20)

    assert values(rows) == [("CS", 2, 23.0), ("EE", 2, 21.0)]
    assert [column.name for column in plan.output_schema] == [
        "career",
        "count",
        "avg_age",
    ]


def test_example_b_at_scale_forces_real_partition_io(tmp_path):
    schema = Schema(
        [Column("bucket", DataType.VARCHAR), Column("value", DataType.INTEGER)]
    )
    rows = [
        Record(schema, [f"b{(number * 7919) % 500:04d}", number % 97])
        for number in range(5000)
    ]
    with HeapFile.create(tmp_path / "buckets.heap", schema) as heap:
        for record in rows:
            heap.insert(record)

        group = ExternalHashGroup(
            TableScan(heap, relation="buckets"),
            ["bucket"],
            [Count(), Sum("value")],
            memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
            partition_count=2,
        )
        plan = ExternalSort(group, SortSpec.ascending("bucket"))
        output = collect(plan, limit=6000)

    expected = defaultdict(lambda: [0, 0])
    for record in rows:
        entry = expected[record.values[0]]
        entry[0] += 1
        entry[1] += record.values[1]

    assert values(output) == [
        (bucket, totals[0], totals[1])
        for bucket, totals in sorted(expected.items())
    ]
    assert len(output) == 500
    assert group.metrics.kernel_overflows > 0
    assert group.metrics.repartitions > 0
    assert group.metrics.temporary_pages_written > 0


def test_a_grouped_pipeline_leaves_no_temporary_files_behind(database):
    group = ExternalHashGroup(
        TableScan(database["heap"], relation="students"),
        ["career"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )
    plan = Projection(group, ["career", "count"])

    with closing(execute(plan)) as stream:
        assert next(stream) is not None
        directory = group._workspace.directory
        assert directory.exists()

    assert not directory.exists()
    assert database["heap"].closed is False


def test_example_c_preserves_join_multiplicity_over_persisted_storage(tmp_path):
    """ETAPA_06 section 11, example C, against real paged files."""

    enrollments = Schema(
        [Column("id", DataType.INTEGER), Column("student_id", DataType.INTEGER)]
    )
    with HeapFile.create(tmp_path / "students.heap", STUDENTS) as heap, \
            HeapFile.create(tmp_path / "enrollments.heap", enrollments) as other:
        for record in students([(7, "Ana", "CS", 22), (7, "Sol", "CS", 24),
                                (9, "Luis", "EE", 19)]):
            heap.insert(record)
        for number, student in enumerate([7, 7, 7, 10]):
            other.insert(Record(enrollments, [number, student]))

        spec = JoinSpec.on(("id", "student_id"))
        grace = GraceHashJoin(
            TableScan(heap, relation="students"),
            TableScan(other, relation="enrollments"),
            spec,
        )
        baseline = NestedLoopJoin(
            TableScan(heap, relation="students"),
            TableScan(other, relation="enrollments"),
            spec,
        )

        hash_rows = collect(grace, limit=100)
        baseline_rows = collect(baseline, limit=100)

    assert len(hash_rows) == 6
    assert sorted(values(hash_rows)) == sorted(values(baseline_rows))
    assert [column.name for column in grace.output_schema] == [
        "students.id",
        "name",
        "career",
        "age",
        "enrollments.id",
        "student_id",
    ]


def test_the_full_stage_six_pipeline_runs_over_paged_storage(tmp_path):
    """Scan, filter, join, group and sort, assembled by hand without SQL."""

    enrollments = Schema(
        [Column("id", DataType.INTEGER), Column("student_id", DataType.INTEGER),
         Column("credits", DataType.INTEGER)]
    )
    student_rows = [
        (number, f"name-{number}", "CS" if number % 2 else "EE", 18 + number % 12)
        for number in range(400)
    ]
    with HeapFile.create(tmp_path / "s.heap", STUDENTS) as heap, \
            HeapFile.create(tmp_path / "e.heap", enrollments) as other:
        for record in students(student_rows):
            heap.insert(record)
        for number in range(1200):
            other.insert(
                Record(enrollments, [number, number % 400, 1 + number % 5])
            )

        plan = ExternalSort(
            ExternalHashGroup(
                GraceHashJoin(
                    Filter(
                        TableScan(heap, relation="students"),
                        Compare(column("age"), ComparisonOperator.GREATER, 20),
                    ),
                    TableScan(other, relation="enrollments"),
                    JoinSpec.on(("id", "student_id")),
                    memory_budget_bytes=16 * 4096,
                    partition_count=4,
                ),
                [ColumnReference("career", "students")],
                [Count(), Sum("credits")],
                memory_budget_bytes=16 * 4096,
                partition_count=4,
            ),
            SortSpec.ascending("career"),
        )
        with ExecutionContext(memory_budget_bytes=512 * 4096) as context:
            output = collect(plan, context, limit=100)

    expected = defaultdict(lambda: [0, 0])
    for number, name, career, age in student_rows:
        if age <= 20:
            continue
        for enrollment in range(1200):
            if enrollment % 400 != number:
                continue
            entry = expected[career]
            entry[0] += 1
            entry[1] += 1 + enrollment % 5

    assert values(output) == [
        (career, totals[0], totals[1]) for career, totals in sorted(expected.items())
    ]
    assert plan.describe().render().splitlines()[0].startswith("ExternalSort")
