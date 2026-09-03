"""Persisted metadata and common lifecycle for organized storage files.

An organized file reserves physical page 0 for this metadata. Data pages are
the contiguous physical pages starting at page 1. Keeping the organization
descriptor above :class:`PageManager` avoids changing the Stage 2 file header
and keeps all raw file access inside that manager.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, ClassVar

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, SchemaError, ValidationError

from .binary import MAX_RECORD_SIZE, MAX_SLOTS, UINT32_MAX, require_bytes
from .page import Page
from .page_manager import PageManager


class OrganizationType(str, Enum):
    """Physical organization identified by the metadata page."""

    HEAP = "heap"
    PAGED_SEQUENTIAL = "paged_sequential"


@dataclass(frozen=True, slots=True)
class OrganizationMetadata:
    """Validated, persisted description of one organized storage file."""

    MAGIC: ClassVar[str] = "MINIDB_ORGANIZATION"
    VERSION: ClassVar[int] = 1
    FIRST_DATA_PAGE_ID: ClassVar[int] = 1

    organization_type: OrganizationType
    schema: Schema
    active_record_count: int = 0
    deleted_record_count: int = 0
    first_data_page_id: int = FIRST_DATA_PAGE_ID
    data_page_count: int = 0
    key_column: str | None = None
    allow_duplicate_keys: bool | None = None
    reorganization_threshold: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.organization_type, OrganizationType):
            raise InvalidTypeError("organization_type must be an OrganizationType")
        if not isinstance(self.schema, Schema):
            raise InvalidTypeError("schema must be a Schema")

        self._validate_nonnegative_int("active_record_count", self.active_record_count)
        self._validate_nonnegative_int("deleted_record_count", self.deleted_record_count)
        self._validate_uint32("first_data_page_id", self.first_data_page_id)
        self._validate_uint32("data_page_count", self.data_page_count)

        if self.first_data_page_id != self.FIRST_DATA_PAGE_ID:
            raise ValidationError("first_data_page_id must be 1")
        if self.data_page_count > UINT32_MAX - self.FIRST_DATA_PAGE_ID:
            raise ValidationError("data_page_count exceeds the physical page-id range")
        if self.active_record_count + self.deleted_record_count > (
            self.data_page_count * MAX_SLOTS
        ):
            raise ValidationError("record counters exceed the possible slot count")

        if self.organization_type is OrganizationType.HEAP:
            self._validate_heap_fields()
        else:
            self._validate_sequential_fields()

    @staticmethod
    def _validate_nonnegative_int(name: str, value: object) -> None:
        if type(value) is not int:
            raise InvalidTypeError(f"{name} must be an int")
        if value < 0:
            raise ValidationError(f"{name} must be non-negative")

    @staticmethod
    def _validate_uint32(name: str, value: object) -> None:
        if type(value) is not int:
            raise InvalidTypeError(f"{name} must be an int")
        if not 0 <= value <= UINT32_MAX:
            raise ValidationError(f"{name} must be in the uint32 range")

    def _validate_heap_fields(self) -> None:
        sequential_fields = (
            self.key_column,
            self.allow_duplicate_keys,
            self.reorganization_threshold,
        )
        if any(value is not None for value in sequential_fields):
            raise ValidationError("Heap metadata cannot define sequential-file fields")

    def _validate_sequential_fields(self) -> None:
        if type(self.key_column) is not str or not self.key_column.strip():
            raise ValidationError("Paged sequential metadata requires a key column")
        try:
            self.schema.column(self.key_column)
        except (KeyError, InvalidTypeError) as exc:
            raise SchemaError(
                f"Sequential key column {self.key_column!r} is not in the schema"
            ) from exc

        if type(self.allow_duplicate_keys) is not bool:
            raise InvalidTypeError("allow_duplicate_keys must be a bool")
        if type(self.reorganization_threshold) is not float:
            raise InvalidTypeError("reorganization_threshold must be a float")
        if not math.isfinite(self.reorganization_threshold):
            raise ValidationError("reorganization_threshold must be finite")
        if not 0.0 < self.reorganization_threshold <= 1.0:
            raise ValidationError("reorganization_threshold must be in (0, 1]")

    @property
    def data_page_ids(self) -> range:
        """Return the persisted contiguous range of physical data page IDs."""

        return range(
            self.first_data_page_id,
            self.first_data_page_id + self.data_page_count,
        )

    def serialize(self) -> bytes:
        """Return the canonical UTF-8 JSON descriptor stored in page 0."""

        document = {
            "active_record_count": self.active_record_count,
            "allow_duplicate_keys": self.allow_duplicate_keys,
            "data_page_count": self.data_page_count,
            "deleted_record_count": self.deleted_record_count,
            "first_data_page_id": self.first_data_page_id,
            "key_column": self.key_column,
            "magic": self.MAGIC,
            "organization_type": self.organization_type.value,
            "reorganization_threshold": self.reorganization_threshold,
            "schema": [
                [column.name, column.data_type.value] for column in self.schema
            ],
            "version": self.VERSION,
        }
        payload = json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError("Organization metadata does not fit in one page slot")
        return payload

    @classmethod
    def deserialize(cls, data: object) -> "OrganizationMetadata":
        """Rebuild metadata, rejecting non-canonical shapes and invalid values."""

        require_bytes(data)
        payload = data

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValidationError(f"Duplicate metadata field: {key!r}")
                result[key] = value
            return result

        def reject_non_finite(constant: str) -> None:
            raise ValidationError(f"Invalid JSON numeric constant: {constant}")

        try:
            text = payload.decode("utf-8")
            document = json.loads(
                text,
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite,
            )
        except ValidationError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Malformed organization metadata") from exc

        if type(document) is not dict:
            raise ValidationError("Organization metadata must be a JSON object")

        expected_fields = {
            "active_record_count",
            "allow_duplicate_keys",
            "data_page_count",
            "deleted_record_count",
            "first_data_page_id",
            "key_column",
            "magic",
            "organization_type",
            "reorganization_threshold",
            "schema",
            "version",
        }
        actual_fields = set(document)
        if actual_fields != expected_fields:
            missing = sorted(expected_fields - actual_fields)
            extra = sorted(actual_fields - expected_fields)
            raise ValidationError(
                f"Invalid organization metadata fields; missing={missing}, extra={extra}"
            )
        if document["magic"] != cls.MAGIC:
            raise ValidationError("Invalid organization metadata signature")
        if type(document["version"]) is not int or document["version"] != cls.VERSION:
            raise ValidationError("Unsupported organization metadata version")
        if type(document["organization_type"]) is not str:
            raise InvalidTypeError("organization_type must be encoded as a string")
        try:
            organization_type = OrganizationType(document["organization_type"])
        except ValueError as exc:
            raise ValidationError("Unknown storage organization type") from exc

        schema = cls._decode_schema(document["schema"])
        return cls(
            organization_type=organization_type,
            schema=schema,
            active_record_count=document["active_record_count"],
            deleted_record_count=document["deleted_record_count"],
            first_data_page_id=document["first_data_page_id"],
            data_page_count=document["data_page_count"],
            key_column=document["key_column"],
            allow_duplicate_keys=document["allow_duplicate_keys"],
            reorganization_threshold=document["reorganization_threshold"],
        )

    @staticmethod
    def _decode_schema(value: object) -> Schema:
        if type(value) is not list:
            raise InvalidTypeError("schema must be encoded as a list")
        columns: list[Column] = []
        for descriptor in value:
            if type(descriptor) is not list or len(descriptor) != 2:
                raise ValidationError(
                    "Each persisted schema column must be a [name, type] pair"
                )
            name, type_name = descriptor
            if type(name) is not str or type(type_name) is not str:
                raise InvalidTypeError(
                    "Persisted schema names and data types must be strings"
                )
            try:
                data_type = DataType(type_name)
            except ValueError as exc:
                raise SchemaError(f"Unknown persisted data type: {type_name!r}") from exc
            columns.append(Column(name, data_type))
        return Schema(columns)


class OrganizationFile:
    """Internal common lifecycle shared by Stage 3 file organizations."""

    _METADATA_PAGE_ID = 0
    _METADATA_SLOT_ID = 0

    def __init__(self, manager: PageManager, metadata: OrganizationMetadata) -> None:
        if not isinstance(manager, PageManager):
            raise InvalidTypeError("manager must be a PageManager")
        if not isinstance(metadata, OrganizationMetadata):
            raise InvalidTypeError("metadata must be OrganizationMetadata")
        self._manager = manager
        self._metadata = metadata

    @classmethod
    def _create_file(
        cls,
        path: object,
        metadata: OrganizationMetadata,
    ) -> tuple[PageManager, OrganizationMetadata]:
        payload = metadata.serialize()
        manager = PageManager.create(path)
        try:
            page_id = manager.allocate_page()
            if page_id != cls._METADATA_PAGE_ID:
                raise ValidationError("The metadata page must be physical page 0")
            metadata_page = Page(page_id)
            slot_id = metadata_page.insert(payload)
            if slot_id != cls._METADATA_SLOT_ID:
                raise ValidationError("The organization descriptor must occupy slot 0")
            manager.write_page(metadata_page)
            return manager, metadata
        except BaseException:
            try:
                manager.close()
            except BaseException:
                pass
            raise

    @classmethod
    def _open_file(
        cls,
        path: object,
        expected_type: OrganizationType,
        expected_schema: Schema | None = None,
    ) -> tuple[PageManager, OrganizationMetadata]:
        if not isinstance(expected_type, OrganizationType):
            raise InvalidTypeError("expected_type must be an OrganizationType")
        if expected_schema is not None and not isinstance(expected_schema, Schema):
            raise InvalidTypeError("expected_schema must be a Schema or None")

        manager = PageManager.open(path)
        try:
            if manager.allocated_page_count < 1:
                raise ValidationError("Organized file has no metadata page")
            metadata_page = manager.read_page(cls._METADATA_PAGE_ID)
            if (
                metadata_page.slot_count != 1
                or metadata_page.active_record_count != 1
                or metadata_page.slot_count - metadata_page.active_record_count != 0
            ):
                raise ValidationError("Invalid organization metadata page layout")
            metadata = OrganizationMetadata.deserialize(
                metadata_page.read(cls._METADATA_SLOT_ID)
            )
            if metadata.organization_type is not expected_type:
                raise ValidationError(
                    f"Expected {expected_type.value!r} organization, found "
                    f"{metadata.organization_type.value!r}"
                )
            if expected_schema is not None and metadata.schema != expected_schema:
                raise SchemaError("Provided schema does not match persisted schema")
            if manager.allocated_page_count != metadata.data_page_count + 1:
                raise ValidationError(
                    "Persisted data-page count does not match the physical file"
                )
            return manager, metadata
        except BaseException:
            try:
                manager.close()
            except BaseException:
                pass
            raise

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("Storage file is closed")

    def _visit_and_validate_data_pages(self, visitor: Callable[[Page], None]) -> None:
        self._require_open()
        if not callable(visitor):
            raise InvalidTypeError("visitor must be callable")

        active_records = 0
        deleted_records = 0
        for page_id in self._metadata.data_page_ids:
            page = self._manager.read_page(page_id)
            visitor(page)
            active_records += page.active_record_count
            deleted_records += page.slot_count - page.active_record_count
        if active_records != self._metadata.active_record_count:
            raise ValidationError(
                "Persisted active-record count does not match the data pages"
            )
        if deleted_records != self._metadata.deleted_record_count:
            raise ValidationError(
                "Persisted deleted-record count does not match the data pages"
            )

    def _store_metadata(self, metadata: OrganizationMetadata) -> None:
        """Persist a validated replacement descriptor in the reserved page.

        Record operations use this after their page writes. There is no
        cross-page atomicity or crash recovery in Stage 3; a failed write closes
        the underlying PageManager according to its existing policy.
        """

        self._require_open()
        if not isinstance(metadata, OrganizationMetadata):
            raise InvalidTypeError("metadata must be OrganizationMetadata")
        if metadata.organization_type is not self._metadata.organization_type:
            raise ValidationError("Cannot change an open file's organization type")
        if metadata.schema != self._metadata.schema:
            raise SchemaError("Cannot change an open file's persisted schema")
        if self._manager.allocated_page_count != metadata.data_page_count + 1:
            raise ValidationError(
                "Replacement metadata does not match the physical page count"
            )

        replacement = Page(self._METADATA_PAGE_ID)
        slot_id = replacement.insert(metadata.serialize())
        if slot_id != self._METADATA_SLOT_ID:
            raise ValidationError("The organization descriptor must occupy slot 0")
        self._manager.write_page(replacement)
        self._metadata = metadata

    @property
    def schema(self) -> Schema:
        self._require_open()
        return self._metadata.schema

    @property
    def metadata(self) -> OrganizationMetadata:
        self._require_open()
        return self._metadata

    @property
    def record_count(self) -> int:
        self._require_open()
        return self._metadata.active_record_count

    @property
    def deleted_record_count(self) -> int:
        self._require_open()
        return self._metadata.deleted_record_count

    @property
    def data_page_count(self) -> int:
        self._require_open()
        return self._metadata.data_page_count

    @property
    def allocated_page_count(self) -> int:
        self._require_open()
        return self._manager.allocated_page_count

    @property
    def pages_read(self) -> int:
        self._require_open()
        return self._manager.pages_read

    @property
    def pages_written(self) -> int:
        self._require_open()
        return self._manager.pages_written

    @property
    def pages_allocated(self) -> int:
        self._require_open()
        return self._manager.pages_allocated

    def reset_counters(self) -> None:
        self._require_open()
        self._manager.reset_counters()

    @property
    def closed(self) -> bool:
        return self._manager.closed

    def flush(self) -> None:
        self._require_open()
        self._manager.flush()

    def close(self) -> None:
        self._manager.close()

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
