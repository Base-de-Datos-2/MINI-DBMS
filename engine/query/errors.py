"""Located error hierarchy for the handwritten SQL front end."""

from __future__ import annotations

from engine.errors import ValidationError

from .source import SourceSpan


def _source_excerpt(source: str, offset: int, *, limit: int = 120) -> str:
    """Return a bounded single-line excerpt around ``offset``."""

    offset = min(max(offset, 0), len(source))
    line_start = source.rfind("\n", 0, offset) + 1
    line_end = source.find("\n", offset)
    if line_end < 0:
        line_end = len(source)
    line = source[line_start:line_end]
    relative = offset - line_start
    if len(line) <= limit:
        return line
    half = limit // 2
    excerpt_start = max(0, min(relative - half, len(line) - limit))
    excerpt_end = excerpt_start + limit
    prefix = "..." if excerpt_start else ""
    suffix = "..." if excerpt_end < len(line) else ""
    return f"{prefix}{line[excerpt_start:excerpt_end]}{suffix}"


class SqlQueryError(ValidationError):
    """Base class for controlled SQL-front-end failures."""

    def __init__(
        self,
        message: str,
        *,
        position: int | None = None,
        span: SourceSpan | None = None,
        source: str | None = None,
        expected: str | None = None,
        offending: str | None = None,
    ) -> None:
        if position is None:
            if span is None:
                raise TypeError("SQL errors require a position or source span")
            position = span.position

        self.position = position
        self.span = span
        self.expected = expected
        self.offending = offending
        self.line = span.start_line if span is not None else None
        self.column = span.start_column if span is not None else None
        self.context = (
            _source_excerpt(source, max(position - 1, 0))
            if source is not None and position > 0
            else None
        )

        if self.line is not None and self.column is not None:
            location = (
                f"line {self.line}, column {self.column}; position {self.position}"
            )
        else:
            location = f"position {self.position}"
        context = f"; near {self.context!r}" if self.context else ""
        super().__init__(f"{message} (at {location}{context})")


class SqlSyntaxError(SqlQueryError):
    """Malformed input in an otherwise supported SQL statement family."""


class SqlLexicalError(SqlSyntaxError):
    """Source text that cannot be converted into SQL tokens."""


class SqlUnsupportedError(SqlSyntaxError):
    """Recognized SQL syntax that is outside the adopted Stage 7 subset."""


class SqlLimitError(SqlSyntaxError):
    """A controlled SQL input or parser-depth limit failure."""


__all__ = [
    "SqlLexicalError",
    "SqlLimitError",
    "SqlQueryError",
    "SqlSyntaxError",
    "SqlUnsupportedError",
]
