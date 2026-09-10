"""Tasks 6.9 and 6.10: streaming selection and projection semantics."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidTypeError,
    UnknownColumnError,
    ValidationError,
)
from engine.operators import (
    And,
    BoundExpression,
    ColumnReference,
    Compare,
    ComparisonOperator,
    Expression,
    Filter,
    Literal,
    Projection,
    TableScan,
    collect,
    column,
    execute,
)
from engine.storage import HeapFile, PagedSequentialFile, Record
from tests.operator_helpers import RowSource, STUDENTS, STUDENT_ROWS, students


def values(rows):
    return [tuple(row.values) for row in rows]


@pytest.fixture
def source():
    return RowSource(students(), relation="students")


@pytest.fixture
def heap(tmp_path):
    with HeapFile.create(tmp_path / "students.heap", STUDENTS) as storage:
        for record in students():
            storage.insert(record)
        yield storage


@pytest.fixture
def sequential(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "students.seq", STUDENTS, "id"
    ) as storage:
        for record in students():
            storage.insert(record)
        yield storage


def test_filter_keeps_only_matching_rows_and_preserves_values(source):
    operator = Filter(source, Compare(column("age"), ComparisonOperator.GREATER, 20))

    rows = collect(operator, limit=10)

    assert values(rows) == [
        (1, "Ana", "CS", 22),
        (3, "Sol", "CS", 24),
        (4, "Omar", "EE", 23),
    ]
    assert operator.output_schema is STUDENTS
    assert operator.child is source


def test_filter_matching_all_or_none_of_the_input(source):
    assert len(collect(Filter(source, Literal(True)), limit=10)) == 4
    assert collect(Filter(RowSource(students()), Literal(False)), limit=10) == ()


def test_filter_over_empty_input_emits_nothing():
    operator = Filter(RowSource([]), Literal(True))

    assert collect(operator, limit=5) == ()
    assert operator.statistics.rows_examined == 0


def test_filter_counts_rows_examined_and_emitted_separately(source):
    operator = Filter(source, Compare(column("career"), ComparisonOperator.EQUAL, "CS"))

    collect(operator, limit=10)

    assert operator.statistics.rows_examined == 4
    assert operator.statistics.rows_emitted == 2


def test_filter_never_deduplicates_equal_rows():
    repeated = students([(1, "Ana", "CS", 22)] * 3)
    operator = Filter(RowSource(repeated), Literal(True))

    assert len(collect(operator, limit=10)) == 3


def test_filter_rejects_a_non_boolean_predicate_when_the_plan_is_built(source):
    with pytest.raises(ValidationError, match="must be BOOLEAN"):
        Filter(source, column("age"))
    with pytest.raises(UnknownColumnError):
        Filter(source, Compare(column("missing"), ComparisonOperator.EQUAL, 1))
    with pytest.raises(InvalidTypeError, match="ExecutionOperator child"):
        Filter(object(), Literal(True))
    with pytest.raises(InvalidTypeError, match="Expression predicate"):
        Filter(source, True)


class _BoundExploding(BoundExpression):
    """A predicate that binds cleanly and then fails on the first row."""

    __slots__ = ()

    @property
    def data_type(self):
        return DataType.BOOLEAN

    def evaluate(self, row_values):
        raise ValueError("injected predicate failure")


class Exploding(Expression):
    """Bind successfully so the failure happens mid-stream, not at build time."""

    __slots__ = ()

    def bind(self, layout):
        return _BoundExploding()


def test_a_predicate_failure_fails_the_run_and_still_closes(source):
    operator = Filter(source, Exploding())

    with pytest.raises(ValueError, match="injected predicate failure"):
        list(execute(operator))

    assert source.closes == 1


def test_filter_closes_its_child_when_the_consumer_stops_early(source):
    operator = Filter(source, Literal(True))

    with closing(execute(operator)) as stream:
        assert next(stream) is not None

    assert source.closes == 1


def test_filter_composes_over_both_scan_organizations(heap, sequential):
    predicate = Compare(column("age"), ComparisonOperator.GREATER_OR_EQUAL, 22)

    heap_rows = collect(
        Filter(TableScan(heap, relation="students"), predicate), limit=10
    )
    sequential_rows = collect(
        Filter(TableScan(sequential, relation="students"), predicate), limit=10
    )

    assert sorted(values(heap_rows)) == sorted(values(sequential_rows))
    assert len(heap_rows) == 3


def test_filter_inherits_the_child_ordering_without_inventing_one(heap, sequential):
    over_heap = Filter(TableScan(heap, relation="students"), Literal(True))
    over_sequential = Filter(
        TableScan(sequential, relation="students"), Literal(True)
    )

    assert over_heap.ordering is None
    assert over_sequential.ordering == ColumnReference("id", "students")


def test_filter_forwards_the_provenance_of_the_row_it_emitted(heap):
    operator = Filter(
        TableScan(heap, relation="students"),
        Compare(column("name"), ComparisonOperator.EQUAL, "Sol"),
    )
    operator.open()
    try:
        row = operator.next()
        (origin,) = operator.provenance

        assert origin.relation == "students"
        assert heap.read(origin.rid) == row
    finally:
        operator.close()


def test_projection_selects_subsets_in_the_requested_order(source):
    operator = Projection(source, ["career", "name"])

    rows = collect(operator, limit=10)

    assert [column.name for column in operator.output_schema] == ["career", "name"]
    assert values(rows) == [
        ("CS", "Ana"),
        ("EE", "Luis"),
        ("CS", "Sol"),
        ("EE", "Omar"),
    ]


def test_projection_can_reorder_every_column(source):
    operator = Projection(source, ["age", "career", "name", "id"])

    assert values(collect(operator, limit=10))[0] == (22, "CS", "Ana", 1)


def test_select_all_preserves_the_child_schema_order(source):
    operator = Projection.select_all(source)

    assert [c.name for c in operator.output_schema] == [
        c.name for c in STUDENTS
    ]
    assert values(collect(operator, limit=10)) == list(STUDENT_ROWS)
    with pytest.raises(InvalidTypeError):
        Projection.select_all(object())


def test_projection_applies_aliases_to_the_output_schema(source):
    operator = Projection(source, ["id", "name"], ["student_id", None])

    assert [c.name for c in operator.output_schema] == ["student_id", "name"]
    assert operator.output_schema.column("student_id").data_type is DataType.INTEGER
    assert values(collect(operator, limit=10))[0] == (1, "Ana")


def test_projection_is_not_distinct(source):
    operator = Projection(source, ["career"])

    rows = collect(operator, limit=10)

    assert values(rows) == [("CS",), ("EE",), ("CS",), ("EE",)]
    assert len(rows) == 4


def test_projection_preserves_every_occurrence_of_identical_rows():
    repeated = students([(1, "Ana", "CS", 22)] * 5)
    operator = Projection(RowSource(repeated), ["career"])

    assert len(collect(operator, limit=10)) == 5


def test_projection_rejects_unknown_columns_when_the_plan_is_built(source):
    with pytest.raises(UnknownColumnError):
        Projection(source, ["missing"])
    with pytest.raises(ValidationError, match="same output name twice"):
        Projection(source, ["id", "id"])
    with pytest.raises(InvalidTypeError, match="ExecutionOperator child"):
        Projection(object(), ["id"])


def test_projection_keeps_an_ordering_only_when_its_column_survives(sequential):
    scan = TableScan(sequential, relation="students")

    keeps = Projection(scan, ["id", "name"])
    drops = Projection(TableScan(sequential, relation="students"), ["name", "career"])
    renames = Projection(
        TableScan(sequential, relation="students"), ["id"], ["student_id"]
    )

    assert keeps.ordering == ColumnReference("id", "students")
    assert keeps.ordered is True
    assert drops.ordering is None
    assert renames.ordering is None


def test_a_downstream_operator_rejects_a_key_the_projection_dropped(source):
    projected = Projection(source, ["name", "career"])

    with pytest.raises(UnknownColumnError):
        Filter(projected, Compare(column("age"), ComparisonOperator.GREATER, 20))


def test_projection_works_before_and_after_a_filter(heap):
    predicate = Compare(column("career"), ComparisonOperator.EQUAL, "CS")

    after = Projection(
        Filter(TableScan(heap, relation="students"), predicate), ["name"]
    )
    before = Filter(
        Projection(TableScan(heap, relation="students"), ["name", "career"]),
        predicate,
    )

    assert values(collect(after, limit=10)) == [("Ana",), ("Sol",)]
    assert values(collect(before, limit=10)) == [("Ana", "CS"), ("Sol", "CS")]


def test_projection_forwards_provenance_because_row_identity_is_unchanged(heap):
    operator = Projection(TableScan(heap, relation="students"), ["name"])
    operator.open()
    try:
        operator.next()
        (origin,) = operator.provenance

        assert origin.relation == "students"
        assert heap.read(origin.rid)["name"] == "Ana"
    finally:
        operator.close()


def test_projection_exposes_the_positions_it_reads(source):
    operator = Projection(source, ["age", "id"])

    assert operator.positions == (3, 0)
    assert operator.child is source


def test_projection_to_an_empty_selection_still_emits_one_row_per_input(source):
    operator = Projection(source, [])

    rows = collect(operator, limit=10)

    assert len(rows) == 4
    assert all(row.values == () for row in rows)
    assert len(operator.output_schema) == 0
