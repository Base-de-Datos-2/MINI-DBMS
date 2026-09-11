"""Tasks 6.17 and 6.18: aggregate state and the bounded hash-group kernel."""

import math

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.operators import (
    Avg,
    Count,
    CountColumn,
    ExecutionContext,
    HashGroupKernel,
    Max,
    Min,
    RowLayout,
    Sum,
)
from engine.operators.aggregation import GROUP_ENTRY_OVERHEAD_BYTES
from engine.storage.binary import INTEGER_MAX
from engine.storage import Record


NUMBERS = Schema(
    [
        Column("group", DataType.VARCHAR),
        Column("whole", DataType.INTEGER),
        Column("real", DataType.FLOAT),
    ]
)
LAYOUT = RowLayout(NUMBERS, relation="numbers")


def row(group, whole, real):
    return Record(NUMBERS, [group, whole, real])


def fold(aggregate, rows):
    bound = aggregate.bind(LAYOUT)
    state = bound.initialize()
    for record in rows:
        state = bound.accumulate(state, record.values)
    return bound.finalize(state)


def test_count_counts_every_row_and_publishes_an_integer():
    bound = Count().bind(LAYOUT)

    assert bound.output_type is DataType.INTEGER
    assert fold(Count(), [row("a", 1, 1.0)] * 5) == 5
    assert fold(Count(), []) == 0
    assert Count().alias == "count"
    assert Count(alias="total").alias == "total"


def test_count_column_validates_its_column_and_matches_count_star():
    rows = [row("a", 1, 1.0), row("a", 2, 2.0)]

    assert fold(CountColumn("whole"), rows) == fold(Count(), rows) == 2
    assert CountColumn("whole").alias == "count_whole"
    assert CountColumn("whole").column.name == "whole"
    with pytest.raises(UnknownColumnError):
        CountColumn("missing").bind(LAYOUT)


def test_sum_keeps_its_column_type_and_handles_negatives():
    rows = [row("a", 5, 2.5), row("a", -8, -1.25), row("a", 3, 0.0)]

    assert fold(Sum("whole"), rows) == 0
    assert Sum("whole").bind(LAYOUT).output_type is DataType.INTEGER
    assert fold(Sum("real"), rows) == pytest.approx(1.25)
    assert Sum("real").bind(LAYOUT).output_type is DataType.FLOAT
    assert fold(Sum("whole"), []) == 0
    assert fold(Sum("real"), []) == 0.0


def test_sum_refuses_to_leave_the_signed_64_bit_range():
    rows = [row("a", INTEGER_MAX, 0.0), row("a", 1, 0.0)]

    with pytest.raises(ValidationError, match="signed 64-bit"):
        fold(Sum("whole"), rows)


def test_sum_and_average_reject_non_numeric_columns():
    for aggregate in (Sum("group"), Avg("group")):
        with pytest.raises(ValidationError, match="requires a numeric column"):
            aggregate.bind(LAYOUT)


def test_extremes_work_on_every_supported_type_and_reject_empty_input():
    rows = [row("b", 5, 2.5), row("a", -8, -1.25), row("c", 3, 0.0)]

    assert fold(Min("whole"), rows) == -8
    assert fold(Max("whole"), rows) == 5
    assert fold(Min("group"), rows) == "a"
    assert fold(Max("group"), rows) == "c"
    assert fold(Min("real"), rows) == -1.25

    for aggregate in (Min("whole"), Max("whole")):
        with pytest.raises(ValidationError, match="undefined over an empty input"):
            fold(aggregate, [])


def test_average_divides_a_total_by_a_count_and_is_always_a_float():
    rows = [row("a", 1, 1.0), row("a", 2, 2.0), row("a", 4, 4.0)]
    bound = Avg("whole").bind(LAYOUT)

    assert bound.output_type is DataType.FLOAT
    assert fold(Avg("whole"), rows) == pytest.approx(7 / 3)
    assert isinstance(fold(Avg("whole"), rows), float)
    with pytest.raises(ValidationError, match="undefined over an empty input"):
        fold(Avg("whole"), [])


def test_average_merges_totals_and_counts_never_averages_of_averages():
    bound = Avg("whole").bind(LAYOUT)
    left = bound.initialize()
    for value in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        left = bound.accumulate(left, ("a", value, 0.0))
    right = bound.accumulate(bound.initialize(), ("a", 100, 0.0))

    merged = bound.finalize(bound.merge(left, right))
    naive = (bound.finalize(left) + bound.finalize(right)) / 2

    assert merged == pytest.approx(145 / 10)
    assert merged != pytest.approx(naive)


@pytest.mark.parametrize(
    "aggregate", [Count(), Sum("whole"), Sum("real"), Min("whole"), Max("group"),
                  Avg("whole")]
)
def test_merging_partial_states_agrees_with_one_pass(aggregate):
    rows = [row(f"g{n}", n - 5, float(n) / 4) for n in range(12)]
    bound = aggregate.bind(LAYOUT)

    single = bound.initialize()
    for record in rows:
        single = bound.accumulate(single, record.values)

    left = bound.initialize()
    for record in rows[:5]:
        left = bound.accumulate(left, record.values)
    right = bound.initialize()
    for record in rows[5:]:
        right = bound.accumulate(right, record.values)

    combined = bound.finalize(bound.merge(left, right))
    expected = bound.finalize(single)
    if isinstance(expected, float):
        assert math.isclose(combined, expected, rel_tol=1e-12)
    else:
        assert combined == expected


def test_merging_an_extreme_tolerates_an_empty_side():
    bound = Max("whole").bind(LAYOUT)
    empty = bound.initialize()
    filled = bound.accumulate(bound.initialize(), ("a", 7, 0.0))

    assert bound.finalize(bound.merge(empty, filled)) == 7
    assert bound.finalize(bound.merge(filled, empty)) == 7


def test_aggregates_validate_their_arguments():
    with pytest.raises(ValidationError, match="alias"):
        Count(alias="  ")
    with pytest.raises(InvalidTypeError):
        Sum(7)
    with pytest.raises(InvalidTypeError, match="RowLayout"):
        Count().bind(NUMBERS)


def kernel(context, aggregates, *, keys=("group",)):
    fields = [LAYOUT.field(name) for name in keys]
    return HashGroupKernel(
        context,
        key_positions=[field.position for field in fields],
        key_types=[field.data_type for field in fields],
        aggregates=[aggregate.bind(LAYOUT) for aggregate in aggregates],
    )


def test_the_kernel_aggregates_groups_and_agrees_with_an_oracle():
    rows = [row(f"g{n % 4}", n, float(n)) for n in range(40)]

    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context, [Count(), Sum("whole")])
        for record in rows:
            assert engine.admit(record) is True
        results = dict(engine.results())

    assert len(results) == 4
    assert results[("g0",)] == (10, sum(n for n in range(40) if n % 4 == 0))


def test_one_group_with_many_rows_uses_constant_memory():
    rows = [row("hot", n, 0.0) for n in range(5000)]

    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context, [Count(), Sum("whole"), Avg("whole")])
        for record in rows:
            assert engine.admit(record) is True
        after_one = engine.reserved_bytes

        assert engine.group_count == 1
        assert after_one < GROUP_ENTRY_OVERHEAD_BYTES * 4
        assert dict(engine.results())[("hot",)][0] == 5000


def test_memory_follows_distinct_groups_not_input_rows():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context, [Count()])
        engine.admit(row("a", 1, 0.0))
        one_group = engine.reserved_bytes
        for _ in range(100):
            engine.admit(row("a", 1, 0.0))
        assert engine.reserved_bytes == one_group

        engine.admit(row("b", 1, 0.0))
        assert engine.reserved_bytes > one_group
        assert engine.group_count == 2


def test_capacity_exhaustion_is_explicit_and_does_not_consume_the_row():
    budget = 12237
    with ExecutionContext(memory_budget_bytes=budget) as context:
        engine = kernel(context, [Count()])
        admitted = 0
        rejected = None
        for number in range(10_000):
            record = row(f"g{number}", number, 0.0)
            if engine.admit(record):
                admitted += 1
            else:
                rejected = record
                break

        assert rejected is not None
        assert engine.group_count == admitted
        # The refused row left no trace: its key never became a group.
        assert (rejected.values[0],) not in dict(engine.results())
        assert context.available_bytes < GROUP_ENTRY_OVERHEAD_BYTES * 4


def test_collisions_are_resolved_by_full_key_equality():
    schema = Schema([Column("k", DataType.VARCHAR), Column("n", DataType.INTEGER)])
    layout = RowLayout(schema)
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = HashGroupKernel(
            context,
            key_positions=[0],
            key_types=[DataType.VARCHAR],
            aggregates=[Count().bind(layout)],
        )
        for value in ("Aa", "BB", "Aa", "BB", "BB"):
            engine.admit(Record(schema, [value, 1]))

        results = dict(engine.results())

    # "Aa" and "BB" share a Python string hash in some builds; full equality
    # must still keep them apart.
    assert results == {("Aa",): (2,), ("BB",): (3,)}


def test_composite_keys_group_on_the_complete_tuple():
    fields = [LAYOUT.field("group"), LAYOUT.field("whole")]
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = HashGroupKernel(
            context,
            key_positions=[field.position for field in fields],
            key_types=[field.data_type for field in fields],
            aggregates=[Count().bind(LAYOUT)],
        )
        for record in [row("a", 1, 0.0), row("a", 2, 0.0), row("a", 1, 0.0)]:
            engine.admit(record)

        assert dict(engine.results()) == {("a", 1): (2,), ("a", 2): (1,)}


def test_signed_zero_groups_together_and_nan_is_refused():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context, [Count()], keys=("real",))
        engine.admit(row("a", 1, 0.0))
        engine.admit(row("a", 1, -0.0))

        assert engine.group_count == 1
        with pytest.raises(ValidationError, match="NaN"):
            engine.admit(row("a", 1, float("nan")))


def test_a_released_kernel_returns_its_memory_and_refuses_further_work():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context, [Count()])
        engine.admit(row("a", 1, 0.0))
        assert context.reserved_bytes > 0

        engine.release()
        engine.release()

        assert context.reserved_bytes == 0
        with pytest.raises(RuntimeError, match="released group kernel"):
            engine.admit(row("a", 1, 0.0))
        with pytest.raises(RuntimeError, match="released group kernel"):
            list(engine.results())


def test_kernel_arguments_are_validated():
    with pytest.raises(InvalidTypeError, match="ExecutionContext"):
        HashGroupKernel(object(), key_positions=[0], key_types=[], aggregates=[])
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        with pytest.raises(ValidationError, match="needs a data type"):
            HashGroupKernel(
                context, key_positions=[0, 1], key_types=[DataType.VARCHAR],
                aggregates=[],
            )
        engine = kernel(context, [Count()])
        with pytest.raises(InvalidTypeError, match="requires a Record"):
            engine.admit(("a", 1, 0.0))
