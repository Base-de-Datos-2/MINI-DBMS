"""Recursive-descent parser for the supported SQL subset (Stage 7, Tasks 7.5-7.7).

Grammar (EBNF, keywords case-insensitive, identifiers case-sensitive)::

    statement      := select_stmt | insert_stmt | delete_stmt

    select_stmt    := "SELECT" select_list "FROM" table_ref
                       [join_clause] [where_clause]
                       [group_by_clause] [order_by_clause] [";"]
    select_list    := "*" | select_item ("," select_item)*
    select_item    := (aggregate_call | column_ref) ["AS" IDENT]
    aggregate_call := IDENT "(" ("*" | value_expr) ")"
    table_ref      := IDENT ["AS"] IDENT?
    join_clause    := ["INNER"] "JOIN" table_ref "ON" bool_expr
    where_clause   := "WHERE" bool_expr
    group_by_clause:= "GROUP" "BY" column_ref ("," column_ref)*
    order_by_clause:= "ORDER" "BY" order_item ("," order_item)*
    order_item     := value_expr ["ASC" | "DESC"]

    bool_expr      := or_expr
    or_expr        := and_expr ("OR" and_expr)*
    and_expr       := not_expr ("AND" not_expr)*
    not_expr       := "NOT" not_expr | comparison | "(" bool_expr ")"
    comparison     := value_expr comp_op value_expr
    comp_op        := "=" | "<>" | "<" | "<=" | ">" | ">="
    value_expr     := INTEGER | FLOAT | STRING | "TRUE" | "FALSE" | column_ref
    column_ref     := IDENT ["." IDENT] | IDENT "." "*"

    insert_stmt    := "INSERT" "INTO" IDENT ["(" IDENT ("," IDENT)* ")"]
                       "VALUES" "(" value_expr ("," value_expr)* ")" [";"]
    delete_stmt    := "DELETE" "FROM" IDENT [where_clause] [";"]

Every accepted statement consumes the *entire* token stream up to EOF: a
trailing dangling clause is a syntax error, not a silently ignored suffix.
"""

from __future__ import annotations

from .ast import (
    AggregateCall,
    BoolAnd,
    BoolNot,
    BoolOr,
    BooleanLiteral,
    ColumnRef,
    Comparison,
    DeleteStatement,
    FloatLiteral,
    InsertStatement,
    IntegerLiteral,
    JoinClause,
    OrderItem,
    SelectItem,
    SelectStatement,
    Star,
    StringLiteral,
    SqlExpr,
    Statement,
    TableRef,
)
from .lexer import SqlSyntaxError, Token, TokenType, tokenize


#: Function names accepted in aggregate position; anything else is a syntax
#: error here rather than a bind-time "unknown function" (keeps the two
#: layers' responsibilities distinct: the grammar is fixed, applicability of
#: a given name to a given column type is the Binder's concern).
_AGGREGATE_FUNCTIONS = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})

_COMPARISON_OPERATORS = frozenset({"=", "<>", "<", "<=", ">", ">="})


class _Parser:
    __slots__ = ("_tokens", "_pos")

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # -- token stream helpers ------------------------------------------- #

    @property
    def _current(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        token = self._tokens[self._pos]
        if token.type is not TokenType.EOF:
            self._pos += 1
        return token

    def _at_keyword(self, *keywords: str) -> bool:
        token = self._current
        return token.type is TokenType.KEYWORD and token.value in keywords

    def _at_punct(self, *values: str) -> bool:
        token = self._current
        return token.type is TokenType.PUNCTUATION and token.value in values

    def _expect_keyword(self, keyword: str) -> Token:
        if not self._at_keyword(keyword):
            raise SqlSyntaxError(
                f"Expected {keyword!r}, found {self._describe(self._current)}",
                position=self._current.position,
            )
        return self._advance()

    def _expect_punct(self, value: str) -> Token:
        if not self._at_punct(value):
            raise SqlSyntaxError(
                f"Expected {value!r}, found {self._describe(self._current)}",
                position=self._current.position,
            )
        return self._advance()

    def _expect_identifier(self) -> Token:
        if self._current.type is not TokenType.IDENTIFIER:
            raise SqlSyntaxError(
                f"Expected an identifier, found {self._describe(self._current)}",
                position=self._current.position,
            )
        return self._advance()

    @staticmethod
    def _describe(token: Token) -> str:
        if token.type is TokenType.EOF:
            return "end of statement"
        return f"{token.value!r}"

    # -- entry point ------------------------------------------------------ #

    def parse_statement(self) -> Statement:
        if self._at_keyword("SELECT"):
            statement = self._parse_select()
        elif self._at_keyword("INSERT"):
            statement = self._parse_insert()
        elif self._at_keyword("DELETE"):
            statement = self._parse_delete()
        else:
            raise SqlSyntaxError(
                "Expected SELECT, INSERT, or DELETE, found "
                f"{self._describe(self._current)}",
                position=self._current.position,
            )
        if self._at_punct(";"):
            self._advance()
        if self._current.type is not TokenType.EOF:
            raise SqlSyntaxError(
                f"Unexpected trailing input near {self._describe(self._current)}",
                position=self._current.position,
            )
        return statement

    # -- SELECT ------------------------------------------------------------ #

    def _parse_select(self) -> SelectStatement:
        self._expect_keyword("SELECT")
        items = self._parse_select_list()
        self._expect_keyword("FROM")
        from_table = self._parse_table_ref()
        join = self._parse_optional_join()
        where = self._parse_optional_where()
        group_by = self._parse_optional_group_by()
        order_by = self._parse_optional_order_by()
        return SelectStatement(
            items=items,
            from_table=from_table,
            join=join,
            where=where,
            group_by=group_by,
            order_by=order_by,
        )

    def _parse_select_list(self) -> tuple[SelectItem, ...]:
        if self._at_punct("*"):
            self._advance()
            return (SelectItem(Star()),)
        items = [self._parse_select_item()]
        while self._at_punct(","):
            self._advance()
            items.append(self._parse_select_item())
        return tuple(items)

    def _parse_select_item(self) -> SelectItem:
        expr = self._parse_select_expr()
        alias = None
        if self._at_keyword("AS"):
            self._advance()
            alias = self._expect_identifier().value
        elif self._current.type is TokenType.IDENTIFIER:
            alias = self._advance().value
        return SelectItem(expr, alias)

    def _parse_select_expr(self) -> SqlExpr:
        token = self._current
        if (
            token.type is TokenType.IDENTIFIER
            and token.value.upper() in _AGGREGATE_FUNCTIONS
            and self._tokens[self._pos + 1].type is TokenType.PUNCTUATION
            and self._tokens[self._pos + 1].value == "("
        ):
            return self._parse_aggregate_call()
        return self._parse_column_ref_or_relation_star()

    def _parse_aggregate_call(self) -> AggregateCall:
        name = self._advance().value.upper()
        self._expect_punct("(")
        if self._at_punct("*"):
            self._advance()
            self._expect_punct(")")
            return AggregateCall(function=name, argument=None, star=True)
        argument = self._parse_value_expr()
        self._expect_punct(")")
        return AggregateCall(function=name, argument=argument, star=False)

    def _parse_column_ref_or_relation_star(self) -> SqlExpr:
        first = self._expect_identifier().value
        if self._at_punct("."):
            self._advance()
            if self._at_punct("*"):
                self._advance()
                return Star(relation=first)
            second = self._expect_identifier().value
            return ColumnRef(name=second, relation=first)
        return ColumnRef(name=first)

    # -- table references / JOIN ------------------------------------------ #

    def _parse_table_ref(self) -> TableRef:
        name = self._expect_identifier().value
        alias = None
        if self._at_keyword("AS"):
            self._advance()
            alias = self._expect_identifier().value
        elif self._current.type is TokenType.IDENTIFIER:
            alias = self._advance().value
        return TableRef(name, alias)

    def _parse_optional_join(self) -> JoinClause | None:
        if self._at_keyword("INNER"):
            self._advance()
            self._expect_keyword("JOIN")
        elif self._at_keyword("JOIN"):
            self._advance()
        else:
            return None
        table = self._parse_table_ref()
        self._expect_keyword("ON")
        on = self._parse_bool_expr()
        return JoinClause(table, on)

    # -- WHERE / GROUP BY / ORDER BY --------------------------------------- #

    def _parse_optional_where(self) -> SqlExpr | None:
        if not self._at_keyword("WHERE"):
            return None
        self._advance()
        return self._parse_bool_expr()

    def _parse_optional_group_by(self) -> tuple[ColumnRef, ...]:
        if not self._at_keyword("GROUP"):
            return ()
        self._advance()
        self._expect_keyword("BY")
        columns = [self._parse_column_ref()]
        while self._at_punct(","):
            self._advance()
            columns.append(self._parse_column_ref())
        return tuple(columns)

    def _parse_optional_order_by(self) -> tuple[OrderItem, ...]:
        if not self._at_keyword("ORDER"):
            return ()
        self._advance()
        self._expect_keyword("BY")
        items = [self._parse_order_item()]
        while self._at_punct(","):
            self._advance()
            items.append(self._parse_order_item())
        return tuple(items)

    def _parse_order_item(self) -> OrderItem:
        expr = self._parse_value_expr()
        descending = False
        if self._at_keyword("ASC"):
            self._advance()
        elif self._at_keyword("DESC"):
            self._advance()
            descending = True
        return OrderItem(expr, descending)

    def _parse_column_ref(self) -> ColumnRef:
        expr = self._parse_column_ref_or_relation_star()
        if not isinstance(expr, ColumnRef):
            raise SqlSyntaxError(
                "Expected a column name, not '*'", position=self._current.position
            )
        return expr

    # -- boolean expressions ------------------------------------------------ #

    def _parse_bool_expr(self) -> SqlExpr:
        return self._parse_or()

    def _parse_or(self) -> SqlExpr:
        left = self._parse_and()
        while self._at_keyword("OR"):
            self._advance()
            right = self._parse_and()
            left = BoolOr(left, right)
        return left

    def _parse_and(self) -> SqlExpr:
        left = self._parse_not()
        while self._at_keyword("AND"):
            self._advance()
            right = self._parse_not()
            left = BoolAnd(left, right)
        return left

    def _parse_not(self) -> SqlExpr:
        if self._at_keyword("NOT"):
            self._advance()
            return BoolNot(self._parse_not())
        if self._at_punct("("):
            self._advance()
            inner = self._parse_bool_expr()
            self._expect_punct(")")
            return inner
        return self._parse_comparison()

    def _parse_comparison(self) -> SqlExpr:
        left = self._parse_value_expr()
        token = self._current
        if token.type is TokenType.PUNCTUATION and token.value in _COMPARISON_OPERATORS:
            operator = self._advance().value
            right = self._parse_value_expr()
            return Comparison(left, operator, right)
        raise SqlSyntaxError(
            f"Expected a comparison operator, found {self._describe(self._current)}",
            position=self._current.position,
        )

    def _parse_value_expr(self) -> SqlExpr:
        token = self._current
        if token.type is TokenType.INTEGER:
            self._advance()
            return IntegerLiteral(int(token.value))
        if token.type is TokenType.FLOAT:
            self._advance()
            return FloatLiteral(float(token.value))
        if token.type is TokenType.STRING:
            self._advance()
            return StringLiteral(token.value)
        if self._at_keyword("TRUE"):
            self._advance()
            return BooleanLiteral(True)
        if self._at_keyword("FALSE"):
            self._advance()
            return BooleanLiteral(False)
        if token.type is TokenType.IDENTIFIER:
            return self._parse_column_ref_or_relation_star()
        raise SqlSyntaxError(
            f"Expected a value or column, found {self._describe(self._current)}",
            position=self._current.position,
        )

    # -- INSERT / DELETE ----------------------------------------------------- #

    def _parse_insert(self) -> InsertStatement:
        self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        table = self._expect_identifier().value
        columns: tuple[str, ...] | None = None
        if self._at_punct("("):
            self._advance()
            names = [self._expect_identifier().value]
            while self._at_punct(","):
                self._advance()
                names.append(self._expect_identifier().value)
            self._expect_punct(")")
            columns = tuple(names)
        self._expect_keyword("VALUES")
        self._expect_punct("(")
        values = [self._parse_value_expr()]
        while self._at_punct(","):
            self._advance()
            values.append(self._parse_value_expr())
        self._expect_punct(")")
        return InsertStatement(table=table, columns=columns, values=tuple(values))

    def _parse_delete(self) -> DeleteStatement:
        self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table = self._expect_identifier().value
        where = self._parse_optional_where()
        return DeleteStatement(table=table, where=where)


def parse_sql(text: str) -> Statement:
    """Parse one SQL statement, requiring it to consume the full input."""

    tokens = tokenize(text)
    parser = _Parser(tokens)
    return parser.parse_statement()
