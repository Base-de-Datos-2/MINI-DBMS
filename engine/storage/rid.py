"""Physical record identifiers, independent from file allocation and I/O."""

from dataclasses import dataclass

from engine.errors import InvalidTypeError, ValidationError


@dataclass(frozen=True, slots=True, order=True)
class RID:
    """Identify a slot within a page of a particular storage file.

    Both components are non-negative built-in integers (not booleans).
    Ordering is lexicographic: page first, then slot. A RID does not verify
    that its page or slot exists, and is not a globally unique table ID.
    """

    page_id: int
    slot_id: int

    def __post_init__(self) -> None:
        for name, value in (("page_id", self.page_id), ("slot_id", self.slot_id)):
            if type(value) is not int:
                raise InvalidTypeError(f"RID {name} must be an integer, not a boolean")
            if value < 0:
                raise ValidationError(f"RID {name} must be non-negative")
