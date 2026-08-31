"""Immutable page metadata; no records, slot objects, allocation, or file I/O."""

from dataclasses import dataclass

from engine.errors import ValidationError
from engine.storage.binary import (
    PAGE_HEADER_SIZE,
    PAGE_HEADER_STRUCT,
    PAGE_SIZE,
    require_bytes,
    validate_page_layout,
)


@dataclass(frozen=True, slots=True)
class PageHeader:
    """Validated 12-byte v1 header, defaulting to an empty page.

    Counts include all slots versus live records separately. Free bounds report
    only the contiguous gap; reclaimable payload holes are not counted here.
    page_id is representable metadata, not proof of file allocation.
    """

    page_id: int
    slot_count: int = 0
    free_space_start: int = PAGE_HEADER_SIZE
    free_space_end: int = PAGE_SIZE
    active_record_count: int = 0

    def __post_init__(self) -> None:
        validate_page_layout(
            page_id=self.page_id,
            slot_count=self.slot_count,
            free_space_start=self.free_space_start,
            free_space_end=self.free_space_end,
            active_record_count=self.active_record_count,
        )

    @property
    def contiguous_free_space(self) -> int:
        return self.free_space_end - self.free_space_start

    def serialize(self) -> bytes:
        return PAGE_HEADER_STRUCT.pack(
            self.page_id,
            self.slot_count,
            self.free_space_start,
            self.free_space_end,
            self.active_record_count,
        )

    @classmethod
    def deserialize(cls, payload: bytes) -> "PageHeader":
        """Read exactly a header, rejecting invalid fields before returning it."""
        require_bytes(payload)
        if len(payload) != PAGE_HEADER_SIZE:
            raise ValidationError(f"PageHeader requires exactly {PAGE_HEADER_SIZE} bytes")
        return cls(*PAGE_HEADER_STRUCT.unpack(payload))
