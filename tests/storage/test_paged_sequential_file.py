from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import DuplicateError, InvalidTypeError, SchemaError, ValidationError
from engine.storage import (
    HeapFile,
    OrganizationMetadata,
    OrganizationType,
    Page,
    PageManager,
    PagedSequentialFile,
    Record,
    RecordCodec,
    RID,
    Storage,
)
from engine.storage.binary import MAX_RECORD_SIZE


@pytest.fixture
def schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )


def _row(schema, key, label, length=0):
    return Record(schema, [key, label if not length else label * length])


def _create_sequential_fixture(path, schema, pages):
    metadata = OrganizationMetadata(
        OrganizationType.PAGED_SEQUENTIAL,
        schema,
        active_record_count=sum(page.active_record_count for page in pages),
        deleted_record_count=sum(
            page.slot_count - page.active_record_count for page in pages
        ),
        data_page_count=len(pages),
        key_column="id",
        allow_duplicate_keys=True,
        reorganization_threshold=0.30,
    )
    with PageManager.create(path) as manager:
        assert manager.allocate_page() == 0
        metadata_page = Page(0)
        metadata_page.insert(metadata.serialize())
        manager.write_page(metadata_page)
        for page in pages:
            assert manager.allocate_page() == page.page_id
            manager.write_page(page)


def test_create_open_and_empty_operations_persist_key_metadata(tmp_path, schema):
    path = tmp_path / "ordered.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        assert isinstance(sequential, Storage)
        assert sequential.key_column == "id"
        assert sequential.key_type is DataType.INTEGER
        assert sequential.allow_duplicate_keys is True
        assert sequential.reorganization_threshold == 0.30
        assert sequential.record_count == 0
        assert sequential.data_page_count == 0
        assert sequential.allocated_page_count == 1
        assert list(sequential.scan()) == []
        assert list(sequential.search(1)) == []

    with PagedSequentialFile.open(path, Schema(list(schema.columns)), "id") as reopened:
        assert reopened.schema == schema
        assert reopened.metadata.organization_type is OrganizationType.PAGED_SEQUENTIAL
        assert reopened.key_column == "id"
        assert list(reopened.scan()) == []


def test_lifecycle_rejects_incompatible_schema_key_organization_and_closed_use(
    tmp_path, schema
):
    path = tmp_path / "ordered.db"
    PagedSequentialFile.create(path, schema, "id").close()

    incompatible = Schema([Column("id", DataType.FLOAT)])
    with pytest.raises(SchemaError, match="does not match"):
        PagedSequentialFile.open(path, incompatible)
    with pytest.raises(SchemaError, match="Provided key"):
        PagedSequentialFile.open(path, schema, "payload")
    with pytest.raises(InvalidTypeError):
        PagedSequentialFile.open(path, schema, 0)

    heap_path = tmp_path / "heap.db"
    HeapFile.create(heap_path, schema).close()
    with pytest.raises(ValidationError, match="paged_sequential"):
        PagedSequentialFile.open(heap_path)

    sequential = PagedSequentialFile.open(path)
    sequential.close()
    sequential.close()
    for operation in (
        lambda: sequential.key_column,
        sequential.scan,
        lambda: sequential.search(1),
        lambda: sequential.insert(_row(schema, 1, "a")),
        lambda: sequential.read(RID(1, 0)),
        lambda: sequential.delete(RID(1, 0)),
        sequential.wasted_space_ratio,
        sequential.should_reorganize,
        sequential.reorganize,
    ):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


def test_create_validates_key_and_options_before_creating_file(tmp_path, schema):
    cases = [
        ("missing", True, 0.30, SchemaError),
        ("id", 1, 0.30, InvalidTypeError),
        ("id", True, 0.0, ValidationError),
        ("id", True, 1, InvalidTypeError),
    ]
    for position, (key, duplicates, threshold, error) in enumerate(cases):
        path = tmp_path / f"invalid-{position}.db"
        with pytest.raises(error):
            PagedSequentialFile.create(
                path,
                schema,
                key,
                allow_duplicate_keys=duplicates,
                reorganization_threshold=threshold,
            )
        assert not path.exists()


def test_unsorted_insertions_produce_stable_order_and_exact_searches(tmp_path, schema):
    supplied = [
        _row(schema, 5, "last"),
        _row(schema, 1, "first"),
        _row(schema, 3, "equal-a"),
        _row(schema, 3, "equal-b"),
        _row(schema, 2, "middle"),
    ]
    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        for record in supplied:
            rid = sequential.insert(record)
            assert sequential.read(rid) == record

        scanned = list(sequential.scan())
        assert [record.values[0] for _, record in scanned] == [1, 2, 3, 3, 5]
        assert [
            record.values[1] for _, record in scanned if record.values[0] == 3
        ] == ["equal-a", "equal-b"]

        for key, expected_labels in (
            (1, ["first"]),
            (2, ["middle"]),
            (3, ["equal-a", "equal-b"]),
            (5, ["last"]),
            (4, []),
        ):
            matches = list(sequential.search(key))
            assert [record.values[1] for _, record in matches] == expected_labels
        assert sequential.record_count == len(supplied)
        assert sequential.data_page_count == 1


def test_duplicate_rejection_does_not_mutate_file(tmp_path, schema):
    path = tmp_path / "unique.db"
    with PagedSequentialFile.create(
        path,
        schema,
        "id",
        allow_duplicate_keys=False,
    ) as sequential:
        first = _row(schema, 1, "first")
        rid = sequential.insert(first)
        counters = (
            sequential.record_count,
            sequential.data_page_count,
            sequential.pages_written,
        )
        with pytest.raises(DuplicateError, match="Duplicate sequential key"):
            sequential.insert(_row(schema, 1, "second"))
        assert (
            sequential.record_count,
            sequential.data_page_count,
            sequential.pages_written,
        ) == counters
        assert list(sequential.scan()) == [(rid, first)]


def test_duplicate_stability_is_preserved_across_page_boundaries(tmp_path, schema):
    path = tmp_path / "duplicate-pages.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        for label in ("A", "B"):
            sequential.insert(_row(schema, 3, label, length=3000))
        sequential.insert(_row(schema, 5, "Z", length=3000))

        sequential.insert(_row(schema, 3, "C", length=3000))

        matches = list(sequential.search(3))
        assert [record.values[1][0] for _, record in matches] == ["A", "B", "C"]
        assert [record.values[0] for _, record in sequential.scan()] == [3, 3, 3, 5]


def test_insert_rejects_non_record_wrong_schema_and_codec_error_without_writes(
    tmp_path, schema
):
    path = tmp_path / "validation.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        before = (
            sequential.record_count,
            sequential.data_page_count,
            sequential.pages_written,
        )
        with pytest.raises(InvalidTypeError):
            sequential.insert([1, "row"])
        incompatible = Schema(
            [Column("payload", DataType.VARCHAR), Column("id", DataType.INTEGER)]
        )
        with pytest.raises(SchemaError):
            sequential.insert(Record(incompatible, ["row", 1]))
        assert (
            sequential.record_count,
            sequential.data_page_count,
            sequential.pages_written,
        ) == before

    integer_schema = Schema([Column("id", DataType.INTEGER)])
    with PagedSequentialFile.create(
        tmp_path / "codec-error.db", integer_schema, "id"
    ) as sequential:
        with pytest.raises(ValidationError):
            sequential.insert(Record(integer_schema, [2**63]))
        assert sequential.record_count == sequential.data_page_count == 0


def test_insert_splits_target_and_shifts_later_pages(tmp_path, schema):
    path = tmp_path / "split.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        for key in (10, 20, 30):
            sequential.insert(_row(schema, key, chr(64 + key // 10), length=3000))
        assert sequential.data_page_count == 3

        inserted = _row(schema, 15, "X", length=3000)
        inserted_rid = sequential.insert(inserted)

        assert inserted_rid == RID(2, 0)
        assert sequential.data_page_count == 4
        assert [record.values[0] for _, record in sequential.scan()] == [10, 15, 20, 30]
        assert list(sequential.search(15)) == [(inserted_rid, inserted)]
        assert list(sequential.search(30))[0][0] == RID(4, 0)


def test_large_middle_record_can_split_one_target_into_three_pages(tmp_path, schema):
    path = tmp_path / "three-way.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        sequential.insert(_row(schema, 10, "A", length=1900))
        sequential.insert(_row(schema, 30, "C", length=1900))
        assert sequential.data_page_count == 1

        middle = _row(schema, 20, "B", length=MAX_RECORD_SIZE - 12)
        rid = sequential.insert(middle)

        assert rid == RID(2, 0)
        assert sequential.data_page_count == 3
        assert [record.values[0] for _, record in sequential.scan()] == [10, 20, 30]


def test_maximum_record_fits_and_oversized_record_changes_nothing(tmp_path, schema):
    exact = _row(schema, 1, "X", length=MAX_RECORD_SIZE - 12)
    oversized = _row(schema, 2, "Y", length=MAX_RECORD_SIZE - 11)
    assert len(RecordCodec.serialize(exact)) == MAX_RECORD_SIZE

    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        assert sequential.insert(exact) == RID(1, 0)
        before = (
            sequential.record_count,
            sequential.data_page_count,
            sequential.allocated_page_count,
        )
        with pytest.raises(ValidationError, match="exceeds page capacity"):
            sequential.insert(oversized)
        assert (
            sequential.record_count,
            sequential.data_page_count,
            sequential.allocated_page_count,
        ) == before


def test_scan_is_page_lazy_and_closing_early_keeps_file_open(tmp_path, schema):
    with PagedSequentialFile.create(tmp_path / "ordered.db", schema, "id") as sequential:
        for key in (1, 2, 3):
            sequential.insert(_row(schema, key, "X", length=3000))
        sequential.reset_counters()

        rows = sequential.scan()
        assert sequential.pages_read == 0
        with closing(rows):
            assert next(rows)[1].values[0] == 1
        assert sequential.pages_read == 1
        assert not sequential.closed


def test_scan_and_search_skip_free_slots_in_ordered_fixture(tmp_path, schema):
    page_one = Page(1)
    removed = page_one.insert(RecordCodec.serialize(_row(schema, 1, "removed")))
    page_one.insert(RecordCodec.serialize(_row(schema, 2, "active")))
    page_one.delete(removed)
    page_two = Page(2)
    page_two.insert(RecordCodec.serialize(_row(schema, 3, "last")))
    path = tmp_path / "deleted-fixture.db"
    _create_sequential_fixture(path, schema, [page_one, page_two])

    with PagedSequentialFile.open(path, schema, "id") as sequential:
        assert [record.values[0] for _, record in sequential.scan()] == [2, 3]
        assert list(sequential.search(1)) == []
        assert [record.values[0] for _, record in sequential.search(2)] == [2]


def test_scan_rejects_physically_unordered_pages(tmp_path, schema):
    page = Page(1)
    page.insert(RecordCodec.serialize(_row(schema, 2, "later")))
    page.insert(RecordCodec.serialize(_row(schema, 1, "earlier")))
    path = tmp_path / "unordered.db"
    _create_sequential_fixture(path, schema, [page])

    with PagedSequentialFile.open(path, schema, "id") as sequential:
        with pytest.raises(ValidationError, match="not ordered"):
            list(sequential.scan())


def test_search_validates_exact_key_type_and_nan(tmp_path):
    integer_schema = Schema([Column("id", DataType.INTEGER)])
    with PagedSequentialFile.create(
        tmp_path / "integer.db", integer_schema, "id"
    ) as sequential:
        with pytest.raises(InvalidTypeError):
            sequential.search(True)

    float_schema = Schema([Column("key", DataType.FLOAT)])
    with PagedSequentialFile.create(
        tmp_path / "float.db", float_schema, "key"
    ) as sequential:
        sequential.insert(Record(float_schema, [float("-inf")]))
        sequential.insert(Record(float_schema, [float("inf")]))
        with pytest.raises(ValidationError, match="NaN"):
            sequential.insert(Record(float_schema, [float("nan")]))
        with pytest.raises(ValidationError, match="NaN"):
            sequential.search(float("nan"))
        assert [record.values[0] for _, record in sequential.scan()] == [
            float("-inf"),
            float("inf"),
        ]


def test_order_and_search_survive_fresh_reopen(tmp_path, schema):
    path = tmp_path / "restart.db"
    with PagedSequentialFile.create(path, schema, "id") as writer:
        for key in (9, 1, 5, 5, 3):
            writer.insert(_row(schema, key, f"row-{key}"))

    fresh_schema = Schema(list(schema.columns))
    with PagedSequentialFile.open(path, fresh_schema, "id") as reader:
        assert [record.values[0] for _, record in reader.scan()] == [1, 3, 5, 5, 9]
        assert len(list(reader.search(5))) == 2


def test_insertion_after_tombstone_preserves_pending_waste(tmp_path, schema):
    path = tmp_path / "ordered.db"
    removed = _row(schema, 2, "removed")
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        sequential.insert(_row(schema, 1, "first"))
        removed_rid = sequential.insert(removed)
        sequential.insert(_row(schema, 3, "last"))
        sequential.delete(removed_rid)
        waste_before = sequential.wasted_space_ratio()

        inserted = _row(schema, 2, "replacement")
        inserted_rid = sequential.insert(inserted)

        assert sequential.read(inserted_rid) == inserted
        assert sequential.deleted_record_count == 1
        assert sequential.wasted_space_ratio() == waste_before
        assert [record.values[0] for _, record in sequential.scan()] == [1, 2, 3]

    with PagedSequentialFile.open(path, schema, "id") as reopened:
        assert reopened.deleted_record_count == 1
        assert reopened.wasted_space_ratio() == waste_before
