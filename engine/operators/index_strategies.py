"""Optional index-assisted execution routes with explicit preconditions."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from dataclasses import dataclass

from engine.errors import (
    InvalidTypeError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.indexes.base import Index, OrderedIndex
from engine.storage.base import Storage
from engine.storage.record import Record, RecordValue

from .aggregation import Aggregate, build_grouped_layout
from .base import ExecutionOperator
from .expressions import BoundExpression, Expression, validate_comparable
from .join import JoinSpec, join_key_of
from .rows import ColumnReference, RowLayout, RowProvenance, as_reference
from .scan import index_storage


def _require_index_key(index: Index, reference: ColumnReference) -> str:
    """Check a reference names exactly the single column this index covers."""

    key_column = getattr(index, "key_column", None)
    if not isinstance(key_column, str):
        raise ValidationError(
            "An index-assisted route requires an index adapter that exposes "
            "its key column"
        )
    if reference.name != key_column:
        raise UnsupportedAccessError(
            f"This index covers {key_column!r}, not {reference.name!r}; an "
            "index is only usable when it covers the whole access key"
        )
    return key_column


@dataclass(slots=True)
class IndexJoinMetrics:
    """Measured work of an index-probing join."""

    outer_rows: int = 0
    index_probes: int = 0
    probes_without_match: int = 0
    inner_rows_fetched: int = 0
    pairs_emitted: int = 0


class IndexNestedLoopJoin(ExecutionOperator):
    """Join by probing a persistent inner index once per outer row.

    This route is **optional**. It is offered because the project already has
    persistent B+ and Extendible Hash indexes, not because the assignment's
    join requirement needs it: that requirement is satisfied by
    :class:`~engine.operators.join.GraceHashJoin`.

    Its preconditions are explicit and checked when the plan is built: the
    join must be a single equality pair, and its inner side must be exactly
    the column the supplied index covers. An index that merely exists over
    some other column is refused rather than silently ignored.

    No cache of probe keys is kept. Each outer row probes the index, matching
    inner records stream back one at a time, and the adapter's own staleness
    checks reject a RID whose stored key no longer matches.
    """

    __slots__ = (
        "_outer",
        "_index",
        "_storage",
        "_relation",
        "_spec",
        "_outer_position",
        "_key_type",
        "_residual_expression",
        "_residual",
        "_metrics",
        "_cursor",
    )

    def __init__(
        self,
        outer: ExecutionOperator,
        index: Index,
        spec: JoinSpec,
        *,
        relation: str,
        residual: Expression | None = None,
    ) -> None:
        if not isinstance(outer, ExecutionOperator):
            raise InvalidTypeError(
                "IndexNestedLoopJoin requires an ExecutionOperator outer input"
            )
        if not isinstance(index, Index):
            raise InvalidTypeError("IndexNestedLoopJoin requires an Index")
        if not isinstance(spec, JoinSpec):
            raise InvalidTypeError("IndexNestedLoopJoin requires a JoinSpec")
        if len(spec.keys) != 1:
            raise ValidationError(
                "An index probe covers one equality column; this join declares "
                f"{len(spec.keys)} key pairs"
            )
        if residual is not None and not isinstance(residual, Expression):
            raise InvalidTypeError("A join residual must be an Expression")
        self._outer = outer
        self._index = index
        self._storage = index_storage(index)
        self._relation = as_reference(relation).name
        self._spec = spec
        self._residual_expression = residual
        self._metrics = IndexJoinMetrics()
        self._cursor: Generator[Record, None, None] | None = None
        key = spec.keys[0]
        _require_index_key(index, key.right)
        outer_field = outer.layout.field(key.left)
        inner_field = RowLayout(
            self._storage.schema, relation=self._relation
        ).field(key.right)
        if outer_field.data_type is not inner_field.data_type:
            raise ValidationError(
                f"Cannot join {outer_field.data_type.value} with "
                f"{inner_field.data_type.value}; no implicit conversion is "
                "performed"
            )
        self._outer_position = outer_field.position
        self._key_type = outer_field.data_type
        super().__init__(children=(outer,))
        self._residual: BoundExpression | None = (
            None if residual is None else residual.bind(self.layout)
        )
        if self._residual is not None and self._residual.data_type.value != "BOOLEAN":
            raise ValidationError(
                "A join residual must be BOOLEAN, not "
                f"{self._residual.data_type.value}"
            )

    def _build_layout(self) -> RowLayout:
        return RowLayout.combine(
            self._outer.layout,
            RowLayout(self._storage.schema, relation=self._relation),
        )

    @property
    def outer(self) -> ExecutionOperator:
        """Return the streamed outer input."""

        return self._outer

    @property
    def index(self) -> Index:
        """Return the borrowed inner index this join probes."""

        return self._index

    @property
    def metrics(self) -> IndexJoinMetrics:
        """Return the measured probe counters."""

        return self._metrics

    def _pairs(self) -> Generator[Record, None, None]:
        while (outer := self._outer.next()) is not None:
            self._statistics.rows_examined += 1
            self._metrics.outer_rows += 1
            key = validate_comparable(
                self._key_type, outer.values[self._outer_position]
            )
            self._metrics.index_probes += 1
            matched = False
            matches = self._index.search_records(key)
            try:
                for rid, inner in matches:
                    matched = True
                    self._metrics.inner_rows_fetched += 1
                    values = outer.values + inner.values
                    if self._residual is not None and not self._residual.matches(
                        values
                    ):
                        continue
                    self._metrics.pairs_emitted += 1
                    self._provenance = self._outer.provenance + (
                        RowProvenance(self._relation, rid),
                    )
                    yield Record(self.output_schema, values)
            finally:
                matches.close()
            if not matched:
                self._metrics.probes_without_match += 1

    def _open(self) -> None:
        self._metrics = IndexJoinMetrics()
        self._cursor = self._pairs()

    def _next(self) -> Record | None:
        return next(self._cursor, None)

    def _close(self) -> None:
        cursor, self._cursor = self._cursor, None
        if cursor is not None:
            cursor.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self._spec)),
            ("strategy", "index nested loop"),
            ("index", type(self._index).__name__),
            ("inner_relation", self._relation),
            ("index_probes", str(self._metrics.index_probes)),
        )


@dataclass(slots=True)
class IndexGroupMetrics:
    """Measured work of an ordered-index grouping traversal."""

    rows_read: int = 0
    groups_emitted: int = 0
    entry_count: int = 0
    record_count: int = 0


class IndexOrderedGroup(ExecutionOperator):
    """Group by walking a B+ index whose order matches the grouping key.

    This route is **optional**; the assignment's grouping requirement is
    satisfied by :class:`~engine.operators.aggregation.ExternalHashGroup`.
    Its advantage is that it needs one group's state at a time and produces
    groups already ascending by their key, so no sort is needed afterwards.

    Its preconditions are explicit and are verified, not assumed:

    * the index must be ordered. A hash index has no order and is refused;
    * the index must cover exactly the complete grouping key;
    * the index must contain one entry per live row of its storage. A partial
      index would silently drop rows from the result, so the counts are
      compared when the run opens and a mismatch is an error.

    Non-indexed columns needed by the aggregates are fetched from storage
    through the adapter, so no index-only coverage is invented.
    """

    __slots__ = (
        "_index",
        "_storage",
        "_relation",
        "_group_keys",
        "_aggregate_specs",
        "_bound_aggregates",
        "_key_position",
        "_key_type",
        "_metrics",
        "_cursor",
        "_source_layout",
    )

    def __init__(
        self,
        index: OrderedIndex,
        group_keys: Sequence[object],
        aggregates: Sequence[Aggregate],
        *,
        relation: str,
    ) -> None:
        if not isinstance(index, Index):
            raise InvalidTypeError("IndexOrderedGroup requires an Index")
        if not isinstance(index, OrderedIndex):
            raise UnsupportedAccessError(
                "Ordered grouping requires an ordered index; a hash index "
                "provides equality access only and yields no group order"
            )
        if isinstance(group_keys, (str, bytes, bytearray)) or not isinstance(
            group_keys, Sequence
        ):
            raise InvalidTypeError("group_keys must be a sequence of column selectors")
        keys = tuple(as_reference(key) for key in group_keys)
        if len(keys) != 1:
            raise ValidationError(
                "This index covers one column, so it can only serve a "
                f"single-column grouping key; {len(keys)} were given"
            )
        ordered_aggregates = tuple(aggregates)
        for aggregate in ordered_aggregates:
            if not isinstance(aggregate, Aggregate):
                raise InvalidTypeError("Every aggregate must be an Aggregate")
        if not ordered_aggregates:
            raise ValidationError("Grouping requires at least one aggregate")
        self._index = index
        self._storage = index_storage(index)
        self._relation = as_reference(relation).name
        self._group_keys = keys
        self._aggregate_specs = ordered_aggregates
        _require_index_key(index, keys[0])
        self._source_layout = RowLayout(
            self._storage.schema, relation=self._relation
        )
        field = self._source_layout.field(keys[0])
        self._key_position = field.position
        self._key_type = field.data_type
        self._bound_aggregates = tuple(
            aggregate.bind(self._source_layout) for aggregate in ordered_aggregates
        )
        self._metrics = IndexGroupMetrics()
        self._cursor: Generator[Record, None, None] | None = None
        super().__init__()

    def _build_layout(self) -> RowLayout:
        return build_grouped_layout(
            RowLayout(self._storage.schema, relation=self._relation),
            self._group_keys,
            self._aggregate_specs,
        )

    @property
    def index(self) -> OrderedIndex:
        """Return the borrowed index this grouping traverses."""

        return self._index

    @property
    def metrics(self) -> IndexGroupMetrics:
        """Return the measured traversal counters."""

        return self._metrics

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the group key: a B+ traversal really is ascending by it."""

        return self.layout.field(self._group_keys[0]).reference

    def _verify_coverage(self) -> None:
        """Refuse a partial index instead of silently dropping rows."""

        entry_count = getattr(self._index, "entry_count", None)
        record_count = getattr(self._storage, "record_count", None)
        if not isinstance(entry_count, int) or not isinstance(record_count, int):
            raise ValidationError(
                "Ordered grouping needs comparable index and storage counts to "
                "verify that the index covers every row"
            )
        self._metrics.entry_count = entry_count
        self._metrics.record_count = record_count
        if entry_count != record_count:
            raise ValidationError(
                f"This index holds {entry_count} entries for {record_count} "
                "stored rows, so it does not cover the whole table; grouping "
                "through it would lose rows"
            )

    def _groups(self) -> Generator[Record, None, None]:
        current: RecordValue | None = None
        states: list | None = None
        matches = self._index.range_records()
        try:
            for _, record in matches:
                self._metrics.rows_read += 1
                self._statistics.rows_examined += 1
                key = validate_comparable(
                    self._key_type, record.values[self._key_position]
                )
                if states is None or key != current:
                    if states is not None:
                        yield self._emit(current, states)
                    current = key
                    states = [
                        aggregate.initialize() for aggregate in self._bound_aggregates
                    ]
                states = [
                    aggregate.accumulate(state, record.values)
                    for aggregate, state in zip(self._bound_aggregates, states)
                ]
            if states is not None:
                yield self._emit(current, states)
        finally:
            matches.close()

    def _emit(self, key: RecordValue, states: Sequence) -> Record:
        self._metrics.groups_emitted += 1
        return Record(
            self.output_schema,
            (key,)
            + tuple(
                aggregate.finalize(state)
                for aggregate, state in zip(self._bound_aggregates, states)
            ),
        )

    def _open(self) -> None:
        self._metrics = IndexGroupMetrics()
        self._verify_coverage()
        self._cursor = self._groups()

    def _next(self) -> Record | None:
        return next(self._cursor, None)

    def _close(self) -> None:
        cursor, self._cursor = self._cursor, None
        if cursor is not None:
            cursor.close()

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("keys", self._group_keys[0].qualified_name),
            ("aggregates", ", ".join(a.alias for a in self._aggregate_specs)),
            ("strategy", "ordered index traversal"),
            ("index", type(self._index).__name__),
            ("rows_read", str(self._metrics.rows_read)),
            ("ordered_by", self._group_keys[0].name),
        )
