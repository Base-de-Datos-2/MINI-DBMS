"""Tasks 6.27 and 6.28: the plan runner, descriptors and measured reports."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    SchemaError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.operators import (
    Compare,
    ComparisonOperator,
    Count,
    ExternalHashGroup,
    ExternalSort,
    Filter,
    Literal,
    PhysicalPlan,
    PlanReport,
    Projection,
    SortSpec,
    column,
    run_plan,
)
from engine.operators.sorting import MINIMUM_SORT_BUDGET_BYTES
from engine.storage import Record
from tests.operator_helpers import FailingOpen, RowSource, STUDENTS, students


def plan_of(root, **kwargs):
    return PhysicalPlan(root, **kwargs)


def filtered():
    return Projection(
        Filter(
            RowSource(students()),
            Compare(column("age"), ComparisonOperator.GREATER, 20),
        ),
        ["name", "career"],
    )


def test_a_plan_opens_streams_and_closes_its_root():
    source = RowSource(students())
    plan = plan_of(Projection(source, ["name"]))

    with plan:
        rows = [row for row in plan.rows()]

    assert len(rows) == 4
    assert source.closes == 1
    assert plan.context is None
    assert plan.rows_produced == 4


def test_a_plan_closes_its_root_when_the_consumer_stops_early():
    source = RowSource(students())
    plan = plan_of(Projection(source, ["name"]))

    with plan:
        stream = plan.rows()
        with closing(stream):
            assert next(stream) is not None

    assert source.closes == 1


def test_a_plan_closes_its_root_when_the_body_raises():
    source = RowSource(students())
    plan = plan_of(Projection(source, ["name"]))

    with pytest.raises(ValueError, match="boom"):
        with plan:
            next(plan.rows())
            raise ValueError("boom")

    assert source.closes == 1
    assert plan.context is None


def test_a_failure_while_opening_releases_the_context():
    plan = plan_of(FailingOpen())

    with pytest.raises(ValueError, match="injected open failure"):
        with plan:
            pass

    assert plan.context is None


def test_each_run_gets_a_fresh_context_and_state():
    source = RowSource(students())
    plan = plan_of(Projection(source, ["name"]))

    for expected_run in (1, 2):
        with plan:
            first_context = plan.context
            rows = list(plan.rows())
        assert len(rows) == 4
        assert source.opens == source.closes == expected_run
        assert first_context.closed is True


def test_a_plan_cannot_be_opened_twice_or_streamed_while_closed():
    plan = plan_of(Projection(RowSource(students()), ["name"]))

    with pytest.raises(RuntimeError, match="must be open"):
        next(plan.rows())

    with plan:
        with pytest.raises(RuntimeError, match="already open"):
            plan.__enter__()


def test_verify_checks_declared_columns_and_types():
    plan = plan_of(filtered())

    assert plan.verify(
        columns=["name", "career"],
        types=[DataType.VARCHAR, DataType.VARCHAR],
    ) is plan

    with pytest.raises(SchemaError, match="publishes columns"):
        plan.verify(columns=["name"])
    with pytest.raises(SchemaError, match="publishes types"):
        plan.verify(types=[DataType.INTEGER, DataType.VARCHAR])


def test_verify_rejects_an_ordering_the_access_path_does_not_deliver():
    unordered = plan_of(filtered())
    ordered = plan_of(
        ExternalSort(RowSource(students()), SortSpec.ascending("age"))
    )

    with pytest.raises(UnsupportedAccessError, match="guarantees no ordering"):
        unordered.verify(ordered_by="name")

    assert ordered.verify(ordered_by="age") is ordered
    with pytest.raises(UnsupportedAccessError, match="ordered by"):
        ordered.verify(ordered_by="name")


def test_a_plan_reports_the_schema_and_ordering_it_really_has():
    sorted_plan = plan_of(
        ExternalSort(RowSource(students()), SortSpec.descending("age"))
    )

    assert [c.name for c in sorted_plan.output_schema] == [
        c.name for c in STUDENTS
    ]
    # Descending output is not ascending by that column, so nothing is claimed.
    assert sorted_plan.ordering is None


def test_the_report_describes_the_actual_operator_tree():
    rows, report = run_plan(filtered(), limit=10)

    assert isinstance(report, PlanReport)
    assert report.rows_produced == len(rows) == 3
    assert [node.name for node in report.operators] == [
        "Projection",
        "Filter",
        "RowSource",
    ]
    assert [node.operator_id for node in report.operators] == ["0", "0.0", "0.0.0"]
    assert report.operators[0].output_columns == (
        ("name", "VARCHAR"),
        ("career", "VARCHAR"),
    )


def test_row_counters_are_local_and_are_not_double_counted():
    _, report = run_plan(filtered(), limit=10)
    projection, filter_node, source = report.operators

    assert source.rows_emitted == 4
    assert filter_node.rows_examined == 4
    assert filter_node.rows_emitted == 3
    assert projection.rows_examined == 3
    assert projection.rows_emitted == 3
    # Summing a parent and a child would count the same rows twice; the report
    # exposes the root's own output instead.
    assert report.rows_produced == projection.rows_emitted


def test_timings_are_inclusive_so_a_parent_is_never_faster_than_its_child():
    _, report = run_plan(filtered(), limit=10)
    projection, filter_node, source = report.operators

    assert projection.elapsed_seconds >= filter_node.elapsed_seconds
    assert filter_node.elapsed_seconds >= source.elapsed_seconds
    assert report.elapsed_seconds == projection.elapsed_seconds


def test_the_report_exposes_peak_memory_and_handles_against_the_grant():
    root = ExternalSort(
        RowSource(students() * 200),
        SortSpec.ascending("age"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=2,
    )

    _, report = run_plan(root, memory_budget_bytes=64 * 4096, limit=2000)

    assert report.peak_reserved_bytes > 0
    assert report.peak_reserved_bytes <= report.memory_budget_bytes
    assert report.memory_budget_bytes == 64 * 4096
    assert report.reservations_granted > 0
    assert report.reservations_refused == 0
    assert "peak_memory" in report.render()


def test_a_descriptor_reports_the_fallback_a_run_actually_used():
    hot = [Record(STUDENTS, [1, "n", "CS", 20])] * 200
    plain = ExternalHashGroup(RowSource(hot), ["career"], [Count()])

    collected, _ = run_plan(plain, limit=10)
    details = dict(plain.describe().details)

    assert len(collected) == 1
    assert details["sorted_fallbacks"] == "0"
    assert details["strategy"] == "hash partitions"


def test_descriptors_reflect_counters_that_change_between_runs():
    root = Projection(RowSource(students()), ["name"])

    run_plan(root, limit=10)
    after_first = root.describe().rows_emitted
    run_plan(root, limit=10)
    after_second = root.describe().rows_emitted

    assert after_first == 4
    assert after_second == 8


def test_a_partially_consumed_plan_reports_only_what_it_produced():
    plan = plan_of(Projection(RowSource(students()), ["name"]))

    with plan:
        stream = plan.rows()
        with closing(stream):
            next(stream)
            next(stream)
        report = plan.report()

    assert report.rows_produced == 2
    assert report.operators[0].rows_emitted == 2


def test_run_plan_requires_an_explicit_limit_and_never_truncates():
    rows, _ = run_plan(filtered(), limit=3)

    assert len(rows) == 3
    with pytest.raises(ValidationError, match="more than the requested 1 rows"):
        run_plan(filtered(), limit=1)
    with pytest.raises(InvalidTypeError):
        run_plan(filtered(), limit="3")
    with pytest.raises(ValidationError):
        run_plan(filtered(), limit=-1)


def test_the_plan_runner_validates_its_root():
    with pytest.raises(InvalidTypeError, match="Operator root"):
        PhysicalPlan(object())


def test_an_empty_intermediate_produces_an_empty_result_without_failing():
    empty = Filter(RowSource(students()), Literal(False))
    root = ExternalSort(empty, SortSpec.ascending("age"))

    rows, report = run_plan(root, limit=10)

    assert rows == ()
    assert report.rows_produced == 0
    assert report.operators[0].rows_emitted == 0


def test_a_failure_inside_a_child_propagates_and_closes_everything():
    source = RowSource(students(), fail_at=2)
    root = Projection(Filter(source, Literal(True)), ["name"])
    plan = plan_of(root)

    with pytest.raises(ValueError, match="injected row failure"):
        with plan:
            list(plan.rows())

    assert source.closes == 1
    assert plan.context is None


def test_nested_blocking_operators_share_one_context_budget():
    schema = Schema(
        [Column("k", DataType.VARCHAR), Column("v", DataType.INTEGER)]
    )
    rows = [Record(schema, [f"k{n % 30}", n]) for n in range(600)]
    root = ExternalSort(
        ExternalHashGroup(
            RowSource(rows),
            ["k"],
            [Count()],
            memory_budget_bytes=16 * 4096,
            partition_count=4,
        ),
        SortSpec.ascending("k"),
        memory_budget_bytes=16 * 4096,
    )

    produced, report = run_plan(root, memory_budget_bytes=128 * 4096, limit=100)

    assert len(produced) == 30
    assert [row.values[0] for row in produced] == sorted(
        {f"k{n % 30}" for n in range(600)}
    )
    # Both blocking operators were live at once and still fit the grant.
    assert report.peak_reserved_bytes <= report.memory_budget_bytes
    assert report.reservations_refused == 0
