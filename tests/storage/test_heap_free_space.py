import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import (
    HeapFile,
    HeapFreeSpaceTracker,
    OrganizationMetadata,
    OrganizationType,
    Page,
    PageManager,
    Record,
    RID,
)
from engine.storage.binary import MAX_RECORD_SIZE, PAGE_HEADER_SIZE, PAGE_SIZE, SLOT_SIZE


def _schema():
    return Schema([Column("id", DataType.INTEGER)])


def _create_heap_fixture(path, data_pages):
    active = sum(page.active_record_count for page in data_pages)
    deleted = sum(page.slot_count - page.active_record_count for page in data_pages)
    metadata = OrganizationMetadata(
        OrganizationType.HEAP,
        _schema(),
        active_record_count=active,
        deleted_record_count=deleted,
        data_page_count=len(data_pages),
    )
    with PageManager.create(path) as manager:
        assert manager.allocate_page() == 0
        metadata_page = Page(0)
        assert metadata_page.insert(metadata.serialize()) == 0
        manager.write_page(metadata_page)
        for page in data_pages:
            assert manager.allocate_page() == page.page_id
            manager.write_page(page)


def test_empty_page_capacity_accounts_for_a_new_slot_without_file_io(no_file_io):
    page = Page(1)
    tracker = HeapFreeSpaceTracker()

    with no_file_io():
        tracker.register(page)
        candidate = tracker.find_candidate(MAX_RECORD_SIZE)

    assert tracker.snapshot == ((1, MAX_RECORD_SIZE),)
    assert candidate == 1


def test_tracker_chooses_lowest_eligible_page_id():
    small = Page(2)
    small.insert(b"x" * 3000)
    large = Page(3)
    lower = Page(1)
    tracker = HeapFreeSpaceTracker()
    tracker.rebuild([small, large, lower])

    assert tracker.find_candidate(1000) == 1
    assert tracker.find_candidate(2000) == 1
    lower.insert(b"x" * 3000)
    tracker.update(lower)
    assert tracker.find_candidate(2000) == 3


def test_deleted_slot_recovers_payload_capacity_without_another_slot_cost():
    page = Page(1)
    slot_id = page.insert(b"x" * 1000)
    page.insert(b"y" * 500)
    page.delete(slot_id)

    capacity_before_compaction = HeapFreeSpaceTracker.insertable_payload_bytes(page)
    page.compact()
    capacity_after_compaction = HeapFreeSpaceTracker.insertable_payload_bytes(page)

    expected = PAGE_SIZE - (PAGE_HEADER_SIZE + 2 * SLOT_SIZE) - 500
    assert capacity_before_compaction == expected
    assert capacity_after_compaction == expected


def test_register_observation_can_be_stale_until_explicit_update():
    page = Page(1)
    tracker = HeapFreeSpaceTracker()
    tracker.register(page)
    page.insert(b"x" * MAX_RECORD_SIZE)

    assert tracker.find_candidate(1) == 1
    tracker.update(page)
    assert tracker.find_candidate(1) is None


def test_remove_and_atomic_rebuild():
    first = Page(1)
    second = Page(2)
    tracker = HeapFreeSpaceTracker()
    tracker.rebuild([first, second])

    tracker.remove(1)
    assert tracker.snapshot == ((2, MAX_RECORD_SIZE),)
    tracker.remove(1)

    with pytest.raises(ValidationError, match="Duplicate"):
        tracker.rebuild([first, first])
    assert tracker.snapshot == ((2, MAX_RECORD_SIZE),)


@pytest.mark.parametrize("value", [True, 1.5, "1", None])
def test_tracker_rejects_invalid_page_ids(value):
    tracker = HeapFreeSpaceTracker()
    with pytest.raises(InvalidTypeError):
        tracker.remove(value)


def test_tracker_rejects_metadata_page_id_and_invalid_payload_sizes():
    tracker = HeapFreeSpaceTracker()
    with pytest.raises(ValidationError):
        tracker.register(Page(0))
    for value in (-1, MAX_RECORD_SIZE + 1):
        with pytest.raises(ValidationError):
            tracker.find_candidate(value)
    for value in (True, 1.5, "1", None):
        with pytest.raises(InvalidTypeError):
            tracker.find_candidate(value)


def test_rebuild_validates_iterable_and_page_members():
    tracker = HeapFreeSpaceTracker()
    with pytest.raises(InvalidTypeError):
        tracker.rebuild(1)
    with pytest.raises(InvalidTypeError):
        tracker.rebuild([Page(1), "page"])
    assert tracker.snapshot == ()


def test_heap_open_rebuilds_tracker_from_every_data_page(tmp_path):
    path = tmp_path / "heap.db"
    page_one = Page(1)
    page_one.insert(b"a" * 100)
    page_two = Page(2)
    deleted_slot = page_two.insert(b"b" * 200)
    page_two.delete(deleted_slot)
    _create_heap_fixture(path, [page_one, page_two])

    with HeapFile.open(path, _schema()) as heap:
        assert heap.record_count == 1
        assert heap.deleted_record_count == 1
        assert heap.data_page_count == 2
        assert heap.pages_read == 3
        assert heap.free_space_snapshot == (
            (1, PAGE_SIZE - (PAGE_HEADER_SIZE + SLOT_SIZE) - 100 - SLOT_SIZE),
            (2, MAX_RECORD_SIZE),
        )


def test_heap_insert_refreshes_stale_candidate_and_continues_safely(tmp_path):
    path = tmp_path / "stale.db"
    schema = Schema([Column("value", DataType.VARCHAR)])
    full_record = Record(schema, ["x" * (MAX_RECORD_SIZE - 4)])
    next_record = Record(schema, ["next"])

    with HeapFile.create(path, schema) as heap:
        assert heap.insert(full_record) == RID(1, 0)
        # Inject an old observation without changing the physical page.
        heap._free_space.register(Page(1))

        new_rid = heap.insert(next_record)

        assert new_rid == RID(2, 0)
        assert heap.read(RID(1, 0)) == full_record
        assert heap.read(new_rid) == next_record
        assert heap.data_page_count == 2


def test_heap_insert_discards_stale_reference_outside_data_page_range(tmp_path):
    path = tmp_path / "stale-reference.db"
    schema = Schema([Column("id", DataType.INTEGER)])
    with HeapFile.create(path, schema) as heap:
        heap._free_space.register(Page(99))

        rid = heap.insert(Record(schema, [1]))

        assert rid == RID(1, 0)
        assert all(page_id != 99 for page_id, _ in heap.free_space_snapshot)


@pytest.mark.parametrize(
    ("active_count", "deleted_count", "message"),
    [(1, 0, "active-record"), (0, 1, "deleted-record")],
)
def test_heap_open_rejects_record_counters_that_disagree_with_pages(
    tmp_path, active_count, deleted_count, message
):
    path = tmp_path / "bad-count.db"
    metadata = OrganizationMetadata(
        OrganizationType.HEAP,
        _schema(),
        active_record_count=active_count,
        deleted_record_count=deleted_count,
        data_page_count=1,
    )
    with PageManager.create(path) as manager:
        manager.allocate_page()
        metadata_page = Page(0)
        metadata_page.insert(metadata.serialize())
        manager.write_page(metadata_page)
        manager.allocate_page()

    with pytest.raises(ValidationError, match=message):
        HeapFile.open(path)
