"""Tasks 6.20 and 6.21: external hash grouping, skew, and termination."""

from collections import defaultdict
from contextlib import closing
import random

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.operators import (
    Avg,
    Compare,
    ComparisonOperator,
    Count,
    ExecutionContext,
    ExternalHashGroup,
    ExternalSort,
    Filter,
    Max,
    Min,
    Projection,
    SortSpec,
    Sum,
    collect,
    column,
    execute,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.context import DEFAULT_MAX_OPEN_HANDLES
from engine.operators.partitioning import maximum_partition_count
from engine.storage import Record
from tests.operator_helpers import RowSource, STUDENTS, students


SALES = Schema(
    [
        Column("region", DataType.VARCHAR),
        Column("amount", DataType.INTEGER),
    ]
)


def sales(rows):
    return [Record(SALES, list(row)) for row in rows]


def grouped(operator, limit=5000):
    return {row.values[0]: tuple(row.values[1:]) for row in collect(operator, limit=limit)}


def count_oracle(rows):
    totals = defaultdict(int)
    for region, _ in rows:
        totals[region] += 1
    return {region: (total,) for region, total in totals.items()}


def test_grouping_computes_one_row_per_group():
    data = [("north", 10), ("south", 5), ("north", 7), ("east", 1)]
    operator = ExternalHashGroup(RowSource(sales(data)), ["region"], [Count(), Sum("amount")])

    results = grouped(operator)

    assert results == {"north": (2, 17), "south": (1, 5), "east": (1, 1)}
    assert operator.metrics.groups_emitted == 3


def test_the_output_schema_carries_group_keys_then_aggregates():
    operator = ExternalHashGroup(
        RowSource(students()), ["career"], [Count(), Avg("age"), Min("age")]
    )

    names = [column.name for column in operator.output_schema]
    types = [column.data_type for column in operator.output_schema]

    assert names == ["career", "count", "avg_age", "min_age"]
    assert types == [
        DataType.VARCHAR,
        DataType.INTEGER,
        DataType.FLOAT,
        DataType.INTEGER,
    ]
    assert operator.layout.field("career").relation == "rows"
    assert operator.layout.field("count").relation is None


def test_grouped_rows_advertise_no_ordering_and_no_provenance():
    operator = ExternalHashGroup(RowSource(students()), ["career"], [Count()])
    operator.open()
    try:
        operator.next()
        assert operator.provenance == ()
    finally:
        operator.close()

    assert operator.ordering is None
    assert operator.ordered is False


def test_grouping_an_empty_input_emits_no_rows():
    operator = ExternalHashGroup(RowSource([]), ["career"], [Count()])

    assert collect(operator, limit=5) == ()
    assert operator.metrics.groups_emitted == 0


def test_global_aggregation_emits_one_row_with_constant_state():
    data = [("north", 10), ("south", 5), ("north", 7)]
    operator = ExternalHashGroup(RowSource(sales(data)), [], [Count(), Sum("amount")])

    rows = collect(operator, limit=5)

    assert [tuple(row.values) for row in rows] == [(3, 22)]
    assert operator.metrics.global_aggregation is True
    assert operator.metrics.partitions_written == 0


def test_global_aggregation_over_empty_input_reports_zero_count():
    operator = ExternalHashGroup(
        RowSource([], schema=SALES), [], [Count(), Sum("amount")]
    )

    rows = collect(operator, limit=5)

    assert [tuple(row.values) for row in rows] == [(0, 0)]


def test_global_variable_width_state_respects_its_memory_grant():
    fitting = ExternalHashGroup(
        RowSource(sales([("x" * 5000, 1)])),
        [],
        [Min("region")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
    )
    assert [row.values[0] for row in collect(fitting, limit=2)] == ["x" * 5000]

    too_wide = ExternalHashGroup(
        RowSource(sales([("x" * 40000, 1)])),
        [],
        [Min("region")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
    )
    with pytest.raises(ValidationError, match="global aggregate state"):
        collect(too_wide, limit=2)


def test_global_extremes_over_empty_input_are_refused_not_invented():
    for aggregate in (Min("amount"), Max("amount"), Avg("amount")):
        operator = ExternalHashGroup(
            RowSource([], schema=SALES), [], [Count(), aggregate]
        )
        with pytest.raises(ValidationError, match="undefined over an empty input"):
            collect(operator, limit=5)


def test_more_distinct_groups_than_memory_still_produce_one_row_each():
    random.seed(21)
    data = [(f"r{random.randrange(400)}", random.randrange(1, 50)) for _ in range(4000)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count(), Sum("amount"), Avg("amount"), Min("amount"), Max("amount")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)
    metrics = operator.metrics

    oracle = defaultdict(list)
    for region, amount in data:
        oracle[region].append(amount)
    expected = {
        region: (len(v), sum(v), sum(v) / len(v), min(v), max(v))
        for region, v in oracle.items()
    }

    assert results == expected
    assert len(results) == len(expected) == 400
    assert metrics.kernel_overflows > 0
    assert metrics.repartitions > 0
    assert metrics.deepest_level >= 1
    assert metrics.partitions_written > operator._partition_count
    assert metrics.temporary_pages_written > 0
    assert metrics.temporary_pages_read > 0


def test_the_hash_route_finishes_without_needing_the_sorted_fallback():
    random.seed(22)
    data = [(f"r{random.randrange(600)}", 1) for _ in range(3000)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)

    assert results == count_oracle(data)
    assert operator.metrics.repartitions > 0
    assert operator.metrics.fallback_partitions == 0


def test_a_partition_overflow_neither_double_counts_nor_loses_the_trigger_row():
    random.seed(23)
    data = [(f"r{n}", 1) for n in range(600)] * 3
    random.shuffle(data)
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count(), Sum("amount")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)

    assert operator.metrics.kernel_overflows > 0
    assert len(results) == 600
    assert all(value == (3, 3) for value in results.values())
    assert sum(value[0] for value in results.values()) == len(data)


def test_a_dominant_key_is_processed_without_an_unbounded_member_list():
    data = [("hot", 1)] * 20_000 + [("cold", 2)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count(), Sum("amount"), Avg("amount")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)

    assert results["hot"] == (20_000, 20_000, 1.0)
    assert results["cold"] == (1, 2, 2.0)
    assert operator.metrics.kernel_overflows == 0
    assert operator.metrics.fallback_partitions == 0


def test_every_row_sharing_one_key_needs_no_repartitioning():
    data = [("same", n % 10) for n in range(10_000)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count(), Min("amount"), Max("amount")],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)

    assert results == {"same": (10_000, 0, 9)}
    assert operator.metrics.repartitions == 0


def test_distinct_keys_under_a_constant_hash_fall_back_and_stay_correct(monkeypatch):
    monkeypatch.setattr(
        "engine.operators.partitioning.partition_hash",
        lambda values, data_types, *, level=0: 0,
    )
    data = [(f"r{n}", 1) for n in range(400)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    results = grouped(operator)
    metrics = operator.metrics

    assert results == count_oracle(data)
    assert len(results) == 400
    # Hashing cannot separate these keys, so the bounded sorted route finishes
    # the job and says so instead of pretending it was hash-only execution.
    assert metrics.fallback_partitions > 0
    assert metrics.fallback_rows > 0
    assert dict(operator.describe().details)["sorted_fallbacks"] != "0"


def test_reaching_the_recursion_limit_falls_back_instead_of_looping():
    random.seed(24)
    data = [(f"r{n}", 1) for n in range(1500)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
        max_level=1,
    )

    results = grouped(operator)

    assert results == count_oracle(data)
    assert operator.metrics.fallback_partitions > 0
    assert operator.metrics.deepest_level <= 1


def test_the_fallback_result_matches_the_pure_hash_result():
    random.seed(25)
    data = [(f"r{n % 750}", n % 13) for n in range(3000)]
    aggregates = [Count(), Sum("amount"), Min("amount"), Max("amount")]

    generous = ExternalHashGroup(RowSource(sales(data)), ["region"], aggregates)
    forced = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        aggregates,
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
        max_level=1,
    )

    assert grouped(generous) == grouped(forced)
    assert generous.metrics.partitions_written > 0
    assert forced.metrics.fallback_partitions > 0


def test_composite_grouping_keys_group_on_the_complete_tuple():
    data = [("a", 1), ("a", 2), ("a", 1), ("b", 1)]
    operator = ExternalHashGroup(
        RowSource(sales(data)), ["region", "amount"], [Count()]
    )

    rows = {tuple(row.values[:2]): row.values[2] for row in collect(operator, limit=10)}

    assert rows == {("a", 1): 2, ("a", 2): 1, ("b", 1): 1}


def test_grouping_composes_above_a_filter_and_below_a_sort():
    plan = ExternalSort(
        ExternalHashGroup(
            Filter(
                RowSource(students()),
                Compare(column("age"), ComparisonOperator.GREATER, 20),
            ),
            ["career"],
            [Count()],
        ),
        SortSpec.ascending("career"),
    )

    rows = [tuple(row.values) for row in collect(plan, limit=10)]

    assert rows == [("CS", 2), ("EE", 1)]


def test_early_close_during_grouping_cleans_up_every_temporary():
    random.seed(26)
    data = [(f"r{n % 200}", 1) for n in range(2000)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    with closing(execute(operator)) as stream:
        assert next(stream) is not None
        directory = operator._workspace.directory
        assert directory.exists()

    assert not directory.exists()
    assert operator.state.value == "CLOSED"


def test_a_failing_child_during_partitioning_cleans_up():
    source = RowSource(sales([(f"r{n}", 1) for n in range(300)]), fail_at=200)
    operator = ExternalHashGroup(
        source,
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    with pytest.raises(ValueError, match="injected row failure"):
        collect(operator, limit=500)

    assert source.closes == 1
    assert operator._workspace is None


def test_grouping_releases_its_nested_budget_back_to_the_parent():
    data = [(f"r{n % 20}", 1) for n in range(200)]
    operator = ExternalHashGroup(RowSource(sales(data)), ["region"], [Count()])

    with ExecutionContext(memory_budget_bytes=512 * 4096) as context:
        collect(operator, context, limit=100)

        assert context.reserved_bytes == 0
        assert context.statistics.children_created == 1


def test_grouping_runs_twice_from_one_plan_object():
    data = [("a", 1), ("b", 2), ("a", 3)]
    operator = ExternalHashGroup(RowSource(sales(data)), ["region"], [Sum("amount")])

    first = grouped(operator)
    second = grouped(operator)

    assert first == second == {"a": (4,), "b": (2,)}
    assert operator.statistics.runs == 2


def test_the_descriptor_reports_the_real_strategy_and_counters():
    random.seed(27)
    data = [(f"r{n % 300}", 1) for n in range(3000)]
    operator = ExternalHashGroup(
        RowSource(sales(data)),
        ["region"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    collect(operator, limit=400)
    details = dict(operator.describe().details)

    assert details["keys"] == "region"
    assert details["aggregates"] == "count"
    assert details["strategy"] == "hash partitions"
    assert details["partitions"] == str(operator.metrics.partitions_written)
    assert details["repartitions"] == str(operator.metrics.repartitions)

    scalar = ExternalHashGroup(RowSource(sales(data)), [], [Count()])
    collect(scalar, limit=5)
    assert dict(scalar.describe().details)["strategy"] == "global state"
    assert dict(scalar.describe().details)["keys"] == "(global)"


def test_grouping_validates_its_construction_arguments():
    source = RowSource(students())

    with pytest.raises(InvalidTypeError, match="ExecutionOperator child"):
        ExternalHashGroup(object(), ["career"], [Count()])
    with pytest.raises(ValidationError, match="at least one aggregate"):
        ExternalHashGroup(source, ["career"], [])
    with pytest.raises(InvalidTypeError, match="must be an Aggregate"):
        ExternalHashGroup(source, ["career"], ["count"])
    with pytest.raises(UnknownColumnError):
        ExternalHashGroup(source, ["missing"], [Count()])
    with pytest.raises(ValidationError, match="at least"):
        ExternalHashGroup(source, ["career"], [Count()], memory_budget_bytes=1024)
    with pytest.raises(ValidationError, match="at least two partitions"):
        ExternalHashGroup(source, ["career"], [Count()], partition_count=1)
    with pytest.raises(ValidationError, match="max_level"):
        ExternalHashGroup(source, ["career"], [Count()], max_level=0)
    with pytest.raises(InvalidTypeError, match="group_keys"):
        ExternalHashGroup(source, "career", [Count()])


def test_a_duplicate_output_name_is_rejected_when_the_plan_is_built():
    source = RowSource(students())

    with pytest.raises(ValidationError, match="same name twice"):
        ExternalHashGroup(source, ["career"], [Count(alias="career")])
    with pytest.raises(ValidationError, match="same name twice"):
        ExternalHashGroup(source, ["career"], [Count(), Count()])


def test_a_fan_out_beyond_the_granted_budget_is_refused_at_open():
    operator = ExternalHashGroup(
        RowSource(students()),
        ["career"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=(
            maximum_partition_count(
                MINIMUM_GROUP_BUDGET_BYTES, DEFAULT_MAX_OPEN_HANDLES
            ) + 1
        ),
    )

    with pytest.raises(ValidationError, match="needs more than the granted"):
        collect(operator, limit=10)
