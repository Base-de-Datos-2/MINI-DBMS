"""One fixed-size slotted page in memory, with no schema or file ownership."""

from dataclasses import replace

from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage.binary import (
    MAX_RECORD_SIZE,
    PAGE_HEADER_SIZE,
    PAGE_SIZE,
    SLOT_ACTIVE,
    SLOT_SIZE,
    require_bytes,
    validate_page_buffer,
    validate_page_layout,
)
from engine.storage.page_header import PageHeader
from engine.storage.slot_entry import SlotEntry


class Page:
    """Own a private page buffer; expose immutable metadata/byte snapshots.

    Insert uses contiguous free space and the first free slot, if any. Delete
    releases that slot but leaves its payload as a hole until explicit compact().
    Live slots never move or change id. A reused deleted id names a new record.
    This class is not Storage: it handles bytes/slot ids, not Records/RIDs.
    """

    __slots__ = ("_data",)

    def __init__(self, page_id: int) -> None:
        header = PageHeader(page_id)
        self._data = bytearray(PAGE_SIZE)
        self._data[:PAGE_HEADER_SIZE] = header.serialize()

    @staticmethod
    def _inspect(data: bytes | bytearray) -> tuple[PageHeader, tuple[SlotEntry, ...]]:
        """Validate the whole directory before exposing records or mutating it."""
        validate_page_buffer(bytes(data))
        header = PageHeader.deserialize(bytes(data[:PAGE_HEADER_SIZE]))
        slots = tuple(
            SlotEntry.deserialize(bytes(data[start:start + SLOT_SIZE]))
            for start in range(PAGE_HEADER_SIZE, header.free_space_start, SLOT_SIZE)
        )
        validate_page_layout(
            page_id=header.page_id,
            slot_count=header.slot_count,
            free_space_start=header.free_space_start,
            free_space_end=header.free_space_end,
            active_record_count=header.active_record_count,
            active_regions=[(slot.offset, slot.length) for slot in slots if slot.is_active],
        )
        return header, slots

    @property
    def header(self) -> PageHeader:
        return self._inspect(self._data)[0]

    @property
    def slots(self) -> tuple[SlotEntry, ...]:
        return self._inspect(self._data)[1]

    @property
    def page_id(self) -> int:
        return self.header.page_id

    @property
    def slot_count(self) -> int:
        return self.header.slot_count

    @property
    def active_record_count(self) -> int:
        return self.header.active_record_count

    def free_space(self) -> int:
        """Contiguous gap only; a new slot still costs SLOT_SIZE bytes from it."""
        return self.header.contiguous_free_space

    def _commit_update(
        self, header: PageHeader, slot_id: int, slot: SlotEntry,
        payload: bytes | None = None,
    ) -> None:
        # Work on a bounded copy: validation failures never partially update the
        # live buffer. This is local error atomicity, not concurrency/recovery.
        updated = self._data.copy()
        updated[:PAGE_HEADER_SIZE] = header.serialize()
        start = PAGE_HEADER_SIZE + slot_id * SLOT_SIZE
        updated[start:start + SLOT_SIZE] = slot.serialize()
        if payload is not None:
            updated[slot.offset:slot.offset + slot.length] = payload
        self._inspect(updated)
        self._data = updated

    def insert(self, payload: bytes) -> int:
        """Insert opaque bytes, returning a slot id; capacity failures are ValueError.

        Domain ValidationError reports an oversized payload or insufficient
        contiguous space. No automatic compaction or overflow pages are used.
        Empty payloads are active records and still need a directory entry.
        """
        require_bytes(payload)
        header, slots = self._inspect(self._data)
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError(f"Record payload exceeds page capacity of {MAX_RECORD_SIZE} bytes")

        slot_id = next((i for i, slot in enumerate(slots) if not slot.is_active), len(slots))
        new_slot = slot_id == len(slots)
        directory_cost = SLOT_SIZE if new_slot else 0
        required = len(payload) + directory_cost
        if required > header.contiguous_free_space:
            raise ValidationError(
                f"Insufficient contiguous free space: requires {required} bytes, "
                f"available {header.contiguous_free_space}; payload holes need compaction"
            )

        free_end = header.free_space_end - len(payload)
        slot = SlotEntry(free_end if payload else PAGE_SIZE, len(payload), SLOT_ACTIVE)
        updated_header = replace(
            header,
            slot_count=header.slot_count + int(new_slot),
            free_space_start=header.free_space_start + directory_cost,
            free_space_end=free_end,
            active_record_count=header.active_record_count + 1,
        )
        self._commit_update(updated_header, slot_id, slot, payload)
        return slot_id

    def _active_slot(self, slot_id: int) -> tuple[PageHeader, SlotEntry]:
        if type(slot_id) is not int:
            raise InvalidTypeError("slot_id must be a built-in int")
        header, slots = self._inspect(self._data)
        if not 0 <= slot_id < len(slots):
            raise InvalidReferenceError(f"Unknown slot_id: {slot_id}")
        slot = slots[slot_id]
        if not slot.is_active:
            raise InvalidReferenceError(f"Slot {slot_id} is free/deleted")
        return header, slot

    def read(self, slot_id: int) -> bytes:
        """Return live payload bytes, never bytes from a free or unknown slot.

        Unknown and free/deleted slots raise InvalidReferenceError with distinct
        messages. Corrupt metadata raises ValidationError before payload access.
        """
        _, slot = self._active_slot(slot_id)
        return bytes(self._data[slot.offset:slot.offset + slot.length])

    def delete(self, slot_id: int) -> None:
        """Free one slot without moving payloads or recovering its byte hole.

        A second delete raises InvalidReferenceError. The old bytes are not
        securely erased; only the slot state and active count change.
        """
        header, _ = self._active_slot(slot_id)
        updated_header = replace(header, active_record_count=header.active_record_count - 1)
        self._commit_update(updated_header, slot_id, SlotEntry())

    def serialize(self) -> bytes:
        """Return the entire validated PAGE_SIZE frame, including unused bytes."""
        self._inspect(self._data)
        return bytes(self._data)

    def compact(self) -> None:
        """Repack live payloads, retaining every directory position and live RID.

        The directory is never shortened, even when all records were deleted.
        Packing follows slot order and zero-fills unused bytes in the new frame;
        it is deterministic, not a secure erase of any existing disk contents.
        Validation failure leaves the original buffer unchanged.
        """
        header, slots = self._inspect(self._data)
        updated = bytearray(PAGE_SIZE)
        free_end = PAGE_SIZE
        for slot_id, slot in enumerate(slots):
            if slot.is_active:
                free_end -= slot.length
                offset = free_end if slot.length else PAGE_SIZE
                updated[offset:offset + slot.length] = self._data[
                    slot.offset:slot.offset + slot.length
                ]
                slot = replace(slot, offset=offset)
            start = PAGE_HEADER_SIZE + slot_id * SLOT_SIZE
            updated[start:start + SLOT_SIZE] = slot.serialize()
        updated[:PAGE_HEADER_SIZE] = replace(header, free_space_end=free_end).serialize()
        self._inspect(updated)
        self._data = updated

    @classmethod
    def deserialize(cls, payload: bytes) -> "Page":
        """Reconstruct an independent, fully validated page, preserving all bytes."""
        validate_page_buffer(payload)
        header, _ = cls._inspect(payload)
        page = cls(header.page_id)
        page._data = bytearray(payload)
        return page
