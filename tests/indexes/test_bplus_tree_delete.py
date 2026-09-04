"""Tasks 4.16--4.20: exact deletion and B+ underflow repair."""

from contextlib import contextmanager

import pytest

from engine.catalog import DataType
from engine.errors import InvalidReferenceError
from engine.indexes import (
    BPlusFreeNode,
    BPlusHeaderPageIO,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodePageIO,
    BPlusTree,
)
from engine.storage import PageManager, RID

from tests.bplus_helpers import persist_bplus_tree


CREATE_ARGUMENTS = {
    "index_name": "idx_students_key",
    "table_name": "students",
    "key_column": "key",
    "key_type": DataType.VARCHAR,
}


def key(number):
    return f"{number:04d}"


def value_rid(number):
    return RID(number, 0)


@contextmanager
def persisted_nodes(path):
    manager = PageManager.open(path)
    try:
        header = BPlusHeaderPageIO.read(manager)
        yield header, BPlusNodePageIO(manager, header.key_type)
    finally:
        manager.close()


def insert_range(tree, stop):
    for number in range(stop):
        tree.insert(key(number), value_rid(number))


def persist_three_level_tree(path, left_leaf_count, right_leaf_count):
    """Create a valid height-three VARCHAR tree with minimum-full leaves."""

    leaf_minimum = BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count
    leaf_count = left_leaf_count + right_leaf_count
    leaves = []
    first_keys = []
    number = 0
    for page_id in range(1, leaf_count + 1):
        keys = [key(value) for value in range(number, number + leaf_minimum)]
        rids = [value_rid(value) for value in range(number, number + leaf_minimum)]
        first_keys.append(keys[0])
        leaves.append(
            BPlusLeafNode(
                page_id,
                DataType.VARCHAR,
                keys,
                rids,
                next_leaf_page_id=(page_id + 1 if page_id < leaf_count else None),
            )
        )
        number += leaf_minimum

    left_page_id = leaf_count + 1
    right_page_id = leaf_count + 2
    root_page_id = leaf_count + 3
    left_children = list(range(1, left_leaf_count + 1))
    right_children = list(range(left_leaf_count + 1, leaf_count + 1))
    left = BPlusInternalNode(
        left_page_id,
        DataType.VARCHAR,
        [first_keys[child - 1] for child in left_children[1:]],
        left_children,
    )
    right = BPlusInternalNode(
        right_page_id,
        DataType.VARCHAR,
        [first_keys[child - 1] for child in right_children[1:]],
        right_children,
    )
    root = BPlusInternalNode(
        root_page_id,
        DataType.VARCHAR,
        [first_keys[right_children[0] - 1]],
        [left_page_id, right_page_id],
    )
    persist_bplus_tree(
        path,
        [*leaves, left, right, root],
        root_page_id=root_page_id,
        first_leaf_page_id=1,
        height=3,
        key_type=DataType.VARCHAR,
    )
    return number, left_page_id, right_page_id, root_page_id


def assert_all_except(tree, count, removed):
    assert list(tree.range_search()) == [
        value_rid(number) for number in range(count) if number != removed
    ]
    assert list(tree.search(key(removed))) == []


def test_delete_one_duplicate_and_then_the_final_rid_for_that_key(tmp_path):
    path = tmp_path / "duplicates.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        associations = [
            ("same", RID(1, 0)),
            ("same", RID(1, 1)),
            ("same", RID(1, 2)),
            ("z", RID(2, 0)),
        ]
        for association in associations:
            tree.insert(*association)

        tree.delete("same", RID(1, 1))
        assert list(tree.search("same")) == [RID(1, 0), RID(1, 2)]
        tree.delete("same", RID(1, 0))
        tree.delete("same", RID(1, 2))
        assert list(tree.search("same")) == []
        assert list(tree.range_search()) == [RID(2, 0)]
        assert tree.entry_count == 1


def test_duplicate_group_survives_cross_leaf_merge_in_rid_order(tmp_path):
    path = tmp_path / "duplicate-merge.idx"
    maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
    rids = [RID(7, slot_id) for slot_id in range(maximum + 1)]
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        for rid in reversed(rids):
            tree.insert("same", rid)
        assert tree.height == 2

        tree.delete("same", rids[0])

        assert list(tree.search("same")) == rids[1:]
        assert list(tree.range_search("same", "same")) == rids[1:]
        assert tree.entry_count == maximum
        assert tree.header.free_node_head_page_id is not None

    with BPlusTree.open(path) as reopened:
        assert list(reopened.search("same")) == rids[1:]


def test_delete_missing_key_or_duplicate_rid_is_write_free(tmp_path):
    path = tmp_path / "missing.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        tree.insert("a", RID(1, 0))
        tree.insert("a", RID(1, 1))
        tree.insert("z", RID(2, 0))
        tree.reset_counters()
        with pytest.raises(InvalidReferenceError, match=r"Unknown B\+ key/RID"):
            tree.delete("missing", RID(9, 0))
        with pytest.raises(InvalidReferenceError, match=r"Unknown B\+ key/RID"):
            tree.delete("a", RID(1, 9))
        assert tree.entry_count == 3
        assert tree.pages_written == tree.pages_allocated == 0


def test_delete_without_underflow_updates_direct_parent_separator(tmp_path):
    path = tmp_path / "separator.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        insert_range(tree, 17)
        original_pages = tree.node_page_count
        tree.reset_counters()
        tree.delete(key(8), value_rid(8))
        assert tree.entry_count == 16
        assert tree.node_page_count == original_pages
        assert tree.header.free_node_head_page_id is None
        assert tree.pages_allocated == 0
        assert_all_except(tree, 17, 8)
        root_page_id = tree.header.root_page_id

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        assert isinstance(root, BPlusInternalNode)
        assert root.keys[0] == key(9)


def test_leaf_redistribution_prefers_left_donor_and_preserves_links(tmp_path):
    path = tmp_path / "borrow-left.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        insert_range(tree, 16)
        tree.insert("-001", RID(99, 0))
        tree.delete(key(8), value_rid(8))
        assert tree.header.free_node_head_page_id is None
        assert list(tree.range_search()) == [
            RID(99, 0),
            *(value_rid(number) for number in range(8)),
            *(value_rid(number) for number in range(9, 16)),
        ]
        root_page_id = tree.header.root_page_id

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        left = node_io.read_node(root.children[0])
        right = node_io.read_node(root.children[1])
        assert root.keys == (key(7),)
        assert left.key_count == right.key_count == left.minimum_key_count
        assert left.next_leaf_page_id == right.page_id


def test_leaf_redistribution_uses_right_donor_and_updates_separator(tmp_path):
    path = tmp_path / "borrow-right.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        insert_range(tree, 17)
        tree.delete(key(0), value_rid(0))
        assert tree.header.free_node_head_page_id is None
        assert_all_except(tree, 17, 0)
        root_page_id = tree.header.root_page_id

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        left = node_io.read_node(root.children[0])
        right = node_io.read_node(root.children[1])
        assert root.keys == (key(9),)
        assert left.keys[-1] == key(8)
        assert right.keys[0] == key(9)
        assert left.next_leaf_page_id == right.page_id


@pytest.mark.parametrize("removed", [0, 8])
def test_leaf_merge_repairs_links_parent_and_registers_freed_page(
    tmp_path, removed
):
    path = tmp_path / f"merge-{removed}.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        insert_range(tree, 16)
        tree.delete(key(removed), value_rid(removed))
        assert tree.entry_count == 15
        assert tree.height == 1
        assert tree.header.free_node_head_page_id == 3
        assert_all_except(tree, 16, removed)
        tree.validate_structure()

    with persisted_nodes(path) as (header, node_io):
        root = node_io.read_node(header.root_page_id)
        released = node_io.read_node(header.free_node_head_page_id)
        assert isinstance(root, BPlusLeafNode)
        assert root.next_leaf_page_id is None
        assert isinstance(released, BPlusFreeNode)
        assert released.next_free_page_id == 2
        assert isinstance(node_io.read_node(2), BPlusFreeNode)


def test_leaf_minimum_change_propagates_through_child_zero_ancestors(tmp_path):
    path = tmp_path / "ancestor-separator.idx"
    count, _, _, root_page_id = persist_three_level_tree(path, 8, 8)
    first_right = 8 * BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count
    with BPlusTree.open(path) as tree:
        tree.insert(key(first_right + 7) + "a", RID(999, 0))
        tree.delete(key(first_right), value_rid(first_right))
        assert tree.header.free_node_head_page_id is None
        assert tree.entry_count == count

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        assert root.keys == (key(first_right + 1),)


def test_internal_redistribution_borrows_from_left_sibling(tmp_path):
    path = tmp_path / "internal-left.idx"
    count, left_page_id, right_page_id, root_page_id = persist_three_level_tree(
        path, 9, 8
    )
    removed = 9 * BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count
    with BPlusTree.open(path) as tree:
        tree.delete(key(removed), value_rid(removed))
        assert_all_except(tree, count, removed)
        assert tree.height == 3

    with persisted_nodes(path) as (header, node_io):
        root = node_io.read_node(root_page_id)
        left = node_io.read_node(left_page_id)
        right = node_io.read_node(right_page_id)
        assert root.key_count == 1
        assert left.key_count == right.key_count == left.minimum_key_count
        leaf_minimum = BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count
        assert root.keys[0] == key(8 * leaf_minimum)
        assert isinstance(node_io.read_node(header.free_node_head_page_id), BPlusFreeNode)


def test_internal_redistribution_borrows_from_right_sibling(tmp_path):
    path = tmp_path / "internal-right.idx"
    count, left_page_id, right_page_id, root_page_id = persist_three_level_tree(
        path, 8, 9
    )
    removed = 0
    with BPlusTree.open(path) as tree:
        tree.delete(key(removed), value_rid(removed))
        assert_all_except(tree, count, removed)
        assert tree.height == 3

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        left = node_io.read_node(left_page_id)
        right = node_io.read_node(right_page_id)
        assert root.key_count == 1
        assert left.key_count == right.key_count == left.minimum_key_count
        assert root.keys[0] == key(9 * BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count)


def test_internal_merge_preserves_subtrees_and_chains_freed_pages(tmp_path):
    path = tmp_path / "internal-merge.idx"
    count, left_page_id, right_page_id, root_page_id = persist_three_level_tree(
        path, 8, 8
    )
    leaf_minimum = BPlusLeafNode(1, DataType.VARCHAR).minimum_key_count
    removed = 8 * leaf_minimum
    with BPlusTree.open(path) as tree:
        tree.delete(key(removed), value_rid(removed))
        assert_all_except(tree, count, removed)
        assert tree.height == 2
        assert tree.header.root_page_id == left_page_id
        assert tree.header.free_node_head_page_id == root_page_id
        tree.validate_structure()

    with persisted_nodes(path) as (header, node_io):
        merged = node_io.read_node(left_page_id)
        released_internal = node_io.read_node(header.free_node_head_page_id)
        assert isinstance(merged, BPlusInternalNode)
        assert merged.key_count == 2 * merged.minimum_key_count
        assert isinstance(released_internal, BPlusFreeNode)
        assert released_internal.next_free_page_id == right_page_id
        removed_internal = node_io.read_node(released_internal.next_free_page_id)
        assert isinstance(removed_internal, BPlusFreeNode)
        assert removed_internal.next_free_page_id == 10
        released_leaf = node_io.read_node(removed_internal.next_free_page_id)
        assert isinstance(released_leaf, BPlusFreeNode)
        assert released_leaf.next_free_page_id is None

    with BPlusTree.open(path) as reopened:
        assert_all_except(reopened, count, removed)
