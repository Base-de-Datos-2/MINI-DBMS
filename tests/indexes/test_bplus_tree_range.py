"""Task 4.10: linked-leaf traversal and bounded range semantics."""

import math

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


def test_full_and_partially_bounded_ranges_are_ordered_and_duplicate_complete(tmp_path):
    path = tmp_path / "ranges.idx"
    persist_integer_three_leaf_tree(path)
    with BPlusTree.open(path) as tree:
        assert list(tree.range_search()) == [
            rid(1), rid(5), rid(10), rid(10, 1), rid(10, 2),
            rid(15), rid(20), rid(30),
        ]
        assert list(tree.range_search(10, 20)) == [
            rid(10), rid(10, 1), rid(10, 2), rid(15), rid(20),
        ]
        assert list(tree.range_search(10, 20, include_lower=False)) == [
            rid(15), rid(20),
        ]
        assert list(tree.range_search(10, 20, include_upper=False)) == [
            rid(10), rid(10, 1), rid(10, 2), rid(15),
        ]
        assert list(tree.range_search(None, 5)) == [rid(1), rid(5)]
        assert list(tree.range_search(20, None)) == [rid(20), rid(30)]
        assert list(tree.range_search(11, 14)) == []
        assert list(tree.range_search(10, 10)) == [
            rid(10), rid(10, 1), rid(10, 2),
        ]
        assert list(tree.range_search(10, 10, include_lower=False)) == []


def test_bounded_range_performs_one_descent_then_follows_leaf_links(tmp_path, monkeypatch):
    path = tmp_path / "single-descent.idx"
    persist_integer_three_leaf_tree(path)
    calls = 0
    original = BPlusTree.descend

    def counted(self, key):
        nonlocal calls
        calls += 1
        return original(self, key)

    monkeypatch.setattr(BPlusTree, "descend", counted)
    with BPlusTree.open(path) as tree:
        assert list(tree.range_search(10, 30))[-1] == rid(30)
        assert calls == 1


@pytest.mark.parametrize(
    ("lower", "upper", "include_lower", "include_upper"),
    [
        (20, 10, True, True),
        (1, 2, 1, True),
        (1, 2, True, 0),
    ],
)
def test_range_rejects_inverted_bounds_or_non_boolean_flags(
    tmp_path, lower, upper, include_lower, include_upper
):
    path = tmp_path / f"invalid-{lower}-{upper}-{include_lower}-{include_upper}.idx"
    persist_integer_three_leaf_tree(path)
    with BPlusTree.open(path) as tree:
        with pytest.raises((InvalidTypeError, ValidationError)):
            tree.range_search(
                lower,
                upper,
                include_lower=include_lower,
                include_upper=include_upper,
            )


def test_float_ranges_reject_nan_but_support_infinities(tmp_path):
    path = tmp_path / "float.idx"
    leaf = BPlusLeafNode(
        1,
        DataType.FLOAT,
        [-math.inf, 0.0, math.inf],
        [rid(1), rid(2), rid(3)],
    )
    persist_bplus_tree(
        path,
        [leaf],
        root_page_id=1,
        first_leaf_page_id=1,
        height=1,
        key_type=DataType.FLOAT,
    )
    with BPlusTree.open(path) as tree:
        assert list(tree.range_search(-math.inf, math.inf)) == [
            rid(1), rid(2), rid(3)
        ]
        with pytest.raises(ValidationError, match="NaN"):
            tree.range_search(float("nan"), 1.0)


def test_range_detects_leaf_link_outside_allocated_node_pages(tmp_path):
    nodes = list(integer_three_leaf_nodes())
    nodes[0] = BPlusLeafNode(
        1,
        DataType.INTEGER,
        [1, 5, 10],
        [rid(1), rid(5), rid(10)],
        next_leaf_page_id=99,
    )
    path = tmp_path / "bad-link.idx"
    persist_bplus_tree(
        path, nodes, root_page_id=4, first_leaf_page_id=1, height=2
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="outside"):
            list(tree.range_search())


def test_range_detects_leaf_link_to_internal_node(tmp_path):
    nodes = list(integer_three_leaf_nodes())
    nodes[0] = BPlusLeafNode(
        1,
        DataType.INTEGER,
        [1, 5, 10],
        [rid(1), rid(5), rid(10)],
        next_leaf_page_id=4,
    )
    path = tmp_path / "link-to-root.idx"
    persist_bplus_tree(
        path, nodes, root_page_id=4, first_leaf_page_id=1, height=2
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="non-leaf"):
            list(tree.range_search())


def test_range_detects_leaf_link_cycle(tmp_path):
    nodes = list(integer_three_leaf_nodes())
    nodes[2] = BPlusLeafNode(
        3,
        DataType.INTEGER,
        [20, 30],
        [rid(20), rid(30)],
        next_leaf_page_id=1,
    )
    path = tmp_path / "link-cycle.idx"
    persist_bplus_tree(
        path, nodes, root_page_id=4, first_leaf_page_id=1, height=2
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="Cycle"):
            list(tree.range_search())


def test_range_detects_cross_leaf_key_or_duplicate_rid_disorder(tmp_path):
    unordered = list(integer_three_leaf_nodes())
    unordered[1] = BPlusLeafNode(
        2,
        DataType.INTEGER,
        [9, 15],
        [rid(9), rid(15)],
        next_leaf_page_id=3,
    )
    path = tmp_path / "key-disorder.idx"
    persist_bplus_tree(
        path, unordered, root_page_id=4, first_leaf_page_id=1, height=2
    )
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="not ordered"):
            list(tree.range_search())

    duplicate_disorder = list(integer_three_leaf_nodes())
    duplicate_disorder[0] = BPlusLeafNode(
        1,
        DataType.INTEGER,
        [1, 10],
        [rid(1), rid(10, 9)],
        next_leaf_page_id=2,
    )
    second_path = tmp_path / "rid-disorder.idx"
    persist_bplus_tree(
        second_path,
        duplicate_disorder,
        root_page_id=4,
        first_leaf_page_id=1,
        height=2,
    )
    with BPlusTree.open(second_path) as tree:
        with pytest.raises(ValidationError, match="RID order"):
            list(tree.range_search())


def test_full_range_detects_header_entry_count_mismatch(tmp_path):
    path = tmp_path / "count-mismatch.idx"
    persist_integer_three_leaf_tree(path, entry_count=9)
    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="entry count"):
            list(tree.range_search())
