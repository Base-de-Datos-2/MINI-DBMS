"""Physical B+ fixtures for read-path tests before insertion exists."""

from dataclasses import replace

from engine.catalog import DataType
from engine.indexes import (
    BPlusFileHeader,
    BPlusHeaderPageIO,
    BPlusInternalNode,
    BPlusLeafNode,
    BPlusNodePageIO,
)
from engine.storage import PageManager, RID


def rid(key: int, duplicate: int = 0) -> RID:
    return RID(key, duplicate)


def persist_bplus_tree(
    path,
    nodes,
    *,
    root_page_id: int,
    first_leaf_page_id: int,
    height: int,
    entry_count: int | None = None,
    key_type: DataType = DataType.INTEGER,
    **header_overrides,
) -> BPlusFileHeader:
    """Persist a deliberately assembled tree using only its public page I/O.

    Read-path corruption and boundary tests still need an honest disk fixture
    assembled independently of BPlusTree mutation internals.
    """

    ordered_nodes = tuple(sorted(nodes, key=lambda node: node.page_id))
    expected_ids = tuple(range(1, len(ordered_nodes) + 1))
    assert tuple(node.page_id for node in ordered_nodes) == expected_ids
    if entry_count is None:
        entry_count = sum(
            node.key_count for node in ordered_nodes
            if isinstance(node, BPlusLeafNode)
        )

    initial = BPlusFileHeader(
        index_name="idx_students_id",
        table_name="students",
        key_column="id",
        key_type=key_type,
        **header_overrides,
    )
    manager = PageManager.create(path)
    try:
        BPlusHeaderPageIO.initialize(manager, initial)
        node_io = BPlusNodePageIO(manager, key_type)
        for expected_id in expected_ids:
            assert node_io.allocate_page() == expected_id
        for node in ordered_nodes:
            node_io.write_node(node)
        final = replace(
            initial,
            root_page_id=root_page_id,
            first_leaf_page_id=first_leaf_page_id,
            height=height,
            entry_count=entry_count,
            node_page_count=len(ordered_nodes),
        )
        BPlusHeaderPageIO.write(manager, final)
        manager.flush()
        return final
    finally:
        manager.close()


def integer_three_leaf_nodes():
    """Return a two-level tree whose duplicate key 10 crosses a leaf edge."""

    return (
        BPlusLeafNode(
            1,
            DataType.INTEGER,
            [1, 5, 10],
            [rid(1), rid(5), rid(10)],
            next_leaf_page_id=2,
        ),
        BPlusLeafNode(
            2,
            DataType.INTEGER,
            [10, 10, 15],
            [rid(10, 1), rid(10, 2), rid(15)],
            next_leaf_page_id=3,
        ),
        BPlusLeafNode(
            3,
            DataType.INTEGER,
            [20, 30],
            [rid(20), rid(30)],
        ),
        BPlusInternalNode(4, DataType.INTEGER, [10, 20], [1, 2, 3]),
    )


def persist_integer_three_leaf_tree(path, **overrides) -> BPlusFileHeader:
    return persist_bplus_tree(
        path,
        integer_three_leaf_nodes(),
        root_page_id=4,
        first_leaf_page_id=1,
        height=2,
        **overrides,
    )
