"""Deterministic B+ node payload serialization without file ownership."""

from __future__ import annotations

from engine.catalog.types import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.storage.binary import require_bytes

from .bplus_binary import (
    BPLUS_CHILD_SIZE,
    BPLUS_CHILD_STRUCT,
    BPLUS_NODE_FORMAT_VERSION,
    BPLUS_NODE_HEADER_SIZE,
    BPLUS_NODE_HEADER_STRUCT,
    BPLUS_NODE_MAGIC,
    BPLUS_NODE_PAYLOAD_SIZE,
    BPLUS_NULL_PAGE_ID,
    BPLUS_RID_SIZE,
    BPlusNodeType,
    maximum_internal_keys,
    maximum_leaf_keys,
)
from .bplus_codec import BPlusKeyCodec, BPlusRIDCodec
from .bplus_node import BPlusFreeNode, BPlusInternalNode, BPlusLeafNode


BPlusNode = BPlusLeafNode | BPlusInternalNode | BPlusFreeNode


def _require_key_type(key_type: object) -> DataType:
    if not isinstance(key_type, DataType):
        raise InvalidTypeError("key_type must be a DataType")
    return key_type


def _take(payload: bytes, offset: int, size: int, label: str) -> tuple[bytes, int]:
    end = offset + size
    if end > len(payload):
        raise ValidationError(f"Truncated B+ node {label}")
    return payload[offset:end], end


class BPlusNodeCodec:
    """Encode one node as a fixed-size payload for one slotted page.

    The payload is ``MAX_RECORD_SIZE`` bytes.  The outer :class:`Page` adds its
    normal header and single slot entry, so the persisted physical frame is
    exactly ``PAGE_SIZE`` bytes.  Unused node-payload bytes are canonical zero
    padding and are validated during decoding.
    """

    @staticmethod
    def serialize(node: BPlusNode) -> bytes:
        if not isinstance(node, (BPlusLeafNode, BPlusInternalNode, BPlusFreeNode)):
            raise InvalidTypeError("node must be a B+ leaf, internal, or free node")

        if isinstance(node, BPlusLeafNode):
            pointer = (
                BPLUS_NULL_PAGE_ID
                if node.next_leaf_page_id is None
                else node.next_leaf_page_id
            )
        elif isinstance(node, BPlusInternalNode):
            pointer = BPLUS_NULL_PAGE_ID
        else:
            pointer = (
                BPLUS_NULL_PAGE_ID
                if node.next_free_page_id is None
                else node.next_free_page_id
            )

        encoded = bytearray(
            BPLUS_NODE_HEADER_STRUCT.pack(
                BPLUS_NODE_MAGIC,
                BPLUS_NODE_FORMAT_VERSION,
                int(node.node_type),
                node.key_count,
                node.page_id,
                pointer,
            )
        )

        if isinstance(node, BPlusLeafNode):
            for key, rid in zip(node.keys, node.rids):
                encoded.extend(BPlusKeyCodec.encode(node.key_type, key))
                encoded.extend(BPlusRIDCodec.encode(rid))
        elif isinstance(node, BPlusInternalNode):
            encoded.extend(BPLUS_CHILD_STRUCT.pack(node.children[0]))
            for key, child in zip(node.keys, node.children[1:]):
                encoded.extend(BPlusKeyCodec.encode(node.key_type, key))
                encoded.extend(BPLUS_CHILD_STRUCT.pack(child))

        if len(encoded) > BPLUS_NODE_PAYLOAD_SIZE:
            raise ValidationError("Serialized B+ node exceeds one page payload")
        encoded.extend(bytes(BPLUS_NODE_PAYLOAD_SIZE - len(encoded)))
        return bytes(encoded)

    @staticmethod
    def deserialize(key_type: DataType, payload: bytes) -> BPlusNode:
        checked_type = _require_key_type(key_type)
        require_bytes(payload)
        if len(payload) != BPLUS_NODE_PAYLOAD_SIZE:
            raise ValidationError(
                "Serialized B+ node requires exactly "
                f"{BPLUS_NODE_PAYLOAD_SIZE} bytes"
            )

        try:
            magic, version, raw_type, key_count, page_id, pointer = (
                BPLUS_NODE_HEADER_STRUCT.unpack_from(payload)
            )
        except Exception as exc:  # pragma: no cover - exact length already guards struct
            raise ValidationError("Malformed B+ node header") from exc
        if magic != BPLUS_NODE_MAGIC:
            raise ValidationError("Invalid B+ node signature")
        if version != BPLUS_NODE_FORMAT_VERSION:
            raise ValidationError(f"Unsupported B+ node version: {version}")
        try:
            node_type = BPlusNodeType(raw_type)
        except ValueError as exc:
            raise ValidationError(f"Unknown B+ node type: {raw_type}") from exc

        if node_type is BPlusNodeType.LEAF:
            maximum = maximum_leaf_keys(checked_type)
        elif node_type is BPlusNodeType.INTERNAL:
            maximum = maximum_internal_keys(checked_type)
        else:
            maximum = 0
        if key_count > maximum:
            raise ValidationError(
                f"B+ node key count {key_count} exceeds capacity {maximum}"
            )

        offset = BPLUS_NODE_HEADER_SIZE
        keys: list = []
        if node_type is BPlusNodeType.LEAF:
            rids = []
            for _ in range(key_count):
                key, offset = BPlusKeyCodec.decode_from(
                    checked_type, payload, offset
                )
                encoded_rid, offset = _take(
                    payload, offset, BPLUS_RID_SIZE, "RID"
                )
                keys.append(key)
                rids.append(BPlusRIDCodec.decode(encoded_rid))
            next_leaf_page_id = (
                None if pointer == BPLUS_NULL_PAGE_ID else pointer
            )
            node: BPlusNode = BPlusLeafNode(
                page_id,
                checked_type,
                keys,
                rids,
                next_leaf_page_id=next_leaf_page_id,
            )
        elif node_type is BPlusNodeType.INTERNAL:
            if pointer != BPLUS_NULL_PAGE_ID:
                raise ValidationError(
                    "Internal B+ node reserved pointer must be null"
                )
            encoded_child, offset = _take(
                payload, offset, BPLUS_CHILD_SIZE, "left child"
            )
            children = [BPLUS_CHILD_STRUCT.unpack(encoded_child)[0]]
            for _ in range(key_count):
                key, offset = BPlusKeyCodec.decode_from(
                    checked_type, payload, offset
                )
                encoded_child, offset = _take(
                    payload, offset, BPLUS_CHILD_SIZE, "child"
                )
                keys.append(key)
                children.append(BPLUS_CHILD_STRUCT.unpack(encoded_child)[0])
            node = BPlusInternalNode(page_id, checked_type, keys, children)
        else:
            next_free_page_id = (
                None if pointer == BPLUS_NULL_PAGE_ID else pointer
            )
            node = BPlusFreeNode(
                page_id,
                next_free_page_id=next_free_page_id,
            )

        if any(payload[offset:]):
            raise ValidationError("B+ node has nonzero bytes after its entries")
        return node
