"""External sorting: bounded sorted runs plus multi-pass k-way merging."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass
import heapq

from engine.catalog import DataType
from engine.errors import (
    InsufficientBudgetError,
    InvalidTypeError,
    OversizedRowError,
    ValidationError,
)
from engine.storage.record import Record, RecordValue

from .base import ExecutionOperator
from .context import (
    MINIMUM_BUDGET_BYTES,
    ExecutionContext,
    operator_context,
    row_footprint_bytes,
)
from .expressions import validate_comparable
from .rows import ColumnReference, RowLayout, as_reference
from .temp_files import TemporaryWorkspace, REGISTRY_WORK_BYTES, cleanup_preserving_error
from .run_catalog import RunCatalog, CATALOG_WORK_BYTES, RUN_ENTRY_BYTES
from engine.storage.binary import PAGE_SIZE
from .temp_stream import (
    CHUNK_PAYLOAD_SIZE,
    TemporaryRowReader,
    TemporaryRowWriter,
    TemporaryRun,
)


#: Smallest number of runs a merge step may consume. A fan-in of one would
#: copy a run instead of merging, and would never reduce the run count.
MINIMUM_FAN_IN = 2

#: Default ceiling on simultaneously open runs, independent of the budget.
DEFAULT_MAX_FAN_IN = 8

#: Minimum accounts for metadata, two readers, a writer, row heads and scratch.
#: The additional maximum row width is derived from each actual grant, ensuring
#: every admitted row can participate in at least a two-way merge.
MINIMUM_SORT_BUDGET_BYTES = 8 * PAGE_SIZE
SORT_ENTRY_OVERHEAD_BYTES = 128


class _Descending:
    """Invert one value's ordering inside a composite sort key.

    Mixed ascending and descending keys cannot be expressed by reversing a
    whole sort, and text values cannot be negated the way numbers can, so the
    direction is carried by the key itself.
    """

    __slots__ = ("value",)

    def __init__(self, value: RecordValue) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        """Compare wrapped values so tuple comparison can move to the next key."""

        if not isinstance(other, _Descending):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other: "_Descending") -> bool:
        """Order in reverse of the wrapped values."""

        if not isinstance(other, _Descending):
            return NotImplemented
        return other.value < self.value

    def __hash__(self) -> int:
        """Hash the wrapped value."""

        return hash(self.value)

    def __repr__(self) -> str:
        """Show the wrapped value and its inverted direction."""

        return f"_Descending({self.value!r})"


@dataclass(frozen=True, slots=True)
class SortKey:
    """One ordering column and its direction."""

    column: object
    descending: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "column", as_reference(self.column))
        if type(self.descending) is not bool:
            raise InvalidTypeError("SortKey descending must be a bool")


class BoundSortSpec:
    """A sort specification resolved to positions of one input layout.

    The same bound specification produces the keys used for the in-memory
    chunk sort and for every merge pass, so initial runs and merges cannot
    induce different orders.
    """

    __slots__ = ("_positions", "_types", "_descending", "_keys")

    def __init__(self, keys: tuple[SortKey, ...], layout: RowLayout) -> None:
        positions = []
        types = []
        descending = []
        for key in keys:
            field = layout.field(key.column)
            positions.append(field.position)
            types.append(field.data_type)
            descending.append(key.descending)
        self._positions = tuple(positions)
        self._types = tuple(types)
        self._descending = tuple(descending)
        self._keys = keys

    @property
    def keys(self) -> tuple[SortKey, ...]:
        """Return the declared sort keys in priority order."""

        return self._keys

    @property
    def positions(self) -> tuple[int, ...]:
        """Return the pre-resolved row positions the keys read."""

        return self._positions

    def key(self, record: Record) -> tuple:
        """Build the comparison key of one row.

        Every key value is validated, so NaN is rejected here rather than
        producing a silently inconsistent order once it reaches a heap.
        """

        values = record.values
        return tuple(
            _Descending(validate_comparable(data_type, values[position]))
            if reverse
            else validate_comparable(data_type, values[position])
            for position, data_type, reverse in zip(
                self._positions, self._types, self._descending
            )
        )


class SortSpec:
    """A declarative ordering over named columns.

    Equal-key rows are **stable**: they keep their input order. Within a chunk
    that follows from Python's stable sort; across runs it follows from the
    merge preferring the lower run index, since an earlier run always holds
    earlier input. No sequence column is stored, and no row object is ever
    compared, because heap entries break ties on the run index.

    An empty specification is legal and means "preserve input order". It is
    still a real sort operator: rows round-trip through runs unchanged.
    """

    __slots__ = ("_keys",)

    def __init__(self, keys: Sequence[SortKey] = ()) -> None:
        if isinstance(keys, (str, bytes, bytearray)) or not isinstance(
            keys, Sequence
        ):
            raise InvalidTypeError("SortSpec keys must be a sequence of SortKey")
        ordered = tuple(keys)
        for key in ordered:
            if not isinstance(key, SortKey):
                raise InvalidTypeError("Every SortSpec entry must be a SortKey")
        seen: set[tuple[str, str | None]] = set()
        for key in ordered:
            identity = (key.column.name, key.column.relation)
            if identity in seen:
                raise ValidationError(
                    f"Duplicate sort key: {key.column.qualified_name!r}"
                )
            seen.add(identity)
        self._keys = ordered

    @classmethod
    def ascending(cls, *columns: object) -> "SortSpec":
        """Build an all-ascending specification from column selectors."""

        return cls([SortKey(name) for name in columns])

    @classmethod
    def descending(cls, *columns: object) -> "SortSpec":
        """Build an all-descending specification from column selectors."""

        return cls([SortKey(name, descending=True) for name in columns])

    @property
    def keys(self) -> tuple[SortKey, ...]:
        """Return the declared sort keys in priority order."""

        return self._keys

    def bind(self, layout: RowLayout) -> BoundSortSpec:
        """Resolve every key against an input layout, rejecting bad columns."""

        if not isinstance(layout, RowLayout):
            raise InvalidTypeError("A sort specification binds against a RowLayout")
        return BoundSortSpec(self._keys, layout)

    def __repr__(self) -> str:
        """Show each key with its direction."""

        rendered = ", ".join(
            f"{key.column.qualified_name}{' DESC' if key.descending else ' ASC'}"
            for key in self._keys
        )
        return f"SortSpec({rendered})"


@dataclass(slots=True)
class ExternalSortMetrics:
    """Measured external-sorting work, separate from any expected cost."""

    initial_runs: int = 0
    merge_passes: int = 0
    max_fan_in: int = 0
    rows_spilled: int = 0
    bytes_spilled: int = 0
    runs_written: int = 0
    temporary_pages_written: int = 0
    temporary_pages_read: int = 0
    final_merge_streamed: bool = False
    metadata_reads: int = 0
    metadata_writes: int = 0
    max_active_descriptors: int = 0


class ExternalSort(ExecutionOperator):
    """Sort a stream with disk-backed runs and bounded k-way merging.

    Phase one admits rows only while the granted budget allows, sorts each
    admitted chunk in memory, and writes it as a sorted run. Phase two merges
    at most ``fan_in`` runs at a time, repeating until one merge can finish
    the job. The final merge is **streamed** rather than materialized, so the
    last pass costs no extra write.

    The standard-library sort is used on an already-admitted chunk, never on
    the whole input: the external behaviour comes from real spills, which the
    metrics report and the tests force.
    """

    memory_budget_minimum = MINIMUM_SORT_BUDGET_BYTES

    __slots__ = (
        "_child",
        "_spec",
        "_bound",
        "_budget",
        "_max_fan_in",
        "_context",
        "_owned_context",
        "_workspace",
        "_output",
        "_metrics",
        "_fan_in",
        "_ordering",
        "_final_descriptors",
    )

    def __init__(
        self,
        child: ExecutionOperator,
        spec: SortSpec,
        *,
        memory_budget_bytes: int | None = None,
        max_fan_in: int = DEFAULT_MAX_FAN_IN,
    ) -> None:
        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError("ExternalSort requires an ExecutionOperator child")
        if not isinstance(spec, SortSpec):
            raise InvalidTypeError("ExternalSort requires a SortSpec")
        if memory_budget_bytes is not None:
            if type(memory_budget_bytes) is not int:
                raise InvalidTypeError("memory_budget_bytes must be an int")
            if memory_budget_bytes < MINIMUM_SORT_BUDGET_BYTES:
                raise InsufficientBudgetError(
                    f"ExternalSort needs at least {MINIMUM_SORT_BUDGET_BYTES} "
                    f"bytes to merge {MINIMUM_FAN_IN} runs, got "
                    f"{memory_budget_bytes}"
                )
        if type(max_fan_in) is not int:
            raise InvalidTypeError("max_fan_in must be an int")
        if max_fan_in < MINIMUM_FAN_IN:
            raise ValidationError(f"max_fan_in must be at least {MINIMUM_FAN_IN}")
        self._child = child
        self._spec = spec
        self._bound = spec.bind(child.layout)
        self._budget = memory_budget_bytes
        self._max_fan_in = max_fan_in
        self._owned_context: ExecutionContext | None = None
        self._workspace: TemporaryWorkspace | None = None
        self._output: Generator[Record, None, None] | None = None
        self._metrics = ExternalSortMetrics()
        self._fan_in = 0
        self._final_descriptors = None
        super().__init__(children=(child,))
        self._ordering = (
            None
            if not spec.keys or spec.keys[0].descending
            else child.layout.field(spec.keys[0].column).reference
        )

    def _build_layout(self) -> RowLayout:
        return self._child.layout

    @property
    def child(self) -> ExecutionOperator:
        """Return the child operator this sort consumes."""

        return self._child

    @property
    def sort_spec(self) -> SortSpec:
        """Return the declared ordering, including descending keys."""

        return self._spec

    @property
    def metrics(self) -> ExternalSortMetrics:
        """Return the measured run, pass and temporary-I/O counters."""

        return self._metrics

    @property
    def fan_in(self) -> int:
        """Return the fan-in derived from the granted resources."""

        return self._fan_in

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the leading key when the output really is ascending by it."""

        return self._ordering

    def _sorting_context(self) -> ExecutionContext:
        owned = operator_context(
            self.context,
            requested=self._budget,
            minimum=MINIMUM_SORT_BUDGET_BYTES,
            label="external-sort",
        )
        self._owned_context = owned
        return owned

    def _row_cost(self, size: int) -> int:
        # Tuple/key/list entries plus stable-sort pointer workspace. Values in
        # comparison keys reference the immutable row rather than copying it.
        return size + SORT_ENTRY_OVERHEAD_BYTES + 16 * len(self._spec.keys)

    def _merge_cost(self, count: int, width: int) -> int:
        # Reader page + framing/payload scratch + decoded head + heap/key and
        # descriptor; writer page + serialization scratch (also kept for the
        # final streamed merge so that scheduling has one conservative rule).
        return (PAGE_SIZE + 2 * width + count * (
            PAGE_SIZE + 2 * width + self._row_cost(width) + RUN_ENTRY_BYTES))

    def _resolve_fan_in(self, context, run_count, width=0):
        # Two catalogs coexist during a pass, even when only one exists now.
        available = context.memory_budget_bytes - REGISTRY_WORK_BYTES - 2 * CATALOG_WORK_BYTES
        by_handles = context.available_handles - 1
        fan_in = min(by_handles, self._max_fan_in)
        while fan_in >= 2 and self._merge_cost(fan_in, width) > available:
            fan_in -= 1
        if run_count > 1 and fan_in < 2:
            raise InsufficientBudgetError(
                "Merging needs at least two accounted heads, buffers and handles")
        return max(1, fan_in)

    def _spill(self, chunk):
        chunk.sort(key=lambda entry: entry[0])
        writer = TemporaryRowWriter(self._workspace, self.output_schema, label="run")
        try:
            for _, row in chunk:
                writer.write(row)
            run = writer.finish()
        finally:
            cleanup_preserving_error(writer.close)
        self._metrics.runs_written += 1
        self._metrics.rows_spilled += run.row_count
        self._metrics.bytes_spilled += run.byte_length
        self._metrics.temporary_pages_written += writer.pages_written
        return run

    def _row_capacity(self, context):
        available = context.memory_budget_bytes - REGISTRY_WORK_BYTES - 2 * CATALOG_WORK_BYTES
        # Solve the two-way merge inequality for the maximum decoded row size.
        return (available - self._merge_cost(2, 0)) // 8

    def _generate_runs(self, context):
        runs = RunCatalog(self._workspace, self.output_schema)
        capacity = self._row_capacity(context)
        scratch = context.reserve(PAGE_SIZE + 3 * capacity + RUN_ENTRY_BYTES,
                                  "sort-writer-and-pending-row")
        chunk_reservation = context.reserve(0, "sort-chunk-and-keys")
        chunk = []
        try:
            while (row := self._child.next()) is not None:
                self._statistics.rows_examined += 1
                size = row_footprint_bytes(row)
                if size > capacity:
                    raise OversizedRowError(
                        f"A single row needs {size} bytes; this sort grant supports "
                        f"at most {capacity} per row including decoded overhead")
                cost = self._row_cost(size)
                if context.available_bytes < cost:
                    if not chunk:
                        raise InsufficientBudgetError("No room for a sort chunk")
                    run = self._spill(chunk)
                    chunk.clear()
                    chunk_reservation.shrink(chunk_reservation.bytes)
                    runs.append(run)
                chunk_reservation.grow(cost)
                chunk.append((self._bound.key(row), row))
            if chunk:
                run = self._spill(chunk)
                chunk.clear()
                chunk_reservation.shrink(chunk_reservation.bytes)
                runs.append(run)
            self._metrics.initial_runs = len(runs)
            return runs
        except BaseException:
            cleanup_preserving_error(runs.close)
            raise
        finally:
            chunk.clear()
            chunk_reservation.release()
            scratch.release()

    def _merge_rows(self, runs):
        context = self._owned_context
        width = max((run.max_row_bytes for run in runs), default=0)
        # The caller reserves the input descriptors before loading them from
        # the catalog; do not count those bytes twice here.
        reservation = context.reserve(
            self._merge_cost(len(runs), width) - len(runs) * RUN_ENTRY_BYTES,
                                      "merge-buffers-heads-keys-output")
        self._metrics.max_active_descriptors = max(
            self._metrics.max_active_descriptors, len(runs))
        readers = []
        heap = []
        try:
            for index, run in enumerate(runs):
                reader = TemporaryRowReader(self._workspace, run)
                readers.append(reader)
                head = reader.next_row()
                if head is not None:
                    heapq.heappush(heap, (self._bound.key(head), index, head))
            while heap:
                _, index, row = heapq.heappop(heap)
                yield row
                # Drop the emitted head before advancing its reader.
                row = None
                head = None
                head = readers[index].next_row()
                if head is not None:
                    heapq.heappush(heap, (self._bound.key(head), index, head))
        finally:
            heap.clear()
            def close_readers():
                failure = None
                for reader in readers:
                    self._metrics.temporary_pages_read += reader.pages_read
                    try:
                        reader.close()
                    except BaseException as error:
                        failure = failure or error
                if failure is not None:
                    raise failure
            try:
                cleanup_preserving_error(close_readers)
            finally:
                reservation.release()

    def _merge_to_run(self, runs):
        # Reserve merge work before opening any stream. The generator acquires
        # its reservation on its first pull, so open the writer afterwards.
        merged = self._merge_rows(runs)
        writer = None
        try:
            first = next(merged, None)
            writer = TemporaryRowWriter(self._workspace, self.output_schema, label="pass")
            if first is not None:
                writer.write(first)
                first = None
            for row in merged:
                writer.write(row)
            run = writer.finish()
            self._metrics.runs_written += 1
            self._metrics.temporary_pages_written += writer.pages_written
            return run
        finally:
            try:
                cleanup_preserving_error(merged.close)
            finally:
                if writer is not None:
                    cleanup_preserving_error(writer.close)

    def _reduce_runs(self, runs, fan_in):
        try:
            while len(runs) > fan_in:
                self._metrics.merge_passes += 1
                produced = RunCatalog(self._workspace, self.output_schema)
                try:
                    for start in range(0, len(runs), fan_in):
                        stop = min(start + fan_in, len(runs))
                        with self._owned_context.reserve(
                            (stop - start) * RUN_ENTRY_BYTES, "active-run-descriptors"
                        ):
                            group = []
                            try:
                                for index in range(start, stop):
                                    group.append(runs.read(index))
                                if len(group) == 1:
                                    produced.append(group[0])
                                    continue
                                self._metrics.max_fan_in = max(
                                    self._metrics.max_fan_in, len(group))
                                merged = self._merge_to_run(group)
                                produced.append(merged)
                                for consumed in group:
                                    self._workspace.discard(consumed.path)
                            finally:
                                group.clear()
                    runs.close()
                    runs = produced
                except BaseException:
                    cleanup_preserving_error(produced.close)
                    raise
            return runs
        except BaseException:
            cleanup_preserving_error(runs.close)
            raise

    @staticmethod
    def _empty_output():
        yield from ()

    def _final_output(self, runs):
        self._final_descriptors = self._owned_context.reserve(
            len(runs) * RUN_ENTRY_BYTES, "final-run-descriptors")
        try:
            group = [runs.read(i) for i in range(len(runs))]
        finally:
            runs.close()
        if not group:
            return self._empty_output()
        self._metrics.merge_passes += 1
        self._metrics.max_fan_in = max(self._metrics.max_fan_in, len(group))
        self._metrics.final_merge_streamed = True
        return self._merge_rows(group)

    def _open(self):
        context = self._sorting_context()
        self._workspace = TemporaryWorkspace(label="sort", context=context)
        self._metrics = ExternalSortMetrics()
        runs = self._generate_runs(context)
        try:
            self._fan_in = self._resolve_fan_in(context, len(runs), runs.max_row_bytes)
            remaining = self._reduce_runs(runs, self._fan_in)
            self._output = self._final_output(remaining)
        except BaseException:
            cleanup_preserving_error(runs.close)
            raise

    def _next(self):
        return next(self._output, None)

    def _close(self):
        output, self._output = self._output, None
        workspace, self._workspace = self._workspace, None
        owned, self._owned_context = self._owned_context, None
        descriptors, self._final_descriptors = self._final_descriptors, None
        try:
            if output is not None:
                cleanup_preserving_error(output.close)
        finally:
            try:
                if workspace is not None:
                    cleanup_preserving_error(workspace.close)
                    self._metrics.metadata_reads = workspace.statistics.metadata_reads
                    self._metrics.metadata_writes = workspace.statistics.metadata_writes
            finally:
                if descriptors is not None:
                    descriptors.release()
                if owned is not None:
                    owned.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("order", repr(self._spec)),
            ("initial_runs", str(self._metrics.initial_runs)),
            ("merge_passes", str(self._metrics.merge_passes)),
            ("fan_in", str(self._fan_in)),
        )
