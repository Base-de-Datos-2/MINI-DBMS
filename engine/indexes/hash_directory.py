"""Pure directory model and fixed-page codec for Extendible Hashing."""

from __future__ import annotations

from dataclasses import dataclass

from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import UINT32_MAX, require_bytes

from .hash_binary import (
    HASH_DIRECTORY_ENTRIES_PER_PAGE,
    HASH_DIRECTORY_ENTRY_STRUCT,
    HASH_DIRECTORY_HEADER_SIZE,
    HASH_DIRECTORY_HEADER_STRUCT,
    HASH_DIRECTORY_MAGIC,
    HASH_MAX_PAGE_ID,
    HASH_NULL_PAGE_ID,
    HASH_PAGE_FORMAT_VERSION,
    HASH_BUCKET_PAYLOAD_SIZE,
    HASH_WIDTH,
)
from .hash_codec import HashCodec


def _page_reference(value: object, label: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is not int:
        raise InvalidTypeError(f"{label} must be a built-in int")
    if not 1 <= value <= HASH_MAX_PAGE_ID:
        raise ValidationError(f"{label} must reference a non-header page")
    return value


@dataclass(frozen=True, slots=True, init=False)
class HashDirectory:
    """Logical ``2^D`` map; aliases intentionally repeat bucket page IDs."""

    global_depth: int
    entries: tuple[int, ...]

    def __init__(self, global_depth: int, entries) -> None:
        if type(global_depth) is not int:
            raise InvalidTypeError("global_depth must be a built-in int")
        if not 0 <= global_depth <= HASH_WIDTH:
            raise ValidationError(f"global_depth must be between 0 and {HASH_WIDTH}")
        if isinstance(entries, (str, bytes, bytearray)):
            raise InvalidTypeError("directory entries must be an iterable of page IDs")
        try:
            checked = tuple(
                _page_reference(value, "bucket page_id") for value in entries
            )
        except TypeError as exc:
            raise InvalidTypeError(
                "directory entries must be an iterable of page IDs"
            ) from exc
        if len(checked) != 1 << global_depth:
            raise ValidationError("Hash directory size must equal 2^global_depth")
        object.__setattr__(self, "global_depth", global_depth)
        object.__setattr__(self, "entries", checked)

    def lookup_bucket(self, hash_value: int) -> int:
        return self.entries[HashCodec.directory_index(hash_value, self.global_depth)]

    def get_entry(self, index: object) -> int:
        if type(index) is not int:
            raise InvalidTypeError("directory index must be a built-in int")
        if not 0 <= index < len(self.entries):
            raise ValidationError("directory index is outside the logical directory")
        return self.entries[index]

    def set_entry(self, index: object, page_id: object) -> "HashDirectory":
        checked_page = _page_reference(page_id, "bucket page_id")
        if checked_page is None:  # pragma: no cover - optional=False above
            raise ValidationError("bucket page_id cannot be null")
        checked_index = HashCodec.directory_index(index, self.global_depth)
        if index != checked_index:
            raise ValidationError("directory index is outside the logical directory")
        updated = list(self.entries)
        updated[checked_index] = checked_page
        return type(self)(self.global_depth, updated)

    def double(self) -> "HashDirectory":
        if self.global_depth == HASH_WIDTH:
            raise ValidationError("Hash directory cannot exceed the hash width")
        # With LSB addressing, indices i and i + 2^D initially remain aliases.
        return type(self)(self.global_depth + 1, self.entries + self.entries)

    def iter_entries(self):
        return iter(self.entries)

    def validate_shape(self) -> None:
        # Reconstruction reruns every constructor invariant without mutation.
        type(self)(self.global_depth, self.entries)


@dataclass(frozen=True, slots=True, init=False)
class HashDirectoryPage:
    """One ordered chunk of the logical directory's persistent chain."""

    ordinal: int
    bucket_page_ids: tuple[int, ...]
    next_page_id: int | None

    def __init__(self, ordinal: int, bucket_page_ids, *, next_page_id=None) -> None:
        if type(ordinal) is not int:
            raise InvalidTypeError("directory page ordinal must be a built-in int")
        if not 0 <= ordinal <= UINT32_MAX:
            raise ValidationError("directory page ordinal exceeds uint32")
        if isinstance(bucket_page_ids, (str, bytes, bytearray)):
            raise InvalidTypeError("bucket_page_ids must be an iterable")
        try:
            entries = tuple(
                _page_reference(value, "bucket page_id")
                for value in bucket_page_ids
            )
        except TypeError as exc:
            raise InvalidTypeError("bucket_page_ids must be an iterable") from exc
        if not 1 <= len(entries) <= HASH_DIRECTORY_ENTRIES_PER_PAGE:
            raise ValidationError("directory page has an invalid entry count")
        checked_next = _page_reference(
            next_page_id, "next directory page_id", optional=True
        )
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "bucket_page_ids", entries)
        object.__setattr__(self, "next_page_id", checked_next)


class HashDirectoryCodec:
    """Encode a directory chunk as exactly one Page payload."""

    @staticmethod
    def serialize(page: HashDirectoryPage) -> bytes:
        if not isinstance(page, HashDirectoryPage):
            raise InvalidTypeError("page must be a HashDirectoryPage")
        next_page_id = (
            HASH_NULL_PAGE_ID if page.next_page_id is None else page.next_page_id
        )
        payload = bytearray(
            HASH_DIRECTORY_HEADER_STRUCT.pack(
                HASH_DIRECTORY_MAGIC,
                HASH_PAGE_FORMAT_VERSION,
                0,
                len(page.bucket_page_ids),
                page.ordinal,
                next_page_id,
            )
        )
        for bucket_page_id in page.bucket_page_ids:
            payload.extend(HASH_DIRECTORY_ENTRY_STRUCT.pack(bucket_page_id))
        payload.extend(bytes(HASH_BUCKET_PAYLOAD_SIZE - len(payload)))
        return bytes(payload)

    @staticmethod
    def deserialize(payload: bytes) -> HashDirectoryPage:
        require_bytes(payload)
        if len(payload) != HASH_BUCKET_PAYLOAD_SIZE:
            raise ValidationError("Hash directory payload has an invalid length")
        magic, version, reserved, count, ordinal, raw_next = (
            HASH_DIRECTORY_HEADER_STRUCT.unpack_from(payload)
        )
        if magic != HASH_DIRECTORY_MAGIC:
            raise ValidationError("Invalid hash directory signature")
        if version != HASH_PAGE_FORMAT_VERSION:
            raise ValidationError("Unsupported hash directory page version")
        if reserved != 0:
            raise ValidationError("Hash directory reserved byte must be zero")
        if not 1 <= count <= HASH_DIRECTORY_ENTRIES_PER_PAGE:
            raise ValidationError("Hash directory page has an invalid entry count")

        offset = HASH_DIRECTORY_HEADER_SIZE
        entries: list[int] = []
        for _ in range(count):
            entries.append(HASH_DIRECTORY_ENTRY_STRUCT.unpack_from(payload, offset)[0])
            offset += HASH_DIRECTORY_ENTRY_STRUCT.size
        if any(payload[offset:]):
            raise ValidationError("Hash directory has nonzero trailing bytes")
        next_page_id = None if raw_next == HASH_NULL_PAGE_ID else raw_next
        return HashDirectoryPage(ordinal, entries, next_page_id=next_page_id)
