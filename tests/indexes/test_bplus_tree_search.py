"""Tasks 4.8--4.9: lower-bound descent, paths, and exact search."""

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import BPlusInternalNode, BPlusLeafNode, BPlusTree

from tests.bplus_helpers import (
    integer_three_leaf_nodes,
    persist_bplus_tree,
    persist_integer_three_leaf_tree,
    rid,
)


def test_descent_captures_root_to_parent_path_and_separator_equality_goes_left(
    tmp_path,
):
    path = tmp_path / "descent.idx"
    persist_integer_three_leaf_tree(path)
    tree = BPlusTree.open(path)
    try:
        tree.reset_counters()
        descent = tree.descend(10)
        assert descent.leaf.page_id == 1
        assert [(item.node.page_id, item.child_index) for item in descent.ancestors] == [
            (4, 0)
        ]
        assert tree.pages_read == 2

        assert tree.descend(11).leaf.page_id == 2
        assert tree.descend(99).leaf.page_id == 3
    finally:
        tree.close()


def test_multilevel_descent_retains_every_ancestor(tmp_path):
    nodes = (
        BPlusLeafNode(1, DataType.INTEGER, [1], [rid(1)], next_leaf_page_id=2),
        BPlusLeafNode(2, DataType.INTEGER, [10], [rid(10)], next_leaf_page_id=3),
        BPlusLeafNode(3, DataType.INTEGER, [20], [rid(20)], next_leaf_page_id=4),
        BPlusLeafNode(4, DataType.INTEGER, [30], [rid(30)]),
        BPlusInternalNode(5, DataType.INTEGER, [10], [1, 2]),
        BPlusInternalNode(6, DataType.INTEGER, [30], [3, 4]),
        BPlusInternalNode(7, DataType.INTEGER, [20], [5, 6]),
    )
    path = tmp_path / "tall.idx"
    persist_bplus_tree(
        path,
        nodes,
        root_page_id=7,
        first_leaf_page_id=1,
        height=3,
    )
    tree = BPlusTree.open(path)
    try:
        tree.reset_counters()
        descent = tree.descend(20)
        assert descent.leaf.page_id == 2
        assert [(item.node.page_id, item.child_index) for item in descent.ancestors] == [
            (7, 0),
            (5, 1),
        ]
        assert tree.pages_read == 3
    finally:
        tree.close()


def test_exact_search_handles_absence_edges_and_cross_leaf_duplicates(tmp_path):
    path = tmp_path / "search.idx"
    persist_integer_three_leaf_tree(path)
    with BPlusTree.open(path) as tree:
        assert list(tree.search(0)) == []
        assert list(tree.search(1)) == [rid(1)]
        assert list(tree.search(7)) == []
        assert list(tree.search(10)) == [rid(10), rid(10, 1), rid(10, 2)]
        assert list(tree.search(15)) == [rid(15)]
        assert list(tree.search(30)) == [rid(30)]
        assert list(tree.search(31)) == []


def test_exact_search_in_single_leaf_persists_across_fresh_tree_instances(tmp_path):
    path = tmp_path / "single.idx"
    leaf = BPlusLeafNode(
        1,
        DataType.VARCHAR,
        ["a", "ñ", "ñ", "東京"],
        [rid(1), rid(2), rid(2, 1), rid(3)],
    )
    persist_bplus_tree(
        path,
        [leaf],
        root_page_id=1,
        first_leaf_page_id=1,
        height=1,
        key_type=DataType.VARCHAR,
    )
    first = BPlusTree.open(path)
    assert list(first.search("ñ")) == [rid(2), rid(2, 1)]
    first.close()
    second = BPlusTree.open(path)
    try:
        assert list(second.search("東京")) == [rid(3)]
        with pytest.raises(InvalidTypeError):
            second.search(3)
    finally:
        second.close()


def test_search_rejects_duplicates_when_persisted_policy_is_unique(tmp_path):
    path = tmp_path / "unique-corrupt.idx"
    leaf = BPlusLeafNode(
        1,
        DataType.INTEGER,
        [7, 7],
        [rid(7), rid(7, 1)],
    )
    persist_bplus_tree(
        path,
        [leaf],
        root_page_id=1,
        first_leaf_page_id=1,
        height=1,
        allow_duplicate_keys=False,
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="duplicates forbidden"):
            list(tree.search(7))


def test_descent_rejects_out_of_range_child_reference(tmp_path):
    nodes = list(integer_three_leaf_nodes())
    nodes[-1] = BPlusInternalNode(4, DataType.INTEGER, [10, 20], [1, 2, 99])
    path = tmp_path / "bad-child.idx"
    persist_bplus_tree(
        path,
        nodes,
        root_page_id=4,
        first_leaf_page_id=1,
        height=2,
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="outside"):
            tree.descend(99)


def test_descent_rejects_height_node_type_mismatch(tmp_path):
    nodes = list(integer_three_leaf_nodes())
    nodes[-1] = BPlusLeafNode(4, DataType.INTEGER, [50], [rid(50)])
    path = tmp_path / "bad-height.idx"
    persist_bplus_tree(
        path,
        nodes,
        root_page_id=4,
        first_leaf_page_id=1,
        height=2,
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="internal"):
            tree.descend(1)


def test_descent_rejects_child_pointer_cycle(tmp_path):
    nodes = (
        BPlusLeafNode(1, DataType.INTEGER, [1], [rid(1)]),
        BPlusInternalNode(2, DataType.INTEGER, [5], [1, 3]),
        BPlusInternalNode(3, DataType.INTEGER, [9], [1, 2]),
        BPlusInternalNode(4, DataType.INTEGER, [5], [1, 2]),
    )
    path = tmp_path / "child-cycle.idx"
    persist_bplus_tree(
        path,
        nodes,
        root_page_id=4,
        first_leaf_page_id=1,
        height=4,
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="Cycle"):
            tree.descend(99)
