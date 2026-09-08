"""Validated persistent metadata for one Extendible Hash index file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_SIZE, UINT32_MAX, require_bytes

from .hash_binary import (
    HASH_ALGORITHM,
    HASH_ALGORITHM_VERSION,
    HASH_BIT_SELECTION,
    HASH_DEFAULT_MAX_GLOBAL_DEPTH,
    HASH_FILE_MAGIC,
    HASH_FORMAT_VERSION,
    HASH_INITIAL_GLOBAL_DEPTH,
    HASH_PAGE_FORMAT_VERSION,
    HASH_UINT64_MAX,
    HASH_WIDTH,
)


def _validate_name(value: object, label: str) -> str:
    if type(value) is not str:
        raise InvalidTypeError(f"{label} must be a string")
    if not value.strip():
        raise ValidationError(f"{label} must not be empty or whitespace-only")
    return value


def _validate_uint(value: object, label: str, maximum: int) -> int:
    if type(value) is not int:
        raise InvalidTypeError(f"{label} must be a built-in int")
    if not 0 <= value <= maximum:
        raise ValidationError(f"{label} must be between 0 and {maximum}")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class HashFileHeader:
    """Canonical page-zero descriptor; no reopen default remains implicit."""

    MAGIC: ClassVar[str] = HASH_FILE_MAGIC
    VERSION: ClassVar[int] = HASH_FORMAT_VERSION

    index_name: str
    table_name: str
    key_column: str
    key_type: DataType
    allow_duplicate_keys: bool = True
    build_complete: bool = True
    hash_algorithm: str = HASH_ALGORITHM
    hash_algorithm_version: int = HASH_ALGORITHM_VERSION
    hash_width: int = HASH_WIDTH
    bit_selection: str = HASH_BIT_SELECTION
    directory_format_version: int = HASH_PAGE_FORMAT_VERSION
    bucket_format_version: int = HASH_PAGE_FORMAT_VERSION
    initial_global_depth: int = HASH_INITIAL_GLOBAL_DEPTH
    global_depth: int = HASH_INITIAL_GLOBAL_DEPTH
    maximum_global_depth: int = HASH_DEFAULT_MAX_GLOBAL_DEPTH
    directory_first_page_id: int = 1
    directory_page_count: int = 1
    directory_entry_count: int = 2
    bucket_count: int = 2
    association_count: int = 0
    index_page_count: int = 3
    magic: str = HASH_FILE_MAGIC
    version: int = HASH_FORMAT_VERSION
    page_size: int = PAGE_SIZE

    def __post_init__(self) -> None:
        _validate_name(self.index_name, "Index name")
        _validate_name(self.table_name, "Table name")
        _validate_name(self.key_column, "Key column")
        if not isinstance(self.key_type, DataType):
            raise InvalidTypeError("key_type must be a DataType")
        if type(self.allow_duplicate_keys) is not bool:
            raise InvalidTypeError("allow_duplicate_keys must be a bool")
        if type(self.build_complete) is not bool:
            raise InvalidTypeError("build_complete must be a bool")

        # Format identity is persisted so a future version never silently opens
        # bytes with different hashing or bit-selection semantics.
        if type(self.magic) is not str:
            raise InvalidTypeError("Hash file magic must be a string")
        if self.magic != self.MAGIC:
            raise ValidationError("Invalid Extendible Hash index signature")
        _validate_uint(self.version, "version", UINT32_MAX)
        if self.version != self.VERSION:
            raise ValidationError(
                f"Unsupported Extendible Hash index version: {self.version}"
            )
        _validate_uint(self.page_size, "page_size", UINT32_MAX)
        if self.page_size != PAGE_SIZE:
            raise ValidationError(
                f"Unsupported hash page size: {self.page_size}; expected {PAGE_SIZE}"
            )
        if type(self.hash_algorithm) is not str:
            raise InvalidTypeError("hash_algorithm must be a string")
        if self.hash_algorithm != HASH_ALGORITHM:
            raise ValidationError("Unsupported persisted hash algorithm")
        _validate_uint(
            self.hash_algorithm_version,
            "hash_algorithm_version",
            UINT32_MAX,
        )
        if self.hash_algorithm_version != HASH_ALGORITHM_VERSION:
            raise ValidationError("Unsupported persisted hash algorithm version")
        _validate_uint(self.hash_width, "hash_width", UINT32_MAX)
        if self.hash_width != HASH_WIDTH:
            raise ValidationError("Unsupported persisted hash width")
        if type(self.bit_selection) is not str:
            raise InvalidTypeError("bit_selection must be a string")
        if self.bit_selection != HASH_BIT_SELECTION:
            raise ValidationError("Unsupported persisted hash bit convention")
        _validate_uint(
            self.directory_format_version,
            "directory_format_version",
            UINT32_MAX,
        )
        if self.directory_format_version != HASH_PAGE_FORMAT_VERSION:
            raise ValidationError("Unsupported hash directory format version")
        _validate_uint(
            self.bucket_format_version,
            "bucket_format_version",
            UINT32_MAX,
        )
        if self.bucket_format_version != HASH_PAGE_FORMAT_VERSION:
            raise ValidationError("Unsupported hash bucket format version")

        # Format v1 deliberately caps directory growth at 2^20 entries even
        # though the hash itself contains 64 useful bits.
        _validate_uint(
            self.initial_global_depth,
            "initial_global_depth",
            HASH_DEFAULT_MAX_GLOBAL_DEPTH,
        )
        _validate_uint(
            self.global_depth,
            "global_depth",
            HASH_DEFAULT_MAX_GLOBAL_DEPTH,
        )
        _validate_uint(
            self.maximum_global_depth,
            "maximum_global_depth",
            HASH_DEFAULT_MAX_GLOBAL_DEPTH,
        )
        if not (
            self.initial_global_depth
            <= self.global_depth
            <= self.maximum_global_depth
        ):
            raise ValidationError(
                "Hash depths must satisfy initial <= global <= maximum"
            )
        expected_entries = 1 << self.global_depth
        _validate_uint(
            self.directory_entry_count,
            "directory_entry_count",
            UINT32_MAX,
        )
        if self.directory_entry_count != expected_entries:
            raise ValidationError("Hash directory size must equal 2^global_depth")

        _validate_uint(
            self.directory_first_page_id,
            "directory_first_page_id",
            UINT32_MAX - 1,
        )
        _validate_uint(self.directory_page_count, "directory_page_count", UINT32_MAX)
        _validate_uint(self.bucket_count, "bucket_count", UINT32_MAX)
        _validate_uint(self.association_count, "association_count", HASH_UINT64_MAX)
        _validate_uint(self.index_page_count, "index_page_count", UINT32_MAX - 1)
        if self.directory_first_page_id == 0:
            raise ValidationError("Hash directory cannot use reserved metadata page 0")
        if self.directory_page_count == 0 or self.bucket_count == 0:
            raise ValidationError("Hash index requires directory and bucket pages")
        if self.index_page_count < self.directory_page_count + self.bucket_count:
            raise ValidationError("Hash index page count is too small for its topology")
        if self.directory_first_page_id > self.index_page_count:
            raise ValidationError("Hash directory page is outside the index page range")

    def _document(self) -> dict[str, object]:
        # Sorted canonical JSON follows the existing B+ metadata convention.
        return {
            "allow_duplicate_keys": self.allow_duplicate_keys,
            "association_count": self.association_count,
            "bit_selection": self.bit_selection,
            "bucket_format_version": self.bucket_format_version,
            "bucket_count": self.bucket_count,
            "build_complete": self.build_complete,
            "directory_entry_count": self.directory_entry_count,
            "directory_first_page_id": self.directory_first_page_id,
            "directory_format_version": self.directory_format_version,
            "directory_page_count": self.directory_page_count,
            "global_depth": self.global_depth,
            "hash_algorithm": self.hash_algorithm,
            "hash_algorithm_version": self.hash_algorithm_version,
            "hash_width": self.hash_width,
            "index_name": self.index_name,
            "index_page_count": self.index_page_count,
            "initial_global_depth": self.initial_global_depth,
            "key_column": self.key_column,
            "key_type": self.key_type.value,
            "magic": self.magic,
            "maximum_global_depth": self.maximum_global_depth,
            "page_size": self.page_size,
            "table_name": self.table_name,
            "version": self.version,
        }

    def serialize(self) -> bytes:
        try:
            payload = json.dumps(
                self._document(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValidationError("Hash metadata names must be strict UTF-8") from exc
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError("Hash file header does not fit in page 0")
        return payload

    @classmethod
    def deserialize(cls, payload: bytes) -> "HashFileHeader":
        require_bytes(payload)

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ValidationError(f"Duplicate hash metadata field: {key!r}")
                result[key] = value
            return result

        def reject_non_finite(value: str) -> None:
            raise ValidationError(f"Invalid hash JSON constant: {value}")

        try:
            document = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicates,
                parse_constant=reject_non_finite,
            )
        except ValidationError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Malformed hash file header") from exc
        if type(document) is not dict:
            raise ValidationError("Hash file header must be a JSON object")
        expected = set(cls(
            index_name="x", table_name="t", key_column="k", key_type=DataType.INTEGER
        )._document())
        if set(document) != expected:
            missing = sorted(expected - set(document))
            extra = sorted(set(document) - expected)
            raise ValidationError(
                f"Invalid hash file-header fields; missing={missing}, extra={extra}"
            )
        if type(document["key_type"]) is not str:
            raise InvalidTypeError("Persisted hash key_type must be a string")
        try:
            document["key_type"] = DataType(document["key_type"])
        except ValueError as exc:
            raise ValidationError("Unknown persisted hash key type") from exc
        return cls(**document)
