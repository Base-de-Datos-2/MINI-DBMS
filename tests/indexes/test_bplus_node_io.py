"""Task 4.6: fixed node frames and PageManager-only index I/O."""

from dataclasses import replace
import struct

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError, ValidationError
from engine.indexes import (
    BPlusFileHeader,
    BPlusFreeNode,
    BPlusHeaderPageIO,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodeCodec,
    BPlusNodePageIO,
)
from engine.indexes.bplus_binary import (
    BPLUS_NODE_HEADER_SIZE,
    BPLUS_NODE_PAYLOAD_SIZE,
    BPLUS_NULL_PAGE_ID,
    maximum_leaf_keys,
)
from engine.storage import Page, PageManager, RID
from engine.storage.binary import PAGE_SIZE


def empty_header(**overrides):
    values = {
        "index_name": "idx_students_id",
        "table_name": "students",
        "key_column": "id",
        "key_type": DataType.INTEGER,
    }
    values.update(overrides)
    return BPlusFileHeader(**values)


@pytest.mark.parametrize(
    "node",
    [
        BPlusLeafNode(
            1,
            DataType.INTEGER,
            [-7, 4, 4],
            [RID(1, 0), RID(2, 0), RID(2, 1)],
            next_leaf_page_id=2,
        ),
        BPlusLeafNode(
            2,
            DataType.VARCHAR,
            ["árbol", "東京"],
            [RID(3, 0), RID(4, 0)],
        ),
        BPlusInternalNode(3, DataType.FLOAT, [-float("inf"), 1.5], [1, 2, 4]),
        BPlusInternalNode(4, DataType.BOOLEAN, [False, True], [1, 2, 3]),
        BPlusFreeNode(5, next_free_page_id=2),
    ],
)
def test_node_codec_round_trip_is_exact_fixed_and_canonical(node):
    payload = BPlusNodeCodec.serialize(node)
    assert len(payload) == BPLUS_NODE_PAYLOAD_SIZE
    key_type = getattr(node, "key_type", DataType.INTEGER)
    recovered = BPlusNodeCodec.deserialize(key_type, payload)
    assert recovered == node
    assert BPlusNodeCodec.serialize(recovered) == payload


def test_node_frame_occupies_exactly_one_physical_page(tmp_path):
    path = tmp_path / "one-node.idx"
    manager = PageManager.create(path)
    try:
        BPlusHeaderPageIO.initialize(manager, empty_header())
        io = BPlusNodePageIO(manager, DataType.INTEGER)
        assert io.allocate_page() == 1
        node = BPlusLeafNode(1, DataType.INTEGER, [8], [RID(3, 2)])
        frame = io.frame_node(node)
        assert frame.page_id == 1
        assert frame.slot_count == frame.active_record_count == 1
        assert len(frame.read(0)) == BPLUS_NODE_PAYLOAD_SIZE
        assert len(frame.serialize()) == PAGE_SIZE
    finally:
        manager.close()


def test_node_page_io_persists_through_a_fresh_manager_and_counts_io(tmp_path):
    path = tmp_path / "nodes.idx"
    manager = PageManager.create(path)
    BPlusHeaderPageIO.initialize(manager, empty_header())
    io = BPlusNodePageIO(manager, DataType.INTEGER)
    assert io.allocate_page() == 1
    leaf = BPlusLeafNode(1, DataType.INTEGER, [2, 9], [RID(4, 0), RID(8, 1)])
    io.write_node(leaf)
    BPlusHeaderPageIO.write(
        manager,
        replace(empty_header(), node_page_count=1),
    )
    manager.close()

    reopened = PageManager.open(path)
    try:
        reopened.reset_counters()
        assert BPlusHeaderPageIO.read(reopened).node_page_count == 1
        assert BPlusNodePageIO(reopened, DataType.INTEGER).read_node(1) == leaf
        assert reopened.pages_read == 2
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.__setitem__(slice(0, 4), b"NOPE"), "signature"),
        (lambda data: data.__setitem__(4, 99), "version"),
        (lambda data: data.__setitem__(5, 99), "node type"),
        (
            lambda data: struct.pack_into(
                "<H", data, 6, maximum_leaf_keys(DataType.INTEGER) + 1
            ),
            "exceeds capacity",
        ),
        (lambda data: data.__setitem__(-1, 1), "nonzero bytes"),
    ],
)
def test_node_codec_rejects_corrupt_header_count_or_padding(mutator, message):
    payload = bytearray(
        BPlusNodeCodec.serialize(
            BPlusLeafNode(1, DataType.INTEGER, [3], [RID(1, 0)])
        )
    )
    mutator(payload)
    with pytest.raises(ValidationError, match=message):
        BPlusNodeCodec.deserialize(DataType.INTEGER, bytes(payload))


def test_node_codec_rejects_internal_reserved_pointer_and_invalid_child():
    node = BPlusInternalNode(3, DataType.INTEGER, [5], [1, 2])
    reserved = bytearray(BPlusNodeCodec.serialize(node))
    struct.pack_into("<I", reserved, 12, 7)
    with pytest.raises(ValidationError, match="reserved pointer"):
        BPlusNodeCodec.deserialize(DataType.INTEGER, bytes(reserved))

    child_zero = bytearray(BPlusNodeCodec.serialize(node))
    struct.pack_into("<I", child_zero, BPLUS_NODE_HEADER_SIZE, 0)
    with pytest.raises(ValidationError, match="child page_id"):
        BPlusNodeCodec.deserialize(DataType.INTEGER, bytes(child_zero))


def test_node_codec_rejects_malformed_varchar_and_wrong_payload_size():
    node = BPlusLeafNode(1, DataType.VARCHAR, ["ok"], [RID(1, 0)])
    malformed = bytearray(BPlusNodeCodec.serialize(node))
    struct.pack_into("<I", malformed, BPLUS_NODE_HEADER_SIZE, 300)
    with pytest.raises(ValidationError):
        BPlusNodeCodec.deserialize(DataType.VARCHAR, bytes(malformed))
    with pytest.raises(ValidationError, match="exactly"):
        BPlusNodeCodec.deserialize(DataType.VARCHAR, bytes(malformed[:-1]))


def test_node_page_io_rejects_empty_layout_and_stored_physical_id_mismatch(tmp_path):
    path = tmp_path / "bad-node.idx"
    manager = PageManager.create(path)
    try:
        BPlusHeaderPageIO.initialize(manager, empty_header())
        io = BPlusNodePageIO(manager, DataType.INTEGER)
        assert io.allocate_page() == 1
        with pytest.raises(ValidationError, match="page layout"):
            io.read_node(1)

        mismatched = Page(1)
        mismatched.insert(
            BPlusNodeCodec.serialize(BPlusLeafNode(2, DataType.INTEGER))
        )
        manager.write_page(mismatched)
        with pytest.raises(ValidationError, match="physical page_id"):
            io.read_node(1)
    finally:
        manager.close()


def test_header_page_io_rejects_missing_metadata_and_physical_count_mismatch(tmp_path):
    path = tmp_path / "missing-header.idx"
    manager = PageManager.create(path)
    try:
        with pytest.raises(ValidationError, match="no metadata"):
            BPlusHeaderPageIO.read(manager)
        BPlusHeaderPageIO.initialize(manager, empty_header())
        BPlusNodePageIO(manager, DataType.INTEGER).allocate_page()
        with pytest.raises(ValidationError, match="physical file"):
            BPlusHeaderPageIO.read(manager)
    finally:
        manager.close()


def test_node_io_delegates_unallocated_access_to_page_manager(tmp_path):
    path = tmp_path / "bounds.idx"
    manager = PageManager.create(path)
    try:
        BPlusHeaderPageIO.initialize(manager, empty_header())
        io = BPlusNodePageIO(manager, DataType.INTEGER)
        with pytest.raises(ValidationError, match="reserved metadata"):
            io.read_node(0)
        with pytest.raises(InvalidReferenceError, match="Unallocated"):
            io.read_node(1)
    finally:
        manager.close()
