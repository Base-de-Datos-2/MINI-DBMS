"""Immutable bucket model and strict one-page codec."""

from __future__ import annotations

from dataclasses import dataclass

from engine.catalog.types import DataType
from engine.errors import InvalidReferenceError, InvalidTypeError, ValidationError
from engine.storage.binary import require_bytes
from engine.storage.record import RecordValue
from engine.storage.rid import RID

from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .hash_binary import (
    HASH_BUCKET_HEADER_SIZE,
    HASH_BUCKET_HEADER_STRUCT,
    HASH_BUCKET_KEY_LENGTH_SIZE,
    HASH_BUCKET_KEY_LENGTH_STRUCT,
    HASH_BUCKET_MAGIC,
    HASH_BUCKET_PAYLOAD_SIZE,
    HASH_MAX_PAGE_ID,
    HASH_PAGE_FORMAT_VERSION,
    HASH_WIDTH,
)


HashAssociation = tuple[RecordValue, RID]


def _validated_rid(value: object) -> RID:
    if not isinstance(value, RID):
        raise InvalidTypeError("hash association value must be a RID")
    BPlusRIDCodec.encode(value)
    return value


def _association_size(key_type: DataType, association: HashAssociation) -> int:
    key, rid = association
    key_bytes = BPlusKeyCodec.encode(key_type, key)
    BPlusRIDCodec.encode(rid)
    return HASH_BUCKET_KEY_LENGTH_SIZE + len(key_bytes) + BPlusRIDCodec.SIZE


@dataclass(frozen=True, slots=True, init=False)
class HashBucket:
    """One page-sized collection carrying the Extendible Hash local depth."""

    page_id: int
    key_type: DataType
    local_depth: int
    entries: tuple[HashAssociation, ...]

    def __init__(self, page_id: int, key_type: DataType, local_depth: int, entries=()):
        if type(page_id) is not int:
            raise InvalidTypeError("bucket page_id must be a built-in int")
        if not 1 <= page_id <= HASH_MAX_PAGE_ID:
            raise ValidationError("bucket page_id must reference a non-header page")
        if not isinstance(key_type, DataType):
            raise InvalidTypeError("bucket key_type must be a DataType")
        if type(local_depth) is not int:
            raise InvalidTypeError("bucket local_depth must be a built-in int")
        if not 0 <= local_depth <= HASH_WIDTH:
            raise ValidationError(f"bucket local_depth must be between 0 and {HASH_WIDTH}")
        if isinstance(entries, (str, bytes, bytearray)):
            raise InvalidTypeError("bucket entries must be an iterable")
        try:
            checked = tuple((key, rid) for key, rid in entries)
        except (TypeError, ValueError) as exc:
            raise InvalidTypeError("bucket entries must contain (key, RID) pairs") from exc

        # Canonical RID order inside equal keys makes restart results stable while
        # leaving different hash-key groups in deterministic encoded-key order.
        normalized = tuple(
            sorted(
                checked,
                key=lambda item: (BPlusKeyCodec.encode(key_type, item[0]), item[1]),
            )
        )
        for association in normalized:
            _association_size(key_type, association)
        if len(set(normalized)) != len(normalized):
            raise ValidationError("Hash bucket contains a duplicate key/RID pair")
        if self.serialized_size_for(key_type, normalized) > HASH_BUCKET_PAYLOAD_SIZE:
            raise ValidationError("Hash bucket associations exceed one page")
        object.__setattr__(self, "page_id", page_id)
        object.__setattr__(self, "key_type", key_type)
        object.__setattr__(self, "local_depth", local_depth)
        object.__setattr__(self, "entries", normalized)

    @staticmethod
    def serialized_size_for(key_type: DataType, entries) -> int:
        return HASH_BUCKET_HEADER_SIZE + sum(
            _association_size(key_type, association) for association in entries
        )

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def used_payload_bytes(self) -> int:
        return self.serialized_size_for(self.key_type, self.entries)

    def find(self, key: object) -> list[RID]:
        checked = BPlusKeyCodec.validate(self.key_type, key)
        return [
            rid
            for existing, rid in self.entries
            if BPlusKeyCodec.compare(self.key_type, existing, checked) == 0
        ]

    def contains(self, key: object, rid: object) -> bool:
        checked_rid = _validated_rid(rid)
        return checked_rid in self.find(key)

    def can_fit(self, key: object, rid: object) -> bool:
        BPlusKeyCodec.validate(self.key_type, key)
        checked_rid = _validated_rid(rid)
        if self.contains(key, checked_rid):
            return True
        return self.serialized_size_for(
            self.key_type, (*self.entries, (key, checked_rid))
        ) <= HASH_BUCKET_PAYLOAD_SIZE

    def insert(self, key: object, rid: object) -> "HashBucket":
        checked = BPlusKeyCodec.validate(self.key_type, key)
        checked_rid = _validated_rid(rid)
        if self.contains(checked, checked_rid):
            return self
        return type(self)(
            self.page_id,
            self.key_type,
            self.local_depth,
            (*self.entries, (checked, checked_rid)),
        )

    def delete(self, key: object, rid: object) -> "HashBucket":
        checked = BPlusKeyCodec.validate(self.key_type, key)
        checked_rid = _validated_rid(rid)
        remaining = [
            association
            for association in self.entries
            if not (
                BPlusKeyCodec.compare(
                    self.key_type, association[0], checked
                ) == 0
                and association[1] == checked_rid
            )
        ]
        if len(remaining) == len(self.entries):
            raise InvalidReferenceError("Hash key/RID association does not exist")
        return type(self)(self.page_id, self.key_type, self.local_depth, remaining)

    def iter_entries(self):
        return iter(self.entries)

    def replace_entries(self, entries, *, local_depth: int | None = None) -> "HashBucket":
        depth = self.local_depth if local_depth is None else local_depth
        return type(self)(self.page_id, self.key_type, depth, entries)


class HashBucketCodec:
    """Encode every complete key and RID; a hash value is never stored as equality."""

    @staticmethod
    def serialize(bucket: HashBucket) -> bytes:
        if not isinstance(bucket, HashBucket):
            raise InvalidTypeError("bucket must be a HashBucket")
        payload = bytearray(
            HASH_BUCKET_HEADER_STRUCT.pack(
                HASH_BUCKET_MAGIC,
                HASH_PAGE_FORMAT_VERSION,
                bucket.local_depth,
                bucket.entry_count,
                bucket.page_id,
                bucket.used_payload_bytes,
            )
        )
        for key, rid in bucket.entries:
            key_bytes = BPlusKeyCodec.encode(bucket.key_type, key)
            payload.extend(HASH_BUCKET_KEY_LENGTH_STRUCT.pack(len(key_bytes)))
            payload.extend(key_bytes)
            payload.extend(BPlusRIDCodec.encode(rid))
        payload.extend(bytes(HASH_BUCKET_PAYLOAD_SIZE - len(payload)))
        return bytes(payload)

    @staticmethod
    def deserialize(key_type: DataType, payload: bytes) -> HashBucket:
        if not isinstance(key_type, DataType):
            raise InvalidTypeError("bucket key_type must be a DataType")
        require_bytes(payload)
        if len(payload) != HASH_BUCKET_PAYLOAD_SIZE:
            raise ValidationError("Hash bucket payload has an invalid length")
        magic, version, local_depth, count, page_id, used_bytes = (
            HASH_BUCKET_HEADER_STRUCT.unpack_from(payload)
        )
        if magic != HASH_BUCKET_MAGIC:
            raise ValidationError("Invalid hash bucket signature")
        if version != HASH_PAGE_FORMAT_VERSION:
            raise ValidationError("Unsupported hash bucket page version")
        if not HASH_BUCKET_HEADER_SIZE <= used_bytes <= HASH_BUCKET_PAYLOAD_SIZE:
            raise ValidationError("Hash bucket used-byte count is invalid")

        offset = HASH_BUCKET_HEADER_SIZE
        entries: list[HashAssociation] = []
        for _ in range(count):
            if offset + HASH_BUCKET_KEY_LENGTH_SIZE > used_bytes:
                raise ValidationError("Truncated hash bucket key length")
            key_length = HASH_BUCKET_KEY_LENGTH_STRUCT.unpack_from(payload, offset)[0]
            offset += HASH_BUCKET_KEY_LENGTH_SIZE
            key_end = offset + key_length
            rid_end = key_end + BPlusRIDCodec.SIZE
            if rid_end > used_bytes:
                raise ValidationError("Truncated hash bucket association")
            key = BPlusKeyCodec.decode(key_type, payload[offset:key_end])
            rid = BPlusRIDCodec.decode(payload[key_end:rid_end])
            entries.append((key, rid))
            offset = rid_end
        if offset != used_bytes:
            raise ValidationError("Hash bucket used-byte count does not match entries")
        if any(payload[offset:]):
            raise ValidationError("Hash bucket has nonzero trailing bytes")
        bucket = HashBucket(page_id, key_type, local_depth, entries)
        if bucket.used_payload_bytes != used_bytes:
            raise ValidationError("Hash bucket byte count is not canonical")
        return bucket
