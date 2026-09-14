"""Bound typed predicates and value expressions, with no SQL text or eval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from enum import Enum
import math

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.record import Record, RecordValue

from .rows import ColumnReference, RowLayout, as_reference


_PYTHON_TYPES = {
    DataType.INTEGER: int,
    DataType.FLOAT: float,
    DataType.BOOLEAN: bool,
    DataType.VARCHAR: str,
}

_LITERAL_TYPES = (
    (bool, DataType.BOOLEAN),
    (int, DataType.INTEGER),
    (float, DataType.FLOAT),
    (str, DataType.VARCHAR),
)


def data_type_of(value: object) -> DataType:
    """Return the DataType a Python value denotes, without any coercion.

    ``bool`` is checked before ``int`` because Python's bool is an int
    subclass, and the engine's typing policy keeps them distinct everywhere.
    """

    for python_type, data_type in _LITERAL_TYPES:
        if type(value) is python_type:
            return data_type
    raise InvalidTypeError(
        f"Unsupported literal type: {type(value).__name__}; "
        "NULL and non-scalar values are not supported"
    )


def validate_comparable(data_type: DataType, value: RecordValue) -> RecordValue:
    """Check a value may take part in comparison, grouping, or ordering.

    Rejects NaN, which has no reflexive equality and would make a predicate,
    a hash bucket, and a sort order disagree about the same row. The rule is
    the one the B+ and hash key codecs already apply, but it deliberately
    omits their index-specific encoded-size limits: a WHERE clause may
    compare a string longer than any indexable key.
    """

    if not isinstance(data_type, DataType):
        raise InvalidTypeError("data_type must be a DataType")
    expected = _PYTHON_TYPES[data_type]
    if type(value) is not expected:
        raise InvalidTypeError(
            f"{data_type.value} requires {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    if data_type is DataType.FLOAT and math.isnan(value):
        raise ValidationError("NaN cannot be compared, grouped, or ordered")
    return value


def compare_values(
    data_type: DataType,
    left: RecordValue,
    right: RecordValue,
) -> int:
    """Return -1, 0 or 1 for two values of the same declared type.

    Ordering is the native ordering of the Python type: signed numeric order
    with ``-0.0 == 0.0``, ``False < True``, and case-sensitive Unicode order
    for VARCHAR. It agrees with the index comparison used by B+ traversal on
    every value that is a legal index key.
    """

    checked_left = validate_comparable(data_type, left)
    checked_right = validate_comparable(data_type, right)
    return (checked_left > checked_right) - (checked_left < checked_right)


class ComparisonOperator(Enum):
    """The comparison subset approved for Stage 6 predicates."""

    EQUAL = "="
    NOT_EQUAL = "<>"
    LESS = "<"
    LESS_OR_EQUAL = "<="
    GREATER = ">"
    GREATER_OR_EQUAL = ">="

    def satisfied_by(self, ordering: int) -> bool:
        """Map a -1/0/1 comparison result onto this operator's truth value."""

        if self is ComparisonOperator.EQUAL:
            return ordering == 0
        if self is ComparisonOperator.NOT_EQUAL:
            return ordering != 0
        if self is ComparisonOperator.LESS:
            return ordering < 0
        if self is ComparisonOperator.LESS_OR_EQUAL:
            return ordering <= 0
        if self is ComparisonOperator.GREATER:
            return ordering > 0
        return ordering >= 0


class BoundExpression(ABC):
    """An expression already resolved against one input layout.

    Binding happens once per run, before any row is read, so type errors and
    unknown columns surface during ``open``. Evaluation then only reads
    pre-resolved positions and never inspects a schema again.
    """

    __slots__ = ()

    @property
    @abstractmethod
    def data_type(self) -> DataType:
        """Return the declared type of the value this expression produces."""

        raise NotImplementedError

    @abstractmethod
    def evaluate(self, values: Sequence[RecordValue]) -> RecordValue:
        """Compute the expression over one row's values in layout order."""

        raise NotImplementedError

    def evaluate_record(self, record: Record) -> RecordValue:
        """Evaluate against a Record whose values follow the bound layout."""

        if not isinstance(record, Record):
            raise InvalidTypeError("evaluate_record requires a Record")
        return self.evaluate(record.values)

    def matches(self, values: Sequence[RecordValue]) -> bool:
        """Evaluate as a predicate, requiring a BOOLEAN result.

        There is no NULL in the row model, so a predicate over valid rows is
        TRUE or FALSE and Filter keeps only TRUE. No UNKNOWN state exists.
        """

        if self.data_type is not DataType.BOOLEAN:
            raise ValidationError(
                f"A predicate must be BOOLEAN, not {self.data_type.value}"
            )
        result = self.evaluate(values)
        if type(result) is not bool:
            raise InvalidTypeError("A predicate must evaluate to a bool")
        return result


class Expression(ABC):
    """A declarative expression that must be bound before it can be evaluated."""

    __slots__ = ()

    @abstractmethod
    def bind(self, layout: RowLayout) -> BoundExpression:
        """Resolve references and validate types against an input layout."""

        raise NotImplementedError


def _require_layout(layout: object) -> RowLayout:
    if not isinstance(layout, RowLayout):
        raise InvalidTypeError("Expressions bind against a RowLayout")
    return layout


class _BoundLiteral(BoundExpression):
    __slots__ = ("_value", "_data_type")

    def __init__(self, value: RecordValue, data_type: DataType) -> None:
        self._value = value
        self._data_type = data_type

    @property
    def data_type(self) -> DataType:
        """Return the literal's inferred type."""

        return self._data_type

    def evaluate(self, values: Sequence[RecordValue]) -> RecordValue:
        """Return the constant, ignoring the row."""

        return self._value


class Literal(Expression):
    """A constant of one of the four supported types."""

    __slots__ = ("_value", "_data_type")

    def __init__(self, value: RecordValue) -> None:
        self._data_type = data_type_of(value)
        if self._data_type is DataType.FLOAT and math.isnan(value):
            raise ValidationError("NaN is not a usable literal")
        self._value = value

    @property
    def value(self) -> RecordValue:
        """Return the constant this literal carries."""

        return self._value

    @property
    def data_type(self) -> DataType:
        """Return the inferred type of the constant."""

        return self._data_type

    def bind(self, layout: RowLayout) -> BoundExpression:
        """Return a bound literal; the layout is validated but unused."""

        _require_layout(layout)
        return _BoundLiteral(self._value, self._data_type)

    def __repr__(self) -> str:
        """Show the constant value."""

        return f"Literal({self._value!r})"


class _BoundColumn(BoundExpression):
    __slots__ = ("_position", "_data_type")

    def __init__(self, position: int, data_type: DataType) -> None:
        self._position = position
        self._data_type = data_type

    @property
    def position(self) -> int:
        """Return the pre-resolved position this reference reads."""

        return self._position

    @property
    def data_type(self) -> DataType:
        """Return the referenced column's declared type."""

        return self._data_type

    def evaluate(self, values: Sequence[RecordValue]) -> RecordValue:
        """Read the bound position out of one row."""

        try:
            return values[self._position]
        except IndexError as error:
            raise ValidationError(
                "Row is narrower than the layout the expression was bound to"
            ) from error


class ColumnValue(Expression):
    """A reference to one input column, optionally qualified by relation."""

    __slots__ = ("_reference",)

    def __init__(self, reference: object) -> None:
        self._reference = as_reference(reference)

    @property
    def reference(self) -> ColumnReference:
        """Return the column reference this expression resolves."""

        return self._reference

    def bind(self, layout: RowLayout) -> BoundExpression:
        """Resolve the reference to a position, rejecting unknown or ambiguous."""

        resolved = _require_layout(layout).field(self._reference)
        return _BoundColumn(resolved.position, resolved.data_type)

    def __repr__(self) -> str:
        """Show the qualified column identity."""

        return f"ColumnValue({self._reference.qualified_name!r})"


class _BoundComparison(BoundExpression):
    __slots__ = ("_left", "_operator", "_right", "_operand_type")

    def __init__(
        self,
        left: BoundExpression,
        operator: ComparisonOperator,
        right: BoundExpression,
        operand_type: DataType,
    ) -> None:
        self._left = left
        self._operator = operator
        self._right = right
        self._operand_type = operand_type

    @property
    def data_type(self) -> DataType:
        """A comparison always produces a BOOLEAN."""

        return DataType.BOOLEAN

    def evaluate(self, values: Sequence[RecordValue]) -> bool:
        """Compare both operands under the shared comparison semantics."""

        ordering = compare_values(
            self._operand_type,
            self._left.evaluate(values),
            self._right.evaluate(values),
        )
        return self._operator.satisfied_by(ordering)


class Compare(Expression):
    """Compare two same-typed operands with an approved operator.

    Both sides must share a declared type: INTEGER and FLOAT are not compared
    to each other, matching the record model and the index key codecs. That
    strictness is what stops a predicate and an index probe from disagreeing.
    """

    __slots__ = ("_left", "_operator", "_right")

    def __init__(
        self,
        left: object,
        operator: ComparisonOperator,
        right: object,
    ) -> None:
        if not isinstance(operator, ComparisonOperator):
            raise InvalidTypeError("operator must be a ComparisonOperator member")
        self._left = _as_expression(left)
        self._operator = operator
        self._right = _as_expression(right)

    def bind(self, layout: RowLayout) -> BoundExpression:
        """Bind both operands and require identical declared types."""

        checked = _require_layout(layout)
        left = self._left.bind(checked)
        right = self._right.bind(checked)
        if left.data_type is not right.data_type:
            raise ValidationError(
                f"Cannot compare {left.data_type.value} with "
                f"{right.data_type.value}; no implicit conversion is performed"
            )
        return _BoundComparison(left, self._operator, right, left.data_type)

    def __repr__(self) -> str:
        """Show the comparison in operand-operator-operand order."""

        return f"Compare({self._left!r}, {self._operator.value!r}, {self._right!r})"


class _BoundConjunction(BoundExpression):
    __slots__ = ("_terms", "_require_all")

    def __init__(self, terms: tuple[BoundExpression, ...], require_all: bool) -> None:
        self._terms = terms
        self._require_all = require_all

    @property
    def data_type(self) -> DataType:
        """Boolean composition always produces a BOOLEAN."""

        return DataType.BOOLEAN

    def evaluate(self, values: Sequence[RecordValue]) -> bool:
        """Evaluate terms in order, short-circuiting on a decisive result."""

        for term in self._terms:
            if term.matches(values) is not self._require_all:
                return not self._require_all
        return self._require_all


class _BooleanComposition(Expression):
    __slots__ = ("_terms",)
    _require_all = True

    def __init__(self, *terms: object) -> None:
        if len(terms) < 2:
            raise ValidationError(
                "Boolean composition requires at least two terms"
            )
        self._terms = tuple(_as_expression(term) for term in terms)

    def bind(self, layout: RowLayout) -> BoundExpression:
        """Bind every term and require each one to be a BOOLEAN predicate."""

        checked = _require_layout(layout)
        bound = []
        for term in self._terms:
            expression = term.bind(checked)
            if expression.data_type is not DataType.BOOLEAN:
                raise ValidationError(
                    f"{type(self).__name__} terms must be BOOLEAN, not "
                    f"{expression.data_type.value}"
                )
            bound.append(expression)
        return _BoundConjunction(tuple(bound), self._require_all)

    def __repr__(self) -> str:
        """Show the composed terms."""

        inner = ", ".join(repr(term) for term in self._terms)
        return f"{type(self).__name__}({inner})"


class And(_BooleanComposition):
    """Conjunction of two or more BOOLEAN predicates."""

    __slots__ = ()
    _require_all = True


class Or(_BooleanComposition):
    """Disjunction of two or more BOOLEAN predicates."""

    __slots__ = ()
    _require_all = False


class _BoundNegation(BoundExpression):
    __slots__ = ("_term",)

    def __init__(self, term: BoundExpression) -> None:
        self._term = term

    @property
    def data_type(self) -> DataType:
        """Negation always produces a BOOLEAN."""

        return DataType.BOOLEAN

    def evaluate(self, values: Sequence[RecordValue]) -> bool:
        """Invert the term; with no NULL there is no UNKNOWN to preserve."""

        return not self._term.matches(values)


class Not(Expression):
    """Negation of one BOOLEAN predicate."""

    __slots__ = ("_term",)

    def __init__(self, term: object) -> None:
        self._term = _as_expression(term)

    def bind(self, layout: RowLayout) -> BoundExpression:
        """Bind the term and require it to be a BOOLEAN predicate."""

        expression = self._term.bind(_require_layout(layout))
        if expression.data_type is not DataType.BOOLEAN:
            raise ValidationError(
                f"Not requires a BOOLEAN term, not {expression.data_type.value}"
            )
        return _BoundNegation(expression)

    def __repr__(self) -> str:
        """Show the negated term."""

        return f"Not({self._term!r})"


def _as_expression(value: object) -> Expression:
    """Accept an Expression, a column reference, or a scalar literal."""

    if isinstance(value, Expression):
        return value
    if isinstance(value, ColumnReference):
        return ColumnValue(value)
    return Literal(value)


def column(name: object, relation: str | None = None) -> ColumnValue:
    """Build a column expression from a name and optional relation."""

    if relation is None:
        return ColumnValue(name)
    return ColumnValue(ColumnReference(as_reference(name).name, relation))
