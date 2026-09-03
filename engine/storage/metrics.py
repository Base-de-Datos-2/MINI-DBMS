"""Immutable measurements produced by storage maintenance operations."""

from dataclasses import dataclass
import math

from engine.errors import InvalidTypeError, ValidationError


@dataclass(frozen=True, slots=True)
class ReorganizationMetrics:
    """Actual elapsed time, page transfers, and file sizes for one rewrite.

    Page counters aggregate the source scan, compact candidate construction,
    and candidate validation. As in :class:`PageManager`, header transfers,
    flushes, and the filesystem replacement itself are not page transfers.
    """

    elapsed_seconds: float
    pages_read: int
    pages_written: int
    pages_allocated: int
    file_size_before: int
    file_size_after: int

    def __post_init__(self) -> None:
        if type(self.elapsed_seconds) is not float:
            raise InvalidTypeError("elapsed_seconds must be a float")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0.0:
            raise ValidationError("elapsed_seconds must be finite and non-negative")

        for name in (
            "pages_read",
            "pages_written",
            "pages_allocated",
            "file_size_before",
            "file_size_after",
        ):
            value = getattr(self, name)
            if type(value) is not int:
                raise InvalidTypeError(f"{name} must be an int")
            if value < 0:
                raise ValidationError(f"{name} must be non-negative")

    @property
    def bytes_reclaimed(self) -> int:
        """Return the physical size reduction, or zero when size did not fall."""

        return max(0, self.file_size_before - self.file_size_after)
