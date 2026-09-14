"""Pull-based relational execution contract and the shared operator lifecycle."""

from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
from time import perf_counter

from engine.catalog import Schema
from engine.errors import InvalidTypeError, SchemaError, ValidationError
from engine.storage.record import Record

from .context import ExecutionContext
from .temp_files import cleanup_preserving_error
from .rows import ColumnReference, RowLayout, RowProvenance


class Operator(ABC):
    """A reusable open/next/close execution boundary yielding Record objects.

    Instances start closed. A successful open starts a new run; next consumes
    it; close releases resources. Results in one run share an output schema
    determined by the implementation. An empty Record is still a result;
    only None denotes exhaustion. Operators need not be Python iterators.

    Consumers must close on normal completion, early exit, and exceptions,
    including a failed open, e.g.::

        try:
            operator.open()
            while (record := operator.next()) is not None:
                consume(record)
        finally:
            operator.close()

    ABC enforces the methods only. State checks, execution and cleanup belong
    to future concrete operators and their tests; no TableScan is supplied.
    """

    @abstractmethod
    def open(self) -> None:
        """Initialize a run from its beginning and acquire owned resources.

        Opening an already open (even exhausted) operator raises RuntimeError
        without resetting that run. Opening after close is allowed. A failed
        open must release partially acquired resources and leave it closed.
        Reopening does not promise a snapshot if underlying data has changed.
        """
        raise NotImplementedError

    @abstractmethod
    def next(self) -> Record | None:
        """Return the next row, or None repeatedly after exhaustion.

        Calling before open or after close raises RuntimeError. Do not use
        StopIteration for normal exhaustion. Other execution errors propagate;
        after one, the consumer must close before opening another run.
        Exhaustion does not replace the obligation to call close().
        """
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Release resources and leave the operator closed; return None.

        Idempotent, including before open, after a failed open, or after an
        execution failure. Close owned child operators, search/scan generators,
        and temporary resources, even if not fully consumed. Do not close
        borrowed storage/index managers. Cleanup must attempt to release all
        owned resources even if releasing one fails.
        """
        raise NotImplementedError


class OperatorState(Enum):
    """Legal lifecycle states of a physical operator.

    ``EXHAUSTED`` is still an open state: a drained operator keeps its
    resources until ``close``, which is what lets a consumer inspect
    statistics after the last row.
    """

    CREATED = "CREATED"
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


@dataclass(slots=True)
class OperatorStatistics:
    """Measured work of one operator, accumulated across its runs.

    These counters describe what actually happened. Estimated costs, when a
    planner eventually produces them, are reported separately.

    ``rows_examined`` and ``rows_emitted`` are **local** to this operator.
    ``elapsed_seconds`` is **inclusive**: it covers the time spent inside this
    operator's own ``open`` and ``next``, which includes the child calls they
    make. Inclusive timings of a parent and a child overlap, so they must
    never be added together as if they were independent.
    """

    runs: int = 0
    rows_examined: int = 0
    rows_emitted: int = 0
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class OperatorDescriptor:
    """A truthful description of one node of an executed plan.

    Everything here is derived from a real operator instance. ``details``
    carries only facts the operator can vouch for, such as the access path it
    actually used, and a fallback route must change what a descriptor says
    rather than hiding behind a static strategy label.

    ``operator_id`` is a positional path within one plan (``0`` for the root,
    ``0.1`` for its second input), which is stable for a given plan shape and
    needs no global registry.
    """

    name: str
    operator_id: str = "0"
    output_columns: tuple[tuple[str, str], ...] = ()
    details: tuple[tuple[str, str], ...] = ()
    children: tuple["OperatorDescriptor", ...] = ()
    ordered: bool = False
    ordered_by: str | None = None
    rows_examined: int = 0
    rows_emitted: int = 0
    elapsed_seconds: float = 0.0

    def render(self, indent: int = 0) -> str:
        """Render the subtree as indented text for inspection and tests."""

        prefix = "  " * indent
        detail = ", ".join(f"{key}={value}" for key, value in self.details)
        head = f"{prefix}{self.name}" + (f"({detail})" if detail else "")
        lines = [head]
        for child in self.children:
            lines.append(child.render(indent + 1))
        return "\n".join(lines)

    def walk(self):
        """Yield this descriptor and every descendant, parents first."""

        yield self
        for child in self.children:
            yield from child.walk()


class ExecutionOperator(Operator):
    """Shared lifecycle, ownership, and accounting for Stage 6 operators.

    The output layout is built during construction, so an invalid plan fails
    while it is being assembled rather than in the middle of a stream. Opening
    then acquires only per-run resources.

    A parent owns its children: it opens them, closes them, and closes them
    again on any failure path. It never closes a borrowed storage file or
    index, which remain owned by whoever opened them.
    """

    __slots__ = (
        "_children",
        "_state",
        "_stack",
        "_context",
        "_layout",
        "_statistics",
        "_provenance",
    )

    def __init__(self, *, children: Sequence[Operator] = ()) -> None:
        if isinstance(children, (str, bytes, bytearray)) or not isinstance(
            children, Sequence
        ):
            raise InvalidTypeError("Operator children must be a sequence")
        ordered = tuple(children)
        for child in ordered:
            if not isinstance(child, Operator):
                raise InvalidTypeError("Every operator child must be an Operator")
        self._children = ordered
        self._state = OperatorState.CREATED
        self._stack: ExitStack | None = None
        self._context: ExecutionContext | None = None
        self._statistics = OperatorStatistics()
        self._provenance: tuple[RowProvenance, ...] = ()
        self._layout = self._build_layout()
        if not isinstance(self._layout, RowLayout):
            raise InvalidTypeError("An operator must publish a RowLayout")

    def _build_layout(self) -> RowLayout:
        """Return the output layout; called once, during construction."""

        raise NotImplementedError

    def _open(self) -> None:
        """Acquire per-run resources after children are open."""

    def _next(self) -> Record | None:
        """Produce the next row, or None once the input is drained."""

        raise NotImplementedError

    def _close(self) -> None:
        """Release per-run resources acquired by ``_open``."""

    def _details(self) -> tuple[tuple[str, str], ...]:
        """Return truthful descriptor facts for this operator."""

        return ()

    @property
    def children(self) -> tuple[Operator, ...]:
        """Return the child operators this operator owns."""

        return self._children

    @property
    def layout(self) -> RowLayout:
        """Return the output layout, available before the first open."""

        return self._layout

    @property
    def output_schema(self) -> Schema:
        """Return the schema every emitted row conforms to."""

        return self._layout.schema

    @property
    def state(self) -> OperatorState:
        """Return the current lifecycle state."""

        return self._state

    @property
    def context(self) -> ExecutionContext | None:
        """Return the execution context of the current run, if any."""

        return self._context

    @property
    def statistics(self) -> OperatorStatistics:
        """Return the measured counters of this operator."""

        return self._statistics

    @property
    def provenance(self) -> tuple[RowProvenance, ...]:
        """Return the origin of the row most recently returned by ``next``.

        Base scans report one entry. A join combines origins only when it can
        identify the exact input pair; spooled or partitioned joins report
        none. Computed rows also report none. A derived row never borrows a
        base RID it does not have.
        """

        return self._provenance

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the column this output is ascending by, or None.

        Only an operator whose physical access really produces that order may
        answer here. Declaring an order a later operator then relies on, but
        which the access path does not deliver, is worse than declaring none.
        """

        return None

    @property
    def ordered(self) -> bool:
        """Report whether this operator advertises a preserved ordering."""

        return self.ordering is not None

    def describe(self, operator_id: str = "0") -> OperatorDescriptor:
        """Return a descriptor of this operator and the subtree below it.

        The description is built from this live instance, so it reports the
        route that actually ran, including any fallback, rather than a label
        chosen when the plan was assembled.
        """

        children = tuple(
            child.describe(f"{operator_id}.{position}")
            for position, child in enumerate(self._children)
            if isinstance(child, ExecutionOperator)
        )
        ordering = self.ordering
        return OperatorDescriptor(
            name=type(self).__name__,
            operator_id=operator_id,
            output_columns=tuple(
                (column.name, column.data_type.value)
                for column in self.output_schema
            ),
            details=self._details(),
            children=children,
            ordered=ordering is not None,
            ordered_by=None if ordering is None else ordering.qualified_name,
            rows_examined=self._statistics.rows_examined,
            rows_emitted=self._statistics.rows_emitted,
            elapsed_seconds=self._statistics.elapsed_seconds,
        )

    def _preflight(self, available):
        """Check grants in the same postorder as open, before any source pulls."""
        from engine.errors import InsufficientBudgetError
        for child in self._children:
            if isinstance(child, ExecutionOperator):
                available = child._preflight(available)
        minimum = getattr(self, "memory_budget_minimum", 0)
        if minimum:
            requested = getattr(self, "_budget", None)
            grant = requested if requested is not None else max(minimum, available // 2)
            if grant < minimum or grant > available:
                raise InsufficientBudgetError(
                    "The blocking operators of this plan do not fit simultaneously")
            available -= grant
        return available

    def open(self, context: ExecutionContext | None = None) -> None:
        """Start a run, opening children first and cleaning up on failure."""

        if self._state not in (OperatorState.CREATED, OperatorState.CLOSED):
            raise RuntimeError(f"{type(self).__name__} is already open")
        if context is not None and not isinstance(context, ExecutionContext):
            raise InvalidTypeError("context must be an ExecutionContext")
        if context is not None:
            self._preflight(context.available_bytes)
        self._context = context
        self._provenance = ()
        self._state = OperatorState.OPEN
        self._stack = ExitStack()
        started = perf_counter()
        try:
            for child in self._children:
                # Register the close first: a child that fails inside open is
                # required to clean itself up, but closing twice is safe and
                # a partially opened sibling must still be released.
                self._stack.callback(child.close)
                if isinstance(child, ExecutionOperator):
                    child.open(context)
                else:
                    child.open()
            self._open()
        except BaseException:
            self._statistics.elapsed_seconds += perf_counter() - started
            cleanup_preserving_error(self.close)
            raise
        self._statistics.elapsed_seconds += perf_counter() - started
        self._statistics.runs += 1

    def next(self) -> Record | None:
        """Return the next row, or None once and forever after exhaustion."""

        if self._state is OperatorState.EXHAUSTED:
            return None
        if self._state is not OperatorState.OPEN:
            raise RuntimeError(
                f"{type(self).__name__} needs an open, non-failed run"
            )
        started = perf_counter()
        try:
            row = self._next()
        except BaseException:
            self._statistics.elapsed_seconds += perf_counter() - started
            self._state = OperatorState.FAILED
            self._provenance = ()
            raise
        self._statistics.elapsed_seconds += perf_counter() - started
        if row is None:
            self._state = OperatorState.EXHAUSTED
            self._provenance = ()
            return None
        if not isinstance(row, Record):
            self._state = OperatorState.FAILED
            raise InvalidTypeError(
                f"{type(self).__name__} produced {type(row).__name__}, not a Record"
            )
        if row.schema is not self._layout.schema and (
            row.schema != self._layout.schema
        ):
            self._state = OperatorState.FAILED
            raise SchemaError(
                f"{type(self).__name__} produced a row that does not match its "
                "advertised output schema"
            )
        self._statistics.rows_emitted += 1
        return row

    def close(self) -> None:
        """Release owned resources; idempotent on every path, including failure."""

        stack, self._stack = self._stack, None
        self._state = OperatorState.CLOSED
        self._context = None
        self._provenance = ()
        if stack is None:
            return
        try:
            # ExitStack attempts every callback even when one cleanup raises,
            # so one failing child cannot strand its siblings.
            stack.callback(self._close)
            stack.close()
        finally:
            self._stack = None


def execute(
    operator: Operator,
    context: ExecutionContext | None = None,
) -> Generator[Record, None, None]:
    """Stream every row of a plan, guaranteeing close on all exit paths.

    This is the small physical-execution helper of Stage 6, not the Stage 7
    executor: it runs an already-assembled plan and knows nothing about SQL,
    planning, or statements. It streams rather than materializing, so a caller
    that stops early must close the generator, normally with
    ``contextlib.closing``.
    """

    if not isinstance(operator, Operator):
        raise InvalidTypeError("execute requires an Operator")
    try:
        if isinstance(operator, ExecutionOperator):
            operator.open(context)
        else:
            operator.open()
        while (row := operator.next()) is not None:
            yield row
    finally:
        cleanup_preserving_error(operator.close)


def collect(
    operator: Operator,
    context: ExecutionContext | None = None,
    *,
    limit: int,
) -> tuple[Record, ...]:
    """Materialize at most ``limit`` rows, refusing to truncate silently.

    ``limit`` is mandatory: a helper that returns every row of an arbitrary
    table would defeat the streaming contract the operators exist to provide.
    Producing more rows than requested is an error, not a quiet cut.
    """

    if type(limit) is not int:
        raise InvalidTypeError("limit must be an int")
    if limit < 0:
        raise ValidationError("limit must be non-negative")
    rows: list[Record] = []
    stream = execute(operator, context)
    try:
        for row in stream:
            if len(rows) == limit:
                raise ValidationError(
                    f"The plan produced more than the requested {limit} rows"
                )
            rows.append(row)
    finally:
        cleanup_preserving_error(stream.close)
    return tuple(rows)
