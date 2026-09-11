"""Task 6.30: differential, semantic, and resource stress tests.

Oracle policy, as ETAPA_06 requires: every expected result comes from plain
test-only loops, dictionaries and ``sorted`` over deliberately bounded
fixtures. Unordered results are compared as multisets with ``Counter`` (never
as sets, which would hide duplicate occurrences); explicitly ordered results
are compared as sequences. No external DBMS or dataframe library is used.
"""

from collections import Counter, defaultdict
import random

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InsufficientBudgetError
from engine.indexes import UnclusteredBPlusIndex, UnclusteredHashIndex
from engine.operators import (
    Avg,
    ColumnReference,
    Count,
    ExecutionContext,
    ExternalHashGroup,
    ExternalSort,
    Filter,
    GraceHashJoin,
    IndexScan,
    JoinSpec,
    Literal,
    Max,
    Min,
    NestedLoopJoin,
    Projection,
    SortSpec,
    Sum,
    TableScan,
    collect,
    run_plan,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.join import MINIMUM_JOIN_BUDGET_BYTES
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.storage import HeapFile, PagedSequentialFile, Record
from tests.operator_helpers import RowSource


ITEMS = Schema(
    [Column("key", DataType.INTEGER), Column("label", DataType.VARCHAR)]
)
OTHER = Schema(
    [Column("key", DataType.INTEGER), Column("note", DataType.VARCHAR)]
)

# Three valid budgets from the smallest legal grant to a comfortable one. A
# result that changes across them would mean memory pressure altered meaning.
BUDGETS = [MINIMUM_SORT_BUDGET_BYTES, 16 * 4096, 64 * 4096]


def shape(name, size, seed=0):
    """Build one of the required data distributions as (key, label) pairs."""

    rng = random.Random(seed)
    if name == "empty":
        return []
    if name == "one":
        return [(1, "only")]
    if name == "uniform":
        return [(rng.randrange(size // 4 + 1), f"u{n}") for n in range(size)]
    if name == "sorted":
        return [(n // 3, f"s{n}") for n in range(size)]
    if name == "reverse":
        return [((size - n) // 3, f"r{n}") for n in range(size)]
    if name == "dominant":
        return [(0 if n % 10 else n, f"d{n}") for n in range(size)]
    if name == "all_one_key":
        return [(42, f"a{n}") for n in range(size)]
    if name == "duplicates":
        return [(n % 5, "same") for n in range(size)]
    if name == "wide":
        return [(rng.randrange(40), "x" * rng.randrange(1, 600)) for _ in range(size)]
    raise AssertionError(name)


SHAPES = [
    "empty", "one", "uniform", "sorted", "reverse", "dominant",
    "all_one_key", "duplicates", "wide",
]


def rows_of(pairs, schema=ITEMS):
    return [Record(schema, list(pair)) for pair in pairs]


def multiset(rows):
    return Counter(tuple(row.values) for row in rows)


@pytest.mark.parametrize("budget", BUDGETS)
@pytest.mark.parametrize("name", SHAPES)
def test_external_sort_matches_a_stable_oracle_for_every_shape(name, budget):
    pairs = shape(name, 700, seed=1)
    operator = ExternalSort(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        SortSpec.ascending("key"),
        memory_budget_bytes=budget,
        max_fan_in=MINIMUM_FAN_IN,
    )

    output = [tuple(row.values) for row in collect(operator, limit=1000)]

    # ``sorted`` is stable, so equal keys keep input order, exactly the
    # documented ExternalSort contract: a sequence comparison, not a multiset.
    assert output == sorted(pairs, key=lambda pair: pair[0])


@pytest.mark.parametrize("budget", [MINIMUM_GROUP_BUDGET_BYTES, 16 * 4096, 64 * 4096])
@pytest.mark.parametrize("name", SHAPES)
def test_external_grouping_matches_a_dictionary_oracle_for_every_shape(name, budget):
    pairs = shape(name, 700, seed=2)
    operator = ExternalHashGroup(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        ["key"],
        [Count(), Sum("key"), Min("label"), Max("label")],
        memory_budget_bytes=budget,
        partition_count=2,
    )

    output = multiset(collect(operator, limit=1000))

    groups = defaultdict(list)
    for key, label in pairs:
        groups[key].append(label)
    expected = Counter(
        (key, len(labels), key * len(labels), min(labels), max(labels))
        for key, labels in groups.items()
    )
    assert output == expected


@pytest.mark.parametrize("budget", [MINIMUM_JOIN_BUDGET_BYTES, 16 * 4096, 64 * 4096])
@pytest.mark.parametrize("name", ["empty", "one", "uniform", "dominant",
                                  "all_one_key", "duplicates", "wide"])
def test_grace_join_matches_a_loop_oracle_for_every_shape(name, budget):
    left_pairs = shape(name, 150, seed=3)
    right_pairs = [(key, f"o{n}") for n, (key, _) in enumerate(shape(name, 90, seed=4))]
    operator = GraceHashJoin(
        RowSource(rows_of(left_pairs), relation="items", schema=ITEMS),
        RowSource(rows_of(right_pairs, OTHER), relation="other", schema=OTHER),
        JoinSpec.on(("key", "key")),
        memory_budget_bytes=budget,
        partition_count=2,
    )

    output = multiset(collect(operator, limit=100_000))

    expected = Counter(
        (lk, ll, rk, rn)
        for lk, ll in left_pairs
        for rk, rn in right_pairs
        if lk == rk
    )
    assert output == expected


@pytest.mark.parametrize("name", SHAPES)
def test_results_are_independent_of_the_valid_memory_budget(name):
    pairs = shape(name, 600, seed=5)

    def pipeline(budget):
        root = ExternalSort(
            ExternalHashGroup(
                Filter(RowSource(rows_of(pairs), relation="items", schema=ITEMS),
                       Literal(True)),
                ["key"],
                [Count(), Avg("key")],
                memory_budget_bytes=budget,
                partition_count=2,
            ),
            SortSpec.ascending("key"),
            memory_budget_bytes=budget,
            max_fan_in=MINIMUM_FAN_IN,
        )
        rows, _ = run_plan(root, memory_budget_bytes=4 * budget, limit=1000)
        return [tuple(row.values) for row in rows]

    results = [pipeline(budget) for budget in BUDGETS]

    assert results[0] == results[1] == results[2]


def test_the_baseline_and_optimized_joins_agree_under_every_budget():
    rng = random.Random(6)
    left_pairs = [(rng.randrange(60), f"l{n}") for n in range(400)]
    right_pairs = [(rng.randrange(60), f"r{n}") for n in range(300)]
    spec = JoinSpec.on(("key", "key"))

    baseline = multiset(collect(
        NestedLoopJoin(
            RowSource(rows_of(left_pairs), relation="items", schema=ITEMS),
            RowSource(rows_of(right_pairs, OTHER), relation="other", schema=OTHER),
            spec,
        ),
        limit=100_000,
    ))
    for budget in (MINIMUM_JOIN_BUDGET_BYTES, 16 * 4096, 64 * 4096):
        optimized = multiset(collect(
            GraceHashJoin(
                RowSource(rows_of(left_pairs), relation="items", schema=ITEMS),
                RowSource(rows_of(right_pairs, OTHER), relation="other", schema=OTHER),
                spec,
                memory_budget_bytes=budget,
                partition_count=2,
            ),
            limit=100_000,
        ))
        assert optimized == baseline


def test_every_storage_organization_yields_the_same_multiset(tmp_path):
    pairs = shape("uniform", 500, seed=7)
    heap_path = tmp_path / "items.heap"
    bplus_path = tmp_path / "items.bpt"
    hash_path = tmp_path / "items.hsh"
    with HeapFile.create(heap_path, ITEMS) as heap, PagedSequentialFile.create(
        tmp_path / "items.seq", ITEMS, "key"
    ) as sequential:
        for record in rows_of(pairs):
            heap.insert(record)
            sequential.insert(record)
        with UnclusteredBPlusIndex.build(
            bplus_path, heap=heap, index_name="ix", table_name="items",
            key_column="key",
        ), UnclusteredHashIndex.build(
            hash_path, heap=heap, index_name="hx", table_name="items",
            key_column="key",
        ):
            pass
        sequential_rows = multiset(
            collect(TableScan(sequential, relation="items"), limit=1000)
        )

    fresh = Schema(list(ITEMS.columns))
    with HeapFile.open(heap_path, fresh) as heap:
        with UnclusteredBPlusIndex.open(bplus_path, heap=heap) as bplus, \
                UnclusteredHashIndex.open(hash_path, heap=heap) as hashed:
            heap_rows = multiset(collect(TableScan(heap, relation="items"), limit=1000))
            range_rows = multiset(
                collect(IndexScan.between(bplus, relation="items"), limit=1000)
            )
            probe = next(iter(Counter(key for key, _ in pairs)))
            by_bplus = multiset(
                collect(IndexScan.equality(bplus, probe, relation="items"), limit=1000)
            )
            by_hash = multiset(
                collect(IndexScan.equality(hashed, probe, relation="items"), limit=1000)
            )

    expected = Counter(pairs)
    assert heap_rows == sequential_rows == range_rows == expected
    assert by_bplus == by_hash == Counter(
        pair for pair in pairs if pair[0] == probe
    )


def test_hard_gate_sort_forces_more_runs_than_fan_in_and_two_passes():
    pairs = shape("uniform", 3000, seed=8)
    operator = ExternalSort(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        SortSpec.ascending("key"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    collect(operator, limit=4000)

    assert operator.metrics.initial_runs > operator.fan_in
    assert operator.metrics.merge_passes >= 2
    assert operator.metrics.rows_spilled == len(pairs)


def test_hard_gate_grouping_forces_group_states_beyond_the_grant():
    pairs = [(n % 500, f"g{n}") for n in range(3000)]
    operator = ExternalHashGroup(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        ["key"],
        [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2,
    )

    output = collect(operator, limit=1000)

    assert len(output) == 500
    assert operator.metrics.kernel_overflows > 0
    assert operator.metrics.repartitions > 0
    assert operator.metrics.partitions_written > 2


def test_hard_gate_grace_join_uses_real_partitions_not_only_its_kernel():
    rng = random.Random(9)
    left_pairs = [(rng.randrange(200), f"l{n}") for n in range(2000)]
    right_pairs = [(rng.randrange(200), f"r{n}") for n in range(2000)]
    operator = GraceHashJoin(
        RowSource(rows_of(left_pairs), relation="items", schema=ITEMS),
        RowSource(rows_of(right_pairs, OTHER), relation="other", schema=OTHER),
        JoinSpec.on(("key", "key")),
        memory_budget_bytes=16 * 4096,
        partition_count=8,
    )

    collect(operator, limit=100_000)
    metrics = operator.metrics

    assert metrics.partition_pairs > 1
    assert metrics.pairs_joined_by_hash > 0
    assert metrics.temporary_pages_written > 0
    assert metrics.left_rows_partitioned == metrics.right_rows_partitioned == 2000


def test_hard_gate_skew_fallbacks_terminate_for_grouping_and_joins(monkeypatch):
    monkeypatch.setattr(
        "engine.operators.partitioning.partition_hash",
        lambda values, data_types, *, level=0: 0,
    )
    pairs = [(n % 300, f"k{n}") for n in range(900)]
    grouping = ExternalHashGroup(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        ["key"], [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES, partition_count=2,
    )
    joining = GraceHashJoin(
        RowSource(rows_of(pairs), relation="items", schema=ITEMS),
        RowSource(rows_of(pairs[:300], OTHER), relation="other", schema=OTHER),
        JoinSpec.on(("key", "key")),
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=2,
    )

    grouped = collect(grouping, limit=1000)
    joined = collect(joining, limit=100_000)

    assert len(grouped) == 300
    assert grouping.metrics.fallback_partitions > 0
    assert len(joined) == 900
    assert joining.metrics.fallback_pairs > 0


def test_hard_gate_complete_pipeline_peaks_stay_within_the_grant():
    rng = random.Random(10)
    left_pairs = [(rng.randrange(150), f"l{n}") for n in range(1500)]
    right_pairs = [(rng.randrange(150), f"r{n}") for n in range(600)]
    root = ExternalSort(
        ExternalHashGroup(
            GraceHashJoin(
                RowSource(rows_of(left_pairs), relation="items", schema=ITEMS),
                RowSource(rows_of(right_pairs, OTHER), relation="other",
                          schema=OTHER),
                JoinSpec.on(("key", "key")),
                partition_count=4,
            ),
            [ColumnReference("key", "items")],
            [Count()],
            partition_count=4,
        ),
        SortSpec.ascending("key"),
    )
    budget = 256 * 4096

    rows, report = run_plan(root, memory_budget_bytes=budget, max_open_handles=12,
                            limit=1000)

    expected = Counter(key for key, _ in left_pairs for rk, _ in right_pairs if key == rk)
    assert [tuple(row.values) for row in rows] == sorted(expected.items())
    assert report.peak_reserved_bytes <= budget
    assert report.peak_open_handles <= 12
    assert report.reservations_refused == 0


def test_a_below_minimum_budget_is_refused_for_every_blocking_operator():
    source = RowSource(rows_of(shape("uniform", 10)), relation="items", schema=ITEMS)

    for build in (
        lambda: ExternalSort(source, SortSpec.ascending("key"), memory_budget_bytes=4096),
        lambda: ExternalHashGroup(source, ["key"], [Count()], memory_budget_bytes=4096),
        lambda: GraceHashJoin(source, RowSource([], relation="o", schema=OTHER),
                              JoinSpec.on(("key", "key")), memory_budget_bytes=4096),
    ):
        with pytest.raises(InsufficientBudgetError):
            build()


def test_a_fresh_execution_after_an_exception_produces_correct_results():
    pairs = shape("uniform", 400, seed=11)
    failing = RowSource(rows_of(pairs), relation="items", schema=ITEMS, fail_at=200)
    operator = ExternalSort(failing, SortSpec.ascending("key"),
                            memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES)

    with pytest.raises(ValueError, match="injected row failure"):
        collect(operator, limit=500)

    failing.fail_at = None
    output = [tuple(row.values) for row in collect(operator, limit=500)]

    assert output == sorted(pairs, key=lambda pair: pair[0])


def test_projection_over_a_join_never_collapses_duplicate_occurrences():
    pairs = [(1, "same")] * 4
    others = [(1, "same")] * 5
    root = Projection(
        GraceHashJoin(
            RowSource(rows_of(pairs), relation="items", schema=ITEMS),
            RowSource(rows_of(others, OTHER), relation="other", schema=OTHER),
            JoinSpec.on(("key", "key")),
        ),
        ["label"],
    )

    output = collect(root, limit=100)

    # A set would report one row; the bag has twenty identical occurrences.
    assert multiset(output) == Counter({("same",): 20})
