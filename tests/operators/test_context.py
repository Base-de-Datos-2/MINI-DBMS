"""Task 6.5: execution context, memory accounting and handle limits."""

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.operators import (
    DEFAULT_BUDGET_BYTES,
    MINIMUM_BUDGET_BYTES,
    ROW_OVERHEAD_BYTES,
    ExecutionContext,
    row_footprint_bytes,
    value_footprint_bytes,
)
from engine.storage import Record
from tests.operator_helpers import STUDENTS


def test_value_footprint_matches_the_version_one_encoded_widths():
    assert value_footprint_bytes(DataType.INTEGER, 5) == 8
    assert value_footprint_bytes(DataType.FLOAT, 1.5) == 8
    assert value_footprint_bytes(DataType.BOOLEAN, True) == 1
    assert value_footprint_bytes(DataType.VARCHAR, "abc") == 4 + 3
    assert value_footprint_bytes(DataType.VARCHAR, "ñ") == 4 + 2
    with pytest.raises(InvalidTypeError):
        value_footprint_bytes(DataType.VARCHAR, 3)
    with pytest.raises(InvalidTypeError):
        value_footprint_bytes("INTEGER", 3)


def test_row_footprint_adds_the_declared_bookkeeping_overhead():
    record = Record(STUDENTS, [1, "Ana", "CS", 22])
    payload = 8 + (4 + 3) + (4 + 2) + 8

    assert row_footprint_bytes(record) == payload + ROW_OVERHEAD_BYTES
    with pytest.raises(InvalidTypeError):
        row_footprint_bytes((1, "Ana"))


def test_context_grants_releases_and_reports_peak_accounted_memory():
    with ExecutionContext(memory_budget_bytes=8192, label="q") as context:
        assert context.memory_budget_bytes == 8192
        assert context.available_bytes == 8192

        first = context.reserve(3000, "sort")
        second = context.reserve(2000, "group")
        assert context.reserved_bytes == 5000
        assert context.peak_reserved_bytes == 5000

        second.release()
        assert context.reserved_bytes == 3000
        assert context.peak_reserved_bytes == 5000
        assert second.bytes == 0
        assert second.released is True

        second.release()
        assert context.reserved_bytes == 3000

        first.release()
        assert context.available_bytes == 8192
        assert context.statistics.reservations_granted == 2


def test_a_refused_reservation_claims_nothing_and_is_counted():
    with ExecutionContext(memory_budget_bytes=8192) as context:
        held = context.reserve(8000, "sort")

        with pytest.raises(ValidationError, match="cannot reserve"):
            context.reserve(1000, "group")

        assert context.reserved_bytes == 8000
        assert context.statistics.reservations_refused == 1
        held.release()
        assert context.reserved_bytes == 0


def test_reservations_grow_and_shrink_within_the_budget():
    with ExecutionContext(memory_budget_bytes=8192) as context:
        reservation = context.reserve(1000, "runs")
        reservation.grow(1000)
        assert context.reserved_bytes == 2000

        reservation.shrink(500)
        assert context.reserved_bytes == 1500
        assert reservation.bytes == 1500

        with pytest.raises(ValidationError):
            reservation.shrink(5000)
        with pytest.raises(ValidationError):
            reservation.grow(100000)

        reservation.release()
        with pytest.raises(RuntimeError):
            reservation.grow(10)
        with pytest.raises(RuntimeError):
            reservation.shrink(10)


def test_reserving_one_row_refuses_a_row_wider_than_the_whole_budget():
    wide = Record(STUDENTS, [1, "x" * 6000, "CS", 22])

    with ExecutionContext(memory_budget_bytes=MINIMUM_BUDGET_BYTES) as context:
        with pytest.raises(ValidationError, match="a single row needs"):
            context.reserve_row(wide)

        narrow = Record(STUDENTS, [1, "Ana", "CS", 22])
        reservation = context.reserve_row(narrow)
        assert reservation.bytes == row_footprint_bytes(narrow)
        reservation.release()


def test_a_tiny_budget_below_the_documented_minimum_is_rejected_up_front():
    with pytest.raises(ValidationError, match="at least"):
        ExecutionContext(memory_budget_bytes=MINIMUM_BUDGET_BYTES - 1)
    with pytest.raises(InvalidTypeError):
        ExecutionContext(memory_budget_bytes="8192")
    with pytest.raises(ValidationError):
        ExecutionContext(memory_budget_bytes=DEFAULT_BUDGET_BYTES, max_open_handles=0)
    with pytest.raises(ValidationError):
        ExecutionContext(label=" ")


def test_nested_contexts_cannot_promise_the_same_bytes_twice():
    with ExecutionContext(memory_budget_bytes=4 * MINIMUM_BUDGET_BYTES) as parent:
        sorting = parent.child(2 * MINIMUM_BUDGET_BYTES, label="sort")

        assert parent.reserved_bytes == 2 * MINIMUM_BUDGET_BYTES
        assert sorting.memory_budget_bytes == 2 * MINIMUM_BUDGET_BYTES
        assert parent.statistics.children_created == 1

        grouping = parent.child(MINIMUM_BUDGET_BYTES, label="group")
        assert parent.available_bytes == MINIMUM_BUDGET_BYTES

        with pytest.raises(ValidationError, match="cannot reserve"):
            parent.child(2 * MINIMUM_BUDGET_BYTES, label="join")

        grouping.close()
        assert parent.available_bytes == 2 * MINIMUM_BUDGET_BYTES
        sorting.close()
        assert parent.available_bytes == 4 * MINIMUM_BUDGET_BYTES


def test_a_nested_budget_below_the_minimum_is_refused_without_claiming_bytes():
    with ExecutionContext(memory_budget_bytes=4 * MINIMUM_BUDGET_BYTES) as parent:
        with pytest.raises(ValidationError, match="at least"):
            parent.child(MINIMUM_BUDGET_BYTES - 1, label="tiny")

        assert parent.reserved_bytes == 0


def test_closing_a_parent_closes_its_children_and_returns_every_byte():
    parent = ExecutionContext(memory_budget_bytes=4 * MINIMUM_BUDGET_BYTES)
    child = parent.child(MINIMUM_BUDGET_BYTES, label="nested")
    child.reserve(100, "state")

    parent.close()

    assert parent.closed is True
    assert child.closed is True
    assert parent.reserved_bytes == 0
    parent.close()

    with pytest.raises(RuntimeError, match="closed"):
        parent.reserve(10, "late")


def test_handles_are_bounded_independently_from_bytes():
    with ExecutionContext(
        memory_budget_bytes=DEFAULT_BUDGET_BYTES, max_open_handles=2
    ) as context:
        first = context.acquire_handle("run")
        second = context.acquire_handle("run")

        assert context.open_handle_count == 2
        assert context.available_bytes == DEFAULT_BUDGET_BYTES

        with pytest.raises(ValidationError, match="handle limit"):
            context.acquire_handle("run")

        first.release()
        first.release()
        third = context.acquire_handle("run")
        assert context.statistics.peak_open_handles == 2
        assert context.statistics.handles_opened == 3
        second.release()
        third.release()
        assert context.open_handle_count == 0


def test_reservations_and_handles_release_through_with_blocks():
    with ExecutionContext(memory_budget_bytes=8192) as context:
        with context.reserve(1000, "scoped") as reservation:
            assert context.reserved_bytes == 1000
        assert reservation.released is True
        assert context.reserved_bytes == 0

        with context.acquire_handle("scoped") as lease:
            assert context.open_handle_count == 1
        assert lease.released is True
        assert context.open_handle_count == 0


def test_reservation_arguments_are_validated_before_any_byte_is_claimed():
    with ExecutionContext(memory_budget_bytes=8192) as context:
        with pytest.raises(InvalidTypeError):
            context.reserve("100", "sort")
        with pytest.raises(ValidationError):
            context.reserve(-1, "sort")
        with pytest.raises(ValidationError):
            context.reserve(100, " ")
        with pytest.raises(ValidationError):
            context.acquire_handle("")

        assert context.reserved_bytes == 0
        assert context.open_handle_count == 0
