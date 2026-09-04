"""Task 4.22: persisted global B+ structural validation."""

from dataclasses import replace
import random

import pytest

from engine.catalog import DataType
from engine.errors import ValidationError
from engine.indexes import (
    BPlusHeaderPageIO,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodePageIO,
    BPlusTree,
)
from engine.storage import PageManager, RID


ARGUMENTS = {
    "index_name": "idx_validator",
    "table_name": "rows",
    "key_column": "code",
    "key_type": DataType.VARCHAR,
}


def populate(tree, count):
    values = list(range(count))
    random.Random(422).shuffle(values)
    for value in values:
        tree.insert(f"{value:04d}", RID(value, 0))


def test_validator_accepts_empty_multilevel_and_mutated_trees(tmp_path):
    path = tmp_path / "valid.idx"
    with BPlusTree.create(path, **ARGUMENTS) as tree:
        empty = tree.validate_structure()
        assert empty.height == empty.entry_count == empty.leaf_count == 0

        populate(tree, 180)
        report = tree.validate_structure()
        assert report.height == tree.height >= 3
        assert report.entry_count == 180
        assert report.leaf_count > 2
        assert report.internal_count > 1

        for value in range(0, 160):
            tree.delete(f"{value:04d}", RID(value, 0))
        reduced = tree.validate_structure()
        assert reduced.entry_count == 20
        assert reduced.height < report.height
        assert reduced.free_page_count > 0


def test_validator_detects_wrong_separator(tmp_path):
    path = tmp_path / "separator.idx"
    with BPlusTree.create(path, **ARGUMENTS) as tree:
        populate(tree, 40)
        root_page_id = tree.header.root_page_id

    with PageManager.open(path) as manager:
        header = BPlusHeaderPageIO.read(manager)
        nodes = BPlusNodePageIO(manager, header.key_type)
        root = nodes.read_node(root_page_id)
        assert isinstance(root, BPlusInternalNode)
        changed = list(root.keys)
        changed[0] = "-wrong"
        nodes.write_node(
            BPlusInternalNode(root.page_id, root.key_type, changed, root.children)
        )

    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="right-min separator"):
            tree.validate_structure()


def test_validator_detects_broken_leaf_chain(tmp_path):
    path = tmp_path / "links.idx"
    with BPlusTree.create(path, **ARGUMENTS) as tree:
        populate(tree, 40)
        first_leaf_page_id = tree.header.first_leaf_page_id

    with PageManager.open(path) as manager:
        header = BPlusHeaderPageIO.read(manager)
        nodes = BPlusNodePageIO(manager, header.key_type)
        leaf = nodes.read_node(first_leaf_page_id)
        assert isinstance(leaf, BPlusLeafNode)
        nodes.write_node(
            BPlusLeafNode(leaf.page_id, leaf.key_type, leaf.keys, leaf.rids)
        )

    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="leaf chain"):
            tree.validate_structure()


def test_validator_detects_wrong_entry_count(tmp_path):
    path = tmp_path / "count.idx"
    with BPlusTree.create(path, **ARGUMENTS) as tree:
        populate(tree, 20)

    with PageManager.open(path) as manager:
        header = BPlusHeaderPageIO.read(manager)
        BPlusHeaderPageIO.write(
            manager, replace(header, entry_count=header.entry_count + 1)
        )

    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="entry count"):
            tree.validate_structure()


def test_validator_rejects_untracked_allocated_node_page(tmp_path):
    path = tmp_path / "orphan.idx"
    with BPlusTree.create(path, **ARGUMENTS) as tree:
        tree.insert("0001", RID(1, 0))

    with PageManager.open(path) as manager:
        header = BPlusHeaderPageIO.read(manager)
        nodes = BPlusNodePageIO(manager, header.key_type)
        orphan_id = nodes.allocate_page()
        nodes.write_node(BPlusLeafNode(orphan_id, header.key_type, ["9999"], [RID(9, 0)]))
        BPlusHeaderPageIO.write(
            manager, replace(header, node_page_count=header.node_page_count + 1)
        )

    with BPlusTree.open(path) as tree:
        with pytest.raises(ValidationError, match="untracked"):
            tree.validate_structure()
