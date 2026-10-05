"""Append scalar expressions while retaining the input row provenance."""

from engine.catalog import Column, Schema
from engine.errors import InvalidTypeError
from engine.storage.record import Record

from .base import ExecutionOperator
from .expressions import Expression
from .rows import RowLayout


def computed_layout(layout: RowLayout, expressions: tuple[tuple[str, Expression], ...]) -> RowLayout:
    fields = Schema([Column(name, expr.bind(layout).data_type) for name, expr in expressions])
    return RowLayout.combine(layout, RowLayout(fields))


class Compute(ExecutionOperator):
    __slots__ = ("_child", "_expressions", "_bound")

    def __init__(self, child: ExecutionOperator, expressions: tuple[tuple[str, Expression], ...]):
        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError("Compute requires an operator child")
        self._child = child
        self._expressions = expressions
        self._bound = tuple(expr.bind(child.layout) for _, expr in expressions)
        super().__init__(children=(child,))

    def _build_layout(self) -> RowLayout:
        return computed_layout(self._child.layout, self._expressions)

    @property
    def ordering(self):
        return self._child.ordering

    def _next(self) -> Record | None:
        row = self._child.next()
        if row is None:
            return None
        self._statistics.rows_examined += 1
        self._provenance = self._child.provenance
        computed = tuple(expr.evaluate(row.values) for expr in self._bound)
        return Record(self.output_schema, (*row.values, *computed))

    def _details(self) -> tuple[tuple[str, str], ...]:
        return tuple((name, repr(expr)) for name, expr in self._expressions)
