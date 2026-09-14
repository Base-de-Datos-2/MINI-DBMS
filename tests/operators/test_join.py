"""Tasks 6.22-6.25: nested-loop baseline, hash kernel, Grace join and skew."""

from contextlib import closing
import random

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.operators import (
    ColumnReference,
    Compare,
    ComparisonOperator,
    ExecutionContext,
    GraceHashJoin,
    HashJoinKernel,
    JoinKey,
    JoinSpec,
    NestedLoopJoin,
    Projection,
    RowSpool,
    TableScan,
    TemporaryWorkspace,
    collect,
    column,
    execute,
)
from engine.operators.join import MINIMUM_JOIN_BUDGET_BYTES
from engine.operators.partitioning import partition_hash
from engine.storage import HeapFile, Record
from tests.operator_helpers import RowSource


STUDENTS = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)
ENROLLMENTS = Schema(
    [Column("id", DataType.INTEGER), Column("course", DataType.VARCHAR)]
)
ON_ID = JoinSpec.on(("id", "id"))


def left_rows(pairs):
    return [Record(STUDENTS, list(pair)) for pair in pairs]


def right_rows(pairs):
    return [Record(ENROLLMENTS, list(pair)) for pair in pairs]


def left(pairs):
    return RowSource(left_rows(pairs), relation="students", schema=STUDENTS)


def right(pairs):
    return RowSource(right_rows(pairs), relation="enrollments", schema=ENROLLMENTS)


def values(rows):
    return sorted(tuple(row.values) for row in rows)


def both_joins(left_pairs, right_pairs, **kwargs):
    """Build the baseline and the optimized join over the same inputs."""

    return (
        NestedLoopJoin(left(left_pairs), right(right_pairs), ON_ID),
        GraceHashJoin(left(left_pairs), right(right_pairs), ON_ID, **kwargs),
    )


class OnceOnly(RowSource):
    """An inner producer that refuses to be opened a second time."""

    __slots__ = ()

    def _open(self) -> None:
        if self.opens:
            raise RuntimeError("this producer cannot be rewound")
        super()._open()


def test_join_spec_binds_both_sides_and_requires_one_type_per_pair():
    positions_left, positions_right, types = ON_ID.bind(
        left([]).layout, right([]).layout
    )

    assert positions_left == (0,)
    assert positions_right == (0,)
    assert types == (DataType.INTEGER,)

    mismatched = JoinSpec.on(("id", "course"))
    with pytest.raises(ValidationError, match="Cannot join INTEGER with VARCHAR"):
        mismatched.bind(left([]).layout, right([]).layout)


def test_join_spec_construction_is_validated():
    assert JoinSpec.using("id").keys == (JoinKey("id", "id"),)
    assert JoinSpec.on(JoinKey("id", "id")).keys[0].left == ColumnReference("id")

    with pytest.raises(ValidationError, match="at least one equality pair"):
        JoinSpec([])
    with pytest.raises(InvalidTypeError, match="must be a JoinKey"):
        JoinSpec(["id"])
    with pytest.raises(InvalidTypeError, match="left, right"):
        JoinSpec.on("id")
    with pytest.raises(InvalidTypeError, match="sequence of JoinKey"):
        JoinSpec("id")
    with pytest.raises(UnknownColumnError):
        JoinSpec.using("missing").bind(left([]).layout, right([]).layout)


@pytest.mark.parametrize("index", [0, 1])
def test_both_joins_publish_qualified_columns_from_both_inputs(index):
    operator = both_joins([(1, "Ana")], [(1, "BD2")])[index]

    assert [c.name for c in operator.output_schema] == [
        "students.id",
        "name",
        "enrollments.id",
        "course",
    ]
    assert operator.layout.resolve(ColumnReference("id", "students")) == 0
    assert operator.layout.resolve(ColumnReference("id", "enrollments")) == 2
    assert values(collect(operator, limit=5)) == [(1, "Ana", 1, "BD2")]


@pytest.mark.parametrize("index", [0, 1])
def test_an_empty_side_produces_no_pairs(index):
    assert collect(both_joins([], [(1, "BD2")])[index], limit=5) == ()
    assert collect(both_joins([(1, "Ana")], [])[index], limit=5) == ()
    assert collect(both_joins([], [])[index], limit=5) == ()


@pytest.mark.parametrize("index", [0, 1])
def test_no_matching_keys_produce_no_pairs(index):
    operator = both_joins([(1, "Ana"), (2, "Luis")], [(8, "BD2"), (9, "SO")])[index]

    assert collect(operator, limit=5) == ()


@pytest.mark.parametrize("index", [0, 1])
def test_every_row_matching_produces_the_full_cross_product(index):
    operator = both_joins([(1, "a"), (1, "b")], [(1, "x"), (1, "y")])[index]

    rows = collect(operator, limit=20)

    assert len(rows) == 4
    assert values(rows) == [
        (1, "a", 1, "x"),
        (1, "a", 1, "y"),
        (1, "b", 1, "x"),
        (1, "b", 1, "y"),
    ]


@pytest.mark.parametrize("index", [0, 1])
def test_example_c_preserves_join_multiplicity(index):
    """ETAPA_06 section 11, example C: 2 left and 3 right matches give 6 rows."""

    operator = both_joins(
        [(7, "a"), (7, "b"), (9, "c")],
        [(7, "x"), (7, "y"), (7, "z"), (10, "w")],
    )[index]

    rows = collect(operator, limit=50)

    assert len(rows) == 6
    assert all(row.values[0] == 7 and row.values[2] == 7 for row in rows)


def test_projected_identical_looking_rows_are_still_six_occurrences():
    operator = GraceHashJoin(
        left([(7, "same"), (7, "same")]),
        right([(7, "same"), (7, "same"), (7, "same")]),
        ON_ID,
    )
    plan = Projection(operator, [ColumnReference("id", "students")])

    rows = collect(plan, limit=50)

    assert len(rows) == 6
    assert {tuple(row.values) for row in rows} == {(7,)}


@pytest.mark.parametrize("index", [0, 1])
def test_one_to_many_and_many_to_many_multiplicity(index):
    one_to_many = both_joins([(1, "a")], [(1, "x"), (1, "y"), (1, "z")])[index]
    many_to_many = both_joins(
        [(1, "a"), (1, "b"), (2, "c")], [(1, "x"), (1, "y"), (2, "z"), (2, "w")]
    )[index]

    assert len(collect(one_to_many, limit=10)) == 3
    assert len(collect(many_to_many, limit=20)) == 2 * 2 + 1 * 2


@pytest.mark.parametrize("index", [0, 1])
def test_a_composite_key_joins_on_the_complete_tuple(index):
    schema_left = Schema(
        [Column("a", DataType.INTEGER), Column("b", DataType.VARCHAR)]
    )
    schema_right = Schema(
        [Column("a", DataType.INTEGER), Column("b", DataType.VARCHAR),
         Column("tag", DataType.VARCHAR)]
    )
    outer = RowSource(
        [Record(schema_left, [1, "x"]), Record(schema_left, [1, "y"])],
        relation="l",
    )
    inner = RowSource(
        [Record(schema_right, [1, "x", "hit"]), Record(schema_right, [1, "z", "miss"])],
        relation="r",
    )
    spec = JoinSpec.on(("a", "a"), ("b", "b"))
    operator = (
        NestedLoopJoin(outer, inner, spec)
        if index == 0
        else GraceHashJoin(outer, inner, spec)
    )

    rows = collect(operator, limit=10)

    assert len(rows) == 1
    assert rows[0].values[4] == "hit"


@pytest.mark.parametrize("index", [0, 1])
def test_a_residual_predicate_filters_matched_pairs(index):
    residual = Compare(
        column(ColumnReference("course", "enrollments")),
        ComparisonOperator.EQUAL,
        "BD2",
    )
    operator = (
        NestedLoopJoin(
            left([(1, "Ana")]), right([(1, "BD2"), (1, "SO")]), ON_ID,
            residual=residual,
        )
        if index == 0
        else GraceHashJoin(
            left([(1, "Ana")]), right([(1, "BD2"), (1, "SO")]), ON_ID,
            residual=residual,
        )
    )

    rows = collect(operator, limit=10)

    assert len(rows) == 1
    assert rows[0].values[3] == "BD2"


def test_a_non_boolean_residual_is_rejected_when_the_plan_is_built():
    with pytest.raises(ValidationError, match="residual must be BOOLEAN"):
        GraceHashJoin(
            left([]), right([]), ON_ID,
            residual=column(ColumnReference("id", "students")),
        )
    with pytest.raises(InvalidTypeError, match="residual must be an Expression"):
        NestedLoopJoin(left([]), right([]), ON_ID, residual=True)


def test_the_baseline_spools_a_non_rewindable_inner_producer():
    inner = OnceOnly(right_rows([(1, "x"), (1, "y")]), relation="enrollments")
    operator = NestedLoopJoin(left([(1, "a"), (1, "b")]), inner, ON_ID, block_rows=1)

    rows = collect(operator, limit=10)

    assert len(rows) == 4
    assert inner.opens == 1
    assert operator.metrics.inner_passes == 2
    assert operator.metrics.inner_rows_spooled == 2


@pytest.mark.parametrize("block_rows", [1, 2, 50])
def test_block_size_changes_passes_but_never_the_result(block_rows):
    pairs = [(number % 5, f"n{number}") for number in range(40)]
    courses = [(number % 5, f"c{number}") for number in range(20)]
    operator = NestedLoopJoin(
        left(pairs), right(courses), ON_ID, block_rows=block_rows
    )

    rows = collect(operator, limit=1000)
    expected = NestedLoopJoin(left(pairs), right(courses), ON_ID, block_rows=1)

    assert values(rows) == values(collect(expected, limit=1000))
    assert operator.metrics.inner_passes == -(-40 // block_rows)


def test_the_baseline_streams_and_closes_on_early_termination():
    inner = right([(1, "x")] * 10)
    operator = NestedLoopJoin(left([(1, "a")] * 10), inner, ON_ID)

    with closing(execute(operator)) as stream:
        assert next(stream) is not None
        directory = operator._workspace.directory
        assert directory.exists()

    assert not directory.exists()
    assert inner.closes == 1


def test_the_baseline_reports_itself_as_a_baseline_not_an_optimization():
    operator = NestedLoopJoin(left([(1, "a")]), right([(1, "x")]), ON_ID)
    collect(operator, limit=5)

    details = dict(operator.describe().details)

    assert "nested loop" in details["strategy"]
    assert details["inner"] == "spooled temporary stream"
    assert "hash" not in details["strategy"]


def kernel(context, **kwargs):
    return HashJoinKernel(
        context,
        build_positions=[0],
        probe_positions=[0],
        key_types=[DataType.INTEGER],
        **kwargs,
    )


def test_the_kernel_stores_every_build_occurrence_of_a_key():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context)
        for name in ("a", "b", "c"):
            assert engine.admit_build(Record(STUDENTS, [1, name])) is True

        matches = list(engine.probe(Record(ENROLLMENTS, [1, "x"])))

        assert [row.values[1] for row in matches] == ["a", "b", "c"]
        assert engine.build_rows == 3
        assert engine.key_count == 1


def test_the_kernel_returns_nothing_for_a_nonmatching_probe():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context)
        engine.admit_build(Record(STUDENTS, [1, "a"]))

        assert list(engine.probe(Record(ENROLLMENTS, [2, "x"]))) == []


def test_the_kernel_reports_overflow_before_any_output_exists():
    with ExecutionContext(memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES) as context:
        engine = kernel(context)
        admitted = 0
        for number in range(10_000):
            if engine.admit_build(Record(STUDENTS, [number, f"n{number}"])):
                admitted += 1
            else:
                break

        assert 0 < admitted < 10_000
        assert engine.build_rows == admitted
        assert context.available_bytes < 400


def test_the_kernel_memory_is_released_and_refuses_later_work():
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        engine = kernel(context)
        engine.admit_build(Record(STUDENTS, [1, "a"]))
        assert engine.reserved_bytes > 0

        engine.release()
        engine.release()

        assert context.reserved_bytes == 0
        with pytest.raises(RuntimeError, match="released join kernel"):
            engine.admit_build(Record(STUDENTS, [1, "a"]))
        with pytest.raises(RuntimeError, match="released join kernel"):
            list(engine.probe(Record(ENROLLMENTS, [1, "x"])))


def test_kernel_arguments_are_validated():
    with pytest.raises(InvalidTypeError, match="ExecutionContext"):
        HashJoinKernel(object(), build_positions=[0], probe_positions=[0],
                       key_types=[DataType.INTEGER])
    with ExecutionContext(memory_budget_bytes=64 * 4096) as context:
        with pytest.raises(ValidationError, match="matching type"):
            HashJoinKernel(context, build_positions=[0, 1], probe_positions=[0],
                           key_types=[DataType.INTEGER])
        with pytest.raises(InvalidTypeError, match="requires a Record"):
            kernel(context).admit_build((1, "a"))


def test_grace_join_partitions_inputs_far_beyond_its_memory_grant():
    random.seed(31)
    outer = [(random.randrange(300), f"n{n}") for n in range(3000)]
    inner = [(random.randrange(300), f"c{n}") for n in range(3000)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=16 * 4096, partition_count=8,
    )

    rows = collect(operator, limit=200_000)
    metrics = operator.metrics

    baseline = NestedLoopJoin(left(outer), right(inner), ON_ID)

    assert values(rows) == values(collect(baseline, limit=200_000))
    assert metrics.left_rows_partitioned == 3000
    assert metrics.right_rows_partitioned == 3000
    assert metrics.partition_pairs > 1
    assert metrics.pairs_joined_by_hash > 0
    assert metrics.fallback_pairs == 0
    assert metrics.temporary_pages_written > 0
    assert metrics.temporary_pages_read > 0


def test_grace_join_repartitions_an_oversized_pair_on_both_sides():
    random.seed(32)
    outer = [(random.randrange(200), f"n{n}") for n in range(2000)]
    inner = [(random.randrange(200), f"c{n}") for n in range(2000)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=12 * 4096, partition_count=4,
    )

    rows = collect(operator, limit=200_000)
    baseline = NestedLoopJoin(left(outer), right(inner), ON_ID)

    assert values(rows) == values(collect(baseline, limit=200_000))
    assert operator.metrics.build_overflows > 0
    assert operator.metrics.repartitions > 0
    assert operator.metrics.deepest_level >= 1


def test_grace_join_swaps_the_build_side_towards_the_smaller_partition():
    outer = [(number % 4, f"n{number}") for number in range(400)]
    inner = [(number % 4, f"c{number}") for number in range(8)]
    operator = GraceHashJoin(left(outer), right(inner), ON_ID)

    rows = collect(operator, limit=5000)

    assert len(rows) == 400 * 8 // 4
    assert operator.metrics.build_side_swaps > 0
    # Swapping the physical build side must not reorder the output columns.
    assert all(row.values[1].startswith("n") for row in rows)
    assert all(row.values[3].startswith("c") for row in rows)


def test_a_partition_without_a_counterpart_is_released_without_reading_it():
    # Pick keys that demonstrably route to different partitions, so one side
    # really has an index the other never fills.
    buckets = {}
    for key in range(200):
        index = partition_hash((key,), (DataType.INTEGER,), level=0) % 4
        buckets.setdefault(index, []).append(key)
    first, second = sorted(buckets)[:2]

    operator = GraceHashJoin(
        left([(key, f"n{key}") for key in buckets[first]]),
        right([(key, f"c{key}") for key in buckets[second]]),
        ON_ID,
        partition_count=4,
    )

    rows = collect(operator, limit=100)

    assert rows == ()
    assert operator.metrics.pairs_skipped_empty == 2
    assert operator.metrics.partition_pairs == 0


def test_all_rows_sharing_one_key_produce_exactly_m_times_n_pairs():
    outer = [(7, f"n{number}") for number in range(40)]
    inner = [(7, f"c{number}") for number in range(30)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=2,
    )

    rows = collect(operator, limit=5000)

    assert len(rows) == 40 * 30
    assert len({tuple(row.values) for row in rows}) == 40 * 30


def test_a_small_counterpart_saves_a_skewed_pair_from_any_fallback():
    """Choosing the smaller build side handles skew when one side is small."""

    operator = GraceHashJoin(
        left([(7, f"n{number}") for number in range(300)]),
        right([(7, f"c{number}") for number in range(20)]),
        ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES,
        partition_count=2,
    )

    rows = collect(operator, limit=20_000)

    assert len(rows) == 300 * 20
    assert operator.metrics.build_side_swaps == 1
    assert operator.metrics.fallback_pairs == 0


def test_an_unsplittable_skewed_pair_falls_back_and_says_so():
    # Both sides are far larger than the grant and share one key, so no hash
    # can separate them while keeping equal keys co-located.
    outer = [(7, f"n{number}") for number in range(300)]
    inner = [(7, f"c{number}") for number in range(300)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=2,
        max_level=1,
    )

    rows = collect(operator, limit=200_000)
    metrics = operator.metrics

    assert len(rows) == 300 * 300
    assert metrics.build_overflows > 0
    assert metrics.fallback_pairs > 0
    assert metrics.fallback_rows > 0
    assert dict(operator.describe().details)["nested_loop_fallbacks"] != "0"


def test_distinct_keys_under_a_constant_hash_still_join_correctly(monkeypatch):
    monkeypatch.setattr(
        "engine.operators.partitioning.partition_hash",
        lambda values, data_types, *, level=0: 0,
    )
    outer = [(number % 50, f"n{number}") for number in range(400)]
    inner = [(number % 50, f"c{number}") for number in range(200)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=2,
    )

    rows = collect(operator, limit=50_000)
    baseline = NestedLoopJoin(left(outer), right(inner), ON_ID)

    assert values(rows) == values(collect(baseline, limit=50_000))
    assert operator.metrics.fallback_pairs > 0


def test_early_stop_during_a_large_result_cleans_up_and_bounds_memory():
    outer = [(7, f"n{number}") for number in range(200)]
    inner = [(7, f"c{number}") for number in range(200)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=2,
    )

    with ExecutionContext(memory_budget_bytes=256 * 4096) as context:
        stream = execute(operator, context)
        with closing(stream):
            for _ in range(5):
                assert next(stream) is not None
            directory = operator._workspace.directory
            assert directory.exists()
            assert context.reserved_bytes <= MINIMUM_JOIN_BUDGET_BYTES

        assert not directory.exists()
        assert context.reserved_bytes == 0


def test_handle_and_memory_peaks_stay_within_the_grant():
    random.seed(33)
    outer = [(random.randrange(100), f"n{n}") for n in range(1000)]
    inner = [(random.randrange(100), f"c{n}") for n in range(1000)]
    operator = GraceHashJoin(
        left(outer), right(inner), ON_ID,
        memory_budget_bytes=12 * 4096, partition_count=4,
    )

    with ExecutionContext(
        memory_budget_bytes=256 * 4096, max_open_handles=8
    ) as context:
        collect(operator, context, limit=200_000)

        assert context.statistics.peak_reserved_bytes <= 12 * 4096
        assert context.statistics.peak_open_handles <= 8
        assert context.open_handle_count == 0


def test_a_fan_out_beyond_the_granted_budget_is_refused_at_open():
    operator = GraceHashJoin(
        left([(1, "a")]), right([(1, "x")]), ON_ID,
        memory_budget_bytes=MINIMUM_JOIN_BUDGET_BYTES, partition_count=8,
    )

    with pytest.raises(ValidationError, match="needs more than the granted"):
        collect(operator, limit=10)


def test_joins_advertise_no_ordering():
    operator = GraceHashJoin(left([(1, "a")]), right([(1, "x")]), ON_ID)

    assert operator.ordering is None
    assert operator.ordered is False

    baseline = NestedLoopJoin(left([(1, "a")]), right([(1, "x")]), ON_ID)
    assert baseline.ordering is None


def test_spooled_baseline_does_not_report_another_rows_rid_as_provenance(tmp_path):
    with HeapFile.create(tmp_path / "left.heap", STUDENTS) as left_storage:
        with HeapFile.create(tmp_path / "right.heap", ENROLLMENTS) as right_storage:
            for record in left_rows([(1, "a"), (1, "b"), (1, "c")]):
                left_storage.insert(record)
            right_storage.insert(Record(ENROLLMENTS, [1, "course"]))

            join = NestedLoopJoin(
                TableScan(left_storage, relation="students"),
                TableScan(right_storage, relation="enrollments"),
                ON_ID,
                block_rows=1,
            )
            join.open()
            try:
                assert join.next() is not None
                assert join.provenance == ()
            finally:
                join.close()


def test_joins_run_twice_from_one_plan_object():
    for operator in both_joins([(1, "a")], [(1, "x"), (1, "y")]):
        first = values(collect(operator, limit=10))
        second = values(collect(operator, limit=10))

        assert first == second
        assert len(first) == 2
        assert operator.statistics.runs == 2


def test_a_failing_input_cleans_up_both_sides():
    outer = RowSource(left_rows([(n, f"n{n}") for n in range(200)]), fail_at=150,
                      relation="students")
    inner = right([(1, "x")])
    operator = GraceHashJoin(outer, inner, ON_ID)

    with pytest.raises(ValueError, match="injected row failure"):
        collect(operator, limit=500)

    assert outer.closes == 1
    assert inner.closes == 1
    assert operator._workspace is None


def test_join_construction_is_validated():
    with pytest.raises(InvalidTypeError, match="ExecutionOperator inputs"):
        GraceHashJoin(object(), right([]), ON_ID)
    with pytest.raises(InvalidTypeError, match="requires a JoinSpec"):
        GraceHashJoin(left([]), right([]), "id")
    with pytest.raises(ValidationError, match="at least"):
        GraceHashJoin(left([]), right([]), ON_ID, memory_budget_bytes=1024)
    with pytest.raises(ValidationError, match="at least two partitions"):
        GraceHashJoin(left([]), right([]), ON_ID, partition_count=1)
    with pytest.raises(ValidationError, match="max_level"):
        GraceHashJoin(left([]), right([]), ON_ID, max_level=0)
    with pytest.raises(ValidationError, match="block_rows"):
        NestedLoopJoin(left([]), right([]), ON_ID, block_rows=0)
    with pytest.raises(InvalidTypeError):
        NestedLoopJoin(left([]), right([]), ON_ID, block_rows="2")


def test_a_spool_is_filled_once_and_re_read_many_times(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        spool = RowSpool(workspace, ENROLLMENTS, label="inner")
        rows = iter(right_rows([(1, "x"), (2, "y")]))
        spool.fill(lambda: next(rows, None))

        assert spool.row_count == 2
        for _ in range(3):
            reader = spool.reader()
            with reader:
                assert reader.next_row().values == (1, "x")

        with pytest.raises(RuntimeError, match="only be filled once"):
            spool.fill(lambda: None)

        path = spool.run.path
        spool.close()
        spool.close()
        assert not path.exists()


def test_an_unfilled_spool_has_nothing_to_read(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        spool = RowSpool(workspace, ENROLLMENTS)

        with pytest.raises(RuntimeError, match="unfilled spool"):
            spool.reader()
