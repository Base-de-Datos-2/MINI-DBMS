"""Task 4.29: structural metrics alongside real PageManager I/O."""

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import BPlusLeafNode, BPlusTree
from engine.storage import RID


ARGS = dict(
    index_name="idx_key",
    table_name="items",
    key_column="key",
    key_type=DataType.VARCHAR,
)


def key(number):
    return f"{number:04d}"


def test_structural_counters_observe_split_io_and_reset_together(tmp_path):
    maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
    with BPlusTree.create(tmp_path / "split.idx", **ARGS) as tree:
        tree.reset_counters()
        for number in range(maximum + 1):
            tree.insert(key(number), RID(number, 0))

        metrics = tree.structural_metrics
        assert metrics.leaf_splits == metrics.node_splits == 1
        assert metrics.root_splits == 1
        assert tree.pages_written > 0
        assert tree.pages_allocated > 0

        tree.reset_counters()
        assert tree.structural_metrics.node_splits == 0
        assert tree.structural_metrics.root_splits == 0
        assert tree.pages_read == tree.pages_written == tree.pages_allocated == 0


def test_structural_counters_observe_leaf_redistribution_merge_and_root_shrink(
    tmp_path,
):
    with BPlusTree.create(tmp_path / "redistribute.idx", **ARGS) as tree:
        for number in range(17):
            tree.insert(key(number), RID(number, 0))
        tree.reset_counters()
        tree.delete(key(0), RID(0, 0))
        assert tree.structural_metrics.leaf_redistributions == 1
        assert tree.structural_metrics.redistributions == 1

    with BPlusTree.create(tmp_path / "merge.idx", **ARGS) as tree:
        for number in range(16):
            tree.insert(key(number), RID(number, 0))
        tree.reset_counters()
        tree.delete(key(0), RID(0, 0))
        assert tree.structural_metrics.leaf_merges == 1
        assert tree.structural_metrics.node_merges == 1
        assert tree.structural_metrics.root_shrinks == 1
        assert tree.height == 1


def test_structural_counters_are_session_local_and_closed_boundaries_hold(tmp_path):
    path = tmp_path / "restart.idx"
    tree = BPlusTree.create(path, **ARGS)
    for number in range(17):
        tree.insert(key(number), RID(number, 0))
    assert tree.structural_metrics.node_splits
    tree.close()

    with pytest.raises(RuntimeError, match="closed"):
        _ = tree.structural_metrics
    with pytest.raises(RuntimeError, match="closed"):
        tree.rebuild_from_storage(None)

    with BPlusTree.open(path) as reopened:
        assert reopened.structural_metrics.node_splits == 0
        with pytest.raises(InvalidTypeError):
            reopened.insert(1, RID(1, 0))
        with pytest.raises(ValidationError):
            reopened.insert("x" * 5000, RID(1, 0))
        assert reopened.entry_count == 17
