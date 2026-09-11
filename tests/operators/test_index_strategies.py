"""Task 6.26: optional index-assisted routes and their explicit preconditions."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    UnknownColumnError,
    ValidationError,
)
from engine.indexes import (
    ClusteredBPlusIndex,
    UnclusteredBPlusIndex,
    UnclusteredHashIndex,
)
from engine.operators import (
    ColumnReference,
    Compare,
    ComparisonOperator,
    Count,
    ExternalHashGroup,
    GraceHashJoin,
    IndexNestedLoopJoin,
    IndexOrderedGroup,
    JoinSpec,
    Max,
    Min,
    NestedLoopJoin,
    Sum,
    TableScan,
    collect,
    column,
    execute,
)
from engine.storage import HeapFile, PagedSequentialFile, Record


STUDENTS = Schema(
    [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
)
ENROLLMENTS = Schema(
    [Column("eid", DataType.INTEGER), Column("student_id", DataType.INTEGER)]
)
ON_STUDENT = JoinSpec.on(("student_id", "id"))


@pytest.fixture
def heap(tmp_path):
    with HeapFile.create(tmp_path / "students.heap", STUDENTS) as storage:
        for number in range(60):
            storage.insert(Record(STUDENTS, [number % 20, f"n{number}"]))
        yield storage


@pytest.fixture
def enrollments(tmp_path):
    with HeapFile.create(tmp_path / "enrollments.heap", ENROLLMENTS) as storage:
        for number in range(90):
            storage.insert(Record(ENROLLMENTS, [number, number % 25]))
        yield storage


@pytest.fixture
def bplus(tmp_path, heap):
    with UnclusteredBPlusIndex.build(
        tmp_path / "students.bpt", heap=heap, index_name="ix_students_id",
        table_name="students", key_column="id",
    ) as index:
        yield index


@pytest.fixture
def hash_index(tmp_path, heap):
    with UnclusteredHashIndex.build(
        tmp_path / "students.hsh", heap=heap, index_name="hx_students_id",
        table_name="students", key_column="id",
    ) as index:
        yield index


@pytest.fixture
def name_index(tmp_path, heap):
    with UnclusteredBPlusIndex.build(
        tmp_path / "students-name.bpt", heap=heap, index_name="ix_students_name",
        table_name="students", key_column="name",
    ) as index:
        yield index


def values(rows):
    return sorted(tuple(row.values) for row in rows)


def _enrollment_counts():
    """Occurrences of each student_id in the enrollments fixture."""

    counts = {}
    for number in range(90):
        student_id = number % 25
        counts[student_id] = counts.get(student_id, 0) + 1
    return counts


def test_the_index_join_agrees_with_both_independent_join_routes(
    heap, enrollments, bplus
):
    outer = TableScan(enrollments, relation="enrollments")
    indexed = IndexNestedLoopJoin(outer, bplus, ON_STUDENT, relation="students")
    baseline = NestedLoopJoin(
        TableScan(enrollments, relation="enrollments"),
        TableScan(heap, relation="students"),
        ON_STUDENT,
    )
    grace = GraceHashJoin(
        TableScan(enrollments, relation="enrollments"),
        TableScan(heap, relation="students"),
        ON_STUDENT,
    )

    indexed_rows = values(collect(indexed, limit=10_000))

    # 60 students hold ids 0-19 three times each; 90 enrollments hold ids
    # 0-24, so only ids 0-19 match and each contributes its own multiplicity.
    expected_pairs = sum(
        enrollments_per_id * 3
        for student_id, enrollments_per_id in _enrollment_counts().items()
        if student_id < 20
    )

    assert indexed_rows == values(collect(baseline, limit=10_000))
    assert indexed_rows == values(collect(grace, limit=10_000))
    assert len(indexed_rows) == expected_pairs == 225


@pytest.mark.parametrize("index_name", ["bplus", "hash_index"])
def test_both_index_families_serve_equality_probes(
    request, heap, enrollments, index_name
):
    index = request.getfixturevalue(index_name)
    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), index, ON_STUDENT,
        relation="students",
    )

    rows = collect(operator, limit=10_000)

    assert len(rows) > 0
    assert operator.metrics.index_probes == 90
    assert operator.metrics.outer_rows == 90
    assert operator.metrics.inner_rows_fetched == len(rows)


def test_the_metrics_show_the_index_was_really_probed(heap, enrollments, bplus):
    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), bplus, ON_STUDENT,
        relation="students",
    )

    collect(operator, limit=10_000)
    details = dict(operator.describe().details)

    assert details["strategy"] == "index nested loop"
    assert details["index"] == "UnclusteredBPlusIndex"
    assert details["index_probes"] == "90"
    unmatched = sum(
        count
        for student_id, count in _enrollment_counts().items()
        if student_id >= 20
    )
    assert operator.metrics.probes_without_match == unmatched == 15
    assert operator.metrics.pairs_emitted == 225
    assert operator.index is bplus


def test_the_index_join_preserves_full_multiplicity(tmp_path):
    with HeapFile.create(tmp_path / "inner.heap", STUDENTS) as inner, \
            HeapFile.create(tmp_path / "outer.heap", ENROLLMENTS) as outer:
        for name in ("x", "y", "z"):
            inner.insert(Record(STUDENTS, [7, name]))
        for number in range(2):
            outer.insert(Record(ENROLLMENTS, [number, 7]))
        outer.insert(Record(ENROLLMENTS, [9, 8]))

        with UnclusteredBPlusIndex.build(
            tmp_path / "inner.bpt", heap=inner, index_name="ix",
            table_name="students", key_column="id",
        ) as index:
            operator = IndexNestedLoopJoin(
                TableScan(outer, relation="enrollments"), index, ON_STUDENT,
                relation="students",
            )
            rows = collect(operator, limit=100)

    assert len(rows) == 2 * 3
    assert operator.metrics.probes_without_match == 1


def test_the_index_join_publishes_qualified_columns_and_provenance(
    heap, enrollments, bplus
):
    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), bplus, ON_STUDENT,
        relation="students",
    )

    assert [c.name for c in operator.output_schema] == [
        "eid", "student_id", "id", "name",
    ]
    operator.open()
    try:
        operator.next()
        origins = operator.provenance
        assert [origin.relation for origin in origins] == [
            "enrollments",
            "students",
        ]
        assert heap.read(origins[1].rid).values[0] == 0
    finally:
        operator.close()


def test_a_residual_predicate_filters_index_matches(heap, enrollments, bplus):
    residual = Compare(
        column(ColumnReference("name", "students")),
        ComparisonOperator.EQUAL,
        "n0",
    )
    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), bplus, ON_STUDENT,
        relation="students", residual=residual,
    )

    rows = collect(operator, limit=1000)

    assert all(row.values[3] == "n0" for row in rows)
    assert operator.metrics.inner_rows_fetched > len(rows)


def test_an_empty_outer_input_probes_nothing(tmp_path, heap, bplus):
    with HeapFile.create(tmp_path / "empty.heap", ENROLLMENTS) as empty:
        operator = IndexNestedLoopJoin(
            TableScan(empty, relation="enrollments"), bplus, ON_STUDENT,
            relation="students",
        )

        assert collect(operator, limit=10) == ()
        assert operator.metrics.index_probes == 0


def test_a_stale_association_is_reported_by_the_index_join(
    heap, enrollments, bplus
):
    with closing(heap.scan()) as cursor:
        target = next(rid for rid, record in cursor if record.values[0] == 0)
    heap.delete(target)

    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), bplus, ON_STUDENT,
        relation="students",
    )

    with pytest.raises(InvalidReferenceError):
        collect(operator, limit=10_000)


def test_the_index_join_closes_its_cursor_without_closing_the_index(
    heap, enrollments, bplus
):
    operator = IndexNestedLoopJoin(
        TableScan(enrollments, relation="enrollments"), bplus, ON_STUDENT,
        relation="students",
    )

    with closing(execute(operator)) as stream:
        assert next(stream) is not None

    assert bplus.closed is False
    assert heap.closed is False
    assert len(collect(operator, limit=10_000)) > 0


def test_the_index_join_refuses_an_index_that_covers_another_column(
    heap, enrollments, name_index
):
    with pytest.raises(ValidationError, match="covers 'name', not 'id'"):
        IndexNestedLoopJoin(
            TableScan(enrollments, relation="enrollments"), name_index,
            ON_STUDENT, relation="students",
        )


def test_the_index_join_refuses_a_multi_column_condition(
    heap, enrollments, bplus
):
    spec = JoinSpec.on(("student_id", "id"), ("eid", "id"))

    with pytest.raises(ValidationError, match="one equality column"):
        IndexNestedLoopJoin(
            TableScan(enrollments, relation="enrollments"), bplus, spec,
            relation="students",
        )


def test_the_index_join_refuses_mismatched_key_types(tmp_path, heap, bplus):
    typed = Schema(
        [Column("eid", DataType.INTEGER), Column("student_id", DataType.VARCHAR)]
    )
    with HeapFile.create(tmp_path / "typed.heap", typed) as storage:
        with pytest.raises(ValidationError, match="Cannot join VARCHAR with INTEGER"):
            IndexNestedLoopJoin(
                TableScan(storage, relation="enrollments"), bplus, ON_STUDENT,
                relation="students",
            )


def test_index_join_arguments_are_validated(heap, enrollments, bplus):
    outer = TableScan(enrollments, relation="enrollments")

    with pytest.raises(InvalidTypeError, match="ExecutionOperator outer"):
        IndexNestedLoopJoin(object(), bplus, ON_STUDENT, relation="students")
    with pytest.raises(InvalidTypeError, match="requires an Index"):
        IndexNestedLoopJoin(outer, object(), ON_STUDENT, relation="students")
    with pytest.raises(InvalidTypeError, match="requires a JoinSpec"):
        IndexNestedLoopJoin(outer, bplus, "id", relation="students")
    with pytest.raises(InvalidTypeError, match="residual must be an Expression"):
        IndexNestedLoopJoin(
            outer, bplus, ON_STUDENT, relation="students", residual=True
        )
    with pytest.raises(UnknownColumnError):
        IndexNestedLoopJoin(
            outer, bplus, JoinSpec.on(("missing", "id")), relation="students"
        )


def test_ordered_grouping_agrees_with_external_hash_grouping(heap, bplus):
    indexed = IndexOrderedGroup(
        bplus, ["id"], [Count(), Sum("id"), Min("name"), Max("name")],
        relation="students",
    )
    hashed = ExternalHashGroup(
        TableScan(heap, relation="students"), ["id"],
        [Count(), Sum("id"), Min("name"), Max("name")],
    )

    indexed_rows = {row.values[0]: tuple(row.values[1:]) for row in collect(indexed, limit=100)}
    hashed_rows = {row.values[0]: tuple(row.values[1:]) for row in collect(hashed, limit=100)}

    assert indexed_rows == hashed_rows
    assert len(indexed_rows) == 20


def test_ordered_grouping_emits_groups_already_in_key_order(heap, bplus):
    operator = IndexOrderedGroup(bplus, ["id"], [Count()], relation="students")

    rows = collect(operator, limit=100)

    assert [row.values[0] for row in rows] == sorted(range(20))
    assert operator.ordering == ColumnReference("id", "students")
    assert operator.ordered is True


def test_ordered_grouping_reads_non_indexed_columns_through_storage(heap, bplus):
    operator = IndexOrderedGroup(
        bplus, ["id"], [Min("name"), Max("name")], relation="students"
    )

    rows = collect(operator, limit=100)

    assert rows[0].values == (0, "n0", "n40")
    assert operator.metrics.rows_read == 60


def test_ordered_grouping_verifies_the_index_covers_every_row(tmp_path, heap, bplus):
    heap.insert(Record(STUDENTS, [999, "uncovered"]))

    operator = IndexOrderedGroup(bplus, ["id"], [Count()], relation="students")

    with pytest.raises(ValidationError, match="does not cover the whole table"):
        collect(operator, limit=100)


def test_ordered_grouping_reports_the_counts_it_compared(heap, bplus):
    operator = IndexOrderedGroup(bplus, ["id"], [Count()], relation="students")

    collect(operator, limit=100)

    assert operator.metrics.entry_count == 60
    assert operator.metrics.record_count == 60
    assert operator.metrics.groups_emitted == 20


def test_ordered_grouping_refuses_a_hash_index(heap, hash_index):
    with pytest.raises(ValidationError, match="requires an ordered index"):
        IndexOrderedGroup(hash_index, ["id"], [Count()], relation="students")


def test_ordered_grouping_refuses_an_index_over_another_column(heap, name_index):
    with pytest.raises(ValidationError, match="covers 'name', not 'id'"):
        IndexOrderedGroup(name_index, ["id"], [Count()], relation="students")


def test_ordered_grouping_refuses_a_multi_column_grouping_key(heap, bplus):
    with pytest.raises(ValidationError, match="single-column grouping key"):
        IndexOrderedGroup(bplus, ["id", "name"], [Count()], relation="students")


def test_ordered_grouping_works_over_a_clustered_index(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "ordered.seq", STUDENTS, "id"
    ) as sequential:
        for number in range(40):
            sequential.insert(Record(STUDENTS, [number % 8, f"n{number}"]))

        with ClusteredBPlusIndex.build(
            tmp_path / "ordered.cbt", sequential=sequential,
            index_name="cx", table_name="students", key_column="id",
        ) as clustered:
            operator = IndexOrderedGroup(
                clustered, ["id"], [Count()], relation="students"
            )
            rows = collect(operator, limit=50)

    assert [row.values[0] for row in rows] == list(range(8))
    assert all(row.values[1] == 5 for row in rows)


def test_ordered_grouping_validates_its_arguments(heap, bplus):
    with pytest.raises(InvalidTypeError, match="requires an Index"):
        IndexOrderedGroup(object(), ["id"], [Count()], relation="students")
    with pytest.raises(ValidationError, match="at least one aggregate"):
        IndexOrderedGroup(bplus, ["id"], [], relation="students")
    with pytest.raises(InvalidTypeError, match="must be an Aggregate"):
        IndexOrderedGroup(bplus, ["id"], ["count"], relation="students")
    with pytest.raises(InvalidTypeError, match="group_keys"):
        IndexOrderedGroup(bplus, "id", [Count()], relation="students")


def test_ordered_grouping_over_an_empty_table_emits_nothing(tmp_path):
    with HeapFile.create(tmp_path / "empty.heap", STUDENTS) as storage:
        with UnclusteredBPlusIndex.build(
            tmp_path / "empty.bpt", heap=storage, index_name="ix",
            table_name="students", key_column="id",
        ) as index:
            operator = IndexOrderedGroup(
                index, ["id"], [Count()], relation="students"
            )

            assert collect(operator, limit=10) == ()
            assert operator.metrics.groups_emitted == 0


def test_ordered_grouping_closes_its_cursor_without_closing_the_index(heap, bplus):
    operator = IndexOrderedGroup(bplus, ["id"], [Count()], relation="students")

    with closing(execute(operator)) as stream:
        assert next(stream) is not None

    assert bplus.closed is False
    assert len(collect(operator, limit=100)) == 20
