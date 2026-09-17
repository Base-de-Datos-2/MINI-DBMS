"""Bounded recursive-descent parser for the adopted Stage 7 SQL subset.

The grammar is owned by ``docs/sql-grammar.md``. Parsing is purely syntactic:
it constructs immutable AST nodes and never opens Catalog, storage, index, or
operator objects. Every public call owns fresh parser state and requires EOF.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

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
from .errors import SqlLimitError, SqlSyntaxError, SqlUnsupportedError
from .lexer import Token, TokenType, tokenize
from .source import SourceSpan


MAX_PARSE_NESTING = 128

_AGGREGATE_FUNCTIONS = frozenset({"COUNT", "SUM", "AVG", "MIN", "MAX"})
_COMPARISON_OPERATORS = frozenset({"=", "<>", "<", "<=", ">", ">="})
_UNSUPPORTED_COMPARISON_KEYWORDS = frozenset({"BETWEEN", "IN", "IS", "LIKE"})
_UNSUPPORTED_STATEMENTS = frozenset(
    {
        "ALTER",
        "BEGIN",
        "COMMIT",
        "CREATE",
        "DROP",
        "END",
        "EXPLAIN",
        "ROLLBACK",
        "UPDATE",
        "WITH",
    }
)
_UNSUPPORTED_TRAILING_KEYWORDS = frozenset(
    {
        "CROSS",
        "FETCH",
        "FULL",
        "HAVING",
        "LEFT",
        "LIMIT",
        "NATURAL",
        "NULLS",
        "OFFSET",
        "OUTER",
        "RETURNING",
        "RIGHT",
        "UNION",
    }
)

_T = TypeVar("_T")


class _Parser:
    __slots__ = ("_source", "_tokens", "_pos")

    def __init__(self, source: str, tokens: list[Token]) -> None:
        self._source = source
        self._tokens = tokens
        self._pos = 0

    # -- token navigation ------------------------------------------------- #

    def _peek(self, distance: int = 0) -> Token:
        """Return a token without moving; reads past EOF stay on EOF."""

        return self._tokens[min(self._pos + distance, len(self._tokens) - 1)]

    @property
    def _current(self) -> Token:
        return self._peek()

    @property
    def _previous(self) -> Token:
        return self._tokens[max(self._pos - 1, 0)]

    @property
    def _at_end(self) -> bool:
        return self._current.type is TokenType.EOF

    def _advance(self) -> Token:
        token = self._current
        if token.type is not TokenType.EOF:
            self._pos += 1
        return token

    def _at_keyword(self, *keywords: str) -> bool:
        token = self._current
        return token.type is TokenType.KEYWORD and token.value in keywords

    def _match_keyword(self, *keywords: str) -> Token | None:
        if self._at_keyword(*keywords):
            return self._advance()
        return None

    def _at_punct(self, *values: str) -> bool:
        token = self._current
        return token.type is TokenType.PUNCTUATION and token.value in values

    def _match_punct(self, *values: str) -> Token | None:
        if self._at_punct(*values):
            return self._advance()
        return None

    def _at_type(self, *token_types: TokenType) -> bool:
        return self._current.type in token_types

    @staticmethod
    def _cover(first: SourceSpan, last: SourceSpan) -> SourceSpan:
        return SourceSpan.cover(first, last)

    @staticmethod
    def _word(token: Token) -> str:
        return token.lexeme.upper()

    @staticmethod
    def _describe(token: Token) -> str:
        if token.type is TokenType.EOF:
            return "end of statement"
        return repr(token.lexeme)

    def _error(
        self,
        message: str,
        *,
        token: Token | None = None,
        expected: str | None = None,
        error_type: type[SqlSyntaxError] = SqlSyntaxError,
    ) -> SqlSyntaxError:
        offending_token = token or self._current
        offending = (
            "<EOF>"
            if offending_token.type is TokenType.EOF
            else offending_token.lexeme
        )
        return error_type(
            message,
            span=offending_token.span,
            source=self._source,
            expected=expected,
            offending=offending,
        )

    def _expected(self, expected: str) -> SqlSyntaxError:
        return self._error(
            f"Expected {expected}, found {self._describe(self._current)}",
            expected=expected,
        )

    def _expect_keyword(self, keyword: str) -> Token:
        token = self._match_keyword(keyword)
        if token is None:
            raise self._expected(f"keyword {keyword}")
        return token

    def _expect_punct(self, value: str) -> Token:
        token = self._match_punct(value)
        if token is None:
            raise self._expected(repr(value))
        return token

    def _expect_identifier(self) -> Token:
        if self._current.type is not TokenType.IDENTIFIER:
            raise self._expected("an identifier")
        return self._advance()

    def _parse_comma_list(self, parse_item: Callable[[], _T]) -> tuple[_T, ...]:
        """Parse a non-empty comma list while enforcing cursor progress."""

        items: list[_T] = []
        while True:
            start = self._pos
            items.append(parse_item())
            if self._pos <= start:
                raise RuntimeError("Parser list item did not consume a token")
            if self._match_punct(",") is None:
                return tuple(items)

    # -- statement entry -------------------------------------------------- #

    def parse_statement(self) -> Statement:
        if self._at_keyword("SELECT"):
            statement = self._parse_select()
        elif self._at_keyword("INSERT"):
            statement = self._parse_insert()
        elif self._at_keyword("DELETE"):
            statement = self._parse_delete()
        elif self._word(self._current) in _UNSUPPORTED_STATEMENTS:
            word = self._word(self._current)
            raise self._error(
                f"{word} statements are not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        else:
            raise self._expected("SELECT, INSERT, or DELETE")

        semicolon = self._match_punct(";")
        if semicolon is not None and statement.span is not None:
            statement = replace(
                statement, span=self._cover(statement.span, semicolon.span)
            )

        if not self._at_end:
            raise self._trailing_error()
        return statement

    def _trailing_error(self) -> SqlSyntaxError:
        token = self._current
        word = self._word(token)
        if self._at_punct(";"):
            return self._error("Only one optional final semicolon is allowed")
        if word in {"SELECT", "INSERT", "DELETE"}:
            return self._error("Only one SQL statement may be submitted at a time")
        if word in _UNSUPPORTED_TRAILING_KEYWORDS:
            return self._error(
                f"{word} syntax is not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        if word in {"GROUP", "INNER", "JOIN", "ORDER", "WHERE"}:
            return self._error(f"Unexpected or duplicate {word} clause")
        return self._error(
            f"Unexpected trailing input near {self._describe(token)}"
        )

    # -- SELECT ----------------------------------------------------------- #

    def _parse_select(self) -> SelectStatement:
        start = self._expect_keyword("SELECT")
        if self._at_keyword("DISTINCT"):
            raise self._error(
                "DISTINCT is not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
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
            span=self._cover(start.span, self._previous.span),
        )

    def _parse_select_list(self) -> tuple[SelectItem, ...]:
        star = self._match_punct("*")
        if star is not None:
            expr = Star(span=star.span)
            return (SelectItem(expr, span=star.span),)
        return self._parse_comma_list(self._parse_select_item)

    def _parse_select_item(self) -> SelectItem:
        expr = self._parse_select_expr()
        alias = None
        end_span = expr.span
        if self._match_keyword("AS") is not None:
            alias_token = self._expect_identifier()
            alias = alias_token.value
            end_span = alias_token.span
        elif self._current.type is TokenType.IDENTIFIER:
            alias_token = self._advance()
            alias = alias_token.value
            end_span = alias_token.span
        if expr.span is None or end_span is None:
            raise RuntimeError("Parser-created SELECT expression lacks a span")
        return SelectItem(expr, alias, span=self._cover(expr.span, end_span))

    def _parse_select_expr(self) -> SqlExpr:
        token = self._current
        if (
            token.type is TokenType.IDENTIFIER
            and self._peek(1).type is TokenType.PUNCTUATION
            and self._peek(1).value == "("
        ):
            if token.value.upper() not in _AGGREGATE_FUNCTIONS:
                raise self._error(
                    f"Function {token.lexeme!r} is not supported in Stage 7",
                    token=token,
                    error_type=SqlUnsupportedError,
                )
            return self._parse_aggregate_call()
        return self._parse_select_reference()

    def _parse_aggregate_call(self) -> AggregateCall:
        name_token = self._expect_identifier()
        name = name_token.value.upper()
        self._expect_punct("(")
        star = self._match_punct("*")
        if star is not None:
            if name != "COUNT":
                raise self._error(
                    f"{name}(*) is not supported; only COUNT(*) accepts '*'",
                    token=star,
                    error_type=SqlUnsupportedError,
                )
            close = self._expect_punct(")")
            return AggregateCall(
                function=name,
                argument=None,
                star=True,
                span=self._cover(name_token.span, close.span),
            )

        argument = self._parse_column_ref()
        close = self._expect_punct(")")
        return AggregateCall(
            function=name,
            argument=argument,
            star=False,
            span=self._cover(name_token.span, close.span),
        )

    def _parse_select_reference(self) -> SqlExpr:
        first = self._expect_identifier()
        if self._match_punct(".") is None:
            return ColumnRef(name=first.value, span=first.span)
        star = self._match_punct("*")
        if star is not None:
            return Star(
                relation=first.value,
                span=self._cover(first.span, star.span),
            )
        second = self._expect_identifier()
        return ColumnRef(
            name=second.value,
            relation=first.value,
            span=self._cover(first.span, second.span),
        )

    def _parse_column_ref(self) -> ColumnRef:
        first = self._expect_identifier()
        if self._match_punct(".") is None:
            return ColumnRef(name=first.value, span=first.span)
        second = self._expect_identifier()
        return ColumnRef(
            name=second.value,
            relation=first.value,
            span=self._cover(first.span, second.span),
        )

    # -- table references and JOIN --------------------------------------- #

    def _parse_table_ref(self) -> TableRef:
        if self._at_punct("(") and self._peek(1).value == "SELECT":
            raise self._error(
                "Subqueries are not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        name = self._expect_identifier()
        alias = None
        end = name
        if self._match_keyword("AS") is not None:
            end = self._expect_identifier()
            alias = end.value
        elif self._current.type is TokenType.IDENTIFIER:
            end = self._advance()
            alias = end.value
        return TableRef(
            name.value,
            alias,
            span=self._cover(name.span, end.span),
        )

    def _parse_optional_join(self) -> JoinClause | None:
        start = self._match_keyword("INNER")
        if start is not None:
            self._expect_keyword("JOIN")
        else:
            start = self._match_keyword("JOIN")
        if start is None:
            return None
        table = self._parse_table_ref()
        self._expect_keyword("ON")
        on = self._parse_bool_expr()
        if on.span is None:
            raise RuntimeError("Parser-created JOIN predicate lacks a span")
        return JoinClause(table, on, span=self._cover(start.span, on.span))

    # -- WHERE / GROUP BY / ORDER BY ------------------------------------- #

    def _parse_optional_where(self) -> SqlExpr | None:
        if self._match_keyword("WHERE") is None:
            return None
        return self._parse_bool_expr()

    def _parse_optional_group_by(self) -> tuple[ColumnRef, ...]:
        if self._match_keyword("GROUP") is None:
            return ()
        self._expect_keyword("BY")
        return self._parse_comma_list(self._parse_column_ref)

    def _parse_optional_order_by(self) -> tuple[OrderItem, ...]:
        if self._match_keyword("ORDER") is None:
            return ()
        self._expect_keyword("BY")
        return self._parse_comma_list(self._parse_order_item)

    def _parse_order_item(self) -> OrderItem:
        expr = self._parse_value_expr()
        descending = False
        end_span = expr.span
        direction = self._match_keyword("ASC", "DESC")
        if direction is not None:
            descending = direction.value == "DESC"
            end_span = direction.span
        if expr.span is None or end_span is None:
            raise RuntimeError("Parser-created ORDER BY item lacks a span")
        return OrderItem(
            expr,
            descending,
            span=self._cover(expr.span, end_span),
        )

    # -- Boolean expressions --------------------------------------------- #

    def _parse_bool_expr(self, nesting: int = 0) -> SqlExpr:
        return self._parse_or(nesting)

    def _parse_or(self, nesting: int) -> SqlExpr:
        left = self._parse_and(nesting)
        while self._match_keyword("OR") is not None:
            right = self._parse_and(nesting)
            if left.span is None or right.span is None:
                raise RuntimeError("Parser-created OR term lacks a span")
            left = BoolOr(left, right, span=self._cover(left.span, right.span))
        return left

    def _parse_and(self, nesting: int) -> SqlExpr:
        left = self._parse_not(nesting)
        while self._match_keyword("AND") is not None:
            right = self._parse_not(nesting)
            if left.span is None or right.span is None:
                raise RuntimeError("Parser-created AND term lacks a span")
            left = BoolAnd(left, right, span=self._cover(left.span, right.span))
        return left

    def _check_nesting(self, nesting: int, token: Token) -> None:
        if nesting > MAX_PARSE_NESTING:
            raise self._error(
                f"SQL expression nesting exceeds the {MAX_PARSE_NESTING}-level limit",
                token=token,
                error_type=SqlLimitError,
            )

    def _parse_not(self, nesting: int) -> SqlExpr:
        not_tokens: list[Token] = []
        while self._at_keyword("NOT"):
            token = self._current
            self._check_nesting(nesting + len(not_tokens) + 1, token)
            not_tokens.append(self._advance())

        open_paren = self._match_punct("(")
        if open_paren is not None:
            inner_nesting = nesting + len(not_tokens) + 1
            self._check_nesting(inner_nesting, open_paren)
            expression = self._parse_bool_expr(inner_nesting)
            close_paren = self._expect_punct(")")
            expression = replace(
                expression,
                span=self._cover(open_paren.span, close_paren.span),
            )
        else:
            expression = self._parse_comparison()

        for token in reversed(not_tokens):
            if expression.span is None:
                raise RuntimeError("Parser-created NOT term lacks a span")
            expression = BoolNot(
                expression,
                span=self._cover(token.span, expression.span),
            )
        return expression

    def _parse_comparison(self) -> SqlExpr:
        left = self._parse_value_expr()
        token = self._current
        if (
            token.type is not TokenType.COMPARISON_OPERATOR
            or token.value not in _COMPARISON_OPERATORS
        ):
            if self._at_keyword(*_UNSUPPORTED_COMPARISON_KEYWORDS):
                raise self._error(
                    f"Comparison form {token.value} is not supported in Stage 7",
                    error_type=SqlUnsupportedError,
                )
            raise self._expected("a comparison operator")
        operator = self._advance().value
        right = self._parse_value_expr()
        if self._current.type is TokenType.COMPARISON_OPERATOR:
            raise self._error(
                "Chained comparisons are not supported",
                error_type=SqlUnsupportedError,
            )
        if left.span is None or right.span is None:
            raise RuntimeError("Parser-created comparison term lacks a span")
        return Comparison(
            left,
            operator,
            right,
            span=self._cover(left.span, right.span),
        )

    # -- literals and scalar references ---------------------------------- #

    def _at_literal_start(self) -> bool:
        return self._at_type(
            TokenType.PLUS,
            TokenType.MINUS,
            TokenType.INTEGER,
            TokenType.FLOAT,
            TokenType.STRING,
        ) or self._at_keyword("TRUE", "FALSE", "NULL")

    def _parse_literal(self) -> SqlExpr:
        sign = None
        if self._at_type(TokenType.PLUS, TokenType.MINUS):
            sign = self._advance()
            if not self._at_type(TokenType.INTEGER, TokenType.FLOAT):
                raise self._error(
                    "A leading sign may only prefix a numeric literal",
                    expected="an integer or decimal literal",
                )

        token = self._current
        if token.type is TokenType.INTEGER:
            self._advance()
            if type(token.decoded) is not int:
                raise RuntimeError("Lexer INTEGER token has no integer value")
            value = -token.decoded if sign and sign.type is TokenType.MINUS else token.decoded
            span = self._cover(sign.span, token.span) if sign else token.span
            return IntegerLiteral(value, span=span)
        if token.type is TokenType.FLOAT:
            self._advance()
            if type(token.decoded) is not float:
                raise RuntimeError("Lexer FLOAT token has no float value")
            value = -token.decoded if sign and sign.type is TokenType.MINUS else token.decoded
            span = self._cover(sign.span, token.span) if sign else token.span
            return FloatLiteral(value, span=span)
        if sign is not None:
            raise RuntimeError("Signed-literal validation did not require a number")
        if token.type is TokenType.STRING:
            self._advance()
            if type(token.decoded) is not str:
                raise RuntimeError("Lexer STRING token has no string value")
            return StringLiteral(token.decoded, span=token.span)
        if self._match_keyword("TRUE") is not None:
            return BooleanLiteral(True, span=token.span)
        if self._match_keyword("FALSE") is not None:
            return BooleanLiteral(False, span=token.span)
        if self._at_keyword("NULL"):
            raise self._error(
                "NULL is not supported by the current row model",
                error_type=SqlUnsupportedError,
            )
        raise self._expected("a literal")

    def _parse_value_expr(self) -> SqlExpr:
        if self._at_literal_start():
            return self._parse_literal()
        if self._current.type is TokenType.IDENTIFIER:
            return self._parse_column_ref()
        if self._at_punct("(") and self._peek(1).value == "SELECT":
            raise self._error(
                "Subqueries are not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        if self._at_keyword("EXISTS"):
            raise self._error(
                "Subqueries are not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        raise self._expected("a literal or column reference")

    # -- INSERT / DELETE -------------------------------------------------- #

    def _parse_insert(self) -> InsertStatement:
        start = self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        table = self._expect_identifier().value

        columns: tuple[str, ...] | None = None
        if self._match_punct("(") is not None:
            column_tokens = self._parse_comma_list(self._expect_identifier)
            self._expect_punct(")")
            columns = tuple(token.value for token in column_tokens)

        if self._at_keyword("SELECT"):
            raise self._error(
                "INSERT SELECT is not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        self._expect_keyword("VALUES")
        self._expect_punct("(")
        values = self._parse_comma_list(self._parse_literal)
        close = self._expect_punct(")")

        if self._at_punct(",") and self._peek(1).value == "(":
            raise self._error(
                "Multi-row VALUES is not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        if self._at_keyword("RETURNING"):
            raise self._error(
                "RETURNING is not supported in Stage 7",
                error_type=SqlUnsupportedError,
            )
        return InsertStatement(
            table=table,
            columns=columns,
            values=values,
            span=self._cover(start.span, close.span),
        )

    def _parse_delete(self) -> DeleteStatement:
        start = self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table = self._expect_identifier().value
        where = self._parse_optional_where()
        return DeleteStatement(
            table=table,
            where=where,
            span=self._cover(start.span, self._previous.span),
        )


def parse_sql(text: str) -> Statement:
    """Parse exactly one SQL statement without semantic or storage effects."""

    tokens = tokenize(text)
    return _Parser(text, tokens).parse_statement()


__all__ = ["parse_sql"]
