"""Abstract syntax tree for the supported SQL subset (Stage 7, Task 7.3).

Every node is an immutable, purely syntactic fact: names are kept exactly as
written (case as typed) and nothing here is resolved against a Catalog. That
resolution is the Binder's job (Task 7.8+). Keeping the AST free of any
semantic knowledge is what lets the parser be tested in complete isolation
from storage, indexes, and the operator layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .source import SourceSpan


@dataclass(frozen=True, slots=True, kw_only=True)
class SyntaxNode:
    """Base for immutable syntax nodes with an optional source location.

    The default keeps programmatic AST construction backward compatible.
    Nodes produced by :func:`engine.query.parser.parse_sql` always have a
    concrete span. Locations do not participate in structural equality.
    """

    span: SourceSpan | None = field(default=None, compare=False)


# --------------------------------------------------------------------------- #
# Expressions
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True, kw_only=True)
class SqlExpr(SyntaxNode):
    """Base class of every syntactic expression node."""

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
class SelectItem(SyntaxNode):
    expr: SqlExpr
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class TableRef(SyntaxNode):
    name: str
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class JoinClause(SyntaxNode):
    table: TableRef
    on: SqlExpr


@dataclass(frozen=True, slots=True)
class OrderItem(SyntaxNode):
    expr: SqlExpr
    descending: bool = False


@dataclass(frozen=True, slots=True)
class SelectStatement(SyntaxNode):
    items: tuple[SelectItem, ...]
    from_table: TableRef
    join: JoinClause | None = None
    where: SqlExpr | None = None
    group_by: tuple[ColumnRef, ...] = field(default_factory=tuple)
    order_by: tuple[OrderItem, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class InsertStatement(SyntaxNode):
    table: str
    columns: tuple[str, ...] | None
    values: tuple[SqlExpr, ...]


@dataclass(frozen=True, slots=True)
class DeleteStatement(SyntaxNode):
    table: str
    where: SqlExpr | None = None


@dataclass(frozen=True, slots=True)
class TypeSpecification(SyntaxNode):
    """One CREATE type spelling normalized independently from Catalog types."""

    name: str
    length: int | None = None


@dataclass(frozen=True, slots=True)
class ColumnDefinition(SyntaxNode):
    """One ordered CREATE column definition with an inline key marker."""

    name: str
    data_type: TypeSpecification
    primary_key: bool = False


@dataclass(frozen=True, slots=True)
class CreateTableStatement(SyntaxNode):
    """Pure syntax for the limited single-table CREATE form."""

    table: str
    columns: tuple[ColumnDefinition, ...]


@dataclass(frozen=True, slots=True)
class ExplainStatement(SyntaxNode):
    """A SELECT-only explanation wrapper; execution is decided downstream."""

    select: SelectStatement
    analyze: bool = False


@dataclass(frozen=True, slots=True)
class BeginTransactionStatement(SyntaxNode):
    """Start an explicit group in the owning database session."""


@dataclass(frozen=True, slots=True)
class EndTransactionStatement(SyntaxNode):
    """Commit an explicit group in the owning database session."""


@dataclass(frozen=True, slots=True)
class RollbackStatement(SyntaxNode):
    """Abort an explicit group in the owning database session."""


Statement = (
    SelectStatement
    | InsertStatement
    | DeleteStatement
    | CreateTableStatement
    | ExplainStatement
    | BeginTransactionStatement
    | EndTransactionStatement
    | RollbackStatement
)
