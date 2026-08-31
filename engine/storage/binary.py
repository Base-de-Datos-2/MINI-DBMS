"""Version-1 binary layout and geometry, independent of records and file I/O.

Slot/file formats define the adopted design only; their objects and algorithms
are implemented in later tasks. Sizes always derive from explicit-endian formats.
"""

from collections.abc import Sequence
from struct import Struct

from engine.errors import InvalidTypeError, ValidationError

PAGE_SIZE = 4096
FILE_MAGIC = b"MINIDB\x00\x00"
FORMAT_VERSION = 1
STRING_ENCODING = "utf-8"

PAGE_HEADER_FORMAT = "<IHHHH"
SLOT_FORMAT = "<HHB"
FILE_HEADER_FORMAT = "<8sIII"
INTEGER_FORMAT = "<q"
FLOAT_FORMAT = "<d"
BOOLEAN_FORMAT = "<B"
VARCHAR_LENGTH_FORMAT = "<I"

PAGE_HEADER_STRUCT = Struct(PAGE_HEADER_FORMAT)
SLOT_STRUCT = Struct(SLOT_FORMAT)
FILE_HEADER_STRUCT = Struct(FILE_HEADER_FORMAT)
INTEGER_STRUCT = Struct(INTEGER_FORMAT)
FLOAT_STRUCT = Struct(FLOAT_FORMAT)
BOOLEAN_STRUCT = Struct(BOOLEAN_FORMAT)
VARCHAR_LENGTH_STRUCT = Struct(VARCHAR_LENGTH_FORMAT)

PAGE_HEADER_SIZE = PAGE_HEADER_STRUCT.size
SLOT_SIZE = SLOT_STRUCT.size
FILE_HEADER_SIZE = FILE_HEADER_STRUCT.size
UINT16_MAX = (1 << 16) - 1
UINT32_MAX = (1 << 32) - 1
INTEGER_MIN = -(1 << 63)
INTEGER_MAX = (1 << 63) - 1
MAX_SLOTS = (PAGE_SIZE - PAGE_HEADER_SIZE) // SLOT_SIZE
MAX_RECORD_SIZE = PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_SIZE
SLOT_FREE = 0
SLOT_ACTIVE = 1
CANONICAL_NAN_BYTES = bytes.fromhex("000000000000f87f")


def require_bytes(payload: bytes) -> None:
    """Binary APIs accept immutable bytes, without implicit buffer conversion."""
    if not isinstance(payload, bytes):
        raise InvalidTypeError("payload must be bytes")


def _validate_uint(name: str, value: int, maximum: int) -> None:
    if type(value) is not int:
        raise InvalidTypeError(f"{name} must be a built-in int")
    if not 0 <= value <= maximum:
        raise ValidationError(f"{name} must be between 0 and {maximum}")


def validate_page_buffer(payload: bytes) -> None:
    """Check only a complete page's byte length, not its metadata/content."""
    require_bytes(payload)
    if len(payload) != PAGE_SIZE:
        raise ValidationError(f"A page buffer must contain exactly {PAGE_SIZE} bytes")


def validate_page_layout(
    *,
    page_id: int,
    slot_count: int,
    free_space_start: int,
    free_space_end: int,
    active_record_count: int,
    active_regions: Sequence[tuple[int, int]] | None = None,
) -> None:
    """Validate header geometry and, optionally, live (offset, length) ranges.

    This does not parse slots, verify allocation, or construct a Page. Empty
    ranges occupy no bytes. Holes are allowed because deletion can fragment a
    page; free_space_end marks the beginning of its entire payload area.
    """
    _validate_uint("page_id", page_id, UINT32_MAX)
    for name, value in (
        ("slot_count", slot_count),
        ("free_space_start", free_space_start),
        ("free_space_end", free_space_end),
        ("active_record_count", active_record_count),
    ):
        _validate_uint(name, value, UINT16_MAX)

    if slot_count > MAX_SLOTS:
        raise ValidationError("slot_count exceeds page directory capacity")
    if active_record_count > slot_count:
        raise ValidationError("active_record_count exceeds slot_count")
    if free_space_start != PAGE_HEADER_SIZE + slot_count * SLOT_SIZE:
        raise ValidationError("free_space_start must immediately follow the slot directory")
    if not free_space_start <= free_space_end <= PAGE_SIZE:
        raise ValidationError("Free-space bounds overlap the directory or exceed the page")
    if slot_count == 0 and free_space_end != PAGE_SIZE:
        raise ValidationError("A page without slots cannot contain payload space")

    if active_regions is None:
        return
    if not isinstance(active_regions, Sequence) or isinstance(
        active_regions, (str, bytes, bytearray)
    ):
        raise InvalidTypeError("active_regions must be a sequence of offset/length pairs")
    if len(active_regions) != active_record_count:
        raise ValidationError("active_regions must match active_record_count")

    occupied = []
    for region in active_regions:
        if not isinstance(region, Sequence) or isinstance(region, (str, bytes, bytearray)):
            raise InvalidTypeError("Each active region must be an offset/length pair")
        if len(region) != 2:
            raise ValidationError("Each active region must contain exactly two components")
        offset, length = region
        _validate_uint("record offset", offset, UINT16_MAX)
        _validate_uint("record length", length, UINT16_MAX)
        if offset < free_space_end or offset + length > PAGE_SIZE:
            raise ValidationError("Active record range is outside the payload area")
        if length:
            occupied.append((offset, offset + length))

    previous_end = free_space_end
    for start, end in sorted(occupied):
        if start < previous_end:
            raise ValidationError("Active record ranges overlap")
        previous_end = end
