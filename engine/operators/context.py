"""Query-scoped memory budget, handle limits, and resource statistics."""

from __future__ import annotations

from dataclasses import dataclass

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import (
    BOOLEAN_STRUCT,
    FLOAT_STRUCT,
    INTEGER_STRUCT,
    PAGE_SIZE,
    STRING_ENCODING,
    VARCHAR_LENGTH_STRUCT,
)
from engine.storage.record import Record, RecordValue


#: Conservative per-row bookkeeping charged on top of the encoded payload.
#: Retained rows are decoded Python objects, not packed bytes, so accounting
#: only the payload would understate real working memory. This constant is a
#: declared model, not a measurement of any particular interpreter.
ROW_OVERHEAD_BYTES = 128

#: Smallest budget any blocking operator may be given. Below one page plus a
#: row's worth of overhead no external algorithm can make progress, so the
#: failure is reported up front instead of degrading into unbounded memory.
MINIMUM_BUDGET_BYTES = PAGE_SIZE + ROW_OVERHEAD_BYTES

#: Default working-memory grant for a query that does not choose one.
DEFAULT_BUDGET_BYTES = 64 * PAGE_SIZE

#: Default ceiling on temporary file handles held open at the same time.
DEFAULT_MAX_OPEN_HANDLES = 32

_FIXED_VALUE_BYTES = {
    DataType.INTEGER: INTEGER_STRUCT.size,
    DataType.FLOAT: FLOAT_STRUCT.size,
    DataType.BOOLEAN: BOOLEAN_STRUCT.size,
}


def value_footprint_bytes(data_type: DataType, value: RecordValue) -> int:
    """Return the encoded size one value contributes to a retained row.

    The result matches the version-1 ValueCodec framing so that accounting and
    the temporary-file format cannot drift apart. Nothing is serialized here:
    measuring a VARCHAR only needs its UTF-8 byte length.
    """

    if not isinstance(data_type, DataType):
        raise InvalidTypeError("data_type must be a DataType")
    if data_type is DataType.VARCHAR:
        if type(value) is not str:
            raise InvalidTypeError("VARCHAR footprint requires a str value")
        return VARCHAR_LENGTH_STRUCT.size + len(value.encode(STRING_ENCODING))
    return _FIXED_VALUE_BYTES[data_type]


def row_footprint_bytes(record: Record) -> int:
    """Return the conservative accounted size of retaining one row."""

    if not isinstance(record, Record):
        raise InvalidTypeError("row footprint requires a Record")
    payload = sum(
        value_footprint_bytes(column.data_type, value)
        for column, value in zip(record.schema, record.values)
    )
    return payload + ROW_OVERHEAD_BYTES


@dataclass(slots=True)
class ResourceStatistics:
    """Measured resource use of one execution context.

    Every counter records work that actually happened. Nothing here is an
    estimate, and none of it describes the interpreter's total memory: the
    byte counters only cover memory this context was asked to reserve.
    """

    peak_reserved_bytes: int = 0
    reservations_granted: int = 0
    reservations_refused: int = 0
    bytes_reserved_total: int = 0
    peak_open_handles: int = 0
    handles_opened: int = 0
    children_created: int = 0


class MemoryReservation:
    """A claim on an execution budget, released exactly once.

    Reservations are taken before state is retained or grown, and released
    when the state is spilled, discarded, or the owning operator closes.
    Releasing twice is safe so that ``close`` can run after a ``with`` block
    has already unwound.
    """

    __slots__ = ("_context", "_bytes", "_label", "_released")

    def __init__(self, context: "ExecutionContext", size: int, label: str) -> None:
        self._context = context
        self._bytes = size
        self._label = label
        self._released = False

    @property
    def bytes(self) -> int:
        """Return the currently held byte count; zero once released."""

        return 0 if self._released else self._bytes

    @property
    def label(self) -> str:
        """Return the owner label recorded for diagnostics."""

        return self._label

    @property
    def released(self) -> bool:
        """Report whether this reservation has already been returned."""

        return self._released

    def grow(self, extra: int) -> None:
        """Extend an active reservation, refusing to exceed the budget."""

        if self._released:
            raise RuntimeError("A released reservation cannot grow")
        checked = _validate_size(extra, "Reservation growth")
        self._context._claim(checked)
        self._bytes += checked

    def shrink(self, amount: int) -> None:
        """Return part of an active reservation without releasing it."""

        if self._released:
            raise RuntimeError("A released reservation cannot shrink")
        checked = _validate_size(amount, "Reservation reduction")
        if checked > self._bytes:
            raise ValidationError("Cannot release more bytes than were reserved")
        self._context._return(checked)
        self._bytes -= checked

    def release(self) -> None:
        """Return every held byte to the budget; safe to call repeatedly."""

        if self._released:
            return
        self._released = True
        self._context._return(self._bytes)

    def __enter__(self) -> "MemoryReservation":
        """Return this reservation for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release the reservation on every exit path."""

        self.release()


class HandleLease:
    """A counted permit to keep one temporary file handle open."""

    __slots__ = ("_context", "_label", "_released")

    def __init__(self, context: "ExecutionContext", label: str) -> None:
        self._context = context
        self._label = label
        self._released = False

    @property
    def label(self) -> str:
        """Return the owner label recorded for diagnostics."""

        return self._label

    @property
    def released(self) -> bool:
        """Report whether this lease has already been returned."""

        return self._released

    def release(self) -> None:
        """Return the permit; safe to call repeatedly."""

        if self._released:
            return
        self._released = True
        self._context._return_handle()

    def __enter__(self) -> "HandleLease":
        """Return this lease for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Release the permit on every exit path."""

        self.release()


def _validate_size(value: object, label: str) -> int:
    if type(value) is not int:
        raise InvalidTypeError(f"{label} must be an int")
    if value < 0:
        raise ValidationError(f"{label} must be non-negative")
    return value


class ExecutionContext:
    """The resource boundary shared by every operator of one execution.

    The budget measures *accounted working memory*: bytes this context was
    asked to reserve for retained rows, sort workspace, merge heads, hash
    tables and output buffers. It is deliberately not a guarantee about the
    interpreter's resident set, and it is not enforced by the operating
    system. An operator that never reserves is never bounded, so blocking
    operators must reserve before they retain.

    A nested blocking operator takes a child context carved out of its
    parent's remaining budget. That makes over-commitment impossible: the
    child cannot hand out bytes the parent has already promised elsewhere.
    """

    __slots__ = (
        "_budget",
        "_reserved",
        "_label",
        "_statistics",
        "_max_open_handles",
        "_open_handles",
        "_parent_reservation",
        "_closed",
        "_children",
    )

    def __init__(
        self,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        label: str = "query",
    ) -> None:
        budget = _validate_size(memory_budget_bytes, "Memory budget")
        if budget < MINIMUM_BUDGET_BYTES:
            raise ValidationError(
                f"Memory budget must be at least {MINIMUM_BUDGET_BYTES} bytes"
            )
        handles = _validate_size(max_open_handles, "Handle limit")
        if handles < 1:
            raise ValidationError("Handle limit must allow at least one handle")
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("Context label must be a non-empty string")
        self._budget = budget
        self._reserved = 0
        self._label = label
        self._statistics = ResourceStatistics()
        self._max_open_handles = handles
        self._open_handles = 0
        self._parent_reservation: MemoryReservation | None = None
        self._closed = False
        self._children: list["ExecutionContext"] = []

    @property
    def label(self) -> str:
        """Return the diagnostic name of this context."""

        return self._label

    @property
    def memory_budget_bytes(self) -> int:
        """Return the accounted working-memory grant, not a process limit."""

        return self._budget

    @property
    def reserved_bytes(self) -> int:
        """Return the bytes currently promised to live reservations."""

        return self._reserved

    @property
    def available_bytes(self) -> int:
        """Return the bytes still grantable from this context."""

        return self._budget - self._reserved

    @property
    def peak_reserved_bytes(self) -> int:
        """Return the highest simultaneous reservation seen so far."""

        return self._statistics.peak_reserved_bytes

    @property
    def open_handle_count(self) -> int:
        """Return the number of leased handles currently held."""

        return self._open_handles

    @property
    def max_open_handles(self) -> int:
        """Return the handle ceiling, bounded independently from bytes."""

        return self._max_open_handles

    @property
    def statistics(self) -> ResourceStatistics:
        """Return the measured resource counters of this context."""

        return self._statistics

    @property
    def closed(self) -> bool:
        """Report whether this context has been closed."""

        return self._closed

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("The execution context is closed")

    def _claim(self, size: int) -> None:
        self._require_open()
        if size > self.available_bytes:
            self._statistics.reservations_refused += 1
            raise ValidationError(
                f"{self._label}: cannot reserve {size} bytes; "
                f"{self.available_bytes} of {self._budget} remain"
            )
        self._reserved += size
        self._statistics.bytes_reserved_total += size
        if self._reserved > self._statistics.peak_reserved_bytes:
            self._statistics.peak_reserved_bytes = self._reserved

    def _return(self, size: int) -> None:
        self._reserved -= size
        if self._reserved < 0:
            self._reserved = 0

    def _return_handle(self) -> None:
        self._open_handles -= 1
        if self._open_handles < 0:
            self._open_handles = 0

    def reserve(self, size: int, label: str = "operator") -> MemoryReservation:
        """Grant a reservation, or refuse it without partially claiming bytes."""

        checked = _validate_size(size, "Reservation")
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("Reservation label must be a non-empty string")
        self._claim(checked)
        self._statistics.reservations_granted += 1
        return MemoryReservation(self, checked, label)

    def reserve_row(self, record: Record, label: str = "row") -> MemoryReservation:
        """Reserve exactly what retaining one row costs under the model.

        A single row wider than the whole budget can never be processed, so it
        raises a deterministic error rather than being silently accepted.
        """

        size = row_footprint_bytes(record)
        if size > self._budget:
            raise ValidationError(
                f"{self._label}: a single row needs {size} bytes but the budget "
                f"is {self._budget}"
            )
        return self.reserve(size, label)

    def acquire_handle(self, label: str = "temporary") -> HandleLease:
        """Lease one temporary-file handle permit under the handle ceiling."""

        self._require_open()
        if not isinstance(label, str) or not label.strip():
            raise ValidationError("Handle label must be a non-empty string")
        if self._open_handles >= self._max_open_handles:
            raise ValidationError(
                f"{self._label}: handle limit of {self._max_open_handles} reached"
            )
        self._open_handles += 1
        self._statistics.handles_opened += 1
        if self._open_handles > self._statistics.peak_open_handles:
            self._statistics.peak_open_handles = self._open_handles
        return HandleLease(self, label)

    def child(
        self,
        memory_budget_bytes: int,
        *,
        label: str = "nested",
        max_open_handles: int | None = None,
    ) -> "ExecutionContext":
        """Carve a nested budget out of this context's remaining bytes.

        The bytes are reserved from the parent for as long as the child lives,
        so nested blocking operators can never promise the same memory twice.
        Closing the child returns them.
        """

        self._require_open()
        budget = _validate_size(memory_budget_bytes, "Child memory budget")
        if budget < MINIMUM_BUDGET_BYTES:
            raise ValidationError(
                f"A nested budget must be at least {MINIMUM_BUDGET_BYTES} bytes"
            )
        reservation = self.reserve(budget, f"child:{label}")
        try:
            child = ExecutionContext(
                memory_budget_bytes=budget,
                max_open_handles=(
                    self._max_open_handles
                    if max_open_handles is None
                    else max_open_handles
                ),
                label=label,
            )
        except BaseException:
            reservation.release()
            raise
        child._parent_reservation = reservation
        self._children.append(child)
        self._statistics.children_created += 1
        return child

    def close(self) -> None:
        """Close nested contexts and return this context's parent bytes.

        Cleanup attempts every child even when one of them fails, so a single
        failure cannot strand the remaining reservations.
        """

        if self._closed:
            return
        self._closed = True
        failure: BaseException | None = None
        for child in self._children:
            try:
                child.close()
            except BaseException as error:  # noqa: BLE001 - re-raised below
                failure = failure or error
        self._children.clear()
        self._reserved = 0
        self._open_handles = 0
        if self._parent_reservation is not None:
            self._parent_reservation.release()
            self._parent_reservation = None
        if failure is not None:
            raise failure

    def __enter__(self) -> "ExecutionContext":
        """Return this context for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the context on every exit path."""

        self.close()
