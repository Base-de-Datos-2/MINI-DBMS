from engine.catalog import Column, DataType, Schema
from engine.storage import HeapFile, OrganizationMetadata, OrganizationType, Page, PageManager, Record, RID
from engine.storage.record_codec import RecordCodec


def schema():
    return Schema([Column("id", DataType.INTEGER), Column("value", DataType.VARCHAR)])


def rows(heap):
    return [record.values[0] for _, record in heap.scan()]


def test_variable_sizes_preserve_initial_arrival_after_reopen(tmp_path):
    path = tmp_path / "arrival.heap"
    layout = schema()
    with HeapFile.create(path, layout) as heap:
        rids = [heap.insert(Record(layout, [identity, "x" * size]))
                for identity, size in [(1, 3200), (2, 3200), (3, 100)]]
        assert rids == [RID(1, 0), RID(2, 0), RID(2, 1)]
        assert rows(heap) == [1, 2, 3]
    with HeapFile.open(path) as heap:
        assert rows(heap) == [1, 2, 3]
        assert heap.insert(Record(layout, [4, "x" * 3200])) == RID(3, 0)
        assert heap.insert(Record(layout, [5, "x" * 100])) == RID(3, 1)
        assert rows(heap) == [1, 2, 3, 4, 5]


def test_deleted_slot_reuse_preserves_other_rids_after_reopen(tmp_path):
    path = tmp_path / "reuse.heap"
    layout = schema()
    original = [Record(layout, [i, "x" * 3200]) for i in (1, 2)]
    with HeapFile.create(path, layout) as heap:
        first, second = [heap.insert(record) for record in original]
        heap.delete(first)
    with HeapFile.open(path) as heap:
        assert heap.insert(Record(layout, [3, "y" * 100])) == first
        assert heap.read(second) == original[1]
        assert heap.deleted_record_count == 0
        assert heap.insert(Record(layout, [4, "z" * 100])) == RID(2, 1)
        assert heap.data_page_count == 2
        assert rows(heap) == [3, 2, 4]


def test_open_preserves_existing_v1_pages_without_reordering(tmp_path):
    path = tmp_path / "old.heap"
    layout = schema()
    records = [Record(layout, [i, "x" * size]) for i, size in [(1, 3200), (2, 3200), (3, 100)]]
    first, second = Page(1), Page(2)
    first.insert(RecordCodec.serialize(records[0]))
    first.insert(RecordCodec.serialize(records[2]))
    second.insert(RecordCodec.serialize(records[1]))
    metadata = OrganizationMetadata(OrganizationType.HEAP, layout, active_record_count=3, data_page_count=2)
    header = Page(0)
    header.insert(metadata.serialize())
    with PageManager.create(path) as manager:
        for page in (header, first, second):
            assert manager.allocate_page() == page.page_id
            manager.write_page(page)
    before = path.read_bytes()
    with HeapFile.open(path) as heap:
        assert rows(heap) == [1, 3, 2]
        assert heap.read(RID(1, 1)) == records[2]
    assert path.read_bytes() == before
