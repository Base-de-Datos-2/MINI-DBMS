"""Bounded streaming output without consuming the remaining input."""

from engine.errors import InvalidTypeError, ValidationError
from engine.storage.record import Record

from .base import ExecutionOperator
from .rows import RowLayout


class Limit(ExecutionOperator):
    __slots__ = ("_child", "_limit", "_count")

    def __init__(self, child: ExecutionOperator, limit: int) -> None:
        if not isinstance(child, ExecutionOperator) or type(limit) is not int:
            raise InvalidTypeError("Limit requires an operator and an integer")
        if limit < 0:
            raise ValidationError("Limit cannot be negative")
        self._child = child
        self._limit = limit
        self._count = 0
        super().__init__(children=(child,))

    def _build_layout(self) -> RowLayout:
        return self._child.layout

    @property
    def ordering(self):
        return self._child.ordering

    def _next(self) -> Record | None:
        if self._count >= self._limit:
            return None
        row = self._child.next()
        if row is not None:
            self._count += 1
            self._statistics.rows_examined += 1
            self._provenance = self._child.provenance
        return row

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (("limit", str(self._limit)),)
