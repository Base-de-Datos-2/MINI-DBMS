"""One immutable entry in the version-1 slotted-page directory."""

from dataclasses import dataclass

from engine.errors import ValidationError
from engine.storage.binary import (
    SLOT_ACTIVE,
    SLOT_FREE,
    SLOT_SIZE,
    SLOT_STRUCT,
    require_bytes,
    validate_slot_layout,
)


@dataclass(frozen=True, slots=True)
class SlotEntry:
    """Five-byte (offset, length, status) value, defaulting to a free slot.

    Status is an exact int: SLOT_FREE (0) or SLOT_ACTIVE (1), not a bool.
    The slot id is its directory position, not a field here. Page validates
    overlap and live-record counts using all entries and the page header.
    """

    offset: int = 0
    length: int = 0
    status: int = SLOT_FREE

    def __post_init__(self) -> None:
        validate_slot_layout(offset=self.offset, length=self.length, status=self.status)

    @property
    def is_active(self) -> bool:
        return self.status == SLOT_ACTIVE

    def serialize(self) -> bytes:
        return SLOT_STRUCT.pack(self.offset, self.length, self.status)

    @classmethod
    def deserialize(cls, payload: bytes) -> "SlotEntry":
        require_bytes(payload)
        if len(payload) != SLOT_SIZE:
            raise ValidationError(f"SlotEntry requires exactly {SLOT_SIZE} bytes")
        return cls(*SLOT_STRUCT.unpack(payload))
