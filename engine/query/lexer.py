"""Bounded hand-written lexer for the Stage 7 SQL subset.

Tokens preserve their exact source spelling, expose a normalized parser value,
and carry a half-open source span. A leading sign is deliberately emitted as a
separate token; deciding whether it forms a signed numeric literal is a grammar
decision made by the parser.
"""

from __future__ import annotations

from bisect import bisect_right
from math import isfinite

from .errors import SqlLexicalError, SqlSyntaxError
from .source import SourceSpan
from .tokens import Token, TokenType


MAX_SQL_INPUT_CHARS = 65_536
MAX_NUMERIC_LITERAL_DIGITS = 1_024


KEYWORDS = frozenset(
    {
        "SELECT",
        "FROM",
        "WHERE",
        "AND",
        "OR",
        "NOT",
        "AS",
        "JOIN",
        "INNER",
        "ON",
        "GROUP",
        "BY",
        "ORDER",
        "ASC",
        "DESC",
        "INSERT",
        "INTO",
        "VALUES",
        "DELETE",
        "ANALYZE",
        "INT",
        "INTEGER",
        "KEY",
        "PRIMARY",
        "TRUE",
        "FALSE",
        "VARCHAR",
        # Recognized so unsupported SQL cannot be mistaken for an identifier
        # or implicit alias. The parser reports the subset boundary.
        "ALTER",
        "BEGIN",
        "BETWEEN",
        "COMMIT",
        "CREATE",
        "CROSS",
        "DISTINCT",
        "DROP",
        "END",
        "EXISTS",
        "EXPLAIN",
        "FETCH",
        "FIRST",
        "FULL",
        "HAVING",
        "IN",
        "IS",
        "LAST",
        "LEFT",
        "LIKE",
        "LIMIT",
        "NATURAL",
        "NULL",
        "NULLS",
        "OFFSET",
        "OUTER",
        "RETURNING",
        "RIGHT",
        "ROLLBACK",
        "SET",
        "TABLE",
        "TRANSACTION",
        "UNION",
        "UPDATE",
        "WITH",
    }
)

# Longest punctuation tokens first, so ``<=`` is not split into ``<``/``=``.
_MULTI_CHAR_COMPARISONS = ("<=", ">=", "<>", "!=")
_SINGLE_CHAR_COMPARISONS = frozenset("=<>")
_SINGLE_CHAR_PUNCTUATION = frozenset("*,.();")


def _is_ident_start(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_ident_continue(char: str) -> bool:
    return char.isalnum() or char == "_"


def _is_ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


class _SourceMap:
    """Translate source offsets to one-based line and column coordinates."""

    __slots__ = ("_line_starts",)

    def __init__(self, text: str) -> None:
        self._line_starts = [0]
        offset = 0
        while offset < len(text):
            char = text[offset]
            if char == "\r":
                offset += 1
                if offset < len(text) and text[offset] == "\n":
                    offset += 1
                self._line_starts.append(offset)
            elif char == "\n":
                offset += 1
                self._line_starts.append(offset)
            else:
                offset += 1

    def _line_column(self, offset: int) -> tuple[int, int]:
        line_index = bisect_right(self._line_starts, offset) - 1
        return line_index + 1, offset - self._line_starts[line_index] + 1

    def span(self, start: int, end: int) -> SourceSpan:
        start_line, start_column = self._line_column(start)
        end_line, end_column = self._line_column(end)
        return SourceSpan(
            start=start,
            end=end,
            start_line=start_line,
            start_column=start_column,
            end_line=end_line,
            end_column=end_column,
        )


def tokenize(text: str) -> list[Token]:
    """Tokenize one bounded SQL source string and append exactly one EOF."""

    if not isinstance(text, str):
        raise SqlLexicalError("SQL source must be a string", position=0)
    source_map = _SourceMap(text)
    if len(text) > MAX_SQL_INPUT_CHARS:
        raise SqlLexicalError(
            f"SQL source exceeds the {MAX_SQL_INPUT_CHARS}-character limit",
            span=source_map.span(MAX_SQL_INPUT_CHARS, MAX_SQL_INPUT_CHARS + 1),
            source=text,
        )

    tokens: list[Token] = []
    i = 0
    n = len(text)

    def emit(
        token_type: TokenType,
        start: int,
        end: int,
        value: str,
        decoded: str | int | float | bool | None,
    ) -> None:
        tokens.append(
            Token(
                type=token_type,
                value=value,
                lexeme=text[start:end],
                decoded=decoded,
                span=source_map.span(start, end),
            )
        )

    while i < n:
        char = text[i]

        if char.isspace():
            i += 1
            continue

        if char == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if char == "'":
            start = i
            j = i + 1
            buffer: list[str] = []
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        buffer.append("'")
                        j += 2
                        continue
                    j += 1
                    decoded = "".join(buffer)
                    emit(TokenType.STRING, start, j, decoded, decoded)
                    i = j
                    break
                buffer.append(text[j])
                j += 1
            else:
                span = source_map.span(start, n)
                raise SqlLexicalError(
                    "Unterminated string literal", span=span, source=text
                )
            continue

        if _is_ascii_digit(char):
            start = i
            j = i
            while j < n and _is_ascii_digit(text[j]):
                j += 1
            is_float = False
            if j < n and text[j] == ".":
                if j + 1 >= n or not _is_ascii_digit(text[j + 1]):
                    raise SqlLexicalError(
                        "Decimal literal requires digits after '.'",
                        span=source_map.span(start, j + 1),
                        source=text,
                    )
                is_float = True
            if is_float:
                j += 1
                while j < n and _is_ascii_digit(text[j]):
                    j += 1
                if j < n and text[j] == ".":
                    raise SqlLexicalError(
                        "Decimal literal contains more than one '.'",
                        span=source_map.span(start, j + 1),
                        source=text,
                    )
            lexeme = text[start:j]
            digit_count = len(lexeme) - (1 if is_float else 0)
            if digit_count > MAX_NUMERIC_LITERAL_DIGITS:
                raise SqlLexicalError(
                    "Numeric literal exceeds the supported digit limit",
                    span=source_map.span(start, j),
                    source=text,
                )
            if is_float:
                decoded_float = float(lexeme)
                if not isfinite(decoded_float):
                    raise SqlLexicalError(
                        "Floating-point literal is outside the supported range",
                        span=source_map.span(start, j),
                        source=text,
                    )
                emit(TokenType.FLOAT, start, j, lexeme, decoded_float)
            else:
                emit(TokenType.INTEGER, start, j, lexeme, int(lexeme))
            i = j
            continue

        if _is_ident_start(char):
            start = i
            j = i + 1
            while j < n and _is_ident_continue(text[j]):
                j += 1
            lexeme = text[start:j]
            upper = lexeme.upper()
            if upper in KEYWORDS:
                decoded: str | bool = (
                    upper == "TRUE" if upper in {"TRUE", "FALSE"} else upper
                )
                emit(TokenType.KEYWORD, start, j, upper, decoded)
            else:
                emit(TokenType.IDENTIFIER, start, j, lexeme, lexeme)
            i = j
            continue

        matched_multi = next(
            (op for op in _MULTI_CHAR_COMPARISONS if text.startswith(op, i)), None
        )
        if matched_multi is not None:
            normalized = "<>" if matched_multi == "!=" else matched_multi
            emit(
                TokenType.COMPARISON_OPERATOR,
                i,
                i + len(matched_multi),
                normalized,
                normalized,
            )
            i += len(matched_multi)
            continue

        if char == "+":
            emit(TokenType.PLUS, i, i + 1, char, char)
            i += 1
            continue
        if char == "-":
            emit(TokenType.MINUS, i, i + 1, char, char)
            i += 1
            continue
        if char == "." and i + 1 < n and _is_ascii_digit(text[i + 1]):
            raise SqlLexicalError(
                "Decimal literal requires digits before '.'",
                span=source_map.span(i, i + 2),
                source=text,
            )
        if char in _SINGLE_CHAR_COMPARISONS:
            emit(TokenType.COMPARISON_OPERATOR, i, i + 1, char, char)
            i += 1
            continue
        if char in _SINGLE_CHAR_PUNCTUATION:
            emit(TokenType.PUNCTUATION, i, i + 1, char, char)
            i += 1
            continue

        span = source_map.span(i, i + 1)
        raise SqlLexicalError(
            f"Unrecognized character {char!r}",
            span=span,
            source=text,
            offending=char,
        )

    eof_span = source_map.span(n, n)
    tokens.append(Token(TokenType.EOF, "", "", None, eof_span))
    return tokens


__all__ = [
    "SqlLexicalError",
    "SqlSyntaxError",
    "Token",
    "TokenType",
    "tokenize",
]
