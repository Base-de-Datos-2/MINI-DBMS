"""Task 4.7: one canonical persistent empty-tree lifecycle."""

import pytest

from engine.catalog import DataType
from engine.errors import InvalidTypeError, ValidationError
from engine.indexes import BPlusLeafNode, BPlusTree
from engine.storage import RID
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE


CREATE_ARGUMENTS = {
    "index_name": "idx_students_id",
    "table_name": "students",
    "key_column": "id",
    "key_type": DataType.INTEGER,
}


def test_create_empty_tree_uses_only_metadata_page_and_survives_reopen(tmp_path):
    path = tmp_path / "empty.idx"
    tree = BPlusTree.create(path, **CREATE_ARGUMENTS)
    assert tree.header.root_page_id is None
    assert tree.header.first_leaf_page_id is None
    assert tree.height == tree.entry_count == tree.node_page_count == 0
    assert tree.allocated_page_count == 1
    assert tree.file_size == FILE_HEADER_SIZE + PAGE_SIZE
    assert list(tree.search(7)) == []
    assert list(tree.range_search()) == []
    tree.flush()
    tree.close()

    reopened = BPlusTree.open(path, **CREATE_ARGUMENTS)
    try:
        assert reopened.header.index_name == "idx_students_id"
        assert reopened.header.key_type is DataType.INTEGER
        assert reopened.height == reopened.entry_count == 0
        assert list(reopened.search(7)) == []
    finally:
        reopened.close()


def test_final_entry_deletion_returns_to_empty_tree_and_reuses_page(tmp_path):
    tree = BPlusTree.create(tmp_path / "boundary.idx", **CREATE_ARGUMENTS)
    try:
        tree.insert(1, RID(2, 3))
        assert list(tree.search(1)) == [RID(2, 3)]
        assert tree.entry_count == 1
        allocated = tree.allocated_page_count
        tree.delete(1, RID(2, 3))
        assert list(tree.search(1)) == []
        assert tree.entry_count == tree.height == 0
        assert tree.header.root_page_id is tree.header.first_leaf_page_id is None
        assert tree.header.free_node_head_page_id == 1

        tree.insert(2, RID(4, 5))
        assert list(tree.search(2)) == [RID(4, 5)]
        assert tree.header.root_page_id == 1
        assert tree.header.free_node_head_page_id is None
        assert tree.allocated_page_count == allocated
    finally:
        tree.close()


def test_root_shrink_pages_are_reused_before_physical_allocation(tmp_path):
    path = tmp_path / "root-reuse.idx"
    arguments = {
        **CREATE_ARGUMENTS,
        "key_type": DataType.VARCHAR,
        "key_column": "code",
    }
    with BPlusTree.create(path, **arguments) as tree:
        maximum = BPlusLeafNode(1, DataType.VARCHAR).maximum_key_count
        for number in range(maximum + 1):
            tree.insert(f"{number:04d}", RID(number, 0))
        allocated = tree.allocated_page_count
        tree.delete("0000", RID(0, 0))
        assert tree.height == 1
        assert tree.validate_structure().free_page_count == 2

        tree.reset_counters()
        tree.insert("9999", RID(9999, 0))

        assert tree.height == 2
        assert tree.header.free_node_head_page_id is None
        assert tree.pages_allocated == 0
        assert tree.allocated_page_count == allocated
        tree.validate_structure()

    with BPlusTree.open(path, **arguments) as reopened:
        assert reopened.validate_structure().entry_count == maximum + 1


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("index_name", "different"),
        ("table_name", "different"),
        ("key_column", "other"),
        ("key_type", DataType.FLOAT),
        ("clustered", True),
        ("allow_duplicate_keys", False),
    ],
)
def test_open_rejects_incompatible_external_definition(tmp_path, argument, value):
    path = tmp_path / f"mismatch-{argument}.idx"
    BPlusTree.create(path, **CREATE_ARGUMENTS).close()
    with pytest.raises(ValidationError, match=argument):
        BPlusTree.open(path, **{argument: value})


def test_context_manager_flush_close_and_closed_boundary(tmp_path):
    path = tmp_path / "context.idx"
    with BPlusTree.create(path, **CREATE_ARGUMENTS) as tree:
        tree.flush()
        assert not tree.closed
    assert tree.closed
    tree.close()
    for operation in (
        lambda: tree.flush(),
        lambda: tree.reset_counters(),
        lambda: tree.search(1),
        lambda: tree.range_search(),
        lambda: tree.header,
    ):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


def test_create_is_exclusive_and_open_does_not_create(tmp_path):
    path = tmp_path / "exclusive.idx"
    BPlusTree.create(path, **CREATE_ARGUMENTS).close()
    with pytest.raises(FileExistsError):
        BPlusTree.create(path, **CREATE_ARGUMENTS)
    with pytest.raises(FileNotFoundError):
        BPlusTree.open(tmp_path / "absent.idx")


def test_empty_queries_validate_key_and_range_arguments(tmp_path):
    tree = BPlusTree.create(tmp_path / "validation.idx", **CREATE_ARGUMENTS)
    try:
        with pytest.raises(InvalidTypeError):
            tree.search(True)
        with pytest.raises(InvalidTypeError):
            tree.range_search(include_lower=1)
        with pytest.raises(ValidationError, match="exceeds"):
            tree.range_search(2, 1)
    finally:
        tree.close()
