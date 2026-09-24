"""A minimal runner for manually assembled physical plans."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass, replace

from engine.catalog import DataType, Schema
from engine.errors import (
    InvalidTypeError,
    SchemaError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.storage.record import Record

from .base import ExecutionOperator, Operator, OperatorDescriptor
from .temp_files import cleanup_preserving_error
from .context import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_MAX_OPEN_HANDLES,
    cancellation_point,
    ExecutionContext,
    ResourceStatistics,
)
from engine.storage.page_manager import page_io_scope
from .rows import ColumnReference, as_reference
from .index_strategies import IndexNestedLoopJoin, IndexOrderedGroup
from .scan import IndexScan, TableScan, index_storage


@dataclass(frozen=True, slots=True)
class PlanReport:
    """Measured evidence of one physical execution.

    Row counters are **local** to each operator and are never summed across a
    parent and its children, which would count the same row twice. Timings are
    inclusive of child work, so the report exposes the root's wall time rather
    than a sum of overlapping intervals.

    Nothing here is an estimate: every number was observed while the plan ran.
    """

    root: OperatorDescriptor
    rows_produced: int
    elapsed_seconds: float
    peak_reserved_bytes: int
    memory_budget_bytes: int
    peak_open_handles: int
    reservations_granted: int
    reservations_refused: int
    base_pages_read: int = 0
    base_pages_written: int = 0
    index_pages_read: int = 0
    index_pages_written: int = 0
    temporary_pages_read: int = 0
    temporary_pages_written: int = 0
    temporary_metadata_reads: int = 0
    temporary_metadata_writes: int = 0
    bytes_spilled: int = 0
    peak_live_temporary_bytes: int = 0
    live_temporary_bytes: int = 0

    @property
    def operators(self) -> tuple[OperatorDescriptor, ...]:
        """Return every operator descriptor, parents before children."""

        return tuple(self.root.walk())

    def render(self) -> str:
        """Render the plan and its measured evidence as indented text."""

        lines = [self.root.render()]
        lines.append(
            f"rows={self.rows_produced} "
            f"elapsed={self.elapsed_seconds:.6f}s "
            f"peak_memory={self.peak_reserved_bytes}/{self.memory_budget_bytes}B "
            f"peak_handles={self.peak_open_handles}"
        )
        lines.append(
            f"base_io={self.base_pages_read}r/{self.base_pages_written}w "
            f"index_io={self.index_pages_read}r/{self.index_pages_written}w "
            f"temporary_io={self.temporary_pages_read}r/"
            f"{self.temporary_pages_written}w "
            f"temporary_metadata={self.temporary_metadata_reads}r/"
            f"{self.temporary_metadata_writes}w "
            f"spilled={self.bytes_spilled}B "
            f"peak_temporary={self.peak_live_temporary_bytes}B"
        )
        return "\n".join(lines)


class PhysicalPlan:
    """Open, stream, and close one manually assembled operator tree.

    This is the small execution helper Stage 6 owns. It runs a plan that was
    already built from bound Python objects: it parses nothing, chooses no
    access path, and rewrites no operator. Statement orchestration, name
    resolution and planning belong to Stage 7 and are deliberately absent.

    Each run gets a fresh execution context and exclusive ownership of the
    root's cursors, and the root is closed on every exit path.
    """

    __slots__ = ("_root", "_context", "_budget", "_handles", "_label",
                 "_open", "_rows", "_last_statistics", "_sources",
                 "_last_source_io", "_operator_before", "_last_descriptor",
                 "_source_managers", "_execution_source_io")

    def __init__(
        self,
        root: Operator,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        label: str = "plan",
    ) -> None:
        if not isinstance(root, Operator):
            raise InvalidTypeError("A physical plan needs an Operator root")
        self._root = root
        self._budget = memory_budget_bytes
        self._handles = max_open_handles
        self._label = label
        self._context: ExecutionContext | None = None
        self._open = False
        self._rows = 0
        self._last_statistics = ResourceStatistics()
        self._sources = ()
        self._last_source_io = (0, 0, 0, 0)
        self._operator_before = {}
        self._last_descriptor: OperatorDescriptor | None = None
        self._source_managers: dict[int, str] = {}
        self._execution_source_io = [0, 0, 0, 0]

    def _capture_operators(self):
        before = {}
        def visit(node, identifier):
            if not isinstance(node, ExecutionOperator):
                return
            stats = node.statistics
            before[identifier] = (
                stats.rows_examined, stats.rows_emitted, stats.elapsed_seconds
            )
            for position, child in enumerate(node.children):
                visit(child, f"{identifier}.{position}")
        visit(self._root, "0")
        return before

    def _capture_sources(self):
        """Snapshot each borrowed base/index counter once per physical file."""
        sources = []
        seen = set()
        def add(kind, source):
            if source is None or id(source) in seen:
                return
            if not hasattr(source, "pages_read") or not hasattr(source, "pages_written"):
                return
            seen.add(id(source))
            sources.append((kind, source, source.pages_read, source.pages_written))
        def visit(node):
            if isinstance(node, TableScan):
                add("base", node.storage)
            elif isinstance(node, IndexScan):
                add("base", node._storage)
                add("index", getattr(node.index, "tree", getattr(node.index, "index", None)))
            elif isinstance(node, (IndexNestedLoopJoin, IndexOrderedGroup)):
                add("base", index_storage(node.index))
                add(
                    "index",
                    getattr(node.index, "tree", getattr(node.index, "index", None)),
                )
            if isinstance(node, ExecutionOperator):
                for child in node.children:
                    visit(child)
        visit(self._root)
        return tuple(sources)

    def _source_io(self):
        return tuple(self._execution_source_io)

    def _record_source_io(self, manager: object, operation: str) -> None:
        kind = self._source_managers.get(id(manager))
        if kind is None:
            return
        offset = 0 if kind == "base" else 2
        self._execution_source_io[offset + (operation == "write")] += 1

    def _run_descriptor(self, descriptor):
        before = self._operator_before.get(descriptor.operator_id, (0, 0, 0.0))
        return replace(
            descriptor,
            rows_examined=descriptor.rows_examined - before[0],
            rows_emitted=descriptor.rows_emitted - before[1],
            elapsed_seconds=descriptor.elapsed_seconds - before[2],
            children=tuple(self._run_descriptor(child) for child in descriptor.children),
        )

    @property
    def root(self) -> Operator:
        """Return the root operator of this plan."""

        return self._root

    @property
    def context(self) -> ExecutionContext | None:
        """Return the execution context of the current run, if any."""

        return self._context

    @property
    def output_schema(self) -> Schema:
        """Return the schema every produced row conforms to."""

        if not isinstance(self._root, ExecutionOperator):
            raise UnsupportedAccessError(
                "This root does not publish an output schema"
            )
        return self._root.output_schema

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the ordering this plan really guarantees, if any."""

        if not isinstance(self._root, ExecutionOperator):
            return None
        return self._root.ordering

    @property
    def rows_produced(self) -> int:
        """Return how many rows this plan has produced in the current run."""

        return self._rows

    def verify(
        self,
        *,
        columns: Sequence[str] | None = None,
        types: Sequence[DataType] | None = None,
        ordered_by: object | None = None,
    ) -> "PhysicalPlan":
        """Check declared expectations before the plan runs.

        Verifying an ordering asks the operators what they really guarantee.
        A plan whose access path does not deliver the requested order is
        rejected here rather than producing quietly unordered rows.
        """

        schema = self.output_schema
        if columns is not None:
            actual = [column.name for column in schema]
            if actual != list(columns):
                raise SchemaError(
                    f"Plan publishes columns {actual}, not {list(columns)}"
                )
        if types is not None:
            actual_types = [column.data_type for column in schema]
            if actual_types != list(types):
                raise SchemaError(
                    f"Plan publishes types {[t.value for t in actual_types]}, "
                    f"not {[t.value for t in types]}"
                )
        if ordered_by is not None:
            requested = as_reference(ordered_by)
            guaranteed = self.ordering
            if guaranteed is None:
                raise UnsupportedAccessError(
                    f"This plan guarantees no ordering, so it cannot be "
                    f"verified as ordered by {requested.qualified_name!r}"
                )
            if guaranteed.name != requested.name or (
                requested.relation is not None
                and guaranteed.relation != requested.relation
            ):
                raise UnsupportedAccessError(
                    f"This plan is ordered by {guaranteed.qualified_name!r}, "
                    f"not {requested.qualified_name!r}"
                )
        return self

    def __enter__(self) -> "PhysicalPlan":
        """Open a fresh context and the root operator."""

        if self._open:
            raise RuntimeError("This plan is already open")
        self._rows = 0
        self._last_statistics = ResourceStatistics()
        self._last_source_io = (0, 0, 0, 0)
        self._operator_before = self._capture_operators()
        self._sources = self._capture_sources()
        self._source_managers = {
            id(manager): kind
            for kind, source, _reads, _writes in self._sources
            if (manager := getattr(source, "_manager", None)) is not None
        }
        self._execution_source_io = [0, 0, 0, 0]
        self._last_descriptor = None
        self._context = ExecutionContext(
            memory_budget_bytes=self._budget,
            max_open_handles=self._handles,
            label=self._label,
        )
        try:
            with page_io_scope(self._record_source_io):
                if isinstance(self._root, ExecutionOperator):
                    self._root.open(self._context)
                else:
                    self._root.open()
        except BaseException:
            cleanup_preserving_error(self._context.close)
            self._last_statistics = replace(self._context.statistics)
            self._last_source_io = self._source_io()
            if isinstance(self._root, ExecutionOperator):
                self._last_descriptor = self._run_descriptor(self._root.describe())
            self._context = None
            raise
        self._open = True
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close the root and its context on every exit path."""

        self._open = False
        context, self._context = self._context, None
        try:
            with page_io_scope(self._record_source_io):
                cleanup_preserving_error(self._root.close, exc_value)
        finally:
            if context is not None:
                try:
                    cleanup_preserving_error(context.close, exc_value)
                finally:
                    self._last_statistics = replace(context.statistics)
                    self._last_source_io = self._source_io()
                    if isinstance(self._root, ExecutionOperator):
                        self._last_descriptor = self._run_descriptor(self._root.describe())

    def rows(self) -> Generator[Record, None, None]:
        """Stream every remaining row of the open plan.

        The generator never collects results: a plan whose output is larger
        than both of its inputs stays streamable.
        """

        if not self._open:
            raise RuntimeError("A plan must be open before it produces rows")
        while True:
            cancellation_point()
            with page_io_scope(self._record_source_io):
                row = self._root.next()
            cancellation_point()
            if row is None:
                break
            self._rows += 1
            yield row

    def describe(self) -> OperatorDescriptor:
        """Return the descriptor tree of the actual operator instances."""

        if not isinstance(self._root, ExecutionOperator):
            raise UnsupportedAccessError("This root publishes no descriptor")
        return self._root.describe()

    def report(self) -> PlanReport:
        """Return the measured evidence of the run so far."""

        descriptor = (
            self._run_descriptor(self.describe())
            if self._context is not None or self._last_descriptor is None
            else self._last_descriptor
        )
        statistics: ResourceStatistics = (
            self._context.statistics
            if self._context is not None
            else self._last_statistics
        )
        base_read, base_write, index_read, index_write = (
            self._source_io() if self._context is not None else self._last_source_io
        )
        return PlanReport(
            root=descriptor,
            rows_produced=self._rows,
            elapsed_seconds=descriptor.elapsed_seconds,
            peak_reserved_bytes=statistics.peak_reserved_bytes,
            memory_budget_bytes=self._budget,
            peak_open_handles=statistics.peak_open_handles,
            reservations_granted=statistics.reservations_granted,
            reservations_refused=statistics.reservations_refused,
            base_pages_read=base_read,
            base_pages_written=base_write,
            index_pages_read=index_read,
            index_pages_written=index_write,
            temporary_pages_read=statistics.temporary_pages_read,
            temporary_pages_written=statistics.temporary_pages_written,
            temporary_metadata_reads=statistics.temporary_metadata_reads,
            temporary_metadata_writes=statistics.temporary_metadata_writes,
            bytes_spilled=statistics.bytes_spilled,
            peak_live_temporary_bytes=statistics.peak_live_temporary_bytes,
            live_temporary_bytes=statistics.live_temporary_bytes,
        )


def run_plan(
    root: Operator,
    *,
    memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
    max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
    limit: int,
) -> tuple[tuple[Record, ...], PlanReport]:
    """Run a plan to completion and return its rows and measured report.

    ``limit`` is mandatory and producing more rows than it allows is an error,
    for the same reason ``collect`` requires one: a convenience that quietly
    materializes an arbitrary result would defeat the streaming contract.
    """

    if type(limit) is not int:
        raise InvalidTypeError("limit must be an int")
    if limit < 0:
        raise ValidationError("limit must be non-negative")
    plan = PhysicalPlan(
        root,
        memory_budget_bytes=memory_budget_bytes,
        max_open_handles=max_open_handles,
    )
    with plan:
        rows: list[Record] = []
        for row in plan.rows():
            if len(rows) == limit:
                raise ValidationError(
                    f"The plan produced more than the requested {limit} rows"
                )
            rows.append(row)
    return tuple(rows), plan.report()
