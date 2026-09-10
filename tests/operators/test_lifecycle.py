"""Task 6.4: operator lifecycle, ownership, and the streaming run helper."""

from contextlib import closing

import pytest

from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.operators import (
    ExecutionContext,
    ExecutionOperator,
    Operator,
    OperatorDescriptor,
    OperatorState,
    RowLayout,
    collect,
    execute,
)
from engine.storage import Record
from tests.operator_helpers import (
    ENROLLMENTS,
    FailingOpen,
    RowSource,
    STUDENTS,
    students,
)


def test_an_operator_walks_created_open_exhausted_and_closed_states():
    operator = RowSource(students())

    assert operator.state is OperatorState.CREATED
    assert isinstance(operator, Operator)

    operator.open()
    assert operator.state is OperatorState.OPEN
    assert operator.next() is not None

    while operator.next() is not None:
        pass
    assert operator.state is OperatorState.EXHAUSTED
    assert operator.next() is None
    assert operator.next() is None

    operator.close()
    assert operator.state is OperatorState.CLOSED


def test_next_before_open_and_after_close_is_a_lifecycle_error():
    operator = RowSource(students())

    with pytest.raises(RuntimeError, match="open, non-failed run"):
        operator.next()

    operator.open()
    operator.close()

    with pytest.raises(RuntimeError, match="open, non-failed run"):
        operator.next()


def test_opening_an_open_or_exhausted_operator_does_not_restart_its_run():
    operator = RowSource(students())
    operator.open()
    first = operator.next()

    with pytest.raises(RuntimeError, match="already open"):
        operator.open()

    assert operator.next() is not first
    while operator.next() is not None:
        pass

    with pytest.raises(RuntimeError, match="already open"):
        operator.open()

    operator.close()


def test_closing_is_idempotent_before_open_after_close_and_after_failure():
    operator = RowSource(students(), fail_at=1)

    assert operator.close() is None
    operator.open()
    assert operator.next() is not None

    with pytest.raises(ValueError, match="injected row failure"):
        operator.next()
    assert operator.state is OperatorState.FAILED

    with pytest.raises(RuntimeError, match="open, non-failed run"):
        operator.next()

    assert operator.close() is None
    assert operator.close() is None
    assert operator.closes == 1


def test_reopening_after_close_starts_a_new_independent_run():
    operator = RowSource(students())

    for expected_run in (1, 2):
        operator.open()
        try:
            rows = []
            while (row := operator.next()) is not None:
                rows.append(row)
            assert len(rows) == 4
        finally:
            operator.close()
        assert operator.statistics.runs == expected_run
        assert operator.opens == operator.closes == expected_run


def test_a_parent_opens_and_closes_its_children_exactly_once():
    child = RowSource(students())
    parent = RowSource(students(), children=(child,))

    parent.open()
    assert child.state is OperatorState.OPEN
    assert child.opens == 1

    parent.close()
    assert child.state is OperatorState.CLOSED
    assert child.closes == 1


def test_a_failing_open_releases_partially_acquired_children_and_stays_closed():
    child = RowSource(students())
    parent = FailingOpen(children=(child,))

    with pytest.raises(ValueError, match="injected open failure"):
        parent.open()

    assert parent.state is OperatorState.CLOSED
    assert child.state is OperatorState.CLOSED
    assert child.opens == 1
    assert child.closes == 1
    assert parent.closes == 1

    with pytest.raises(RuntimeError):
        parent.next()


def test_a_child_that_fails_while_opening_still_releases_its_siblings():
    first = RowSource(students())
    failing = FailingOpen()
    parent = RowSource(students(), children=(first, failing))

    with pytest.raises(ValueError, match="injected open failure"):
        parent.open()

    assert first.closes == 1
    assert parent.state is OperatorState.CLOSED


def test_empty_input_reports_exhaustion_immediately():
    operator = RowSource([])

    operator.open()
    try:
        assert operator.next() is None
        assert operator.state is OperatorState.EXHAUSTED
    finally:
        operator.close()

    assert operator.statistics.rows_emitted == 0


def test_two_independent_operators_over_one_source_do_not_share_position():
    rows = students()
    first = RowSource(rows)
    second = RowSource(rows)

    first.open()
    second.open()
    try:
        assert first.next().values == second.next().values
        assert first.next().values[0] == 2
        assert second.next().values[0] == 2
    finally:
        first.close()
        second.close()


def test_a_row_that_violates_the_advertised_schema_fails_the_run():
    class WrongSchema(RowSource):
        __slots__ = ()

        def _next(self):
            return Record(ENROLLMENTS, [1, 2, "BD2"])

    operator = WrongSchema(students())
    operator.open()
    try:
        with pytest.raises(SchemaError, match="advertised output schema"):
            operator.next()
        assert operator.state is OperatorState.FAILED
    finally:
        operator.close()


def test_a_non_record_result_fails_instead_of_reaching_the_consumer():
    class NotARecord(RowSource):
        __slots__ = ()

        def _next(self):
            return (1, "Ana", "CS", 22)

    operator = NotARecord(students())
    operator.open()
    try:
        with pytest.raises(InvalidTypeError, match="not a Record"):
            operator.next()
    finally:
        operator.close()


def test_construction_validates_children_and_the_published_layout():
    with pytest.raises(InvalidTypeError, match="children must be a sequence"):
        RowSource(students(), children="child")
    with pytest.raises(InvalidTypeError, match="must be an Operator"):
        RowSource(students(), children=(object(),))

    class NoLayout(ExecutionOperator):
        __slots__ = ()

        def _build_layout(self):
            return STUDENTS

    with pytest.raises(InvalidTypeError, match="must publish a RowLayout"):
        NoLayout()


def test_open_validates_the_context_argument():
    operator = RowSource(students())

    with pytest.raises(InvalidTypeError, match="ExecutionContext"):
        operator.open(object())

    assert operator.state is OperatorState.CREATED


def test_the_context_reaches_children_and_is_released_on_close():
    child = RowSource(students())
    parent = RowSource(students(), children=(child,))

    with ExecutionContext(memory_budget_bytes=8192) as context:
        parent.open(context)
        assert parent.context is context
        assert child.context is context

        parent.close()
        assert parent.context is None
        assert child.context is None


def test_execute_streams_and_closes_on_normal_completion():
    operator = RowSource(students())

    rows = list(execute(operator))

    assert len(rows) == 4
    assert operator.state is OperatorState.CLOSED
    assert operator.closes == 1


def test_execute_closes_when_the_consumer_stops_early():
    operator = RowSource(students())

    with closing(execute(operator)) as stream:
        assert next(stream) is not None

    assert operator.state is OperatorState.CLOSED
    assert operator.closes == 1


def test_execute_closes_when_the_plan_fails_mid_stream():
    operator = RowSource(students(), fail_at=2)

    with pytest.raises(ValueError, match="injected row failure"):
        list(execute(operator))

    assert operator.state is OperatorState.CLOSED


def test_execute_requires_an_operator():
    with pytest.raises(InvalidTypeError, match="requires an Operator"):
        list(execute(object()))


def test_collect_requires_an_explicit_limit_and_never_truncates_silently():
    assert len(collect(RowSource(students()), limit=4)) == 4
    assert collect(RowSource([]), limit=4) == ()

    with pytest.raises(ValidationError, match="more than the requested 2 rows"):
        collect(RowSource(students()), limit=2)
    with pytest.raises(InvalidTypeError):
        collect(RowSource(students()), limit="4")
    with pytest.raises(ValidationError):
        collect(RowSource(students()), limit=-1)

    with pytest.raises(TypeError):
        collect(RowSource(students()), 4)


def test_descriptors_describe_the_real_subtree_and_render_as_text():
    child = RowSource(students())
    parent = RowSource(students(), children=(child,))

    descriptor = parent.describe()

    assert isinstance(descriptor, OperatorDescriptor)
    assert descriptor.name == "RowSource"
    assert len(descriptor.children) == 1
    assert descriptor.children[0].name == "RowSource"
    assert descriptor.render().splitlines() == ["RowSource", "  RowSource"]


def test_an_operator_publishes_a_layout_and_schema_before_its_first_open():
    operator = RowSource(students())

    assert isinstance(operator.layout, RowLayout)
    assert operator.output_schema is STUDENTS
    assert operator.ordering is None
    assert operator.ordered is False
    assert operator.provenance == ()
    assert operator.children == ()
