"""Abstract syntax tree for the supported SQL subset (Stage 7, Task 7.3).

Every node is an immutable, purely syntactic fact: names are kept exactly as
written (case as typed) and nothing here is resolved against a Catalog. That
resolution is the Binder's job (Task 7.8+). Keeping the AST free of any
semantic knowledge is what lets the parser be tested in complete isolation
from storage, indexes, and the operator layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Expressions
# --------------------------------------------------------------------------- #


class SqlExpr:
    """Base class of every syntactic expression node."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class IntegerLiteral(SqlExpr):
    value: int


@dataclass(frozen=True, slots=True)
class FloatLiteral(SqlExpr):
    value: float


@dataclass(frozen=True, slots=True)
class StringLiteral(SqlExpr):
    value: str


@dataclass(frozen=True, slots=True)
class BooleanLiteral(SqlExpr):
    value: bool


@dataclass(frozen=True, slots=True)
class ColumnRef(SqlExpr):
    """A column name, optionally qualified as ``relation.name``."""

    name: str
    relation: str | None = None


@dataclass(frozen=True, slots=True)
class Star(SqlExpr):
    """``*`` or ``relation.*`` in a SELECT list."""

    relation: str | None = None


@dataclass(frozen=True, slots=True)
class AggregateCall(SqlExpr):
    """A function call in the aggregate position, e.g. ``COUNT(*)``.

    ``argument`` is ``None`` only for the ``COUNT(*)`` form; every other
    accepted aggregate takes exactly one column argument.
    """

    function: str
    argument: SqlExpr | None
    star: bool = False


@dataclass(frozen=True, slots=True)
class Comparison(SqlExpr):
    left: SqlExpr
    operator: str  # one of '=', '<>', '<', '<=', '>', '>='
    right: SqlExpr


@dataclass(frozen=True, slots=True)
class BoolAnd(SqlExpr):
    left: SqlExpr
    right: SqlExpr


@dataclass(frozen=True, slots=True)
class BoolOr(SqlExpr):
    left: SqlExpr
    right: SqlExpr


@dataclass(frozen=True, slots=True)
class BoolNot(SqlExpr):
    term: SqlExpr


# --------------------------------------------------------------------------- #
# Clauses / statements
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SelectItem:
    expr: SqlExpr
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class TableRef:
    name: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class JoinClause:
    table: TableRef
    on: SqlExpr


@dataclass(frozen=True, slots=True)
class OrderItem:
    expr: SqlExpr
    descending: bool = False


@dataclass(frozen=True, slots=True)
class SelectStatement:
    items: tuple[SelectItem, ...]
    from_table: TableRef
    join: JoinClause | None = None
    where: SqlExpr | None = None
    group_by: tuple[ColumnRef, ...] = field(default_factory=tuple)
    order_by: tuple[OrderItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class InsertStatement:
    table: str
    columns: tuple[str, ...] | None
    values: tuple[SqlExpr, ...]


@dataclass(frozen=True, slots=True)
class DeleteStatement:
    table: str
    where: SqlExpr | None = None


Statement = SelectStatement | InsertStatement | DeleteStatement
