"""Inner equijoins: a nested-loop baseline and the Grace hash-join route."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.record import Record, RecordValue

from .base import ExecutionOperator
from .context import (
    DEFAULT_BUDGET_BYTES,
    ExecutionContext,
    row_footprint_bytes,
    value_footprint_bytes,
)
from .expressions import BoundExpression, Expression, validate_comparable
from .partitioning import (
    DEFAULT_PARTITION_COUNT,
    MAX_PARTITION_LEVEL,
    HashPartitioner,
    Partition,
    maximum_partition_count,
)
from .rows import ColumnReference, RowLayout, RowProvenance, as_reference
from .sorting import MINIMUM_SORT_BUDGET_BYTES
from .temp_files import TemporaryWorkspace
from .temp_stream import (
    CHUNK_PAYLOAD_SIZE,
    TemporaryRowReader,
    TemporaryRowWriter,
    TemporaryRun,
)


#: Conservative per-entry bookkeeping for one build-side hash bucket.
BUILD_ENTRY_OVERHEAD_BYTES = 192

#: Smallest budget a join may be granted: enough to spool, partition with the
#: minimum fan-out, and still hold a small build block.
MINIMUM_JOIN_BUDGET_BYTES = MINIMUM_SORT_BUDGET_BYTES


@dataclass(frozen=True, slots=True)
class JoinKey:
    """One equality pair of the join condition."""

    left: object
    right: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "left", as_reference(self.left))
        object.__setattr__(self, "right", as_reference(self.right))


class JoinSpec:
    """The equality condition of an inner equijoin.

    Both sides of every pair must share a declared type: an INTEGER column is
    never joined against a FLOAT one, exactly as a predicate never compares
    them. That strictness is what lets both sides hash to the same partition.

    The row model has no NULL, so there are no null equality keys to exclude.
    """

    __slots__ = ("_keys",)

    def __init__(self, keys: Sequence[JoinKey]) -> None:
        if isinstance(keys, (str, bytes, bytearray)) or not isinstance(
            keys, Sequence
        ):
            raise InvalidTypeError("JoinSpec keys must be a sequence of JoinKey")
        ordered = tuple(keys)
        if not ordered:
            raise ValidationError(
                "An equijoin needs at least one equality pair; a cross join is "
                "out of scope for this stage"
            )
        for key in ordered:
            if not isinstance(key, JoinKey):
                raise InvalidTypeError("Every JoinSpec entry must be a JoinKey")
        self._keys = ordered

    @classmethod
    def on(cls, *pairs: object) -> "JoinSpec":
        """Build a specification from ``(left, right)`` column selector pairs."""

        keys = []
        for pair in pairs:
            if isinstance(pair, JoinKey):
                keys.append(pair)
                continue
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise InvalidTypeError(
                    "Each join pair must be a (left, right) tuple or a JoinKey"
                )
            keys.append(JoinKey(pair[0], pair[1]))
        return cls(keys)

    @classmethod
    def using(cls, *columns: object) -> "JoinSpec":
        """Build a specification joining identically named columns."""

        return cls([JoinKey(name, name) for name in columns])

    @property
    def keys(self) -> tuple[JoinKey, ...]:
        """Return the equality pairs in declaration order."""

        return self._keys

    def bind(
        self,
        left: RowLayout,
        right: RowLayout,
    ) -> tuple[tuple[int, ...], tuple[int, ...], tuple[DataType, ...]]:
        """Resolve both sides to positions, requiring one type per pair."""

        for layout in (left, right):
            if not isinstance(layout, RowLayout):
                raise InvalidTypeError("A join specification binds against layouts")
        left_positions = []
        right_positions = []
        types = []
        for key in self._keys:
            left_field = left.field(key.left)
            right_field = right.field(key.right)
            if left_field.data_type is not right_field.data_type:
                raise ValidationError(
                    f"Cannot join {left_field.data_type.value} with "
                    f"{right_field.data_type.value}; no implicit conversion is "
                    "performed"
                )
            left_positions.append(left_field.position)
            right_positions.append(right_field.position)
            types.append(left_field.data_type)
        return tuple(left_positions), tuple(right_positions), tuple(types)

    def __repr__(self) -> str:
        """Show the equality pairs."""

        rendered = ", ".join(
            f"{key.left.qualified_name}={key.right.qualified_name}"
            for key in self._keys
        )
        return f"JoinSpec({rendered})"


def join_key_of(
    values: Sequence[RecordValue],
    positions: Sequence[int],
    types: Sequence[DataType],
) -> tuple:
    """Extract and validate the equality key of one row."""

    return tuple(
        validate_comparable(data_type, values[position])
        for position, data_type in zip(positions, types)
    )


class RowSpool:
    """Materialize a child's rows once so they can be re-read many times.

    A join's inner input is consumed more than once, and an operator is not
    required to be rewindable. Spooling to a temporary stream makes the
    repeated passes correct for any producer, at the cost of one write.
    """

    __slots__ = ("_workspace", "_schema", "_run", "_row_count", "_closed", "_label")

    def __init__(
        self,
        workspace: TemporaryWorkspace,
        schema,
        *,
        label: str = "spool",
    ) -> None:
        self._workspace = workspace
        self._schema = schema
        self._run: TemporaryRun | None = None
        self._row_count = 0
        self._closed = False
        self._label = label

    @property
    def row_count(self) -> int:
        """Return how many rows were spooled."""

        return self._row_count

    @property
    def run(self) -> TemporaryRun | None:
        """Return the completed temporary run, if the spool has been filled."""

        return self._run

    def fill(self, pull) -> None:
        """Drain a ``pull()`` source into the spool exactly once."""

        if self._run is not None:
            raise RuntimeError("A spool can only be filled once")
        writer = TemporaryRowWriter(self._workspace, self._schema, label=self._label)
        try:
            while (row := pull()) is not None:
                writer.write(row)
                self._row_count += 1
            self._run = writer.finish()
        except BaseException:
            writer.close()
            raise

    def reader(self) -> TemporaryRowReader:
        """Open one more independent reader over the spooled rows."""

        if self._run is None:
            raise RuntimeError("An unfilled spool has no rows to read")
        return TemporaryRowReader(self._workspace, self._run)

    def close(self) -> None:
        """Discard the spooled file."""

        if self._closed:
            return
        self._closed = True
        if self._run is not None:
            self._workspace.discard(self._run.path)
            self._run = None


class _JoinOperator(ExecutionOperator):
    """Shared layout, key binding, and output construction for inner joins."""

    __slots__ = (
        "_left",
        "_right",
        "_spec",
        "_residual_expression",
        "_residual",
        "_left_positions",
        "_right_positions",
        "_key_types",
        "_budget",
        "_owned_context",
        "_workspace",
        "_output",
    )

    def __init__(
        self,
        left: ExecutionOperator,
        right: ExecutionOperator,
        spec: JoinSpec,
        *,
        residual: Expression | None = None,
        memory_budget_bytes: int | None = None,
    ) -> None:
        for side in (left, right):
            if not isinstance(side, ExecutionOperator):
                raise InvalidTypeError("A join requires ExecutionOperator inputs")
        if not isinstance(spec, JoinSpec):
            raise InvalidTypeError("A join requires a JoinSpec")
        if residual is not None and not isinstance(residual, Expression):
            raise InvalidTypeError("A join residual must be an Expression")
        if memory_budget_bytes is not None:
            if type(memory_budget_bytes) is not int:
                raise InvalidTypeError("memory_budget_bytes must be an int")
            if memory_budget_bytes < MINIMUM_JOIN_BUDGET_BYTES:
                raise ValidationError(
                    f"A join needs at least {MINIMUM_JOIN_BUDGET_BYTES} bytes, "
                    f"got {memory_budget_bytes}"
                )
        self._left = left
        self._right = right
        self._spec = spec
        self._residual_expression = residual
        self._budget = memory_budget_bytes
        self._owned_context: ExecutionContext | None = None
        self._workspace: TemporaryWorkspace | None = None
        self._output: Generator[Record, None, None] | None = None
        (
            self._left_positions,
            self._right_positions,
            self._key_types,
        ) = spec.bind(left.layout, right.layout)
        super().__init__(children=(left, right))
        self._residual: BoundExpression | None = (
            None if residual is None else residual.bind(self.layout)
        )
        if self._residual is not None and (
            self._residual.data_type is not DataType.BOOLEAN
        ):
            raise ValidationError(
                "A join residual must be BOOLEAN, not "
                f"{self._residual.data_type.value}"
            )

    def _build_layout(self) -> RowLayout:
        return RowLayout.combine(self._left.layout, self._right.layout)

    @property
    def left(self) -> ExecutionOperator:
        """Return the left input."""

        return self._left

    @property
    def right(self) -> ExecutionOperator:
        """Return the right input."""

        return self._right

    @property
    def spec(self) -> JoinSpec:
        """Return the equality condition."""

        return self._spec

    def _combine(
        self,
        left_values: Sequence[RecordValue],
        right_values: Sequence[RecordValue],
    ) -> Record | None:
        """Build one output row, applying the residual predicate if present.

        Logical left-then-right column order is preserved regardless of which
        side was physically used to build a hash table.
        """

        values = tuple(left_values) + tuple(right_values)
        if self._residual is not None and not self._residual.matches(values):
            return None
        return Record(self.output_schema, values)

    def _join_context(self, label: str) -> ExecutionContext:
        parent = self.context
        budget = self._budget if self._budget is not None else (
            min(DEFAULT_BUDGET_BYTES, parent.memory_budget_bytes)
            if parent is not None
            else DEFAULT_BUDGET_BYTES
        )
        if budget < MINIMUM_JOIN_BUDGET_BYTES:
            raise ValidationError(
                f"A join was granted {budget} bytes but needs at least "
                f"{MINIMUM_JOIN_BUDGET_BYTES}"
            )
        owned = (
            ExecutionContext(memory_budget_bytes=budget, label=label)
            if parent is None
            else parent.child(budget, label=label)
        )
        self._owned_context = owned
        return owned

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


@dataclass(slots=True)
class NestedLoopMetrics:
    """Measured work of the nested-loop baseline."""

    outer_rows: int = 0
    inner_rows_spooled: int = 0
    blocks: int = 0
    inner_passes: int = 0
    pairs_examined: int = 0
    pairs_emitted: int = 0
    temporary_pages_written: int = 0
    temporary_pages_read: int = 0


class NestedLoopJoin(_JoinOperator):
    """An independent inner-equijoin baseline that uses no hashing at all.

    The inner input is spooled once to a temporary stream and re-read per
    block, so a producer that cannot rewind is handled correctly without
    assuming anything about it. With a block of one row this is the textbook
    tuple nested loop; with a larger admitted block it is the bounded block
    nested loop that also serves as the skew fallback.

    This is a correctness baseline. On its own it does **not** satisfy the
    assignment's optimized-join requirement, and it never claims to.
    """

    __slots__ = ("_metrics", "_block_rows")

    def __init__(
        self,
        left: ExecutionOperator,
        right: ExecutionOperator,
        spec: JoinSpec,
        *,
        residual: Expression | None = None,
        memory_budget_bytes: int | None = None,
        block_rows: int | None = None,
    ) -> None:
        if block_rows is not None:
            if type(block_rows) is not int:
                raise InvalidTypeError("block_rows must be an int")
            if block_rows < 1:
                raise ValidationError("block_rows must be at least one row")
        self._metrics = NestedLoopMetrics()
        self._block_rows = block_rows
        super().__init__(
            left,
            right,
            spec,
            residual=residual,
            memory_budget_bytes=memory_budget_bytes,
        )

    @property
    def metrics(self) -> NestedLoopMetrics:
        """Return the measured baseline counters."""

        return self._metrics

    def _can_admit(self, block: Sequence[Record], row: Record, context) -> bool:
        """Report whether one more outer row fits the current block."""

        if self._block_rows is not None:
            return len(block) < self._block_rows
        return context.available_bytes >= row_footprint_bytes(row)

    def _charge(self, row: Record, reservation, context) -> None:
        """Account one admitted outer row, refusing a row that cannot fit."""

        if self._block_rows is not None:
            return
        size = row_footprint_bytes(row)
        if context.available_bytes < size:
            raise ValidationError(
                f"A single join row needs {size} bytes but only "
                f"{context.available_bytes} remain"
            )
        reservation.grow(size)

    def _pairs(self, context: ExecutionContext) -> Generator[Record, None, None]:
        spool = RowSpool(self._workspace, self._right.output_schema, label="inner")
        try:
            spool.fill(self._right.next)
            self._metrics.inner_rows_spooled = spool.row_count
            self._metrics.temporary_pages_written += (
                0 if spool.run is None else spool.run.page_count + 1
            )
            if spool.row_count == 0:
                # An inner equijoin with an empty inner side has no output, and
                # the outer side does not need to be read to know that.
                return
            block: list[Record] = []
            reservation = context.reserve(CHUNK_PAYLOAD_SIZE, "nested-loop-block")
            try:
                while (row := self._left.next()) is not None:
                    self._metrics.outer_rows += 1
                    if block and not self._can_admit(block, row, context):
                        # The triggering row stays in `row` across the flush,
                        # so no outer row is ever skipped.
                        yield from self._scan_block(block, spool)
                        block = []
                        reservation.release()
                        reservation = context.reserve(
                            CHUNK_PAYLOAD_SIZE, "nested-loop-block"
                        )
                    self._charge(row, reservation, context)
                    block.append(row)
                if block:
                    yield from self._scan_block(block, spool)
            finally:
                reservation.release()
        finally:
            spool.close()

    def _scan_block(
        self,
        block: Sequence[Record],
        spool: RowSpool,
    ) -> Generator[Record, None, None]:
        """Stream the spooled inner once, pairing it with an admitted block."""

        self._metrics.blocks += 1
        self._metrics.inner_passes += 1
        keys = [
            join_key_of(row.values, self._left_positions, self._key_types)
            for row in block
        ]
        reader = spool.reader()
        try:
            while (inner := reader.next_row()) is not None:
                inner_key = join_key_of(
                    inner.values, self._right_positions, self._key_types
                )
                for outer, outer_key in zip(block, keys):
                    self._metrics.pairs_examined += 1
                    if outer_key != inner_key:
                        continue
                    combined = self._combine(outer.values, inner.values)
                    if combined is not None:
                        self._metrics.pairs_emitted += 1
                        self._provenance = (
                            self._left.provenance + self._right.provenance
                        )
                        yield combined
        finally:
            self._metrics.temporary_pages_read += reader.pages_read
            reader.close()

    def _open(self) -> None:
        context = self._join_context("nested-loop-join")
        self._workspace = TemporaryWorkspace(label="nlj")
        self._metrics = NestedLoopMetrics()
        self._output = self._pairs(context)

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self._spec)),
            ("strategy", "block nested loop" if self._block_rows != 1 else
             "tuple nested loop"),
            ("inner", "spooled temporary stream"),
            ("inner_passes", str(self._metrics.inner_passes)),
        )


class HashJoinKernel:
    """Hold one build side in memory and probe it with a streaming side.

    Every occurrence of a build key is stored, not just the last one, so a
    probe row matching *m* build rows emits *m* pairs. Matches are yielded one
    at a time: neither the probe side nor the result is ever materialized.

    Build admission is accounted, and exhaustion is reported to the caller
    **before** any output based on an incomplete build table exists.
    """

    __slots__ = ("_context", "_build_positions", "_probe_positions", "_types",
                 "_table", "_reservation", "_released", "_build_rows")

    def __init__(
        self,
        context: ExecutionContext,
        *,
        build_positions: Sequence[int],
        probe_positions: Sequence[int],
        key_types: Sequence[DataType],
        label: str = "hash-join",
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise InvalidTypeError("A join kernel requires an ExecutionContext")
        self._context = context
        self._build_positions = tuple(build_positions)
        self._probe_positions = tuple(probe_positions)
        self._types = tuple(key_types)
        if not (
            len(self._build_positions)
            == len(self._probe_positions)
            == len(self._types)
        ):
            raise ValidationError("Each join key position needs a matching type")
        self._table: dict[tuple, list[Record]] = {}
        self._reservation = context.reserve(0, label)
        self._released = False
        self._build_rows = 0

    @property
    def build_rows(self) -> int:
        """Return how many build rows are held."""

        return self._build_rows

    @property
    def key_count(self) -> int:
        """Return how many distinct build keys are held."""

        return len(self._table)

    @property
    def reserved_bytes(self) -> int:
        """Return the memory this kernel accounts for."""

        return self._reservation.bytes

    def admit_build(self, record: Record) -> bool:
        """Store one build row, or report exhaustion without storing it."""

        if self._released:
            raise RuntimeError("A released join kernel cannot admit rows")
        if not isinstance(record, Record):
            raise InvalidTypeError("A join kernel requires a Record")
        key = join_key_of(record.values, self._build_positions, self._types)
        bucket = self._table.get(key)
        needed = row_footprint_bytes(record)
        if bucket is None:
            needed += BUILD_ENTRY_OVERHEAD_BYTES + sum(
                value_footprint_bytes(data_type, value)
                for data_type, value in zip(self._types, key)
            )
        if self._context.available_bytes < needed:
            return False
        self._reservation.grow(needed)
        if bucket is None:
            self._table[key] = [record]
        else:
            bucket.append(record)
        self._build_rows += 1
        return True

    def probe(self, record: Record) -> Generator[Record, None, None]:
        """Yield the build rows matching one probe row, one at a time."""

        if self._released:
            raise RuntimeError("A released join kernel cannot probe")
        key = join_key_of(record.values, self._probe_positions, self._types)
        bucket = self._table.get(key)
        if bucket is None:
            return
        # Yielding from the stored bucket avoids building any per-probe list,
        # so a probe row with many matches costs no extra memory.
        yield from bucket

    def release(self) -> None:
        """Drop the build table and return its accounted memory."""

        if self._released:
            return
        self._released = True
        self._table.clear()
        self._build_rows = 0
        self._reservation.release()


@dataclass(slots=True)
class GraceHashJoinMetrics:
    """Measured external-join work, separate from any expected cost."""

    left_rows_partitioned: int = 0
    right_rows_partitioned: int = 0
    partition_pairs: int = 0
    pairs_joined_by_hash: int = 0
    pairs_skipped_empty: int = 0
    repartitions: int = 0
    deepest_level: int = 0
    build_overflows: int = 0
    build_side_swaps: int = 0
    fallback_pairs: int = 0
    fallback_rows: int = 0
    pairs_emitted: int = 0
    temporary_pages_written: int = 0
    temporary_pages_read: int = 0


class GraceHashJoin(_JoinOperator):
    """Join two inputs through matching disk partitions of both sides.

    Both inputs are partitioned with the same hash function on their own join
    keys, so equal keys always land in the same partition index on both sides
    and a pair can be joined independently of every other pair. When a pair
    does not fit, both of its sides are repartitioned together at a deeper
    level, which keeps the pairing intact.

    Repeated occurrences of one key cannot be separated by any hash that also
    keeps them co-located, so a pair that stops shrinking falls back to a
    bounded block nested loop over the same partition files. The fallback is
    counted and reported; it is never presented as hash execution.

    Join output is **unordered** and may be far larger than either input, so
    it is streamed rather than collected.
    """

    __slots__ = (
        "_partition_count",
        "_max_level",
        "_metrics",
        "_block_reserve",
    )

    def __init__(
        self,
        left: ExecutionOperator,
        right: ExecutionOperator,
        spec: JoinSpec,
        *,
        residual: Expression | None = None,
        memory_budget_bytes: int | None = None,
        partition_count: int = DEFAULT_PARTITION_COUNT,
        max_level: int = MAX_PARTITION_LEVEL,
    ) -> None:
        if type(partition_count) is not int:
            raise InvalidTypeError("partition_count must be an int")
        if partition_count < 2:
            raise ValidationError("Partitioning needs at least two partitions")
        if type(max_level) is not int or max_level < 1:
            raise ValidationError("max_level must be a positive int")
        self._partition_count = partition_count
        self._max_level = max_level
        self._metrics = GraceHashJoinMetrics()
        super().__init__(
            left,
            right,
            spec,
            residual=residual,
            memory_budget_bytes=memory_budget_bytes,
        )

    @property
    def metrics(self) -> GraceHashJoinMetrics:
        """Return the measured partitioning, overflow and fallback counters."""

        return self._metrics

    def _partition_side(
        self,
        rows,
        *,
        schema,
        positions,
        level: int,
        context: ExecutionContext,
        label: str,
    ) -> dict[int, Partition]:
        partitioner = HashPartitioner(
            self._workspace,
            schema,
            key_positions=positions,
            key_types=self._key_types,
            partition_count=self._partition_count,
            level=level,
            context=context,
            label=label,
        )
        try:
            for row in rows:
                partitioner.write(row)
            produced = partitioner.finish()
        except BaseException:
            partitioner.close()
            raise
        self._metrics.temporary_pages_written += partitioner.pages_written
        self._metrics.deepest_level = max(self._metrics.deepest_level, level)
        return {partition.index: partition for partition in produced}

    def _left_rows(self) -> Generator[Record, None, None]:
        while (row := self._left.next()) is not None:
            self._statistics.rows_examined += 1
            self._metrics.left_rows_partitioned += 1
            yield row

    def _right_rows(self) -> Generator[Record, None, None]:
        while (row := self._right.next()) is not None:
            self._statistics.rows_examined += 1
            self._metrics.right_rows_partitioned += 1
            yield row

    def _partition_rows(self, partition: Partition) -> Generator[Record, None, None]:
        reader = TemporaryRowReader(self._workspace, partition.run)
        try:
            while (row := reader.next_row()) is not None:
                yield row
        finally:
            self._metrics.temporary_pages_read += reader.pages_read
            reader.close()

    def _emit(
        self,
        left_values: Sequence[RecordValue],
        right_values: Sequence[RecordValue],
    ) -> Record | None:
        combined = self._combine(left_values, right_values)
        if combined is not None:
            self._metrics.pairs_emitted += 1
        return combined

    def _join_pair(
        self,
        left_partition: Partition,
        right_partition: Partition,
        context: ExecutionContext,
        status: dict,
    ) -> Generator[Record, None, None]:
        """Join one partition pair, or produce nothing if the build overflows.

        The smaller side by stored bytes is tried as the build side, which is
        metadata the partitioner already recorded: no input is scanned into
        memory merely to estimate its size. The actual admitted state is what
        decides whether it really fits.
        """

        build_is_left = left_partition.byte_length <= right_partition.byte_length
        if not build_is_left:
            self._metrics.build_side_swaps += 1
        build_partition = left_partition if build_is_left else right_partition
        probe_partition = right_partition if build_is_left else left_partition
        build_positions = (
            self._left_positions if build_is_left else self._right_positions
        )
        probe_positions = (
            self._right_positions if build_is_left else self._left_positions
        )
        kernel = HashJoinKernel(
            context,
            build_positions=build_positions,
            probe_positions=probe_positions,
            key_types=self._key_types,
            label=f"join-l{left_partition.level}",
        )
        try:
            overflowed = False
            status["overflowed"] = False
            build_rows = self._partition_rows(build_partition)
            try:
                for row in build_rows:
                    if not kernel.admit_build(row):
                        overflowed = True
                        break
            finally:
                build_rows.close()
            if overflowed:
                # No output has been produced from this incomplete table.
                self._metrics.build_overflows += 1
                status["overflowed"] = True
                return
            probe_rows = self._partition_rows(probe_partition)
            try:
                for row in probe_rows:
                    for match in kernel.probe(row):
                        left_values = row.values if not build_is_left else match.values
                        right_values = match.values if not build_is_left else row.values
                        combined = self._emit(left_values, right_values)
                        if combined is not None:
                            yield combined
            finally:
                probe_rows.close()
            self._metrics.pairs_joined_by_hash += 1
        finally:
            kernel.release()

    def _block_nested_pair(
        self,
        left_partition: Partition,
        right_partition: Partition,
        context: ExecutionContext,
    ) -> Generator[Record, None, None]:
        """Join a skewed pair with a bounded block nested loop.

        Repeated occurrences of one key cannot be split by a different hash
        without breaking co-location, so hashing cannot rescue this pair. One
        admitted block of the left side is kept while the right side streams
        past it, and the Cartesian product of matching occurrences is emitted
        incrementally rather than collected.
        """

        self._metrics.fallback_pairs += 1
        self._metrics.fallback_rows += (
            left_partition.row_count + right_partition.row_count
        )
        reservation = context.reserve(CHUNK_PAYLOAD_SIZE, "join-block")
        try:
            block: list[Record] = []
            keys: list[tuple] = []
            left_rows = self._partition_rows(left_partition)
            try:
                for row in left_rows:
                    size = row_footprint_bytes(row)
                    if block and context.available_bytes < size:
                        yield from self._stream_against_block(
                            block, keys, right_partition
                        )
                        block = []
                        keys = []
                        reservation.release()
                        reservation = context.reserve(
                            CHUNK_PAYLOAD_SIZE, "join-block"
                        )
                    if context.available_bytes < size:
                        raise ValidationError(
                            f"A single join row needs {size} bytes but only "
                            f"{context.available_bytes} remain"
                        )
                    reservation.grow(size)
                    block.append(row)
                    keys.append(
                        join_key_of(
                            row.values, self._left_positions, self._key_types
                        )
                    )
                if block:
                    yield from self._stream_against_block(
                        block, keys, right_partition
                    )
            finally:
                left_rows.close()
        finally:
            reservation.release()

    def _stream_against_block(
        self,
        block: Sequence[Record],
        keys: Sequence[tuple],
        right_partition: Partition,
    ) -> Generator[Record, None, None]:
        right_rows = self._partition_rows(right_partition)
        try:
            for right in right_rows:
                right_key = join_key_of(
                    right.values, self._right_positions, self._key_types
                )
                for left, left_key in zip(block, keys):
                    if left_key != right_key:
                        continue
                    combined = self._emit(left.values, right.values)
                    if combined is not None:
                        yield combined
        finally:
            right_rows.close()

    def _pairs(self, context: ExecutionContext) -> Generator[Record, None, None]:
        left_parts = self._partition_side(
            self._left_rows(),
            schema=self._left.output_schema,
            positions=self._left_positions,
            level=0,
            context=context,
            label="jl",
        )
        right_parts = self._partition_side(
            self._right_rows(),
            schema=self._right.output_schema,
            positions=self._right_positions,
            level=0,
            context=context,
            label="jr",
        )
        pending = self._match_partitions(left_parts, right_parts)
        while pending:
            left_partition, right_partition = pending.pop()
            self._metrics.partition_pairs += 1
            # A pair may legitimately match nothing, so emptiness cannot stand
            # in for overflow: the kernel reports that explicitly.
            status: dict = {"overflowed": False}
            for row in self._join_pair(
                left_partition, right_partition, context, status
            ):
                yield row
            if not status["overflowed"]:
                self._release_pair(left_partition, right_partition)
                continue
            handled = self._retry_pair(left_partition, right_partition, context)
            if handled is None:
                yield from self._block_nested_pair(
                    left_partition, right_partition, context
                )
                self._release_pair(left_partition, right_partition)
                continue
            pending.extend(handled)
            self._release_pair(left_partition, right_partition)

    def _match_partitions(
        self,
        left_parts: dict[int, Partition],
        right_parts: dict[int, Partition],
    ) -> list[tuple[Partition, Partition]]:
        """Pair partitions by index and drop those with no counterpart.

        An inner join produces nothing for a partition whose counterpart is
        empty, so those files are released immediately instead of being read.
        """

        pairs = []
        for index, left_partition in left_parts.items():
            right_partition = right_parts.get(index)
            if right_partition is None:
                self._metrics.pairs_skipped_empty += 1
                self._workspace.discard(left_partition.path)
                continue
            pairs.append((left_partition, right_partition))
        for index, right_partition in right_parts.items():
            if index not in left_parts:
                self._metrics.pairs_skipped_empty += 1
                self._workspace.discard(right_partition.path)
        return pairs

    def _retry_pair(
        self,
        left_partition: Partition,
        right_partition: Partition,
        context: ExecutionContext,
    ) -> list[tuple[Partition, Partition]] | None:
        """Repartition both sides of an oversized pair, or report no progress."""

        if left_partition.level >= self._max_level:
            return None
        level = left_partition.level + 1
        left_children = self._partition_side(
            self._partition_rows(left_partition),
            schema=self._left.output_schema,
            positions=self._left_positions,
            level=level,
            context=context,
            label="jl",
        )
        right_children = self._partition_side(
            self._partition_rows(right_partition),
            schema=self._right.output_schema,
            positions=self._right_positions,
            level=level,
            context=context,
            label="jr",
        )
        self._metrics.repartitions += 1
        progressed = not (
            len(left_children) == 1
            and next(iter(left_children.values())).row_count
            == left_partition.row_count
        )
        if not progressed:
            for partition in list(left_children.values()) + list(
                right_children.values()
            ):
                self._workspace.discard(partition.path)
            return None
        return self._match_partitions(left_children, right_children)

    def _release_pair(self, left_partition: Partition, right_partition: Partition) -> None:
        self._workspace.discard(left_partition.path)
        self._workspace.discard(right_partition.path)

    def _open(self) -> None:
        context = self._join_context("grace-hash-join")
        allowed = maximum_partition_count(
            context.memory_budget_bytes, context.max_open_handles
        )
        if self._partition_count > allowed:
            raise ValidationError(
                f"A fan-out of {self._partition_count} partitions needs more "
                f"than the granted {context.memory_budget_bytes} bytes allow "
                f"({allowed})"
            )
        self._workspace = TemporaryWorkspace(label="ghj")
        self._metrics = GraceHashJoinMetrics()
        self._output = self._pairs(context)

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self._spec)),
            ("strategy", "grace hash join"),
            ("partition_pairs", str(self._metrics.partition_pairs)),
            ("repartitions", str(self._metrics.repartitions)),
            ("build_overflows", str(self._metrics.build_overflows)),
            ("nested_loop_fallbacks", str(self._metrics.fallback_pairs)),
        )
