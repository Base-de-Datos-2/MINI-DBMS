"""Predicate selection over a child row stream."""

from __future__ import annotations

from engine.errors import InvalidTypeError, ValidationError
from engine.catalog import DataType
from engine.storage.record import Record

from .base import ExecutionOperator
from .expressions import BoundExpression, Expression
from .rows import ColumnReference, RowLayout, RowProvenance


class Filter(ExecutionOperator):
    """Emit only the child rows whose predicate evaluates to TRUE.

    Filtering changes membership and nothing else: values, output schema and
    row occurrences are untouched, and duplicates are never collapsed. The
    predicate is bound during construction, so an unknown column or a type
    mismatch is reported while the plan is assembled rather than mid-stream.

    Only bounded state is kept. The operator pulls from its child until a row
    matches, and never accumulates a filtered list.
    """

    __slots__ = ("_child", "_expression", "_predicate")

    def __init__(self, child: ExecutionOperator, predicate: Expression) -> None:
        if not isinstance(child, ExecutionOperator):
            raise InvalidTypeError("Filter requires an ExecutionOperator child")
        if not isinstance(predicate, Expression):
            raise InvalidTypeError("Filter requires an Expression predicate")
        self._child = child
        self._expression = predicate
        self._predicate: BoundExpression = predicate.bind(child.layout)
        if self._predicate.data_type is not DataType.BOOLEAN:
            raise ValidationError(
                "A Filter predicate must be BOOLEAN, not "
                f"{self._predicate.data_type.value}"
            )
        super().__init__(children=(child,))

    def _build_layout(self) -> RowLayout:
        return self._child.layout

    @property
    def child(self) -> ExecutionOperator:
        """Return the child operator this filter consumes."""

        return self._child

    @property
    def predicate(self) -> Expression:
        """Return the declarative predicate this filter applies."""

        return self._expression

    @property
    def ordering(self) -> ColumnReference | None:
        """Return the child ordering; removing rows cannot disturb it."""

        return self._child.ordering

    def _next(self) -> Record | None:
        while (row := self._child.next()) is not None:
            self._statistics.rows_examined += 1
            if self._predicate.matches(row.values):
                self._provenance = self._child.provenance
                return row
        return None

    def _details(self) -> tuple[tuple[str, str], ...]:
        return (("predicate", repr(self._expression)),)
