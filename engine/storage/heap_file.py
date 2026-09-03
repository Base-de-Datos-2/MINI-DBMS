"""Persistent Heap file and its rebuildable in-memory free-space directory."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from dataclasses import replace

from engine.catalog import Schema
from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)

from .base import Storage
from .binary import MAX_RECORD_SIZE, PAGE_SIZE, SLOT_SIZE
from .organization import OrganizationFile, OrganizationMetadata, OrganizationType
from .page import Page
from .record import Record
from .record_codec import RecordCodec
from .rid import RID


class HeapFreeSpaceTracker:
    """In-memory directory of the insertable payload capacity of Heap pages.

    The tracker never performs I/O. It narrows the pages considered by an
    insertion, but the selected :class:`Page` remains the final authority and
    must be read and asked to perform the insertion. A caller must update the
    entry after every mutation, including after finding stale information.
    """

    def __init__(self) -> None:
        self._capacities: dict[int, int] = {}

    @staticmethod
    def insertable_payload_bytes(page: Page) -> int:
        """Return the largest payload insertable after local compaction."""

        if not isinstance(page, Page):
            raise InvalidTypeError("page must be a Page")
        active_payload_bytes = sum(
            slot.length for slot in page.slots if slot.is_active
        )
        reusable_slot_cost = (
            0 if page.slot_count > page.active_record_count else SLOT_SIZE
        )
        return (
            PAGE_SIZE
            - page.header.free_space_start
            - active_payload_bytes
            - reusable_slot_cost
        )

    @staticmethod
    def _validate_page_id(page_id: object) -> int:
        if type(page_id) is not int:
            raise InvalidTypeError("page_id must be an int")
        if page_id < OrganizationMetadata.FIRST_DATA_PAGE_ID:
            raise ValidationError("Heap data page IDs must be at least 1")
        return page_id

    @staticmethod
    def _validate_payload_size(payload_size: object) -> int:
        if type(payload_size) is not int:
            raise InvalidTypeError("payload_size must be an int")
        if not 0 <= payload_size <= MAX_RECORD_SIZE:
            raise ValidationError(
                f"payload_size must be between 0 and {MAX_RECORD_SIZE}"
            )
        return payload_size

    def register(self, page: Page) -> None:
        """Register a new page or replace an existing page observation."""

        if not isinstance(page, Page):
            raise InvalidTypeError("page must be a Page")
        self._validate_page_id(page.page_id)
        self._capacities[page.page_id] = self.insertable_payload_bytes(page)

    update = register

    def remove(self, page_id: object) -> None:
        """Remove a tracked page; an unknown valid page is a no-op."""

        validated_id = self._validate_page_id(page_id)
        self._capacities.pop(validated_id, None)

    def find_candidate(self, payload_size: object) -> int | None:
        """Return the lowest eligible page ID without touching the file."""

        required_bytes = self._validate_payload_size(payload_size)
        eligible_ids = (
            page_id
            for page_id, capacity in self._capacities.items()
            if capacity >= required_bytes
        )
        return min(eligible_ids, default=None)

    def rebuild(self, pages: Iterable[Page]) -> None:
        """Replace all entries from an externally supplied page traversal."""

        if not isinstance(pages, Iterable):
            raise InvalidTypeError("pages must be iterable")
        rebuilt: dict[int, int] = {}
        for page in pages:
            if not isinstance(page, Page):
                raise InvalidTypeError("pages must contain only Page instances")
            self._validate_page_id(page.page_id)
            if page.page_id in rebuilt:
                raise ValidationError(
                    f"Duplicate page in free-space rebuild: {page.page_id}"
                )
            rebuilt[page.page_id] = self.insertable_payload_bytes(page)
        self._capacities = rebuilt

    @property
    def snapshot(self) -> tuple[tuple[int, int], ...]:
        """Return a deterministic immutable view for diagnostics and tests."""

        return tuple(sorted(self._capacities.items()))

    def __len__(self) -> int:
        return len(self._capacities)


class HeapFile(OrganizationFile, Storage):
    """Persistent Heap organization over ``PageManager`` and ``RecordCodec``.

    New records use the lowest eligible data page and append a page only when
    none fits. Scans follow physical ``(page_id, slot_id)`` order, which is not
    guaranteed to remain chronological after deleted slots are reused.
    """

    def __init__(self, manager, metadata: OrganizationMetadata) -> None:
        super().__init__(manager, metadata)
        self._record_codec = RecordCodec
        self._free_space = HeapFreeSpaceTracker()

    @classmethod
    def create(cls, path: object, schema: Schema) -> "HeapFile":
        """Create a new exclusive empty Heap file."""

        if not isinstance(schema, Schema):
            raise InvalidTypeError("schema must be a Schema")
        metadata = OrganizationMetadata(
            organization_type=OrganizationType.HEAP,
            schema=schema,
        )
        manager, metadata = cls._create_file(path, metadata)
        return cls(manager, metadata)

    @classmethod
    def open(cls, path: object, schema: Schema | None = None) -> "HeapFile":
        """Open and validate a Heap file, optionally checking its schema."""

        manager, metadata = cls._open_file(
            path,
            OrganizationType.HEAP,
            schema,
        )
        heap = cls(manager, metadata)
        try:
            heap._rebuild_free_space()
            return heap
        except BaseException:
            try:
                heap.close()
            except BaseException:
                pass
            raise

    def _rebuild_free_space(self) -> None:
        rebuilt = HeapFreeSpaceTracker()
        self._visit_and_validate_data_pages(rebuilt.register)
        self._free_space = rebuilt

    @property
    def free_space_snapshot(self) -> tuple[tuple[int, int], ...]:
        self._require_open()
        return self._free_space.snapshot

    def _validate_record(self, record: object) -> Record:
        if not isinstance(record, Record):
            raise InvalidTypeError("HeapFile requires a Record")
        if record.schema != self._metadata.schema:
            raise SchemaError("Record schema differs from HeapFile schema")
        return record

    def _validate_rid(self, rid: object) -> RID:
        if not isinstance(rid, RID):
            raise InvalidTypeError("HeapFile requires a RID")
        if rid.page_id not in self._metadata.data_page_ids:
            raise InvalidReferenceError(
                f"RID page_id {rid.page_id} is not a Heap data page"
            )
        return rid

    def _read_rid_page(self, rid: object) -> tuple[RID, Page]:
        validated = self._validate_rid(rid)
        return validated, self._manager.read_page(validated.page_id)

    def insert(self, record: Record) -> RID:
        self._require_open()
        checked = self._validate_record(record)
        payload = self._record_codec.serialize(checked)
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError(
                f"Record payload exceeds page capacity of {MAX_RECORD_SIZE} bytes"
            )

        allocated_new_page = False
        while True:
            page_id = self._free_space.find_candidate(len(payload))
            if page_id is None:
                page_id = self._manager.allocate_page()
                expected_page_id = (
                    self._metadata.first_data_page_id
                    + self._metadata.data_page_count
                )
                if page_id != expected_page_id:
                    raise ValidationError(
                        "Allocated Heap page is not the next contiguous data page"
                    )
                page = Page(page_id)
                allocated_new_page = True
                break

            if page_id not in self._metadata.data_page_ids:
                # Defensive recovery from an invalid/stale in-memory entry.
                self._free_space.remove(page_id)
                continue

            page = self._manager.read_page(page_id)
            self._free_space.update(page)
            if (
                self._free_space.insertable_payload_bytes(page)
                < len(payload)
            ):
                # The observation was stale. The refreshed entry will not be
                # selected again unless it truly becomes eligible.
                continue
            break

        reuses_free_slot = page.slot_count > page.active_record_count
        directory_cost = 0 if reuses_free_slot else SLOT_SIZE
        if len(payload) + directory_cost > page.free_space():
            page.compact()
        slot_id = page.insert(payload)

        updated_metadata = replace(
            self._metadata,
            active_record_count=self._metadata.active_record_count + 1,
            deleted_record_count=(
                self._metadata.deleted_record_count - int(reuses_free_slot)
            ),
            data_page_count=(
                self._metadata.data_page_count + int(allocated_new_page)
            ),
        )
        updated_metadata.serialize()  # Validate its new persisted image first.
        self._manager.write_page(page)
        self._store_metadata(updated_metadata)
        self._free_space.update(page)
        return RID(page_id, slot_id)

    def read(self, rid: RID) -> Record:
        self._require_open()
        validated, page = self._read_rid_page(rid)
        payload = page.read(validated.slot_id)
        return self._record_codec.deserialize(self._metadata.schema, payload)

    def delete(self, rid: RID) -> None:
        self._require_open()
        validated, page = self._read_rid_page(rid)
        page.delete(validated.slot_id)
        updated_metadata = replace(
            self._metadata,
            active_record_count=self._metadata.active_record_count - 1,
            deleted_record_count=self._metadata.deleted_record_count + 1,
        )
        updated_metadata.serialize()  # Validate before changing persisted state.
        self._manager.write_page(page)
        self._store_metadata(updated_metadata)
        self._free_space.update(page)

    def scan(self) -> Generator[tuple[RID, Record], None, None]:
        self._require_open()

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_open()
            for page_id in self._metadata.data_page_ids:
                self._require_open()
                page = self._manager.read_page(page_id)
                for slot_id, slot in enumerate(page.slots):
                    if slot.is_active:
                        self._require_open()
                        payload = page.read(slot_id)
                        record = self._record_codec.deserialize(
                            self._metadata.schema,
                            payload,
                        )
                        yield RID(page_id, slot_id), record

        return iterator()
