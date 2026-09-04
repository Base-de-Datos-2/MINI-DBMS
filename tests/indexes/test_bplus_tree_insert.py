"""Tasks 4.11--4.15: persistent B+ insertion and split propagation."""

from contextlib import contextmanager
import random

import pytest

from engine.catalog import DataType
from engine.errors import DuplicateError, InvalidTypeError
from engine.indexes import (
    BPlusHeaderPageIO,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodePageIO,
    BPlusTree,
)
from engine.storage import PageManager, RID

from tests.bplus_helpers import persist_bplus_tree, rid


def create_arguments(key_type=DataType.VARCHAR, **overrides):
    arguments = {
        "index_name": "idx_students_key",
        "table_name": "students",
        "key_column": "key",
        "key_type": key_type,
    }
    arguments.update(overrides)
    return arguments


@contextmanager
def persisted_nodes(path):
    manager = PageManager.open(path)
    try:
        header = BPlusHeaderPageIO.read(manager)
        yield header, BPlusNodePageIO(manager, header.key_type)
    finally:
        manager.close()


def key(number):
    return f"{number:04d}"


def value_rid(number):
    return RID(number, number % 7)


def test_first_insert_allocates_one_leaf_and_persists_header(tmp_path):
    path = tmp_path / "first.idx"
    tree = BPlusTree.create(path, **create_arguments(DataType.INTEGER))
    tree.insert(8, RID(3, 2))
    assert tree.header.root_page_id == tree.header.first_leaf_page_id == 1
    assert tree.height == tree.entry_count == tree.node_page_count == 1
    assert tree.allocated_page_count == 2
    tree.close()

    with BPlusTree.open(path) as reopened:
        assert list(reopened.search(8)) == [RID(3, 2)]
        assert reopened.height == reopened.entry_count == 1


def test_leaf_insert_orders_ascending_descending_middle_and_duplicate_rids(tmp_path):
    path = tmp_path / "ordered.idx"
    with BPlusTree.create(path, **create_arguments(DataType.INTEGER)) as tree:
        entries = [
            (30, RID(30, 0)),
            (10, RID(10, 2)),
            (20, RID(20, 0)),
            (10, RID(10, 0)),
            (10, RID(10, 1)),
        ]
        for entry_key, entry_rid in entries:
            tree.insert(entry_key, entry_rid)
        assert list(tree.range_search()) == [
            RID(10, 0), RID(10, 1), RID(10, 2), RID(20, 0), RID(30, 0)
        ]
        assert list(tree.search(10)) == [RID(10, 0), RID(10, 1), RID(10, 2)]


def test_repeating_exact_pair_is_noop_without_writes_or_count_change(tmp_path):
    path = tmp_path / "idempotent.idx"
    with BPlusTree.create(path, **create_arguments(DataType.INTEGER)) as tree:
        tree.insert(4, RID(2, 1))
        tree.reset_counters()
        tree.insert(4, RID(2, 1))
        assert tree.entry_count == 1
        assert tree.pages_written == tree.pages_allocated == 0


def test_unique_index_rejects_second_rid_for_same_key_without_mutation(tmp_path):
    path = tmp_path / "unique.idx"
    with BPlusTree.create(
        path,
        **create_arguments(DataType.INTEGER, allow_duplicate_keys=False),
    ) as tree:
        tree.insert(5, RID(1, 0))
        tree.reset_counters()
        with pytest.raises(DuplicateError, match="Duplicate key"):
            tree.insert(5, RID(2, 0))
        assert list(tree.search(5)) == [RID(1, 0)]
        assert tree.entry_count == 1
        assert tree.pages_written == tree.pages_allocated == 0


def test_insert_validation_happens_before_first_allocation(tmp_path):
    path = tmp_path / "invalid.idx"
    with BPlusTree.create(path, **create_arguments(DataType.INTEGER)) as tree:
        tree.reset_counters()
        with pytest.raises(InvalidTypeError):
            tree.insert(True, RID(1, 0))
        with pytest.raises(InvalidTypeError):
            tree.insert(1, object())
        assert tree.entry_count == tree.node_page_count == 0
        assert tree.pages_written == tree.pages_allocated == 0


def test_insert_without_split_preserves_existing_leaf_link_and_root(tmp_path):
    path = tmp_path / "linked.idx"
    nodes = (
        BPlusLeafNode(
            1,
            DataType.INTEGER,
            [1, 5],
            [rid(1), rid(5)],
            next_leaf_page_id=2,
        ),
        BPlusLeafNode(2, DataType.INTEGER, [10], [rid(10)]),
        BPlusInternalNode(3, DataType.INTEGER, [10], [1, 2]),
    )
    original = persist_bplus_tree(
        path, nodes, root_page_id=3, first_leaf_page_id=1, height=2
    )
    with BPlusTree.open(path) as tree:
        tree.insert(7, rid(7))
        assert tree.header.root_page_id == original.root_page_id
        assert tree.node_page_count == original.node_page_count

    with persisted_nodes(path) as (header, node_io):
        left = node_io.read_node(header.first_leaf_page_id)
        assert left == BPlusLeafNode(
            1,
            DataType.INTEGER,
            [1, 5, 7],
            [rid(1), rid(5), rid(7)],
            next_leaf_page_id=2,
        )


def test_leaf_split_copies_right_min_and_repairs_forward_links(tmp_path):
    path = tmp_path / "leaf-split.idx"
    with BPlusTree.create(path, **create_arguments()) as tree:
        maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
        for number in reversed(range(maximum + 1)):
            tree.insert(key(number), value_rid(number))
        assert tree.height == 2
        assert tree.entry_count == maximum + 1
        assert tree.node_page_count == 3
        expected = [value_rid(number) for number in range(maximum + 1)]
        assert list(tree.range_search()) == expected
        root_page_id = tree.header.root_page_id

    with persisted_nodes(path) as (header, node_io):
        root = node_io.read_node(root_page_id)
        assert isinstance(root, BPlusInternalNode)
        assert root.key_count == 1
        left = node_io.read_node(root.children[0])
        right = node_io.read_node(root.children[1])
        assert isinstance(left, BPlusLeafNode)
        assert isinstance(right, BPlusLeafNode)
        assert root.keys == (right.keys[0],)
        assert left.next_leaf_page_id == right.page_id
        assert right.next_leaf_page_id is None
        assert left.keys + right.keys == tuple(key(i) for i in range(maximum + 1))
        left.validate_occupancy(is_root=False)
        right.validate_occupancy(is_root=False)
        assert header.first_leaf_page_id == left.page_id


def test_duplicate_group_can_split_and_accept_later_ordered_rids(tmp_path):
    path = tmp_path / "duplicate-split.idx"
    maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
    rids = [RID(1, slot_id) for slot_id in range(maximum + 5)]
    shuffled = list(rids)
    random.Random(412).shuffle(shuffled)

    with BPlusTree.create(path, **create_arguments()) as tree:
        for entry_rid in shuffled:
            tree.insert("same", entry_rid)
        assert tree.height == 2
        assert tree.entry_count == len(rids)
        assert list(tree.search("same")) == rids
        assert list(tree.range_search("same", "same")) == rids

        tree.reset_counters()
        tree.insert("same", rids[-1])
        assert tree.entry_count == len(rids)
        assert tree.pages_written == tree.pages_allocated == 0


def test_nonroot_leaf_split_inserts_between_existing_forward_links(tmp_path):
    path = tmp_path / "middle-leaf-split.idx"
    maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
    left_keys = [key(number) for number in range(maximum)]
    nodes = (
        BPlusLeafNode(
            1,
            DataType.VARCHAR,
            left_keys,
            [value_rid(number) for number in range(maximum)],
            next_leaf_page_id=2,
        ),
        BPlusLeafNode(2, DataType.VARCHAR, [key(100)], [value_rid(100)]),
        BPlusInternalNode(3, DataType.VARCHAR, [key(100)], [1, 2]),
    )
    persist_bplus_tree(
        path,
        nodes,
        root_page_id=3,
        first_leaf_page_id=1,
        height=2,
        key_type=DataType.VARCHAR,
    )

    with BPlusTree.open(path) as tree:
        tree.insert(key(50), value_rid(50))
        assert list(tree.range_search()) == [
            *(value_rid(number) for number in range(maximum)),
            value_rid(50),
            value_rid(100),
        ]

    with persisted_nodes(path) as (header, node_io):
        root = node_io.read_node(header.root_page_id)
        assert isinstance(root, BPlusInternalNode)
        assert len(root.children) == 3
        left = node_io.read_node(root.children[0])
        inserted_right = node_io.read_node(root.children[1])
        old_right = node_io.read_node(root.children[2])
        assert left.next_leaf_page_id == inserted_right.page_id
        assert inserted_right.next_leaf_page_id == old_right.page_id
        assert old_right.next_leaf_page_id is None
        assert root.keys == (inserted_right.keys[0], old_right.keys[0])


def test_later_leaf_split_inserts_separator_into_existing_root(tmp_path):
    path = tmp_path / "parent-insert.idx"
    with BPlusTree.create(path, **create_arguments()) as tree:
        number = 0
        while tree.height < 2 or tree.node_page_count < 4:
            tree.insert(key(number), value_rid(number))
            number += 1
        assert tree.height == 2
        assert tree.node_page_count == 4
        root_page_id = tree.header.root_page_id

    with persisted_nodes(path) as (_, node_io):
        root = node_io.read_node(root_page_id)
        assert isinstance(root, BPlusInternalNode)
        assert root.key_count == 2
        assert len(root.children) == 3
        right_children = [node_io.read_node(page_id) for page_id in root.children[1:]]
        assert root.keys == tuple(node.keys[0] for node in right_children)


def test_internal_overflow_propagates_and_root_split_survives_reopen(tmp_path):
    path = tmp_path / "root-growth.idx"
    arguments = create_arguments()
    with BPlusTree.create(path, **arguments) as tree:
        internal_maximum = BPlusInternalNode(
            1, DataType.VARCHAR, [], [2]
        ).maximum_key_count
        number = 0
        root_growth_allocations = None
        while tree.height < 3:
            previous_height = tree.height
            previous_pages = tree.node_page_count
            tree.insert(key(number), value_rid(number))
            number += 1
            if previous_height == 2 and tree.height == 3:
                root_growth_allocations = tree.node_page_count - previous_pages
        assert number > internal_maximum
        assert tree.height == 3
        # One leaf sibling, one internal sibling, and exactly one new root.
        assert root_growth_allocations == 3
        assert tree.header.root_page_id is not None
        expected = [value_rid(i) for i in range(number)]
        assert list(tree.range_search()) == expected
        persisted_root = tree.header.root_page_id
        persisted_pages = tree.node_page_count

    with BPlusTree.open(path, **arguments) as reopened:
        assert reopened.height == 3
        assert reopened.header.root_page_id == persisted_root
        assert reopened.node_page_count == persisted_pages
        assert list(reopened.range_search()) == expected
        for probe in (0, number // 2, number - 1):
            assert list(reopened.search(key(probe))) == [value_rid(probe)]

    with persisted_nodes(path) as (header, node_io):
        root = node_io.read_node(header.root_page_id)
        assert isinstance(root, BPlusInternalNode)
        assert root.key_count == 1
        assert len(root.children) == 2
        for child_page_id in root.children:
            child = node_io.read_node(child_page_id)
            assert isinstance(child, BPlusInternalNode)
            child.validate_occupancy(is_root=False)


def test_split_propagates_into_nonfull_multilevel_parent(tmp_path):
    path = tmp_path / "cascade-into-root.idx"
    with BPlusTree.create(path, **create_arguments()) as tree:
        number = 0
        while tree.height < 3:
            tree.insert(key(number), value_rid(number))
            number += 1
        root_page_id = tree.header.root_page_id
        observed_internal_split = False
        while not observed_internal_split:
            previous_pages = tree.node_page_count
            tree.insert(key(number), value_rid(number))
            number += 1
            observed_internal_split = tree.node_page_count - previous_pages == 2
        assert tree.height == 3
        assert tree.header.root_page_id == root_page_id
        assert tree.descend(key(number - 1)).ancestors[0].node.key_count == 2
        assert tree.entry_count == number
        assert list(tree.range_search()) == [value_rid(i) for i in range(number)]


def test_shuffled_insertion_preserves_multilevel_search_and_order(tmp_path):
    path = tmp_path / "shuffled.idx"
    numbers = list(range(200))
    random.Random(41015).shuffle(numbers)

    with BPlusTree.create(path, **create_arguments()) as tree:
        for number in numbers:
            tree.insert(key(number), value_rid(number))
        assert tree.height >= 3
        assert tree.entry_count == len(numbers)
        assert list(tree.range_search()) == [
            value_rid(number) for number in range(200)
        ]
        for number in numbers:
            assert list(tree.search(key(number))) == [value_rid(number)]


def test_split_propagates_across_multiple_ancestors_to_a_new_root(tmp_path):
    path = tmp_path / "height-four.idx"
    arguments = create_arguments()
    with BPlusTree.create(path, **arguments) as tree:
        number = 0
        while tree.height < 4:
            tree.insert(key(number), value_rid(number))
            number += 1
        assert number < 2000
        assert tree.height == 4
        assert tree.entry_count == number
        assert list(tree.range_search()) == [value_rid(i) for i in range(number)]
        root_page_id = tree.header.root_page_id

    with BPlusTree.open(path, **arguments) as reopened:
        assert reopened.height == 4
        assert reopened.header.root_page_id == root_page_id
        assert reopened.entry_count == number
        assert list(reopened.range_search()) == [
            value_rid(i) for i in range(number)
        ]
        for probe in (0, number // 3, number // 2, number - 1):
            assert list(reopened.search(key(probe))) == [value_rid(probe)]
