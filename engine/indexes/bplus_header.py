"""Validated, persistent metadata for one independent B+ index file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, ClassVar

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_SIZE, UINT32_MAX, require_bytes

from .bplus_binary import BPLUS_FILE_MAGIC, BPLUS_FORMAT_VERSION


_UINT64_MAX = (1 << 64) - 1


def _validate_name(name: object, label: str) -> str:
    if type(name) is not str:
        raise InvalidTypeError(f"{label} must be a string")
    if not name.strip():
        raise ValidationError(f"{label} must not be empty or whitespace-only")
    return name


def _validate_uint(name: str, value: object, maximum: int) -> int:
    if type(value) is not int:
        raise InvalidTypeError(f"{name} must be a built-in int")
    if not 0 <= value <= maximum:
        raise ValidationError(f"{name} must be between 0 and {maximum}")
    return value


def _validate_page_reference(
    name: str,
    value: object,
    node_page_count: int,
) -> int | None:
    if value is None:
        return None
    checked = _validate_uint(name, value, UINT32_MAX - 1)
    if checked == 0:
        raise ValidationError(f"{name} cannot reference reserved metadata page 0")
    if checked > node_page_count:
        raise ValidationError(f"{name} exceeds the allocated node-page range")
    return checked


@dataclass(frozen=True, slots=True, kw_only=True)
class BPlusFileHeader:
    """Canonical metadata stored in page 0, slot 0 of a B+ file.

    ``node_page_count`` is the allocation high-water mark, including pages on
    the persistent free-node list. Empty trees use a null root and may
    therefore still own reusable node pages after all entries are deleted.
    """

    MAGIC: ClassVar[str] = BPLUS_FILE_MAGIC
    VERSION: ClassVar[int] = BPLUS_FORMAT_VERSION

    index_name: str
    table_name: str
    key_column: str
    key_type: DataType
    clustered: bool = False
    allow_duplicate_keys: bool = True
    build_complete: bool = True
    root_page_id: int | None = None
    first_leaf_page_id: int | None = None
    height: int = 0
    entry_count: int = 0
    node_page_count: int = 0
    free_node_head_page_id: int | None = None
    magic: str = BPLUS_FILE_MAGIC
    version: int = BPLUS_FORMAT_VERSION
    page_size: int = PAGE_SIZE

    def __post_init__(self) -> None:
        _validate_name(self.index_name, "Index name")
        _validate_name(self.table_name, "Table name")
        _validate_name(self.key_column, "Key column")
        if not isinstance(self.key_type, DataType):
            raise InvalidTypeError("key_type must be a DataType")
        if type(self.clustered) is not bool:
            raise InvalidTypeError("clustered must be a bool")
        if type(self.allow_duplicate_keys) is not bool:
            raise InvalidTypeError("allow_duplicate_keys must be a bool")
        if type(self.build_complete) is not bool:
            raise InvalidTypeError("build_complete must be a bool")
        if type(self.magic) is not str:
            raise InvalidTypeError("B+ file magic must be a string")
        if self.magic != self.MAGIC:
            raise ValidationError("Invalid B+ index signature")

        _validate_uint("version", self.version, UINT32_MAX)
        if self.version != self.VERSION:
            raise ValidationError(f"Unsupported B+ index version: {self.version}")
        _validate_uint("page_size", self.page_size, UINT32_MAX)
        if self.page_size != PAGE_SIZE:
            raise ValidationError(
                f"Unsupported B+ page size: {self.page_size}; expected {PAGE_SIZE}"
            )
        _validate_uint("height", self.height, UINT32_MAX)
        _validate_uint("entry_count", self.entry_count, _UINT64_MAX)
        _validate_uint("node_page_count", self.node_page_count, UINT32_MAX - 1)

        root = _validate_page_reference(
            "root_page_id", self.root_page_id, self.node_page_count
        )
        first_leaf = _validate_page_reference(
            "first_leaf_page_id", self.first_leaf_page_id, self.node_page_count
        )
        free_head = _validate_page_reference(
            "free_node_head_page_id",
            self.free_node_head_page_id,
            self.node_page_count,
        )

        if self.entry_count == 0:
            if root is not None or first_leaf is not None or self.height != 0:
                raise ValidationError(
                    "An empty B+ tree requires null root/first leaf and height 0"
                )
        else:
            if root is None or first_leaf is None or self.height == 0:
                raise ValidationError(
                    "A non-empty B+ tree requires a root, first leaf, and positive height"
                )
            if self.node_page_count == 0:
                raise ValidationError("A non-empty B+ tree requires node pages")
            if self.height > self.node_page_count:
                raise ValidationError("B+ height cannot exceed its node-page count")
            if self.height == 1 and root != first_leaf:
                raise ValidationError(
                    "A height-one B+ tree root must also be its first leaf"
                )
            if self.height > 1 and root == first_leaf:
                raise ValidationError(
                    "A multi-level B+ root cannot also be its first leaf"
                )

        if free_head is not None and free_head in {root, first_leaf}:
            raise ValidationError("A live root/first leaf cannot head the free-node list")

    def _document(self) -> dict[str, object]:
        return {
            "allow_duplicate_keys": self.allow_duplicate_keys,
            "build_complete": self.build_complete,
            "clustered": self.clustered,
            "entry_count": self.entry_count,
            "first_leaf_page_id": self.first_leaf_page_id,
            "free_node_head_page_id": self.free_node_head_page_id,
            "height": self.height,
            "index_name": self.index_name,
            "key_column": self.key_column,
            "key_type": self.key_type.value,
            "magic": self.magic,
            "node_page_count": self.node_page_count,
            "page_size": self.page_size,
            "root_page_id": self.root_page_id,
            "table_name": self.table_name,
            "version": self.version,
        }

    def serialize(self) -> bytes:
        """Return canonical strict-UTF-8 JSON suitable for page 0, slot 0."""

        try:
            payload = json.dumps(
                self._document(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValidationError("B+ metadata names must be strict UTF-8") from exc
        if len(payload) > MAX_RECORD_SIZE:
            raise ValidationError("B+ file header does not fit in one page slot")
        return payload

    @classmethod
    def deserialize(cls, payload: bytes) -> "BPlusFileHeader":
        require_bytes(payload)

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            document: dict[str, Any] = {}
            for key, value in pairs:
                if key in document:
                    raise ValidationError(f"Duplicate B+ metadata field: {key!r}")
                document[key] = value
            return document

        def reject_non_finite(constant: str) -> None:
            raise ValidationError(f"Invalid B+ JSON numeric constant: {constant}")

        try:
            document = json.loads(
                payload.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=reject_non_finite,
            )
        except ValidationError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("Malformed B+ file header") from exc
        if type(document) is not dict:
            raise ValidationError("B+ file header must be a JSON object")

        expected = {
            "allow_duplicate_keys", "build_complete", "clustered", "entry_count",
            "first_leaf_page_id", "free_node_head_page_id", "height",
            "index_name", "key_column", "key_type", "magic",
            "node_page_count", "page_size", "root_page_id", "table_name",
            "version",
        }
        if set(document) != expected:
            missing = sorted(expected - set(document))
            extra = sorted(set(document) - expected)
            raise ValidationError(
                f"Invalid B+ file-header fields; missing={missing}, extra={extra}"
            )
        if type(document["key_type"]) is not str:
            raise InvalidTypeError("Persisted B+ key_type must be a string")
        try:
            key_type = DataType(document["key_type"])
        except ValueError as exc:
            raise ValidationError("Unknown persisted B+ key type") from exc

        arguments = dict(document)
        arguments["key_type"] = key_type
        return cls(**arguments)

    def validate_definition(
        self,
        *,
        index_name: str,
        table_name: str,
        key_column: str,
        key_type: DataType,
        clustered: bool,
        allow_duplicate_keys: bool,
    ) -> None:
        """Reject opening this file under incompatible external metadata."""

        expected = type(self)(
            index_name=index_name,
            table_name=table_name,
            key_column=key_column,
            key_type=key_type,
            clustered=clustered,
            allow_duplicate_keys=allow_duplicate_keys,
        )
        for field in (
            "index_name", "table_name", "key_column", "key_type",
            "clustered", "allow_duplicate_keys",
        ):
            if getattr(self, field) != getattr(expected, field):
                raise ValidationError(f"B+ index metadata mismatch for {field}")

    def validate_clustered_storage(self, physical_key_column: str | None) -> None:
        """Ensure a clustered index is paired with matching ordered storage."""

        if physical_key_column is not None and type(physical_key_column) is not str:
            raise InvalidTypeError("physical_key_column must be a string or None")
        if self.clustered and physical_key_column != self.key_column:
            raise ValidationError(
                "Clustered B+ key does not match the physical storage ordering key"
            )
