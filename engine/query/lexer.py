"""Hand-written tokenizer for the supported SQL subset (Stage 7, Task 7.4).

No third-party parsing library is used (adopted decision: manual parser, zero
new dependencies). The lexer never raises on its own initiative for anything
but a genuinely unrecognized character or an unterminated string literal; all
grammar-level rejection belongs to the parser, so that error messages point at
the right production.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from engine.errors import ValidationError


class SqlSyntaxError(ValidationError):
    """Raised for any lexical or syntactic defect in a SQL statement.

    Carries the 1-based character offset so a caller can point at the exact
    spot, matching the "fails without side effects, with a located error"
    exit condition of Increment A.
    """

    def __init__(self, message: str, *, position: int) -> None:
        super().__init__(f"{message} (at position {position})")
        self.position = position


class TokenType(Enum):
    KEYWORD = auto()
    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    PUNCTUATION = auto()
    EOF = auto()


KEYWORDS = frozenset(
    {
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "AS", "JOIN", "INNER",
        "ON", "GROUP", "BY", "ORDER", "ASC", "DESC", "INSERT", "INTO",
        "VALUES", "DELETE", "TRUE", "FALSE",
    }
)

#: Longest punctuation tokens first, so `<=` is not lexed as `<` then `=`.
_MULTI_CHAR_PUNCTUATION = ("<=", ">=", "<>", "!=")
_SINGLE_CHAR_PUNCTUATION = set("*,.()=<>;")


@dataclass(frozen=True, slots=True)
class Token:
    type: TokenType
    value: str
    position: int  # 1-based offset of the first character


def _is_ident_start(char: str) -> bool:
    return char.isalpha() or char == "_"


def _is_ident_continue(char: str) -> bool:
    return char.isalnum() or char == "_"


def tokenize(text: str) -> list[Token]:
    """Turn SQL source text into a token list, terminated by one EOF token."""

    if not isinstance(text, str):
        raise SqlSyntaxError("SQL source must be a string", position=0)
    tokens: list[Token] = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        pos = i + 1  # report 1-based positions to the person reading errors

        if char.isspace():
            i += 1
            continue

        if char == "-" and i + 1 < n and text[i + 1] == "-":
            while i < n and text[i] != "\n":
                i += 1
            continue

        if char == "'":
            j = i + 1
            buffer: list[str] = []
            closed = False
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        buffer.append("'")
                        j += 2
                        continue
                    closed = True
                    j += 1
                    break
                buffer.append(text[j])
                j += 1
            if not closed:
                raise SqlSyntaxError("Unterminated string literal", position=pos)
            tokens.append(Token(TokenType.STRING, "".join(buffer), pos))
            i = j
            continue

        if char.isdigit():
            j = i
            is_float = False
            while j < n and text[j].isdigit():
                j += 1
            if j < n and text[j] == "." and j + 1 < n and text[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and text[j].isdigit():
                    j += 1
            lexeme = text[i:j]
            tokens.append(
                Token(
                    TokenType.FLOAT if is_float else TokenType.INTEGER,
                    lexeme,
                    pos,
                )
            )
            i = j
            continue

        if _is_ident_start(char):
            j = i + 1
            while j < n and _is_ident_continue(text[j]):
                j += 1
            lexeme = text[i:j]
            upper = lexeme.upper()
            if upper in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, upper, pos))
            else:
                tokens.append(Token(TokenType.IDENTIFIER, lexeme, pos))
            i = j
            continue

        matched_multi = next(
            (op for op in _MULTI_CHAR_PUNCTUATION if text.startswith(op, i)), None
        )
        if matched_multi is not None:
            normalized = "<>" if matched_multi == "!=" else matched_multi
            tokens.append(Token(TokenType.PUNCTUATION, normalized, pos))
            i += len(matched_multi)
            continue

        if char in _SINGLE_CHAR_PUNCTUATION:
            tokens.append(Token(TokenType.PUNCTUATION, char, pos))
            i += 1
            continue

        raise SqlSyntaxError(f"Unrecognized character {char!r}", position=pos)

    tokens.append(Token(TokenType.EOF, "", n + 1))
    return tokens
