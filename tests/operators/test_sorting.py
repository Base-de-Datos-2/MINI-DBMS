"""Tasks 6.13-6.16: sort specifications, bounded runs and k-way merging."""

from contextlib import closing
import random

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    UnknownColumnError,
    ValidationError,
)
from engine.operators import (
    ColumnReference,
    ExecutionContext,
    ExternalSort,
    Projection,
    RowLayout,
    SortKey,
    SortSpec,
    collect,
    execute,
)
from engine.operators.sorting import (
    DEFAULT_MAX_FAN_IN,
    MINIMUM_FAN_IN,
    MINIMUM_SORT_BUDGET_BYTES,
)
from engine.storage import Record
from tests.operator_helpers import RowSource, STUDENTS, STUDENT_ROWS, students


PAIRS = Schema(
    [
        Column("key", DataType.INTEGER),
        Column("label", DataType.VARCHAR),
    ]
)


def pairs(rows):
    return [Record(PAIRS, list(row)) for row in rows]


def values(rows):
    return [tuple(row.values) for row in rows]


def sorted_oracle(rows, *, key, reverse=False):
    """A test-only in-memory reference ordering, stable like the operator."""

    return sorted(rows, key=key, reverse=reverse)


def test_sort_spec_binds_columns_and_rejects_unknown_ones():
    layout = RowLayout(STUDENTS, relation="students")
    bound = SortSpec.ascending("age", "name").bind(layout)

    assert bound.positions == (3, 1)
    assert bound.key(Record(STUDENTS, [1, "Ana", "CS", 22])) == (22, "Ana")

    with pytest.raises(UnknownColumnError):
        SortSpec.ascending("missing").bind(layout)
    with pytest.raises(InvalidTypeError):
        SortSpec.ascending("age").bind(STUDENTS)


def test_sort_spec_validates_its_keys():
    with pytest.raises(InvalidTypeError, match="sequence of SortKey"):
        SortSpec("age")
    with pytest.raises(InvalidTypeError, match="must be a SortKey"):
        SortSpec(["age"])
    with pytest.raises(InvalidTypeError):
        SortKey("age", descending="yes")
    with pytest.raises(ValidationError, match="Duplicate sort key"):
        SortSpec([SortKey("age"), SortKey("age", descending=True)])


def test_a_nan_sort_key_is_rejected_rather_than_ordered_inconsistently():
    schema = Schema([Column("value", DataType.FLOAT)])
    layout = RowLayout(schema)
    bound = SortSpec.ascending("value").bind(layout)

    assert bound.key(Record(schema, [float("inf")])) == (float("inf"),)
    with pytest.raises(ValidationError, match="NaN"):
        bound.key(Record(schema, [float("nan")]))


@pytest.mark.parametrize("budget", [None, MINIMUM_SORT_BUDGET_BYTES])
def test_ascending_and_descending_produce_opposite_orders(budget):
    data = [(3, "c"), (1, "a"), (2, "b"), (-5, "neg")]

    ascending = collect(
        ExternalSort(RowSource(pairs(data)), SortSpec.ascending("key"),
                     memory_budget_bytes=budget),
        limit=10,
    )
    descending = collect(
        ExternalSort(RowSource(pairs(data)), SortSpec.descending("key"),
                     memory_budget_bytes=budget),
        limit=10,
    )

    assert values(ascending) == sorted_oracle(data, key=lambda row: row[0])
    assert values(descending) == sorted_oracle(
        data, key=lambda row: row[0], reverse=True
    )


def test_mixed_key_directions_are_supported():
    data = [(1, "b"), (1, "a"), (2, "b"), (2, "a")]
    spec = SortSpec([SortKey("key"), SortKey("label", descending=True)])

    rows = collect(ExternalSort(RowSource(pairs(data)), spec), limit=10)

    assert values(rows) == [(1, "b"), (1, "a"), (2, "b"), (2, "a")]


def test_equal_keys_keep_their_input_order():
    data = [(1, f"row-{number}") for number in range(50)]

    rows = collect(
        ExternalSort(
            RowSource(pairs(data)),
            SortSpec.ascending("key"),
            memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
            max_fan_in=MINIMUM_FAN_IN,
        ),
        limit=100,
    )

    assert values(rows) == data


def test_unicode_and_negative_values_follow_the_documented_order():
    data = [(0, "Z"), (0, "a"), (0, "Á"), (0, "ñ"), (0, "A")]

    rows = collect(
        ExternalSort(RowSource(pairs(data)), SortSpec.ascending("label")), limit=10
    )

    assert values(rows) == sorted_oracle(data, key=lambda row: row[1])
    assert [row.values[1] for row in rows] == ["A", "Z", "a", "Á", "ñ"]


def test_an_empty_sort_specification_preserves_input_order():
    data = [(3, "c"), (1, "a"), (2, "b")]
    operator = ExternalSort(RowSource(pairs(data)), SortSpec())

    rows = collect(operator, limit=10)

    assert values(rows) == data
    assert operator.ordering is None


def test_sorting_an_empty_input_produces_no_rows_and_no_runs():
    operator = ExternalSort(RowSource([]), SortSpec.ascending("id"))

    assert collect(operator, limit=5) == ()
    assert operator.metrics.initial_runs == 0
    assert operator.metrics.merge_passes == 0


def test_a_single_row_needs_no_merge_pass():
    operator = ExternalSort(RowSource(students()[:1]), SortSpec.ascending("age"))

    rows = collect(operator, limit=5)

    assert values(rows) == [STUDENT_ROWS[0]]
    assert operator.metrics.initial_runs == 1
    assert operator.metrics.merge_passes == 1


def test_the_same_input_sorts_identically_with_and_without_spilling():
    random.seed(11)
    data = [(random.randrange(50), f"row-{number}") for number in range(400)]

    in_memory = ExternalSort(RowSource(pairs(data)), SortSpec.ascending("key"))
    spilled = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    memory_rows = values(collect(in_memory, limit=500))
    spilled_rows = values(collect(spilled, limit=500))

    assert memory_rows == spilled_rows == sorted_oracle(data, key=lambda row: row[0])
    assert in_memory.metrics.initial_runs < spilled.metrics.initial_runs
    assert spilled.metrics.initial_runs > 1


def test_more_runs_than_fan_in_force_several_merge_passes():
    random.seed(3)
    data = [(random.randrange(1000), f"row-{number}") for number in range(2000)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    rows = collect(operator, limit=2500)
    metrics = operator.metrics

    assert values(rows) == sorted_oracle(data, key=lambda row: row[0])
    assert metrics.initial_runs > operator.fan_in
    assert metrics.merge_passes >= 2
    assert metrics.max_fan_in <= operator.fan_in
    assert metrics.rows_spilled == len(data)
    assert metrics.bytes_spilled > 0
    assert metrics.temporary_pages_written > 0
    assert metrics.temporary_pages_read > 0
    assert metrics.final_merge_streamed is True


def test_fan_in_comes_from_resources_not_from_the_number_of_runs():
    random.seed(5)
    data = [(random.randrange(100), f"row-{number}") for number in range(600)]
    generous = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=64,
    )

    collect(generous, limit=700)

    assert generous.metrics.initial_runs > generous.fan_in
    assert generous.fan_in < 64
    assert generous.fan_in >= MINIMUM_FAN_IN


def test_a_low_handle_limit_bounds_the_fan_in():
    random.seed(9)
    data = [(random.randrange(100), f"row-{number}") for number in range(300)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=64 * 4096,
        max_fan_in=DEFAULT_MAX_FAN_IN,
    )

    with ExecutionContext(memory_budget_bytes=256 * 4096, max_open_handles=4) as ctx:
        rows = collect(operator, ctx, limit=400)

    assert operator.fan_in <= 3
    assert values(rows) == sorted_oracle(data, key=lambda row: row[0])


def test_runs_of_unequal_length_and_duplicates_across_runs_merge_correctly():
    data = [(1, "a"), (1, "b"), (5, "c")] + [(3, f"d{n}") for n in range(120)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    rows = collect(operator, limit=200)

    assert values(rows) == sorted_oracle(data, key=lambda row: row[0])
    assert len(rows) == len(data)


def test_sorting_preserves_the_exact_input_multiset():
    random.seed(13)
    data = [(random.randrange(5), f"row-{number % 7}") for number in range(500)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key", "label"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )

    rows = values(collect(operator, limit=600))

    assert sorted(rows) == sorted(data)
    assert len(rows) == len(data)


def test_variable_width_rows_are_admitted_across_chunk_boundaries():
    data = [(number, "x" * (number % 400)) for number in range(300)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )

    rows = collect(operator, limit=400)

    assert values(rows) == sorted_oracle(data, key=lambda row: row[0])


def test_a_row_too_wide_for_the_sort_budget_fails_deterministically():
    wide = Record(PAIRS, [1, "x" * (MINIMUM_SORT_BUDGET_BYTES)])
    operator = ExternalSort(
        RowSource([wide]),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )

    with pytest.raises(ValidationError, match="single row needs"):
        collect(operator, limit=5)


def test_early_close_during_the_final_merge_cleans_up_every_temporary():
    random.seed(17)
    data = [(random.randrange(100), f"row-{number}") for number in range(800)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    with closing(execute(operator)) as stream:
        assert next(stream) is not None
        directory = operator._workspace.directory
        assert directory.exists()

    assert not directory.exists()
    assert operator.state.value == "CLOSED"


def test_a_failing_child_during_run_generation_still_cleans_up():
    source = RowSource(pairs([(number, "x") for number in range(200)]), fail_at=150)
    operator = ExternalSort(
        source,
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    with pytest.raises(ValueError, match="injected row failure"):
        collect(operator, limit=300)

    assert source.closes == 1
    assert operator._workspace is None


def test_the_sort_releases_its_nested_budget_back_to_the_parent():
    data = [(number, "x") for number in range(200)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )

    with ExecutionContext(memory_budget_bytes=256 * 4096) as context:
        collect(operator, context, limit=300)

        assert context.reserved_bytes == 0
        assert context.statistics.children_created == 1


def test_the_sort_can_run_twice_from_one_plan_object():
    data = [(3, "c"), (1, "a"), (2, "b")]
    operator = ExternalSort(RowSource(pairs(data)), SortSpec.ascending("key"))

    first = values(collect(operator, limit=10))
    second = values(collect(operator, limit=10))

    assert first == second == sorted_oracle(data, key=lambda row: row[0])
    assert operator.statistics.runs == 2


def test_the_sort_advertises_ordering_only_for_a_leading_ascending_key():
    ascending = ExternalSort(RowSource(students()), SortSpec.ascending("age"))
    descending = ExternalSort(RowSource(students()), SortSpec.descending("age"))
    empty = ExternalSort(RowSource(students()), SortSpec())

    assert ascending.ordering == ColumnReference("age", "rows")
    assert ascending.ordered is True
    assert descending.ordering is None
    assert empty.ordering is None


def test_the_sort_descriptor_reports_real_runs_and_passes():
    random.seed(19)
    data = [(random.randrange(50), f"row-{n}") for n in range(400)]
    operator = ExternalSort(
        RowSource(pairs(data)),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    collect(operator, limit=500)
    details = dict(operator.describe().details)

    assert details["initial_runs"] == str(operator.metrics.initial_runs)
    assert details["merge_passes"] == str(operator.metrics.merge_passes)
    assert details["fan_in"] == str(operator.fan_in)
    assert "key ASC" in details["order"]


def test_external_sort_validates_its_construction_arguments():
    source = RowSource(students())

    with pytest.raises(InvalidTypeError, match="ExecutionOperator child"):
        ExternalSort(object(), SortSpec.ascending("age"))
    with pytest.raises(InvalidTypeError, match="requires a SortSpec"):
        ExternalSort(source, "age")
    with pytest.raises(ValidationError, match="at least"):
        ExternalSort(source, SortSpec.ascending("age"), memory_budget_bytes=1024)
    with pytest.raises(ValidationError, match="max_fan_in"):
        ExternalSort(source, SortSpec.ascending("age"), max_fan_in=1)
    with pytest.raises(InvalidTypeError):
        ExternalSort(source, SortSpec.ascending("age"), max_fan_in="8")
    with pytest.raises(UnknownColumnError):
        ExternalSort(source, SortSpec.ascending("missing"))


def test_sorting_composes_above_a_projection():
    data = [(3, "c"), (1, "a"), (2, "b")]
    plan = ExternalSort(
        Projection(RowSource(pairs(data)), ["label", "key"]),
        SortSpec.ascending("key"),
    )

    rows = collect(plan, limit=10)

    assert values(rows) == [("a", 1), ("b", 2), ("c", 3)]
