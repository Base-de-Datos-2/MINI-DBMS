"""Persistent ordered file organization without a hidden index."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
from dataclasses import replace
from time import perf_counter

from engine.catalog import DataType, Schema
from engine.errors import (
    DuplicateError,
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)

from .base import Storage
from .binary import MAX_RECORD_SIZE, PAGE_SIZE, SLOT_SIZE
from .metrics import ReorganizationMetrics
from .organization import OrganizationFile, OrganizationMetadata, OrganizationType
from .page import Page
from .record import Record, RecordValue
from .record_codec import RecordCodec
from .rid import RID
from .sequential_ordering import SequentialOrdering


class PagedSequentialFile(OrganizationFile, Storage):
    """Keep active records physically ordered by one configured schema column.

    Insertion rebuilds one target page. If it splits, subsequent physical pages
    are shifted right through PageManager. It does not build a B+ Tree, hash
    index, overflow area, or full-file reorganization.
    """

    DEFAULT_REORGANIZATION_THRESHOLD = 0.30

    def __init__(self, manager, metadata: OrganizationMetadata) -> None:
        super().__init__(manager, metadata)
        self._record_codec = RecordCodec
        self._ordering = SequentialOrdering(metadata.schema, metadata.key_column)

    @classmethod
    def create(
        cls,
        path: object,
        schema: Schema,
        key_column: str,
        *,
        allow_duplicate_keys: bool = True,
        reorganization_threshold: float = DEFAULT_REORGANIZATION_THRESHOLD,
    ) -> "PagedSequentialFile":
        if not isinstance(schema, Schema):
            raise InvalidTypeError("schema must be a Schema")
        metadata = OrganizationMetadata(
            organization_type=OrganizationType.PAGED_SEQUENTIAL,
            schema=schema,
            key_column=key_column,
            allow_duplicate_keys=allow_duplicate_keys,
            reorganization_threshold=reorganization_threshold,
        )
        # Constructing the contract here rejects unsupported/invalid key data
        # before the exclusive create operation touches the filesystem.
        SequentialOrdering(schema, key_column)
        manager, metadata = cls._create_file(path, metadata)
        return cls(manager, metadata)

    @classmethod
    def open(
        cls,
        path: object,
        schema: Schema | None = None,
        key_column: str | None = None,
    ) -> "PagedSequentialFile":
        if key_column is not None and type(key_column) is not str:
            raise InvalidTypeError("key_column must be a string or None")
        manager, metadata = cls._open_file(
            path,
            OrganizationType.PAGED_SEQUENTIAL,
            schema,
        )
        sequential = cls(manager, metadata)
        try:
            if key_column is not None and metadata.key_column != key_column:
                raise SchemaError(
                    f"Provided key column {key_column!r} does not match "
                    f"persisted key {metadata.key_column!r}"
                )
            sequential._visit_and_validate_data_pages(lambda page: None)
            return sequential
        except BaseException:
            try:
                sequential.close()
            except BaseException:
                pass
            raise

    @property
    def key_column(self) -> str:
        self._require_open()
        return self._ordering.key_column

    @property
    def key_type(self) -> DataType:
        self._require_open()
        return self._ordering.data_type

    @property
    def allow_duplicate_keys(self) -> bool:
        self._require_open()
        return self._metadata.allow_duplicate_keys

    @property
    def reorganization_threshold(self) -> float:
        self._require_open()
        return self._metadata.reorganization_threshold

    def _validate_record(self, record: object) -> tuple[Record, RecordValue, bytes]:
        self._require_open()
        if not isinstance(record, Record):
            raise InvalidTypeError("PagedSequentialFile requires a Record")
        key = self._ordering.extract(record)
        payload = self._record_codec.serialize(record)
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError(
                f"Record payload exceeds page capacity of {MAX_RECORD_SIZE} bytes"
            )
        return record, key, payload

    def _validate_rid(self, rid: object) -> RID:
        if not isinstance(rid, RID):
            raise InvalidTypeError("PagedSequentialFile requires a RID")
        if rid.page_id not in self._metadata.data_page_ids:
            raise InvalidReferenceError(
                f"RID page_id {rid.page_id} is not a sequential data page"
            )
        return rid

    def read(self, rid: RID) -> Record:
        self._require_open()
        checked = self._validate_rid(rid)
        page = self._manager.read_page(checked.page_id)
        return self._record_codec.deserialize(
            self._metadata.schema,
            page.read(checked.slot_id),
        )

    def _page_entries(
        self,
        page: Page,
    ) -> list[tuple[RecordValue, bytes]]:
        entries: list[tuple[RecordValue, bytes]] = []
        previous = None
        has_previous = False
        for slot_id, slot in enumerate(page.slots):
            if not slot.is_active:
                continue
            payload = page.read(slot_id)
            record = self._record_codec.deserialize(self._metadata.schema, payload)
            key = self._ordering.extract(record)
            if has_previous and self._ordering.compare(previous, key) > 0:
                raise ValidationError(
                    f"Sequential page {page.page_id} is not ordered"
                )
            entries.append((key, payload))
            previous = key
            has_previous = True
        return entries

    @staticmethod
    def _page_waste(page: Page) -> tuple[int, int]:
        """Return ``(payload_hole_bytes, free_slot_count)`` for one page."""

        if not isinstance(page, Page):
            raise InvalidTypeError("page must be a Page")
        active_payload_bytes = sum(
            slot.length for slot in page.slots if slot.is_active
        )
        payload_hole_bytes = (
            PAGE_SIZE - page.header.free_space_end - active_payload_bytes
        )
        free_slot_count = page.slot_count - page.active_record_count
        if payload_hole_bytes < 0 or free_slot_count < 0:
            raise ValidationError("Sequential page has invalid wasted-space geometry")
        return payload_hole_bytes, free_slot_count

    def _find_insertion_target(
        self,
        key: RecordValue,
    ) -> tuple[Page, list[tuple[RecordValue, bytes]], bool]:
        target_page = None
        target_entries: list[tuple[RecordValue, bytes]] = []
        duplicate_found = False
        previous = None
        has_previous = False

        for page_id in self._metadata.data_page_ids:
            page = self._manager.read_page(page_id)
            entries = self._page_entries(page)
            for existing_key, _ in entries:
                if has_previous and self._ordering.compare(previous, existing_key) > 0:
                    raise ValidationError("Sequential data pages are not ordered")
                comparison = self._ordering.compare(existing_key, key)
                if comparison == 0:
                    duplicate_found = True
                    if not self._metadata.allow_duplicate_keys:
                        raise DuplicateError(f"Duplicate sequential key: {key!r}")
                if comparison > 0:
                    return page, entries, duplicate_found
                previous = existing_key
                has_previous = True
            target_page, target_entries = page, entries

        if target_page is None:
            raise ValidationError("Sequential metadata references no insertion page")
        return target_page, target_entries, duplicate_found

    @staticmethod
    def _partition_items(
        items: list[tuple[RecordValue | None, bytes, bool, bool]],
    ) -> list[list[tuple[RecordValue | None, bytes, bool, bool]]]:
        """Partition active rows and retained tombstones into valid pages."""

        chunks: list[list[tuple[RecordValue | None, bytes, bool, bool]]] = []
        current: list[tuple[RecordValue | None, bytes, bool, bool]] = []
        probe = Page(OrganizationMetadata.FIRST_DATA_PAGE_ID)
        for item in items:
            try:
                probe.insert(item[1])
            except ValidationError:
                if not current:
                    raise
                chunks.append(current)
                current = [item]
                probe = Page(OrganizationMetadata.FIRST_DATA_PAGE_ID)
                probe.insert(item[1])
            else:
                current.append(item)
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _retained_tombstone_items(
        payload_hole_bytes: int,
        free_slot_count: int,
    ) -> list[tuple[None, bytes, bool, bool]]:
        """Encode aggregate page waste without reclaiming it during insertion.

        A FREE slot no longer stores the deleted payload length. The page's
        geometry does retain the aggregate hole size, so one tombstone carries
        those bytes and the remaining entries retain the exact FREE-slot count.
        """

        if free_slot_count == 0:
            if payload_hole_bytes:
                raise ValidationError(
                    "Sequential payload holes require a retained FREE slot"
                )
            return []
        return [
            (None, bytes(payload_hole_bytes), False, True),
            *((None, b"", False, True) for _ in range(free_slot_count - 1)),
        ]

    def _shift_suffix_right(self, target_page_id: int, positions: int) -> None:
        if positions == 0:
            return
        old_last_page_id = (
            self._metadata.first_data_page_id + self._metadata.data_page_count - 1
        )
        for _ in range(positions):
            self._manager.allocate_page()
        for old_page_id in range(old_last_page_id, target_page_id, -1):
            page = self._manager.read_page(old_page_id)
            self._manager.write_page(
                page.clone_with_page_id(old_page_id + positions)
            )

    def insert(self, record: Record) -> RID:
        _, key, payload = self._validate_record(record)

        if self._metadata.data_page_count == 0:
            page_id = self._manager.allocate_page()
            if page_id != self._metadata.first_data_page_id:
                raise ValidationError("First sequential data page must have id 1")
            page = Page(page_id)
            slot_id = page.insert(payload)
            updated_metadata = replace(
                self._metadata,
                active_record_count=1,
                data_page_count=1,
            )
            updated_metadata.serialize()
            self._manager.write_page(page)
            self._store_metadata(updated_metadata)
            return RID(page_id, slot_id)

        target_page, entries, _ = self._find_insertion_target(key)
        payload_hole_bytes, free_slot_count = self._page_waste(target_page)
        position = self._ordering.insertion_position(
            [existing_key for existing_key, _ in entries],
            key,
        )
        items = [
            (existing_key, existing_payload, False, False)
            for existing_key, existing_payload in entries
        ]
        items.insert(position, (key, payload, True, False))
        items.extend(
            self._retained_tombstone_items(payload_hole_bytes, free_slot_count)
        )
        chunks = self._partition_items(items)
        additional_pages = len(chunks) - 1

        updated_metadata = replace(
            self._metadata,
            active_record_count=self._metadata.active_record_count + 1,
            data_page_count=self._metadata.data_page_count + additional_pages,
        )
        updated_metadata.serialize()
        self._shift_suffix_right(target_page.page_id, additional_pages)

        inserted_rid = None
        for page_offset, chunk in enumerate(chunks):
            page_id = target_page.page_id + page_offset
            rebuilt = Page(page_id)
            tombstone_slots: list[int] = []
            for _, item_payload, is_inserted, is_tombstone in chunk:
                slot_id = rebuilt.insert(item_payload)
                if is_inserted:
                    inserted_rid = RID(page_id, slot_id)
                if is_tombstone:
                    tombstone_slots.append(slot_id)
            for slot_id in tombstone_slots:
                rebuilt.delete(slot_id)
            self._manager.write_page(rebuilt)
        self._store_metadata(updated_metadata)
        if inserted_rid is None:
            raise ValidationError("Inserted record was lost during page redistribution")
        return inserted_rid

    def scan(self) -> Generator[tuple[RID, Record], None, None]:
        self._require_open()

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_open()
            previous = None
            has_previous = False
            for page_id in self._metadata.data_page_ids:
                self._require_open()
                page = self._manager.read_page(page_id)
                for slot_id, slot in enumerate(page.slots):
                    if not slot.is_active:
                        continue
                    self._require_open()
                    payload = page.read(slot_id)
                    record = self._record_codec.deserialize(
                        self._metadata.schema,
                        payload,
                    )
                    key = self._ordering.extract(record)
                    if has_previous and self._ordering.compare(previous, key) > 0:
                        raise ValidationError("Sequential data pages are not ordered")
                    yield RID(page_id, slot_id), record
                    previous = key
                    has_previous = True

        return iterator()

    def search(
        self,
        key: RecordValue,
    ) -> Generator[tuple[RID, Record], None, None]:
        self._require_open()
        checked_key = self._ordering.validate_key(key)

        def iterator() -> Generator[tuple[RID, Record], None, None]:
            self._require_open()
            with closing(self.scan()) as rows:
                for rid, record in rows:
                    comparison = self._ordering.compare(
                        self._ordering.extract(record),
                        checked_key,
                    )
                    if comparison == 0:
                        yield rid, record
                    elif comparison > 0:
                        return

        return iterator()

    def delete(self, rid: RID) -> None:
        self._require_open()
        checked = self._validate_rid(rid)
        page = self._manager.read_page(checked.page_id)
        page.delete(checked.slot_id)
        updated_metadata = replace(
            self._metadata,
            active_record_count=self._metadata.active_record_count - 1,
            deleted_record_count=self._metadata.deleted_record_count + 1,
        )
        updated_metadata.serialize()
        self._manager.write_page(page)
        self._store_metadata(updated_metadata)

    def wasted_space_ratio(self) -> float:
        self._require_open()
        if self._metadata.data_page_count == 0:
            return 0.0

        wasted_bytes = 0
        for page_id in self._metadata.data_page_ids:
            page = self._manager.read_page(page_id)
            payload_holes, free_slots = self._page_waste(page)
            wasted_bytes += payload_holes + free_slots * SLOT_SIZE
        denominator = self._metadata.data_page_count * PAGE_SIZE
        if not 0 <= wasted_bytes <= denominator:
            raise ValidationError("Sequential wasted-space ratio is invalid")
        return wasted_bytes / denominator

    def should_reorganize(self) -> bool:
        self._require_open()
        return self.wasted_space_ratio() > self._metadata.reorganization_threshold

    def _write_compact_replacement(
        self,
        path: object,
    ) -> tuple[OrganizationMetadata, tuple[int, int, int]]:
        """Build and flush a compact candidate while the source stays open."""

        placeholder = replace(
            self._metadata,
            active_record_count=0,
            deleted_record_count=0,
            data_page_count=0,
        )
        manager, placeholder = self._create_file(path, placeholder)
        replacement = type(self)(manager, placeholder)
        try:
            current_page: Page | None = None
            active_record_count = 0
            data_page_count = 0
            with closing(self.scan()) as rows:
                for _, record in rows:
                    payload = self._record_codec.serialize(record)
                    if current_page is None:
                        page_id = manager.allocate_page()
                        current_page = Page(page_id)
                        data_page_count += 1
                    if len(payload) + SLOT_SIZE > current_page.free_space():
                        manager.write_page(current_page)
                        page_id = manager.allocate_page()
                        current_page = Page(page_id)
                        data_page_count += 1
                    current_page.insert(payload)
                    active_record_count += 1

            if current_page is not None:
                manager.write_page(current_page)
            if active_record_count != self._metadata.active_record_count:
                raise ValidationError(
                    "Sequential active-record count changed during reorganization"
                )
            compact_metadata = replace(
                placeholder,
                active_record_count=active_record_count,
                data_page_count=data_page_count,
            )
            replacement._store_metadata(compact_metadata)
            replacement.flush()
            replacement_io = (
                replacement.pages_read,
                replacement.pages_written,
                replacement.pages_allocated,
            )
            return compact_metadata, replacement_io
        finally:
            replacement.close()

    def reorganize(self) -> ReorganizationMetrics:
        self._require_open()
        started_at = perf_counter()
        file_size_before = self.file_size
        source_io_before = (
            self.pages_read,
            self.pages_written,
            self.pages_allocated,
        )
        schema = self._metadata.schema
        key_column = self._ordering.key_column
        temporary_path = self._manager.temporary_replacement_path()
        committed = False
        try:
            compact_metadata, replacement_io = self._write_compact_replacement(
                temporary_path
            )

            # Validate the complete candidate, including ordered Record decoding,
            # before releasing or replacing the source handle.
            with type(self).open(temporary_path, schema, key_column) as candidate:
                if candidate.deleted_record_count != 0:
                    raise ValidationError("Compact sequential file has tombstones")
                if sum(1 for _ in candidate.scan()) != self.record_count:
                    raise ValidationError(
                        "Compact sequential file lost active records"
                    )
                if candidate.wasted_space_ratio() != 0.0:
                    raise ValidationError("Compact sequential file retains waste")
                validation_io = (
                    candidate.pages_read,
                    candidate.pages_written,
                    candidate.pages_allocated,
                )

            source_io_after = (
                self.pages_read,
                self.pages_written,
                self.pages_allocated,
            )
            source_io = tuple(
                after - before
                for before, after in zip(source_io_before, source_io_after)
            )
            if any(value < 0 for value in source_io):
                raise ValidationError(
                    "Source I/O counters changed incompatibly during reorganization"
                )

            self._manager.commit_replacement(temporary_path)
            committed = True
            self._metadata = compact_metadata
            self._ordering = SequentialOrdering(schema, key_column)
            total_io = tuple(
                sum(values)
                for values in zip(source_io, replacement_io, validation_io)
            )
            return ReorganizationMetrics(
                elapsed_seconds=perf_counter() - started_at,
                pages_read=total_io[0],
                pages_written=total_io[1],
                pages_allocated=total_io[2],
                file_size_before=file_size_before,
                file_size_after=self.file_size,
            )
        finally:
            if not committed:
                self._manager.discard_replacement(temporary_path)
