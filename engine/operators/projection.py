"""Column selection and output-schema construction over a child row stream."""

from __future__ import annotations

from collections.abc import Sequence

from engine.errors import InvalidTypeError, UnknownColumnError, ValidationError
from engine.storage.record import Record

from .base import ExecutionOperator
from .rows import ColumnReference, RowLayout


class Projection(ExecutionOperator):
    """Produce the selected columns, in the requested order, one row at a time.

    Projection is not DISTINCT: every input occurrence produces exactly one
    output row, even when the retained values make two rows look identical.

    Selections are resolved against the child layout during construction, so a
    plan that names an unknown or ambiguous column fails before it runs. The
    output schema is built from those selections and is independent of how the
    child physically stores its rows.
    """

    __slots__ = ("_child", "_selections", "_aliases", "_positions", "_ordering")

    def __init__(
        self,
        child: ExecutionOperator,
        selections: Sequence[object],
        aliases: Sequence[str | None] | None = None,
    ) -> None:
        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError("Projection requires an ExecutionOperator child")
        self._child = child
        self._selections = tuple(selections)
        self._aliases = None if aliases is None else tuple(aliases)
        super().__init__(children=(child,))
        self._positions = child.layout.positions(self._selections)
        self._ordering = self._surviving_ordering()

    def _build_layout(self) -> RowLayout:
        return self._child.layout.project(self._selections, self._aliases)

    def _surviving_ordering(self) -> ColumnReference | None:
        """Keep the child ordering only if that column survives projection.

        An ordering the output can no longer name is not reported. A later
        operator that needs the dropped key resolves it against this layout
        and fails there, which is the intended rejection of such a plan.
        """

        inherited = self._child.ordering
        if inherited is None:
            return None
        try:
            field = self.layout.field(inherited)
        except (UnknownColumnError, ValidationError):
            return None
        return field.reference

    @classmethod
    def select_all(cls, child: ExecutionOperator) -> "Projection":
        """Project every child column, preserving its declared order."""

        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError("Projection requires an ExecutionOperator child")
        return cls(child, [field.reference for field in child.layout])

    @property
    def child(self) -> ExecutionOperator:
        """Return the child operator this projection consumes."""

        return self._child

    @property
    def positions(self) -> tuple[int, ...]:
        """Return the pre-resolved child positions read for every row."""

        return self._positions

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the inherited ordering when its column survives projection."""

        return self._ordering

    def _next(self) -> Record | None:
        row = self._child.next()
        if row is None:
            return None
        self._statistics.rows_examined += 1
        values = row.values
        self._provenance = self._child.provenance
        return Record(
            self.output_schema, tuple(values[position] for position in self._positions)
        )

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("columns", ", ".join(column.name for column in self.output_schema)),
        )
