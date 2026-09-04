"""Pure in-memory B+ leaf/internal node models and local invariants."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.rid import RID

from .bplus_binary import (
    BPLUS_CHILD_SIZE,
    BPLUS_MAX_NODE_PAGE_ID,
    BPLUS_NODE_HEADER_SIZE,
    BPLUS_NODE_PAYLOAD_SIZE,
    BPLUS_RID_SIZE,
    BPlusNodeType,
    maximum_internal_keys,
    maximum_leaf_keys,
)
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec


def _validate_page_id(name: str, value: object, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if type(value) is not int:
        raise InvalidTypeError(f"{name} must be a built-in int")
    if not 1 <= value <= BPLUS_MAX_NODE_PAGE_ID:
        raise ValidationError(
            f"{name} must reference a B+ node page between 1 and "
            f"{BPLUS_MAX_NODE_PAGE_ID}"
        )
    return value


def _sequence(value: object, label: str) -> tuple:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise InvalidTypeError(f"{label} must be a sequence")
    return tuple(value)


def _validated_keys(data_type: object, keys: object) -> tuple:
    if not isinstance(data_type, DataType):
        raise InvalidTypeError("key_type must be a DataType")
    ordered = _sequence(keys, "keys")
    previous = None
    has_previous = False
    for key in ordered:
        BPlusKeyCodec.validate(data_type, key)
        if has_previous and BPlusKeyCodec.compare(data_type, previous, key) > 0:
            raise ValidationError("B+ node keys must be nondecreasing")
        previous = key
        has_previous = True
    return ordered


def _require_root_flag(is_root: object) -> bool:
    if type(is_root) is not bool:
        raise InvalidTypeError("is_root must be a bool")
    return is_root


@dataclass(frozen=True, slots=True, init=False)
class BPlusLeafNode:
    """A forward-linked leaf containing repeated deterministic key/RID pairs."""

    page_id: int
    key_type: DataType
    keys: tuple
    rids: tuple[RID, ...]
    next_leaf_page_id: int | None

    def __init__(
        self,
        page_id: int,
        key_type: DataType,
        keys: Sequence = (),
        rids: Sequence[RID] = (),
        *,
        next_leaf_page_id: int | None = None,
    ) -> None:
        checked_page_id = _validate_page_id("page_id", page_id)
        ordered_keys = _validated_keys(key_type, keys)
        ordered_rids = _sequence(rids, "rids")
        if len(ordered_keys) != len(ordered_rids):
            raise ValidationError("Leaf key and RID cardinalities must match")
        for rid in ordered_rids:
            BPlusRIDCodec.encode(rid)
        for position in range(1, len(ordered_keys)):
            if (
                BPlusKeyCodec.compare(
                    key_type, ordered_keys[position - 1], ordered_keys[position]
                ) == 0
                and ordered_rids[position - 1] >= ordered_rids[position]
            ):
                raise ValidationError(
                    "Equal B+ leaf keys require strictly increasing unique RIDs"
                )
        checked_next = _validate_page_id(
            "next_leaf_page_id", next_leaf_page_id, optional=True
        )
        if checked_next == checked_page_id:
            raise ValidationError("A B+ leaf cannot link to itself")
        if len(ordered_keys) > maximum_leaf_keys(key_type):
            raise ValidationError("B+ leaf exceeds its fixed key capacity")

        object.__setattr__(self, "page_id", checked_page_id)
        object.__setattr__(self, "key_type", key_type)
        object.__setattr__(self, "keys", ordered_keys)
        object.__setattr__(self, "rids", ordered_rids)
        object.__setattr__(self, "next_leaf_page_id", checked_next)
        if self.used_payload_bytes > BPLUS_NODE_PAYLOAD_SIZE:
            raise ValidationError("B+ leaf serialized payload exceeds one page slot")

    @property
    def node_type(self) -> BPlusNodeType:
        return BPlusNodeType.LEAF

    @property
    def key_count(self) -> int:
        return len(self.keys)

    @property
    def maximum_key_count(self) -> int:
        return maximum_leaf_keys(self.key_type)

    @property
    def minimum_key_count(self) -> int:
        return (self.maximum_key_count + 1) // 2

    @property
    def used_payload_bytes(self) -> int:
        return BPLUS_NODE_HEADER_SIZE + sum(
            len(BPlusKeyCodec.encode(self.key_type, key)) + BPLUS_RID_SIZE
            for key in self.keys
        )

    @property
    def is_full(self) -> bool:
        return self.key_count == self.maximum_key_count

    def validate_occupancy(self, *, is_root: bool) -> None:
        """Validate root-special or non-root minimum entry occupancy."""

        if _require_root_flag(is_root):
            return
        if self.key_count < self.minimum_key_count:
            raise ValidationError("Non-root B+ leaf is below minimum occupancy")


@dataclass(frozen=True, slots=True, init=False)
class BPlusInternalNode:
    """An internal node with right-min separators and child pointers."""

    page_id: int
    key_type: DataType
    keys: tuple
    children: tuple[int, ...]

    def __init__(
        self,
        page_id: int,
        key_type: DataType,
        keys: Sequence,
        children: Sequence[int],
    ) -> None:
        checked_page_id = _validate_page_id("page_id", page_id)
        ordered_keys = _validated_keys(key_type, keys)
        ordered_children = _sequence(children, "children")
        if len(ordered_children) != len(ordered_keys) + 1:
            raise ValidationError(
                "Internal child cardinality must equal key cardinality plus one"
            )
        checked_children = tuple(
            _validate_page_id("child page_id", child) for child in ordered_children
        )
        if checked_page_id in checked_children:
            raise ValidationError("A B+ internal node cannot reference itself")
        if len(set(checked_children)) != len(checked_children):
            raise ValidationError("B+ internal child page IDs must be unique")
        if len(ordered_keys) > maximum_internal_keys(key_type):
            raise ValidationError("B+ internal node exceeds its fixed key capacity")

        object.__setattr__(self, "page_id", checked_page_id)
        object.__setattr__(self, "key_type", key_type)
        object.__setattr__(self, "keys", ordered_keys)
        object.__setattr__(self, "children", checked_children)
        if self.used_payload_bytes > BPLUS_NODE_PAYLOAD_SIZE:
            raise ValidationError("B+ internal payload exceeds one page slot")

    @property
    def node_type(self) -> BPlusNodeType:
        return BPlusNodeType.INTERNAL

    @property
    def key_count(self) -> int:
        return len(self.keys)

    @property
    def maximum_key_count(self) -> int:
        return maximum_internal_keys(self.key_type)

    @property
    def minimum_key_count(self) -> int:
        minimum_children = (self.maximum_key_count + 2) // 2
        return minimum_children - 1

    @property
    def used_payload_bytes(self) -> int:
        return BPLUS_NODE_HEADER_SIZE + BPLUS_CHILD_SIZE + sum(
            len(BPlusKeyCodec.encode(self.key_type, key)) + BPLUS_CHILD_SIZE
            for key in self.keys
        )

    @property
    def is_full(self) -> bool:
        return self.key_count == self.maximum_key_count

    def validate_occupancy(self, *, is_root: bool) -> None:
        """Validate the internal-root exception or non-root occupancy."""

        if _require_root_flag(is_root):
            if self.key_count < 1:
                raise ValidationError("A live internal B+ root requires at least one key")
            return
        if self.key_count < self.minimum_key_count:
            raise ValidationError("Non-root B+ internal node is below minimum occupancy")


@dataclass(frozen=True, slots=True, init=False)
class BPlusFreeNode:
    """Persistent marker for a released node page.

    Released pages form a singly linked LIFO list consumed before physical
    page allocation appends to the index file.
    """

    page_id: int
    next_free_page_id: int | None

    def __init__(
        self,
        page_id: int,
        *,
        next_free_page_id: int | None = None,
    ) -> None:
        checked_page_id = _validate_page_id("page_id", page_id)
        checked_next = _validate_page_id(
            "next_free_page_id", next_free_page_id, optional=True
        )
        if checked_next == checked_page_id:
            raise ValidationError("A free B+ node cannot link to itself")
        object.__setattr__(self, "page_id", checked_page_id)
        object.__setattr__(self, "next_free_page_id", checked_next)

    @property
    def node_type(self) -> BPlusNodeType:
        return BPlusNodeType.FREE

    @property
    def key_count(self) -> int:
        return 0

    @property
    def used_payload_bytes(self) -> int:
        return BPLUS_NODE_HEADER_SIZE
