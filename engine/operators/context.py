"""Query-scoped memory budget, handle limits, and resource statistics."""

from __future__ import annotations

from dataclasses import dataclass

from engine.catalog import DataType
from engine.errors import (
    InsufficientBudgetError,
    InvalidTypeError,
    OversizedRowError,
    ValidationError,
)
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
    temporary_pages_read: int = 0
    temporary_pages_written: int = 0
    temporary_metadata_reads: int = 0
    temporary_metadata_writes: int = 0
    bytes_spilled: int = 0
    live_temporary_bytes: int = 0
    peak_live_temporary_bytes: int = 0


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
    """A counted permit to keep one temporary file handle open.

    A lease taken on a nested context also holds a lease on every ancestor, so
    the root context sees, and bounds, every handle open anywhere in the plan.
    """

    __slots__ = ("_context", "_label", "_released", "_parent_lease")

    def __init__(
        self,
        context: "ExecutionContext",
        label: str,
        parent_lease: "HandleLease | None" = None,
    ) -> None:
        self._context = context
        self._label = label
        self._released = False
        self._parent_lease = parent_lease

    @property
    def label(self) -> str:
        """Return the owner label recorded for diagnostics."""

        return self._label

    @property
    def released(self) -> bool:
        """Report whether this lease has already been returned."""

        return self._released

    def release(self) -> None:
        """Return the permit, and the ancestors' permits; safe to repeat."""

        if self._released:
            return
        self._released = True
        try:
            self._context._return_handle()
        finally:
            if self._parent_lease is not None:
                self._parent_lease.release()

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
        "_parent",
        "_resources",
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
            raise InsufficientBudgetError(
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
        self._resources = {}
        self._children: list["ExecutionContext"] = []
        self._parent: "ExecutionContext | None" = None

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
    def available_handles(self) -> int:
        """Permits available simultaneously here and in every ancestor."""
        available = self._max_open_handles - self._open_handles
        return available if self._parent is None else min(
            available, self._parent.available_handles)

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
            raise InsufficientBudgetError(
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

    def record_temporary_io(
        self, *, pages_read=0, pages_written=0,
        metadata_reads=0, metadata_writes=0, bytes_spilled=0,
    ) -> None:
        """Record exclusive temporary work once, also visible at the root."""
        stats = self._statistics
        stats.temporary_pages_read += pages_read
        stats.temporary_pages_written += pages_written
        stats.temporary_metadata_reads += metadata_reads
        stats.temporary_metadata_writes += metadata_writes
        stats.bytes_spilled += bytes_spilled
        if self._parent is not None:
            self._parent.record_temporary_io(
                pages_read=pages_read, pages_written=pages_written,
                metadata_reads=metadata_reads, metadata_writes=metadata_writes,
                bytes_spilled=bytes_spilled,
            )

    def adjust_temporary_bytes(self, delta: int) -> None:
        """Track physical bytes of live owned files across nested workspaces."""
        stats = self._statistics
        stats.live_temporary_bytes += delta
        if stats.live_temporary_bytes < 0:
            raise RuntimeError("Temporary byte accounting became negative")
        stats.peak_live_temporary_bytes = max(
            stats.peak_live_temporary_bytes, stats.live_temporary_bytes
        )
        if self._parent is not None:
            self._parent.adjust_temporary_bytes(delta)

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
            raise OversizedRowError(
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
            raise InsufficientBudgetError(
                f"{self._label}: handle limit of {self._max_open_handles} reached"
            )
        # The ancestor lease is taken first: if the pipeline as a whole is at
        # its ceiling, this context must not count a handle it cannot open.
        parent_lease = (
            self._parent.acquire_handle(label) if self._parent is not None else None
        )
        self._open_handles += 1
        self._statistics.handles_opened += 1
        if self._open_handles > self._statistics.peak_open_handles:
            self._statistics.peak_open_handles = self._open_handles
        return HandleLease(self, label, parent_lease)

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
            raise InsufficientBudgetError(
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
        child._parent = self
        self._children.append(child)
        self._statistics.children_created += 1
        return child

    def manage(self, resource) -> None:
        """Attach a closeable owner whose resources must outlive its permits."""
        self._require_open()
        self._resources[id(resource)] = resource

    def forget(self, resource) -> None:
        self._resources.pop(id(resource), None)

    def close(self) -> None:
        """Close nested contexts and return this context's parent bytes.

        Cleanup attempts every child even when one of them fails, so a single
        failure cannot strand the remaining reservations.
        """

        if self._closed:
            return
        failure: BaseException | None = None
        for resource in reversed(tuple(self._resources.values())):
            try:
                resource.close()
            except BaseException as error:
                failure = failure or error
        self._resources.clear()
        for child in tuple(self._children):
            try:
                child.close()
            except BaseException as error:  # noqa: BLE001 - re-raised below
                failure = failure or error
        self._children.clear()
        self._closed = True
        self._reserved = 0
        self._open_handles = 0
        if self._parent_reservation is not None:
            self._parent_reservation.release()
            self._parent_reservation = None
        if self._parent is not None:
            self._parent._children.remove(self)
            self._parent = None
        if failure is not None:
            raise failure

    def __enter__(self) -> "ExecutionContext":
        """Return this context for use inside a with block."""

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the context on every exit path."""

        try:
            self.close()
        except BaseException as error:
            if exc_value is None:
                raise
            exc_value.add_note(f"Context cleanup also failed: {error}")


def operator_context(
    parent: ExecutionContext | None,
    *,
    requested: int | None,
    minimum: int,
    label: str,
) -> ExecutionContext:
    """Give one blocking operator its own nested budget without starving others.

    An explicit request is carved exactly. Without one, the operator takes
    **half of what its parent still has available**, never less than its own
    minimum. Children open before their parents, so a rule of "take the whole
    parent budget" lets the first blocking operator to open starve every one
    opened after it; halving the remainder leaves room for the rest of the
    chain while still giving each operator a real grant.

    Refusing up front, before any row is read, is deliberate: a plan whose
    simultaneous blocking operators cannot all fit must fail cleanly rather
    than discover it halfway through a spill.
    """

    if type(minimum) is not int or minimum < MINIMUM_BUDGET_BYTES:
        raise ValidationError("An operator minimum must be a valid budget")
    if requested is not None and type(requested) is not int:
        raise InvalidTypeError("A requested budget must be an int")
    if parent is None:
        budget = DEFAULT_BUDGET_BYTES if requested is None else requested
        if budget < minimum:
            raise InsufficientBudgetError(
                f"{label} needs at least {minimum} bytes, got {budget}"
            )
        return ExecutionContext(memory_budget_bytes=budget, label=label)
    if not isinstance(parent, ExecutionContext):
        raise InvalidTypeError("parent must be an ExecutionContext")
    available = parent.available_bytes
    budget = requested if requested is not None else max(minimum, available // 2)
    if budget < minimum:
        raise InsufficientBudgetError(
            f"{label} needs at least {minimum} bytes, got {budget}"
        )
    if budget > available:
        raise InsufficientBudgetError(
            f"{label} needs {budget} bytes but its parent {parent.label!r} has "
            f"only {available} of {parent.memory_budget_bytes} left; the "
            "blocking operators of this plan do not fit simultaneously"
        )
    return parent.child(budget, label=label)
