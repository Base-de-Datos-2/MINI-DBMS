"""Bounded aggregate state, hash-group kernel, and external hash grouping."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator, Sequence
from dataclasses import dataclass

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InsufficientBudgetError,
    InvalidTypeError,
    ValidationError,
)
from engine.storage.binary import INTEGER_MAX, INTEGER_MIN
from engine.storage.record import Record, RecordValue

from .base import ExecutionOperator
from .context import (
    ExecutionContext,
    operator_context,
    value_footprint_bytes,
)
from .expressions import compare_values, validate_comparable
from .partitioning import (
    DEFAULT_PARTITION_COUNT,
    MAX_PARTITION_LEVEL,
    HashPartitioner,
    Partition,
    maximum_partition_count,
)
from .rows import ColumnReference, LayoutField, RowLayout, as_reference
from .sorting import (
    MINIMUM_SORT_BUDGET_BYTES,
    ExternalSort,
    SortKey,
    SortSpec,
)
from .temp_files import TemporaryWorkspace, REGISTRY_WORK_BYTES, cleanup_preserving_error
from .temp_stream import TemporaryRowReader, TemporaryRun


#: Conservative per-group bookkeeping charged on top of key and state bytes.
#: A live group is a dictionary entry holding a key tuple and a state tuple,
#: none of which is free; the constant is a declared model, not a measurement.
GROUP_ENTRY_OVERHEAD_BYTES = 192

#: Smallest budget a grouping operator may be granted. The documented fallback
#: sorts a difficult partition, so the budget must be able to host that sort.
MINIMUM_GROUP_BUDGET_BYTES = MINIMUM_SORT_BUDGET_BYTES + REGISTRY_WORK_BYTES


class BoundAggregate(ABC):
    """An aggregate resolved against one input layout.

    State is a fixed shape per group, never a list of member rows, so a group
    with a million rows costs the same as a group with one.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def output_type(self) -> DataType:
        """Return the type of the finalized value."""

        raise NotImplementedError

    @abstractmethod
    def initialize(self) -> object:
        """Return the state of a group that has seen no rows yet."""

        raise NotImplementedError

    @abstractmethod
    def accumulate(self, state: object, values: Sequence[RecordValue]) -> object:
        """Return the state after folding in one row."""

        raise NotImplementedError

    @abstractmethod
    def merge(self, left: object, right: object) -> object:
        """Combine two partial states of the same group."""

        raise NotImplementedError

    @abstractmethod
    def finalize(self, state: object) -> RecordValue:
        """Return the value this aggregate publishes for a group."""

        raise NotImplementedError

    def state_bytes(self, state: object) -> int:
        """Return the accounted size of one group's state."""

        return 16


class Aggregate(ABC):
    """A declarative aggregate that must be bound before it can accumulate."""

    __slots__ = ("_alias",)

    def __init__(self, alias: str) -> None:
        if not isinstance(alias, str) or not alias.strip():
            raise ValidationError("An aggregate alias must be a non-empty string")
        self._alias = alias

    @property
    def alias(self) -> str:
        """Return the output column name this aggregate publishes."""

        return self._alias

    @abstractmethod
    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Resolve arguments and validate types against an input layout."""

        raise NotImplementedError


def _require_layout(layout: object) -> RowLayout:
    if not isinstance(layout, RowLayout):
        raise InvalidTypeError("Aggregates bind against a RowLayout")
    return layout


class _BoundCount(BoundAggregate):
    """Count rows; with no NULL in the model this is the only counting rule."""

    __slots__ = ()

    @property
    def output_type(self) -> DataType:
        """Counting always produces an INTEGER."""

        return DataType.INTEGER

    def initialize(self) -> int:
        """Start at zero rows."""

        return 0

    def accumulate(self, state: int, values: Sequence[RecordValue]) -> int:
        """Add one row."""

        return state + 1

    def merge(self, left: int, right: int) -> int:
        """Add two partial counts."""

        return left + right

    def finalize(self, state: int) -> int:
        """Return the count, rejecting an impossible out-of-range total."""

        if not INTEGER_MIN <= state <= INTEGER_MAX:
            raise ValidationError("COUNT exceeds the signed 64-bit range")
        return state


class Count(Aggregate):
    """``COUNT(*)``: the number of rows in each group."""

    __slots__ = ()

    def __init__(self, alias: str = "count") -> None:
        super().__init__(alias)

    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Return the bound counter; no column is referenced."""

        _require_layout(layout)
        return _BoundCount()

    def __repr__(self) -> str:
        """Show the aggregate and its output name."""

        return f"Count(alias={self._alias!r})"


class CountColumn(Aggregate):
    """``COUNT(column)``.

    The row model has no NULL, so every row contributes to a column count and
    the result equals ``COUNT(*)``. The two are kept as separate operations,
    and the column is still resolved and validated, so the distinction becomes
    meaningful the day NULL is introduced instead of being lost silently.
    """

    __slots__ = ("_column",)

    def __init__(self, column: object, alias: str | None = None) -> None:
        reference = as_reference(column)
        super().__init__(alias if alias is not None else f"count_{reference.name}")
        self._column = reference

    @property
    def column(self) -> ColumnReference:
        """Return the counted column reference."""

        return self._column

    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Validate the column exists, then count every row."""

        _require_layout(layout).field(self._column)
        return _BoundCount()

    def __repr__(self) -> str:
        """Show the counted column."""

        return f"CountColumn({self._column.qualified_name!r})"


class _BoundSum(BoundAggregate):
    __slots__ = ("_position", "_type")

    def __init__(self, position: int, data_type: DataType) -> None:
        self._position = position
        self._type = data_type

    @property
    def output_type(self) -> DataType:
        """A sum keeps the numeric type of its column."""

        return self._type

    def initialize(self) -> RecordValue:
        """Start at a typed zero, so an empty global sum is representable."""

        return 0 if self._type is DataType.INTEGER else 0.0

    def accumulate(self, state, values: Sequence[RecordValue]):
        """Add one value, refusing to wrap around the INTEGER range."""

        total = state + validate_comparable(self._type, values[self._position])
        return self._checked(total)

    def merge(self, left, right):
        """Add two partial sums."""

        return self._checked(left + right)

    def _checked(self, total):
        if self._type is DataType.INTEGER and not (
            INTEGER_MIN <= total <= INTEGER_MAX
        ):
            raise ValidationError(
                "SUM leaves the signed 64-bit INTEGER range; the result cannot "
                "be represented"
            )
        return total

    def finalize(self, state) -> RecordValue:
        """Return the accumulated total."""

        return state


class Sum(Aggregate):
    """``SUM(column)`` over a numeric column, in that column's type."""

    __slots__ = ("_column",)

    def __init__(self, column: object, alias: str | None = None) -> None:
        reference = as_reference(column)
        super().__init__(alias if alias is not None else f"sum_{reference.name}")
        self._column = reference

    @property
    def column(self) -> ColumnReference:
        """Return the summed column reference."""

        return self._column

    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Resolve the column and require a numeric type."""

        field = _require_layout(layout).field(self._column)
        if field.data_type not in (DataType.INTEGER, DataType.FLOAT):
            raise ValidationError(
                f"SUM requires a numeric column, not {field.data_type.value}"
            )
        return _BoundSum(field.position, field.data_type)

    def __repr__(self) -> str:
        """Show the summed column."""

        return f"Sum({self._column.qualified_name!r})"


class _BoundExtreme(BoundAggregate):
    __slots__ = ("_position", "_type", "_want_maximum")

    def __init__(self, position: int, data_type: DataType, want_maximum: bool) -> None:
        self._position = position
        self._type = data_type
        self._want_maximum = want_maximum

    @property
    def output_type(self) -> DataType:
        """An extreme keeps the type of its column."""

        return self._type

    def initialize(self) -> None:
        """Start with no value: an extreme is undefined before the first row."""

        return None

    def accumulate(self, state, values: Sequence[RecordValue]):
        """Keep whichever of the current state and the new value wins."""

        value = validate_comparable(self._type, values[self._position])
        if state is None:
            return value
        ordering = compare_values(self._type, value, state)
        if (ordering > 0) if self._want_maximum else (ordering < 0):
            return value
        return state

    def merge(self, left, right):
        """Combine two partial extremes, tolerating an empty side."""

        if left is None:
            return right
        if right is None:
            return left
        ordering = compare_values(self._type, left, right)
        if (ordering >= 0) if self._want_maximum else (ordering <= 0):
            return left
        return right

    def finalize(self, state) -> RecordValue:
        """Return the extreme, refusing to invent one for an empty input."""

        if state is None:
            raise ValidationError(
                "MIN and MAX are undefined over an empty input, and the row "
                "model has no NULL to represent that"
            )
        return state

    def state_bytes(self, state: object) -> int:
        """Charge the real width of the retained value."""

        if state is None:
            return 16
        return 16 + value_footprint_bytes(self._type, state)


class Min(Aggregate):
    """``MIN(column)`` over any comparable column."""

    __slots__ = ("_column",)
    _want_maximum = False

    def __init__(self, column: object, alias: str | None = None) -> None:
        reference = as_reference(column)
        prefix = "max" if self._want_maximum else "min"
        super().__init__(alias if alias is not None else f"{prefix}_{reference.name}")
        self._column = reference

    @property
    def column(self) -> ColumnReference:
        """Return the column this extreme reads."""

        return self._column

    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Resolve the column; every supported type is comparable."""

        field = _require_layout(layout).field(self._column)
        return _BoundExtreme(field.position, field.data_type, self._want_maximum)

    def __repr__(self) -> str:
        """Show the column and the direction."""

        return f"{type(self).__name__}({self._column.qualified_name!r})"


class Max(Min):
    """``MAX(column)`` over any comparable column."""

    __slots__ = ()
    _want_maximum = True


class _BoundAverage(BoundAggregate):
    __slots__ = ("_position", "_type")

    def __init__(self, position: int, data_type: DataType) -> None:
        self._position = position
        self._type = data_type

    @property
    def output_type(self) -> DataType:
        """An average is always a FLOAT, even over INTEGER input."""

        return DataType.FLOAT

    def initialize(self) -> tuple:
        """Track a running total and a row count, never a running average."""

        return (0 if self._type is DataType.INTEGER else 0.0, 0)

    def accumulate(self, state: tuple, values: Sequence[RecordValue]) -> tuple:
        """Fold one value into the total and count."""

        total, count = state
        return (total + validate_comparable(self._type, values[self._position]),
                count + 1)

    def merge(self, left: tuple, right: tuple) -> tuple:
        """Combine totals and counts.

        Averaging two averages would weight small and large groups equally and
        is never done here.
        """

        return (left[0] + right[0], left[1] + right[1])

    def finalize(self, state: tuple) -> float:
        """Divide the total by the count, refusing an empty average."""

        total, count = state
        if count == 0:
            raise ValidationError(
                "AVG is undefined over an empty input, and the row model has "
                "no NULL to represent that"
            )
        return total / count

    def state_bytes(self, state: object) -> int:
        """Charge a total and a count."""

        return 32


class Avg(Aggregate):
    """``AVG(column)`` over a numeric column, published as a FLOAT."""

    __slots__ = ("_column",)

    def __init__(self, column: object, alias: str | None = None) -> None:
        reference = as_reference(column)
        super().__init__(alias if alias is not None else f"avg_{reference.name}")
        self._column = reference

    @property
    def column(self) -> ColumnReference:
        """Return the averaged column reference."""

        return self._column

    def bind(self, layout: RowLayout) -> BoundAggregate:
        """Resolve the column and require a numeric type."""

        field = _require_layout(layout).field(self._column)
        if field.data_type not in (DataType.INTEGER, DataType.FLOAT):
            raise ValidationError(
                f"AVG requires a numeric column, not {field.data_type.value}"
            )
        return _BoundAverage(field.position, field.data_type)

    def __repr__(self) -> str:
        """Show the averaged column."""

        return f"Avg({self._column.qualified_name!r})"


def build_grouped_layout(
    source: RowLayout,
    group_keys: Sequence[ColumnReference],
    aggregates: Sequence[Aggregate],
) -> RowLayout:
    """Build the output layout of grouping: key columns, then aggregates.

    Group-key fields keep the origin of the column they came from, because
    their values really are those columns' values. Aggregate fields are
    derived and carry no relation, so a later reference cannot pretend a
    computed value still belongs to a stored column.
    """

    if not isinstance(source, RowLayout):
        raise InvalidTypeError("A grouped layout is built from a RowLayout")
    fields: list[LayoutField] = []
    names: list[str] = []
    for position, reference in enumerate(group_keys):
        field = source.field(reference)
        fields.append(
            LayoutField(position, field.name, field.data_type, field.relation)
        )
        names.append(source.published_name(field))
    bound = tuple(aggregate.bind(source) for aggregate in aggregates)
    for offset, (aggregate, resolved) in enumerate(zip(aggregates, bound)):
        fields.append(
            LayoutField(
                len(group_keys) + offset, aggregate.alias, resolved.output_type
            )
        )
        names.append(aggregate.alias)
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise ValidationError(
            "Grouped output would publish the same name twice: "
            + ", ".join(repr(name) for name in duplicated)
        )
    return RowLayout._build(fields, names)


class HashGroupKernel:
    """Aggregate one bounded segment of input in memory.

    Memory grows with the number of **distinct live groups**, not with the
    number of rows: a group that receives a million rows keeps one fixed-size
    state. Growth is reserved before it happens, and a reservation that cannot
    be granted is reported as capacity exhaustion rather than silently
    exceeding the budget.

    The internal dictionary is a bounded per-partition structure. It is not a
    substitute for the external algorithm: the partitioning above it is what
    keeps the whole operation within memory.
    """

    __slots__ = ("_context", "_positions", "_types", "_aggregates", "_groups",
                 "_reservation", "_label", "_released")

    def __init__(
        self,
        context: ExecutionContext,
        *,
        key_positions: Sequence[int],
        key_types: Sequence[DataType],
        aggregates: Sequence[BoundAggregate],
        label: str = "hash-group",
    ) -> None:
        if not isinstance(context, ExecutionContext):
            raise InvalidTypeError("A group kernel requires an ExecutionContext")
        self._context = context
        self._positions = tuple(key_positions)
        self._types = tuple(key_types)
        if len(self._positions) != len(self._types):
            raise ValidationError("Each grouping key position needs a data type")
        self._aggregates = tuple(aggregates)
        self._groups: dict[tuple, list] = {}
        self._reservation = context.reserve(0, label)
        self._label = label
        self._released = False

    @property
    def group_count(self) -> int:
        """Return how many distinct groups are currently live."""

        return len(self._groups)

    @property
    def reserved_bytes(self) -> int:
        """Return the memory this kernel currently accounts for."""

        return self._reservation.bytes

    def _key_of(self, values: Sequence[RecordValue]) -> tuple:
        return tuple(
            validate_comparable(data_type, values[position])
            for position, data_type in zip(self._positions, self._types)
        )

    def _key_bytes(self, key: tuple) -> int:
        return sum(
            value_footprint_bytes(data_type, value)
            for data_type, value in zip(self._types, key)
        )

    def admit(self, record: Record) -> bool:
        """Fold one row in, or report capacity exhaustion without consuming it.

        Returning False leaves this row unaccounted for **and unapplied**, so
        the caller can reprocess the whole segment from its source without
        double counting it.
        """

        if self._released:
            raise RuntimeError("A released group kernel cannot admit rows")
        if not isinstance(record, Record):
            raise InvalidTypeError("A group kernel requires a Record")
        values = record.values
        key = self._key_of(values)
        existing = self._groups.get(key)
        if existing is None:
            states = [aggregate.initialize() for aggregate in self._aggregates]
            entry_bytes = (
                self._key_bytes(key)
                + GROUP_ENTRY_OVERHEAD_BYTES
                + sum(
                    aggregate.state_bytes(state)
                    for aggregate, state in zip(self._aggregates, states)
                )
            )
            if self._context.available_bytes < entry_bytes:
                return False
            self._reservation.grow(entry_bytes)
            self._groups[key] = states
            existing = states
        # Compute first, charge second, commit last: a refused growth must not
        # leave a half-applied row behind.
        updated = [
            aggregate.accumulate(state, values)
            for aggregate, state in zip(self._aggregates, existing)
        ]
        delta = sum(
            aggregate.state_bytes(new) - aggregate.state_bytes(old)
            for aggregate, new, old in zip(self._aggregates, updated, existing)
        )
        if delta > 0:
            if self._context.available_bytes < delta:
                return False
            self._reservation.grow(delta)
        elif delta < 0:
            self._reservation.shrink(-delta)
        existing[:] = updated
        return True

    def results(self) -> Generator[tuple[tuple, tuple], None, None]:
        """Yield ``(key, finalized values)`` lazily, without copying the map."""

        if self._released:
            raise RuntimeError("A released group kernel has no results")
        for key, states in self._groups.items():
            yield key, tuple(
                aggregate.finalize(state)
                for aggregate, state in zip(self._aggregates, states)
            )

    def release(self) -> None:
        """Drop every group state and return the accounted memory."""

        if self._released:
            return
        self._released = True
        self._groups.clear()
        self._reservation.release()


@dataclass(slots=True)
class HashGroupMetrics:
    """Measured external-grouping work, separate from any expected cost."""

    rows_partitioned: int = 0
    bytes_partitioned: int = 0
    partitions_written: int = 0
    partitions_processed: int = 0
    repartitions: int = 0
    deepest_level: int = 0
    kernel_overflows: int = 0
    fallback_partitions: int = 0
    fallback_rows: int = 0
    groups_emitted: int = 0
    temporary_pages_written: int = 0
    temporary_pages_read: int = 0
    fallback_bytes_spilled: int = 0
    global_aggregation: bool = False


class _PartitionScan(ExecutionOperator):
    """Stream one partition file as an operator, for the sorting fallback."""

    __slots__ = ("_workspace", "_run", "_layout_source", "_reader", "_pages_read")

    def __init__(
        self,
        workspace: TemporaryWorkspace,
        run: TemporaryRun,
        layout: RowLayout,
    ) -> None:
        self._workspace = workspace
        self._run = run
        self._layout_source = layout
        self._reader: TemporaryRowReader | None = None
        self._pages_read = 0
        super().__init__()

    def _build_layout(self) -> RowLayout:
        return self._layout_source

    @property
    def pages_read(self) -> int:
        """Return real page reads performed so far."""

        return self._pages_read if self._reader is None else self._reader.pages_read

    def _open(self) -> None:
        self._reader = TemporaryRowReader(self._workspace, self._run)

    def _next(self) -> Record | None:
        return self._reader.next_row()

    def _close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            self._pages_read = reader.pages_read
            reader.close()


class ExternalHashGroup(ExecutionOperator):
    """Group rows with disk partitioning and bounded per-partition aggregation.

    The adopted route is partition-first: the complete grouping key decides a
    partition, every partition is closed before any is read, and each is then
    aggregated on its own. Because equal keys always land together, a group is
    finalized exactly once and never split across partitions.

    When a partition still holds more distinct groups than memory allows, its
    tentative state is discarded in full and the whole partition is
    repartitioned at a deeper level with a different seed. Discarding rather
    than keeping partial state is what makes double counting impossible.

    When repartitioning stops making progress, or the depth limit is reached,
    a bounded fallback sorts that partition by its grouping key and folds
    adjacent equal keys through a single group state. The fallback is reported
    in the metrics: it is never presented as hash-only execution.

    Grouped output is **unordered**. No ordering is advertised.
    """

    __slots__ = (
        "_child",
        "_group_keys",
        "_aggregate_specs",
        "_bound_aggregates",
        "_key_positions",
        "_key_types",
        "_budget",
        "_partition_count",
        "_max_level",
        "_owned_context",
        "_workspace",
        "_output",
        "_metrics",
    )

    memory_budget_minimum = MINIMUM_GROUP_BUDGET_BYTES

    def __init__(
        self,
        child: ExecutionOperator,
        group_keys: Sequence[object] = (),
        aggregates: Sequence[Aggregate] = (),
        *,
        memory_budget_bytes: int | None = None,
        partition_count: int = DEFAULT_PARTITION_COUNT,
        max_level: int = MAX_PARTITION_LEVEL,
    ) -> None:
        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError(
                "ExternalHashGroup requires an ExecutionOperator child"
            )
        if isinstance(group_keys, (str, bytes, bytearray)) or not isinstance(
            group_keys, Sequence
        ):
            raise InvalidTypeError("group_keys must be a sequence of column selectors")
        if isinstance(aggregates, (str, bytes, bytearray)) or not isinstance(
            aggregates, Sequence
        ):
            raise InvalidTypeError("aggregates must be a sequence of Aggregate")
        ordered_aggregates = tuple(aggregates)
        for aggregate in ordered_aggregates:
            if not isinstance(aggregate, Aggregate):
                raise InvalidTypeError("Every aggregate must be an Aggregate")
        if not ordered_aggregates:
            raise ValidationError(
                "Grouping requires at least one aggregate; DISTINCT is out of "
                "scope for this stage"
            )
        if memory_budget_bytes is not None:
            if type(memory_budget_bytes) is not int:
                raise InvalidTypeError("memory_budget_bytes must be an int")
            if memory_budget_bytes < MINIMUM_GROUP_BUDGET_BYTES:
                raise InsufficientBudgetError(
                    f"ExternalHashGroup needs at least {MINIMUM_GROUP_BUDGET_BYTES} "
                    f"bytes, got {memory_budget_bytes}"
                )
        if type(partition_count) is not int:
            raise InvalidTypeError("partition_count must be an int")
        if partition_count < 2:
            raise ValidationError("Partitioning needs at least two partitions")
        if type(max_level) is not int or max_level < 1:
            raise ValidationError("max_level must be a positive int")
        self._child = child
        self._group_keys = tuple(as_reference(key) for key in group_keys)
        self._aggregate_specs = ordered_aggregates
        self._bound_aggregates = tuple(
            aggregate.bind(child.layout) for aggregate in ordered_aggregates
        )
        fields = [child.layout.field(key) for key in self._group_keys]
        self._key_positions = tuple(field.position for field in fields)
        self._key_types = tuple(field.data_type for field in fields)
        self._budget = memory_budget_bytes
        self._partition_count = partition_count
        self._max_level = max_level
        self._owned_context: ExecutionContext | None = None
        self._workspace: TemporaryWorkspace | None = None
        self._output: Generator[Record, None, None] | None = None
        self._metrics = HashGroupMetrics()
        super().__init__(children=(child,))

    def _build_layout(self) -> RowLayout:
        return build_grouped_layout(
            self._child.layout, self._group_keys, self._aggregate_specs
        )

    @property
    def child(self) -> ExecutionOperator:
        """Return the child operator this grouping consumes."""

        return self._child

    @property
    def group_keys(self) -> tuple[ColumnReference, ...]:
        """Return the grouping key references."""

        return self._group_keys

    @property
    def aggregates(self) -> tuple[Aggregate, ...]:
        """Return the declared aggregates in output order."""

        return self._aggregate_specs

    @property
    def metrics(self) -> HashGroupMetrics:
        """Return the measured partitioning and fallback counters."""

        return self._metrics

    def _grouping_context(self) -> ExecutionContext:
        owned = operator_context(
            self.context,
            requested=self._budget,
            minimum=MINIMUM_GROUP_BUDGET_BYTES,
            label="hash-group",
        )
        allowed = maximum_partition_count(
            owned.memory_budget_bytes, owned.max_open_handles
        )
        if self._group_keys and self._partition_count > allowed:
            granted = owned.memory_budget_bytes
            owned.close()
            raise InsufficientBudgetError(
                f"A fan-out of {self._partition_count} partitions needs more "
                f"than the granted {granted} bytes allow ({allowed})"
            )
        self._owned_context = owned
        return owned

    def _emit(self, key: tuple, finalized: tuple) -> Record:
        self._metrics.groups_emitted += 1
        return Record(self.output_schema, key + finalized)

    def _global_aggregate(
        self,
        context: ExecutionContext,
    ) -> Generator[Record, None, None]:
        """Aggregate the whole input into one row with constant-size state.

        With no grouping key there is exactly one state, so no partitioning is
        needed: this path is bounded by construction, not by a spill.
        """

        self._metrics.global_aggregation = True
        states = [aggregate.initialize() for aggregate in self._bound_aggregates]
        while (row := self._child.next()) is not None:
            self._statistics.rows_examined += 1
            states = [
                aggregate.accumulate(state, row.values)
                for aggregate, state in zip(self._bound_aggregates, states)
            ]
        finalized = tuple(
            aggregate.finalize(state)
            for aggregate, state in zip(self._bound_aggregates, states)
        )
        yield self._emit((), finalized)

    def _partition(
        self,
        rows,
        *,
        level: int,
        context: ExecutionContext,
    ) -> tuple[Partition, ...]:
        partitioner = HashPartitioner(
            self._workspace,
            self.child.output_schema,
            key_positions=self._key_positions,
            key_types=self._key_types,
            partition_count=self._partition_count,
            level=level,
            context=context,
        )
        try:
            for row in rows:
                partitioner.write(row)
            partitions = partitioner.finish()
        except BaseException:
            cleanup_preserving_error(partitioner.close)
            raise
        self._metrics.partitions_written += len(partitions)
        self._metrics.bytes_partitioned += sum(
            partition.byte_length for partition in partitions
        )
        self._metrics.temporary_pages_written += partitioner.pages_written
        self._metrics.deepest_level = max(self._metrics.deepest_level, level)
        return partitions

    def _child_rows(self) -> Generator[Record, None, None]:
        while (row := self._child.next()) is not None:
            self._statistics.rows_examined += 1
            self._metrics.rows_partitioned += 1
            yield row

    def _partition_rows(self, partition: Partition) -> Generator[Record, None, None]:
        reader = TemporaryRowReader(self._workspace, partition.run)
        try:
            while (row := reader.next_row()) is not None:
                yield row
        finally:
            try:
                cleanup_preserving_error(reader.close)
            finally:
                self._metrics.temporary_pages_read += reader.pages_read

    def _aggregate_partition(
        self,
        partition: Partition,
        context: ExecutionContext,
    ) -> Generator[Record, None, None]:
        """Aggregate one partition, or report that it did not fit."""

        kernel = HashGroupKernel(
            context,
            key_positions=self._key_positions,
            key_types=self._key_types,
            aggregates=self._bound_aggregates,
            label=f"group-l{partition.level}",
        )
        overflowed = False
        try:
            rows = self._partition_rows(partition)
            try:
                for row in rows:
                    if not kernel.admit(row):
                        overflowed = True
                        break
            finally:
                rows.close()
            if overflowed:
                # The tentative state of this attempt is dropped in full; the
                # partition file is still the complete truth for these rows.
                self._metrics.kernel_overflows += 1
                return
            for key, finalized in kernel.results():
                yield self._emit(key, finalized)
            self._metrics.partitions_processed += 1
        finally:
            kernel.release()

    def _sorted_fallback(
        self,
        partition: Partition,
        context: ExecutionContext,
    ) -> Generator[Record, None, None]:
        """Aggregate a difficult partition by sorting it on its grouping key.

        This always terminates and needs one group state at a time, so it is
        the bounded correctness route for a partition that further hashing
        cannot split. It is counted separately and never presented as the
        hash-based optimization.
        """

        self._metrics.fallback_partitions += 1
        self._metrics.fallback_rows += partition.row_count
        scan = _PartitionScan(self._workspace, partition.run, self._child.layout)
        spec = SortSpec([SortKey(key) for key in self._group_keys])
        # The sort's supported row width depends on its grant. Reuse the
        # available partition budget instead of always forcing the smallest
        # sort, which would reject wide rows even when this context can fit them.
        sort = ExternalSort(scan, spec, memory_budget_bytes=context.available_bytes)
        sort.open(context)
        try:
            current_key: tuple | None = None
            states: list | None = None
            while (row := sort.next()) is not None:
                key = tuple(
                    validate_comparable(data_type, row.values[position])
                    for position, data_type in zip(self._key_positions, self._key_types)
                )
                if states is None or key != current_key:
                    if states is not None:
                        yield self._emit(
                            current_key,
                            tuple(
                                aggregate.finalize(state)
                                for aggregate, state in zip(
                                    self._bound_aggregates, states
                                )
                            ),
                        )
                    current_key = key
                    states = [
                        aggregate.initialize() for aggregate in self._bound_aggregates
                    ]
                states = [
                    aggregate.accumulate(state, row.values)
                    for aggregate, state in zip(self._bound_aggregates, states)
                ]
            if states is not None:
                yield self._emit(
                    current_key,
                    tuple(
                        aggregate.finalize(state)
                        for aggregate, state in zip(self._bound_aggregates, states)
                    ),
                )
        finally:
            try:
                cleanup_preserving_error(sort.close)
            finally:
                self._metrics.temporary_pages_read += (
                    scan.pages_read + sort.metrics.temporary_pages_read
                )
                self._metrics.temporary_pages_written += (
                    sort.metrics.temporary_pages_written
                )
                self._metrics.fallback_bytes_spilled += sort.metrics.bytes_spilled

    def _grouped(self, context: ExecutionContext) -> Generator[Record, None, None]:
        pending = list(
            self._partition(self._child_rows(), level=0, context=context)
        )
        while pending:
            partition = pending.pop()
            produced_any = False
            for row in self._aggregate_partition(partition, context):
                produced_any = True
                yield row
            if produced_any or partition.row_count == 0:
                self._workspace.discard(partition.path)
                continue
            # The kernel could not hold this partition. Either split it again
            # with a different seed, or fall back to a bounded sort.
            if partition.level >= self._max_level:
                yield from self._sorted_fallback(partition, context)
                self._workspace.discard(partition.path)
                continue
            children = self._partition(
                self._partition_rows(partition),
                level=partition.level + 1,
                context=context,
            )
            self._metrics.repartitions += 1
            if len(children) == 1 and children[0].row_count == partition.row_count:
                # No progress: every row landed in one child again, so hashing
                # deeper cannot help this key distribution.
                for child in children:
                    self._workspace.discard(child.path)
                yield from self._sorted_fallback(partition, context)
                self._workspace.discard(partition.path)
                continue
            pending.extend(children)
            # Children are complete files now, so the parent can go.
            self._workspace.discard(partition.path)

    def _open(self) -> None:
        context = self._grouping_context()
        self._workspace = TemporaryWorkspace(label="group", context=context)
        self._metrics = HashGroupMetrics()
        if not self._group_keys:
            self._output = self._global_aggregate(context)
        else:
            self._output = self._grouped(context)

    def _next(self) -> Record | None:
        return next(self._output, None)

    def _close(self) -> None:
        output, self._output = self._output, None
        workspace, self._workspace = self._workspace, None
        owned, self._owned_context = self._owned_context, None
        try:
            if output is not None:
                cleanup_preserving_error(output.close)
        finally:
            try:
                if workspace is not None:
                    cleanup_preserving_error(workspace.close)
            finally:
                if owned is not None:
                    cleanup_preserving_error(owned.close)

    def _details(self) -> tuple[tuple[str, str], ...]:
        keys = ", ".join(key.qualified_name for key in self._group_keys) or "(global)"
        return (
            ("keys", keys),
            ("aggregates", ", ".join(a.alias for a in self._aggregate_specs)),
            ("strategy", "global state" if not self._group_keys else "hash partitions"),
            ("partitions", str(self._metrics.partitions_written)),
            ("repartitions", str(self._metrics.repartitions)),
            ("sorted_fallbacks", str(self._metrics.fallback_partitions)),
        )
