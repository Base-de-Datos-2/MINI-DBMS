"""Task 4.23: fresh-object restart through growth, shrink, and reuse."""

import random

from engine.catalog import DataType
from engine.indexes import BPlusTree
from engine.storage import RID


ARGUMENTS = {
    "index_name": "idx_restart_code",
    "table_name": "rows",
    "key_column": "code",
    "key_type": DataType.VARCHAR,
}


def key(value):
    return f"{value:04d}"


def rid(value):
    return RID(value, 0)


def test_restart_recovers_growth_shrink_empty_state_and_page_reuse(tmp_path):
    path = tmp_path / "restart.idx"
    initial_values = list(range(300))
    random.Random(423).shuffle(initial_values)
    with BPlusTree.create(path, **ARGUMENTS) as writer:
        for value in initial_values:
            writer.insert(key(value), rid(value))
        assert writer.height >= 3
        original_root = writer.header.root_page_id
        writer.validate_structure()
        writer.flush()

    with BPlusTree.open(path, **ARGUMENTS) as grower:
        assert grower.header.root_page_id == original_root
        assert list(grower.range_search(key(75), key(80))) == [
            rid(value) for value in range(75, 81)
        ]
        for value in range(300, 340):
            grower.insert(key(value), rid(value))
        assert grower.validate_structure().entry_count == 340
        grower.flush()

    with BPlusTree.open(path, **ARGUMENTS) as reducer:
        for value in range(330):
            reducer.delete(key(value), rid(value))
        report = reducer.validate_structure()
        assert report.entry_count == 10
        assert report.height == 1
        assert report.free_page_count > 0
        allocated_before_reuse = reducer.allocated_page_count
        reducer.flush()

    with BPlusTree.open(path, **ARGUMENTS) as reuser:
        reuser.reset_counters()
        for value in range(400, 430):
            reuser.insert(key(value), rid(value))
        assert reuser.pages_allocated == 0
        assert reuser.allocated_page_count == allocated_before_reuse
        assert reuser.validate_structure().entry_count == 40
        for value in [*range(330, 340), *range(400, 430)]:
            reuser.delete(key(value), rid(value))
        empty = reuser.validate_structure()
        assert empty.entry_count == empty.height == empty.leaf_count == 0
        assert empty.free_page_count == reuser.node_page_count
        reuser.flush()

    with BPlusTree.open(path, **ARGUMENTS) as final_reader:
        assert list(final_reader.range_search()) == []
        assert final_reader.validate_structure().entry_count == 0
