"""Immutable 20-byte file prefix; physical allocation belongs to PageManager."""

from dataclasses import dataclass

from engine.errors import ValidationError
from engine.storage.binary import (
    FILE_HEADER_SIZE,
    FILE_HEADER_STRUCT,
    FILE_MAGIC,
    FORMAT_VERSION,
    PAGE_SIZE,
    require_bytes,
    validate_file_header,
)


@dataclass(frozen=True, slots=True)
class FileHeader:
    """Version-1 signature, version, page size and allocated data-page count.

    Data pages are numbered from zero, excluding this prefix. A representable
    count is metadata only; PageManager checks the actual file length.
    """

    magic: bytes = FILE_MAGIC
    version: int = FORMAT_VERSION
    page_size: int = PAGE_SIZE
    allocated_page_count: int = 0

    def __post_init__(self) -> None:
        validate_file_header(
            magic=self.magic,
            version=self.version,
            page_size=self.page_size,
            allocated_page_count=self.allocated_page_count,
        )

    def serialize(self) -> bytes:
        return FILE_HEADER_STRUCT.pack(
            self.magic, self.version, self.page_size, self.allocated_page_count,
        )

    @classmethod
    def deserialize(cls, payload: bytes) -> "FileHeader":
        require_bytes(payload)
        if len(payload) != FILE_HEADER_SIZE:
            raise ValidationError(f"FileHeader requires exactly {FILE_HEADER_SIZE} bytes")
        return cls(*FILE_HEADER_STRUCT.unpack(payload))
