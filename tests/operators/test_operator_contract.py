"""Lifecycle/resource examples for the abstract operator boundary only."""

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import DatabaseError, InvalidReferenceError
from engine.storage import Record
from tests.doubles import OperatorDouble, StreamProbe


@pytest.fixture
def rows():
    schema = Schema([Column("id", DataType.INTEGER)])
    return [Record(schema, [number]) for number in range(3)]


def test_operator_closed_open_exhausted_closed_and_reopened_states(rows):
    probe = StreamProbe()
    operator = OperatorDouble(lambda: probe.stream(rows))
    assert operator.close() is None  # Safe before the first open.
    with pytest.raises(RuntimeError):
        operator.next()
    for run in range(2):
        assert operator.open() is None
        try:
            assert operator.next() == rows[0]
            with pytest.raises(RuntimeError, match="already open"):
                operator.open()
            assert operator.next() == rows[1]  # Failed open did not restart the run.
            assert operator.next() == rows[2]
            assert operator.next() is None
            assert operator.next() is None
            with pytest.raises(RuntimeError):
                operator.open()  # An exhausted operator remains open until close.
        finally:
            operator.close()
        assert operator.close() is None
        with pytest.raises(RuntimeError):
            operator.next()
        assert probe.active == 0
        assert probe.opened == probe.closed == run + 1


@pytest.mark.parametrize("empty_record", [False, True])
def test_operator_distinguishes_empty_input_from_an_empty_schema_record(empty_record):
    rows = [Record(Schema([]), [])] if empty_record else []
    probe = StreamProbe()
    operator = OperatorDouble(lambda: probe.stream(rows))
    try:
        operator.open()
        if empty_record:
            assert operator.next() == rows[0]
        assert operator.next() is None
        assert operator.next() is None
    finally:
        operator.close()
    assert probe.active == 0
    assert probe.opened == probe.closed == 1


@pytest.mark.parametrize("exit_mode", ["exhausted", "early", "consumer_error", "source_error"])
def test_operator_cleanup_and_domain_error_propagation(rows, exit_mode):
    marker = InvalidReferenceError("injected missing RID")
    probe = StreamProbe()
    if exit_mode == "source_error":
        probe.fail_after, probe.error = 1, marker
    operator = OperatorDouble(lambda: probe.stream(rows))

    def consume():
        try:
            operator.open()
            assert operator.next() == rows[0]
            if exit_mode == "consumer_error":
                raise marker
            if exit_mode != "early":
                while operator.next() is not None:
                    pass
        finally:
            operator.close()

    if exit_mode.endswith("error"):
        with pytest.raises(DatabaseError) as caught:
            consume()
        assert caught.value is marker
        assert isinstance(caught.value, KeyError)
    else:
        consume()
    assert probe.active == 0
    assert probe.opened == probe.closed == 1
    operator.close()
    with pytest.raises(RuntimeError):
        operator.next()


def test_execution_error_requires_close_before_reuse(rows):
    marker = InvalidReferenceError("missing row")
    probe = StreamProbe(fail_after=0, error=marker)
    operator = OperatorDouble(lambda: probe.stream(rows))
    try:
        operator.open()
        with pytest.raises(InvalidReferenceError) as caught:
            operator.next()
        assert caught.value is marker
        with pytest.raises(RuntimeError):
            operator.next()
        with pytest.raises(RuntimeError):
            operator.open()
    finally:
        operator.close()
    probe.fail_after = None
    try:
        operator.open()
        assert operator.next() == rows[0]
    finally:
        operator.close()
    assert probe.active == 0


@pytest.mark.parametrize("failure_site", ["parent_source", "second_child"])
def test_failed_open_cleans_partially_opened_children(rows, failure_site):
    marker = RuntimeError("open failure")
    opened, closed = [], []

    def tracked_child(name, fail=False):
        def source():
            opened.append(name)
            if fail:
                raise marker
            return StreamProbe().stream(rows)

        child = OperatorDouble(source)
        original_close = child.close

        def close():
            closed.append(name)
            original_close()

        child.close = close
        return child

    first = tracked_child("first")
    second = tracked_child("second", fail=failure_site == "second_child")

    def parent_source():
        raise marker

    parent = OperatorDouble(parent_source, children=(first, second))
    try:
        with pytest.raises(RuntimeError) as caught:
            parent.open()
        assert caught.value is marker
    finally:
        parent.close()
    assert opened == ["first", "second"]
    assert {"first", "second"} <= set(closed)
    for operator in (parent, first, second):
        operator.close()
        with pytest.raises(RuntimeError):
            operator.next()
    # The successfully opened child can be reused after the parent's failure.
    try:
        first.open()
        assert first.next() == rows[0]
    finally:
        first.close()


def test_close_attempts_all_owned_cleanup_even_if_one_child_raises(rows):
    probes = [StreamProbe() for _ in range(3)]
    first = OperatorDouble(lambda: probes[0].stream(rows))
    second = OperatorDouble(lambda: probes[1].stream(rows))
    original_close = second.close
    marker = RuntimeError("child cleanup failure")

    def failing_close():
        original_close()
        raise marker

    second.close = failing_close
    parent = OperatorDouble(lambda: probes[2].stream(rows), children=(first, second))
    parent.open()
    for operator in (first, second, parent):
        assert operator.next() == rows[0]
    assert all(probe.active == 1 for probe in probes)
    with pytest.raises(RuntimeError) as caught:
        parent.close()
    assert caught.value is marker
    assert all(probe.active == 0 and probe.closed == 1 for probe in probes)
    assert parent.close() is None
    with pytest.raises(RuntimeError):
        parent.next()
