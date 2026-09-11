"""External sorting: bounded sorted runs plus multi-pass k-way merging."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass
import heapq

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.record import Record, RecordValue

from .base import ExecutionOperator
from .context import (
    DEFAULT_BUDGET_BYTES,
    MINIMUM_BUDGET_BYTES,
    ExecutionContext,
    row_footprint_bytes,
)
from .expressions import validate_comparable
from .rows import ColumnReference, RowLayout, as_reference
from .temp_files import TemporaryWorkspace
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

#: Smallest budget that can actually finish a sort. A merge of the minimum two
#: runs needs one page buffer per reader plus one for the output, so a budget
#: below this could generate runs it could never combine. The plan is rejected
#: while it is built rather than failing halfway through a spill.
MINIMUM_SORT_BUDGET_BYTES = (MINIMUM_FAN_IN + 1) * CHUNK_PAYLOAD_SIZE


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
                raise ValidationError(
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
        parent = self.context
        budget = self._budget if self._budget is not None else (
            min(DEFAULT_BUDGET_BYTES, parent.memory_budget_bytes)
            if parent is not None
            else DEFAULT_BUDGET_BYTES
        )
        if budget < MINIMUM_SORT_BUDGET_BYTES:
            raise ValidationError(
                f"ExternalSort was granted {budget} bytes but needs at least "
                f"{MINIMUM_SORT_BUDGET_BYTES} to merge {MINIMUM_FAN_IN} runs"
            )
        if parent is None:
            owned = ExecutionContext(memory_budget_bytes=budget, label="external-sort")
        else:
            owned = parent.child(budget, label="external-sort")
        self._owned_context = owned
        return owned

    def _resolve_fan_in(self, context: ExecutionContext, run_count: int) -> int:
        """Derive fan-in from resources, never from the number of runs."""

        # One handle is left for the run being produced by the current merge.
        by_handles = context.max_open_handles - 1
        per_reader = CHUNK_PAYLOAD_SIZE
        by_memory = (context.memory_budget_bytes - CHUNK_PAYLOAD_SIZE) // per_reader
        fan_in = min(by_handles, by_memory, self._max_fan_in)
        if fan_in < MINIMUM_FAN_IN and run_count > 1:
            raise ValidationError(
                f"Merging {run_count} runs needs a fan-in of at least "
                f"{MINIMUM_FAN_IN}; the granted resources allow {fan_in}"
            )
        return max(fan_in, MINIMUM_FAN_IN)

    def _spill(self, chunk: list[tuple[tuple, Record]]) -> TemporaryRun:
        """Sort an admitted chunk and persist it as one sorted run."""

        # Python's sort is stable, so equal keys keep their input order, and
        # only the key tuples are compared: rows are never ordered against
        # each other.
        chunk.sort(key=lambda entry: entry[0])
        writer = TemporaryRowWriter(self._workspace, self.output_schema, label="run")
        try:
            for _, row in chunk:
                writer.write(row)
            run = writer.finish()
        except BaseException:
            writer.close()
            raise
        self._metrics.runs_written += 1
        self._metrics.rows_spilled += run.row_count
        self._metrics.bytes_spilled += run.byte_length
        self._metrics.temporary_pages_written += run.page_count + 1
        return run

    def _generate_runs(self, context: ExecutionContext) -> list[TemporaryRun]:
        """Admit rows within the budget, spilling each full chunk as a run."""

        runs: list[TemporaryRun] = []
        chunk: list[tuple[tuple, Record]] = []
        writer_reservation = context.reserve(CHUNK_PAYLOAD_SIZE, "sort-output-buffer")
        try:
            chunk_reservation = context.reserve(0, "sort-chunk")
            while (row := self._child.next()) is not None:
                self._statistics.rows_examined += 1
                size = row_footprint_bytes(row)
                if context.available_bytes < size:
                    if not chunk:
                        raise ValidationError(
                            f"A single row needs {size} bytes but only "
                            f"{context.available_bytes} remain in the sort budget"
                        )
                    # The pending row is held in `row` across the spill and is
                    # admitted to the next chunk, so nothing is lost.
                    runs.append(self._spill(chunk))
                    chunk = []
                    chunk_reservation.release()
                    chunk_reservation = context.reserve(0, "sort-chunk")
                    if context.available_bytes < size:
                        raise ValidationError(
                            f"A single row needs {size} bytes, more than the "
                            "sort budget can ever admit"
                        )
                chunk_reservation.grow(size)
                chunk.append((self._bound.key(row), row))
            if chunk:
                runs.append(self._spill(chunk))
            chunk_reservation.release()
        finally:
            writer_reservation.release()
        self._metrics.initial_runs = len(runs)
        return runs

    def _merge_rows(
        self,
        runs: Sequence[TemporaryRun],
    ) -> Generator[Record, None, None]:
        """Yield the merged order of several runs with one head row each."""

        readers: list[TemporaryRowReader] = []
        try:
            heap: list[tuple[tuple, int, Record]] = []
            for index, run in enumerate(runs):
                reader = TemporaryRowReader(self._workspace, run)
                readers.append(reader)
                head = reader.next_row()
                if head is not None:
                    # The run index breaks every tie, so two equal keys never
                    # force a comparison between Record objects, and the older
                    # run wins, which is what keeps the sort stable.
                    heapq.heappush(heap, (self._bound.key(head), index, head))
            while heap:
                _, index, row = heapq.heappop(heap)
                yield row
                head = readers[index].next_row()
                if head is not None:
                    heapq.heappush(heap, (self._bound.key(head), index, head))
        finally:
            pages = 0
            for reader in readers:
                pages += reader.pages_read
                reader.close()
            self._metrics.temporary_pages_read += pages

    def _merge_to_run(self, runs: Sequence[TemporaryRun]) -> TemporaryRun:
        """Merge a group of runs into one new run of the next pass."""

        writer = TemporaryRowWriter(self._workspace, self.output_schema, label="pass")
        merged = self._merge_rows(runs)
        try:
            for row in merged:
                writer.write(row)
            run = writer.finish()
        except BaseException:
            merged.close()
            writer.close()
            raise
        merged.close()
        self._metrics.runs_written += 1
        self._metrics.temporary_pages_written += run.page_count + 1
        return run

    def _reduce_runs(self, runs: list[TemporaryRun], fan_in: int) -> list[TemporaryRun]:
        """Run merge passes until one final merge can consume what is left."""

        while len(runs) > fan_in:
            self._metrics.merge_passes += 1
            produced: list[TemporaryRun] = []
            for start in range(0, len(runs), fan_in):
                group = runs[start:start + fan_in]
                if len(group) == 1:
                    produced.append(group[0])
                    continue
                self._metrics.max_fan_in = max(self._metrics.max_fan_in, len(group))
                merged = self._merge_to_run(group)
                produced.append(merged)
                # Only now that the replacement exists, and with every reader
                # of this group already closed, are the inputs reclaimed.
                for consumed in group:
                    self._workspace.discard(consumed.path)
            runs = produced
        return runs

    @staticmethod
    def _empty_output() -> Generator[Record, None, None]:
        """Return a closable empty stream, so cleanup is uniform."""

        yield from ()

    def _final_output(self, runs: list[TemporaryRun]) -> Generator[Record, None, None]:
        """Stream the last merge instead of materializing another run."""

        if not runs:
            return self._empty_output()
        self._metrics.merge_passes += 1
        self._metrics.max_fan_in = max(self._metrics.max_fan_in, len(runs))
        self._metrics.final_merge_streamed = True
        return self._merge_rows(runs)

    def _open(self) -> None:
        context = self._sorting_context()
        self._workspace = TemporaryWorkspace(label="sort")
        self._metrics = ExternalSortMetrics()
        runs = self._generate_runs(context)
        self._fan_in = self._resolve_fan_in(context, len(runs))
        remaining = self._reduce_runs(runs, self._fan_in)
        self._output = self._final_output(remaining)

    def _next(self) -> Record | None:
        return next(self._output, None)

    def _close(self) -> None:
        output, self._output = self._output, None
        workspace, self._workspace = self._workspace, None
        owned, self._owned_context = self._owned_context, None
        try:
            if output is not None:
                output.close()
        finally:
            try:
                if workspace is not None:
                    workspace.close()
            finally:
                if owned is not None:
                    owned.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("order", repr(self._spec)),
            ("initial_runs", str(self._metrics.initial_runs)),
            ("merge_passes", str(self._metrics.merge_passes)),
            ("fan_in", str(self._fan_in)),
        )
