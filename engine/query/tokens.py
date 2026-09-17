"""Token contracts for the hand-written SQL front end."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .source import SourceSpan


class TokenType(Enum):
    KEYWORD = auto()
    IDENTIFIER = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    COMPARISON_OPERATOR = auto()
    PUNCTUATION = auto()
    PLUS = auto()
    MINUS = auto()
    EOF = auto()


DecodedTokenValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Token:
    """One lexical token with both source spelling and normalized meaning.

    ``value`` remains the parser-facing representation used by the original
    Stage 7 implementation. ``lexeme`` preserves the exact source text and
    ``decoded`` exposes the typed literal value where one exists.
    """

    type: TokenType
    value: str
    lexeme: str
    decoded: DecodedTokenValue
    span: SourceSpan

    @property
    def position(self) -> int:
        """One-based starting offset kept for diagnostic compatibility."""

        return self.span.position
