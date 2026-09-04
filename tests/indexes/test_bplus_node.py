"""Pure B+ node models, fixed capacities, and occupancy invariants."""

from dataclasses import FrozenInstanceError

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import (
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodeType,
)
from engine.storage import RID
from engine.storage.binary import MAX_RECORD_SIZE


def leaf_with_count(count, *, data_type=DataType.INTEGER, page_id=1):
    key = {
        DataType.INTEGER: 7,
        DataType.FLOAT: 7.0,
        DataType.BOOLEAN: False,
        DataType.VARCHAR: "k",
    }[data_type]
    return BPlusLeafNode(
        page_id,
        data_type,
        [key] * count,
        [RID(1, position) for position in range(count)],
    )


def internal_with_count(count, *, data_type=DataType.INTEGER, page_id=1):
    key = {
        DataType.INTEGER: 7,
        DataType.FLOAT: 7.0,
        DataType.BOOLEAN: False,
        DataType.VARCHAR: "k",
    }[data_type]
    return BPlusInternalNode(
        page_id,
        data_type,
        [key] * count,
        list(range(2, count + 3)),
    )


def test_create_empty_leaf_node_and_snapshot_sequences():
    node = BPlusLeafNode(1, DataType.INTEGER)
    assert node.node_type is BPlusNodeType.LEAF
    assert node.keys == node.rids == ()
    assert node.next_leaf_page_id is None
    assert node.key_count == 0
    assert node.used_payload_bytes > 0
    node.validate_occupancy(is_root=True)


def test_create_internal_node_with_no_separators_and_one_child():
    node = BPlusInternalNode(1, DataType.INTEGER, [], [2])
    assert node.node_type is BPlusNodeType.INTERNAL
    assert node.keys == ()
    assert node.children == (2,)
    with pytest.raises(ValidationError, match="root"):
        node.validate_occupancy(is_root=True)


def test_nodes_are_immutable_and_copy_input_sequences():
    keys = [1]
    rids = [RID(2, 3)]
    node = BPlusLeafNode(1, DataType.INTEGER, keys, rids)
    keys.append(2)
    rids.append(RID(2, 4))
    assert node.keys == (1,)
    assert node.rids == (RID(2, 3),)
    with pytest.raises(FrozenInstanceError):
        node.page_id = 2


def test_leaf_key_rid_cardinality_must_match():
    with pytest.raises(ValidationError, match="cardinalities"):
        BPlusLeafNode(1, DataType.INTEGER, [1], [])


@pytest.mark.parametrize(
    ("keys", "rids", "message"),
    [
        ([2, 1], [RID(1, 0), RID(1, 1)], "nondecreasing"),
        ([1, 1], [RID(1, 1), RID(1, 0)], "increasing"),
        ([1, 1], [RID(1, 0), RID(1, 0)], "unique"),
    ],
)
def test_leaf_rejects_unsorted_keys_or_nondeterministic_duplicate_pairs(
    keys, rids, message
):
    with pytest.raises(ValidationError, match=message):
        BPlusLeafNode(1, DataType.INTEGER, keys, rids)


def test_leaf_accepts_duplicate_keys_with_strictly_ordered_rids():
    node = BPlusLeafNode(
        1,
        DataType.INTEGER,
        [1, 1, 2],
        [RID(3, 0), RID(3, 1), RID(2, 0)],
        next_leaf_page_id=2,
    )
    assert node.keys == (1, 1, 2)
    assert node.next_leaf_page_id == 2


def test_internal_cardinality_and_child_references_are_validated():
    with pytest.raises(ValidationError, match="plus one"):
        BPlusInternalNode(1, DataType.INTEGER, [5], [2])
    with pytest.raises(ValidationError, match="unique"):
        BPlusInternalNode(1, DataType.INTEGER, [5], [2, 2])
    with pytest.raises(ValidationError, match="itself"):
        BPlusInternalNode(1, DataType.INTEGER, [5], [1, 2])


@pytest.mark.parametrize("value", [0, -1, 2**32 - 1])
def test_node_page_zero_negative_and_null_sentinel_are_rejected(value):
    with pytest.raises(ValidationError):
        BPlusLeafNode(value, DataType.INTEGER)


@pytest.mark.parametrize("value", [True, 1.0, "1", None])
def test_node_page_id_requires_exact_int(value):
    with pytest.raises(InvalidTypeError):
        BPlusLeafNode(value, DataType.INTEGER)


def test_leaf_cannot_link_to_itself():
    with pytest.raises(ValidationError, match="itself"):
        BPlusLeafNode(1, DataType.INTEGER, next_leaf_page_id=1)


@pytest.mark.parametrize("data_type", list(DataType))
def test_leaf_capacity_is_derived_from_worst_case_and_fits_payload(data_type):
    probe = leaf_with_count(0, data_type=data_type)
    full = leaf_with_count(probe.maximum_key_count, data_type=data_type)
    assert full.is_full
    assert full.used_payload_bytes <= MAX_RECORD_SIZE
    with pytest.raises(ValidationError, match="capacity"):
        leaf_with_count(probe.maximum_key_count + 1, data_type=data_type)


@pytest.mark.parametrize("data_type", list(DataType))
def test_internal_capacity_is_derived_and_fits_payload(data_type):
    probe = internal_with_count(0, data_type=data_type)
    full = internal_with_count(probe.maximum_key_count, data_type=data_type)
    assert full.is_full
    assert full.used_payload_bytes <= MAX_RECORD_SIZE
    with pytest.raises(ValidationError, match="capacity"):
        internal_with_count(probe.maximum_key_count + 1, data_type=data_type)


def test_varchar_worst_case_key_still_fits_fixed_node_capacities():
    key = "x" * 255
    leaf_probe = BPlusLeafNode(1, DataType.VARCHAR)
    leaf = BPlusLeafNode(
        1,
        DataType.VARCHAR,
        [key] * leaf_probe.maximum_key_count,
        [RID(1, position) for position in range(leaf_probe.maximum_key_count)],
    )
    internal_probe = BPlusInternalNode(1, DataType.VARCHAR, [], [2])
    internal = BPlusInternalNode(
        1,
        DataType.VARCHAR,
        [key] * internal_probe.maximum_key_count,
        list(range(2, internal_probe.maximum_key_count + 3)),
    )
    assert leaf.maximum_key_count == internal.maximum_key_count == 15
    assert leaf.used_payload_bytes <= MAX_RECORD_SIZE
    assert internal.used_payload_bytes <= MAX_RECORD_SIZE


def test_non_root_leaf_minimum_occupancy_is_half_rounded_up():
    probe = leaf_with_count(0)
    exact = leaf_with_count(probe.minimum_key_count)
    exact.validate_occupancy(is_root=False)
    with pytest.raises(ValidationError, match="minimum occupancy"):
        leaf_with_count(probe.minimum_key_count - 1).validate_occupancy(
            is_root=False
        )


def test_non_root_internal_minimum_occupancy_uses_half_children():
    probe = internal_with_count(0)
    exact = internal_with_count(probe.minimum_key_count)
    exact.validate_occupancy(is_root=False)
    with pytest.raises(ValidationError, match="minimum occupancy"):
        internal_with_count(probe.minimum_key_count - 1).validate_occupancy(
            is_root=False
        )


@pytest.mark.parametrize("flag", [None, 0, 1, "true"])
def test_occupancy_requires_boolean_root_flag(flag):
    with pytest.raises(InvalidTypeError):
        BPlusLeafNode(1, DataType.INTEGER).validate_occupancy(is_root=flag)


def test_node_key_type_and_scalar_types_are_strict():
    with pytest.raises(InvalidTypeError, match="DataType"):
        BPlusLeafNode(1, "INTEGER")
    with pytest.raises(InvalidTypeError, match="requires int"):
        BPlusLeafNode(1, DataType.INTEGER, [True], [RID(1, 0)])
    with pytest.raises(ValidationError, match="NaN"):
        BPlusLeafNode(1, DataType.FLOAT, [float("nan")], [RID(1, 0)])
