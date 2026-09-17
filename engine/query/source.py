"""Source-location primitives shared by the SQL lexer, AST, and parser."""

from __future__ import annotations

from dataclasses import dataclass

from engine.errors import InvalidTypeError, ValidationError


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Half-open SQL source range with zero-based offsets and one-based lines.

    ``start`` and ``end`` follow Python's slicing convention: ``start`` is
    inclusive and ``end`` is exclusive. Lines and columns are one-based so
    they can be displayed directly in diagnostics.
    """

    start: int
    end: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    def __post_init__(self) -> None:
        for name in (
            "start",
            "end",
            "start_line",
            "start_column",
            "end_line",
            "end_column",
        ):
            if type(getattr(self, name)) is not int:
                raise InvalidTypeError(f"SourceSpan.{name} must be an integer")
        if self.start < 0 or self.end < self.start:
            raise ValidationError("SourceSpan offsets must form a valid range")
        if min(
            self.start_line,
            self.start_column,
            self.end_line,
            self.end_column,
        ) < 1:
            raise ValidationError("SourceSpan lines and columns must be positive")
        if (self.end_line, self.end_column) < (
            self.start_line,
            self.start_column,
        ):
            raise ValidationError("SourceSpan end must not precede its start")

    @property
    def position(self) -> int:
        """Compatibility view of the first character as a one-based offset."""

        return self.start + 1

    @classmethod
    def cover(cls, first: SourceSpan, last: SourceSpan) -> SourceSpan:
        """Return the smallest ordered span covering ``first`` through ``last``."""

        if last.start < first.start:
            raise ValidationError("Cannot cover source spans in reverse order")
        return cls(
            start=first.start,
            end=last.end,
            start_line=first.start_line,
            start_column=first.start_column,
            end_line=last.end_line,
            end_column=last.end_column,
        )
