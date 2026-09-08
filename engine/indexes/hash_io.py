"""PageManager-backed I/O for hash metadata, directory, and bucket pages."""

from __future__ import annotations

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.page import Page
from engine.storage.page_manager import PageManager

from .hash_bucket import HashBucket, HashBucketCodec
from .hash_directory import HashDirectoryCodec, HashDirectoryPage
from .hash_header import HashFileHeader


_HEADER_PAGE_ID = 0
_ONLY_SLOT_ID = 0


def _require_manager(manager: object) -> PageManager:
    if not isinstance(manager, PageManager):
        raise InvalidTypeError("manager must be a PageManager")
    return manager


def _frame(page_id: int, payload: bytes) -> Page:
    # Hash pages deliberately reuse the ordinary slotted-page envelope instead
    # of introducing a second physical I/O subsystem.
    page = Page(page_id)
    if page.insert(payload) != _ONLY_SLOT_ID:
        raise ValidationError("Hash page payload must occupy slot 0")
    return page


def _payload(page: Page, label: str) -> bytes:
    if page.slot_count != 1 or page.active_record_count != 1:
        raise ValidationError(f"Invalid {label} page layout")
    if not page.slots[_ONLY_SLOT_ID].is_active:
        raise ValidationError(f"Invalid {label} page slot state")
    return page.read(_ONLY_SLOT_ID)


class HashHeaderPageIO:
    """Read and publish the canonical descriptor in physical page zero."""

    @staticmethod
    def write(manager: PageManager, header: HashFileHeader) -> None:
        checked = _require_manager(manager)
        if not isinstance(header, HashFileHeader):
            raise InvalidTypeError("header must be a HashFileHeader")
        if checked.allocated_page_count != header.index_page_count + 1:
            raise ValidationError("Hash header page count does not match the file")
        checked.write_page(_frame(_HEADER_PAGE_ID, header.serialize()))

    @staticmethod
    def read(manager: PageManager) -> HashFileHeader:
        checked = _require_manager(manager)
        if checked.allocated_page_count == 0:
            raise ValidationError("Hash file has no metadata page")
        header = HashFileHeader.deserialize(
            _payload(checked.read_page(_HEADER_PAGE_ID), "hash metadata")
        )
        if checked.allocated_page_count != header.index_page_count + 1:
            raise ValidationError("Hash header page count does not match the file")
        return header


class HashDirectoryPageIO:
    """Transfer strict directory chunks through the shared page manager."""

    def __init__(self, manager: PageManager) -> None:
        self._manager = _require_manager(manager)
        # Typed counters complement PageManager's aggregate physical counters.
        self.pages_read = 0
        self.pages_written = 0
        self.pages_allocated = 0

    def allocate_page(self) -> int:
        page_id = self._manager.allocate_page()
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("Allocate hash metadata page before directory pages")
        self.pages_allocated += 1
        return page_id

    def write_page(self, page_id: int, directory_page: HashDirectoryPage) -> None:
        self._manager.write_page(
            _frame(page_id, HashDirectoryCodec.serialize(directory_page))
        )
        self.pages_written += 1

    def read_page(self, page_id: int) -> HashDirectoryPage:
        if type(page_id) is not int:
            raise InvalidTypeError("directory page_id must be a built-in int")
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("Hash directory cannot use metadata page 0")
        physical_page = self._manager.read_page(page_id)
        # A completed physical transfer counts even when strict decoding later
        # identifies corruption in the payload.
        self.pages_read += 1
        return HashDirectoryCodec.deserialize(
            _payload(physical_page, "hash directory")
        )

    def reset_counters(self) -> None:
        """Reset only the counters owned by this typed I/O adapter."""

        self.pages_read = self.pages_written = self.pages_allocated = 0


class HashBucketPageIO:
    """Transfer bucket models while validating physical/stored page identity."""

    def __init__(self, manager: PageManager, key_type: DataType) -> None:
        self._manager = _require_manager(manager)
        if not isinstance(key_type, DataType):
            raise InvalidTypeError("key_type must be a DataType")
        self._key_type = key_type
        self.pages_read = 0
        self.pages_written = 0
        self.pages_allocated = 0
        # Merge is deferred in format v1, so no bucket is currently freed.
        self.pages_freed = 0

    def allocate_page(self) -> int:
        page_id = self._manager.allocate_page()
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("Allocate hash metadata page before bucket pages")
        self.pages_allocated += 1
        return page_id

    def write_bucket(self, bucket: HashBucket) -> None:
        if not isinstance(bucket, HashBucket):
            raise InvalidTypeError("bucket must be a HashBucket")
        if bucket.key_type is not self._key_type:
            raise ValidationError("Hash bucket key type differs from its index")
        self._manager.write_page(
            _frame(bucket.page_id, HashBucketCodec.serialize(bucket))
        )
        self.pages_written += 1

    def read_bucket(self, page_id: int) -> HashBucket:
        if type(page_id) is not int:
            raise InvalidTypeError("bucket page_id must be a built-in int")
        if page_id == _HEADER_PAGE_ID:
            raise ValidationError("Hash bucket cannot use metadata page 0")
        physical_page = self._manager.read_page(page_id)
        # Keep typed counters aligned with PageManager on malformed page reads.
        self.pages_read += 1
        bucket = HashBucketCodec.deserialize(
            self._key_type,
            _payload(physical_page, "hash bucket"),
        )
        if bucket.page_id != page_id:
            raise ValidationError("Stored hash bucket page_id differs from its location")
        return bucket

    def reset_counters(self) -> None:
        """Reset only the counters owned by this typed I/O adapter."""

        self.pages_read = self.pages_written = self.pages_allocated = 0
        self.pages_freed = 0
