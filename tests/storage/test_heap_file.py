from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    SchemaError,
    ValidationError,
)
from engine.storage import (
    HeapFile,
    OrganizationMetadata,
    OrganizationType,
    Page,
    PageManager,
    Record,
    RecordCodec,
    RID,
    Storage,
)
from engine.storage.binary import MAX_RECORD_SIZE


@pytest.fixture
def schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("name", DataType.VARCHAR)]
    )


def _replace_metadata(path, metadata):
    with PageManager.open(path) as manager:
        page = manager.read_page(0)
        page.delete(0)
        page.compact()
        assert page.insert(metadata.serialize()) == 0
        manager.write_page(page)


def test_create_builds_an_empty_storage_with_persisted_metadata(tmp_path, schema):
    path = tmp_path / "heap.db"

    with HeapFile.create(path, schema) as heap:
        assert isinstance(heap, Storage)
        assert heap.schema == schema
        assert heap.metadata.organization_type is OrganizationType.HEAP
        assert heap.record_count == 0
        assert heap.deleted_record_count == 0
        assert heap.data_page_count == 0
        assert heap.allocated_page_count == 1
        assert heap.free_space_snapshot == ()
        assert heap.pages_read == 0
        assert heap.pages_written == 2
        assert heap.pages_allocated == 1

        first_scan = heap.scan()
        second_scan = heap.scan()
        assert first_scan is not second_scan
        assert list(first_scan) == []
        second_scan.close()

    with PageManager.open(path) as manager:
        metadata_page = manager.read_page(0)
        assert metadata_page.slot_count == 1
        assert metadata_page.active_record_count == 1
        assert OrganizationMetadata.deserialize(metadata_page.read(0)).schema == schema


def test_reopen_uses_persisted_schema_and_can_validate_external_schema(tmp_path, schema):
    path = tmp_path / "heap.db"
    HeapFile.create(path, schema).close()

    with HeapFile.open(path) as reopened:
        assert reopened.schema == schema
        assert reopened.pages_read == 1

    with HeapFile.open(path, schema) as checked:
        assert checked.schema == schema

    different = Schema([Column("other", DataType.INTEGER)])
    with pytest.raises(SchemaError, match="does not match"):
        HeapFile.open(path, different)


def test_create_is_exclusive_and_open_never_creates(tmp_path, schema):
    path = tmp_path / "heap.db"
    HeapFile.create(path, schema).close()

    with pytest.raises(FileExistsError):
        HeapFile.create(path, schema)
    with pytest.raises(FileNotFoundError):
        HeapFile.open(tmp_path / "missing.db")


def test_lifecycle_flush_close_context_and_post_close_behavior(tmp_path, schema):
    heap = HeapFile.create(tmp_path / "heap.db", schema)
    heap.flush()
    heap.reset_counters()
    assert (heap.pages_read, heap.pages_written, heap.pages_allocated) == (0, 0, 0)
    heap.close()
    heap.close()

    assert heap.closed
    for operation in (
        lambda: heap.schema,
        lambda: heap.metadata,
        lambda: heap.record_count,
        lambda: heap.free_space_snapshot,
        heap.flush,
        heap.reset_counters,
        heap.scan,
        lambda: heap.insert(Record(schema, [1, "a"])),
        lambda: heap.read(RID(1, 0)),
        lambda: heap.delete(RID(1, 0)),
        lambda: heap.__enter__(),
    ):
        with pytest.raises(RuntimeError, match="closed"):
            operation()


def test_context_closes_on_exception_without_suppressing_it(tmp_path, schema):
    heap = None
    with pytest.raises(LookupError, match="body"):
        with HeapFile.create(tmp_path / "heap.db", schema) as opened:
            heap = opened
            raise LookupError("body")
    assert heap.closed


def test_insert_returns_exact_rid_and_read_reconstructs_record(tmp_path, schema):
    with HeapFile.create(tmp_path / "heap.db", schema) as heap:
        equivalent_schema = Schema(list(schema.columns))
        record = Record(equivalent_schema, [1, "Ada 😀"])

        rid = heap.insert(record)

        assert rid == RID(1, 0)
        assert heap.read(rid) == record
        assert heap.read(rid) is not record
        assert heap.record_count == 1
        assert heap.deleted_record_count == 0
        assert heap.data_page_count == 1
        assert heap.allocated_page_count == 2


def test_insert_accepts_duplicate_and_variable_length_rows(tmp_path, schema):
    records = [
        Record(schema, [1, ""]),
        Record(schema, [1, "x"]),
        Record(schema, [1, "Unicode: áéí 😀"]),
        Record(schema, [1, "x"]),
    ]
    with HeapFile.create(tmp_path / "heap.db", schema) as heap:
        rids = [heap.insert(record) for record in records]

        assert len(set(rids)) == len(records)
        assert [heap.read(rid) for rid in rids] == records


def test_empty_schema_record_uses_a_real_reusable_slot(tmp_path):
    empty_schema = Schema([])
    empty_record = Record(empty_schema, [])
    with HeapFile.create(tmp_path / "empty-schema.db", empty_schema) as heap:
        first_rid = heap.insert(empty_record)
        assert first_rid == RID(1, 0)
        assert heap.read(first_rid) == empty_record

        heap.delete(first_rid)
        second_rid = heap.insert(Record(Schema([]), []))

        assert second_rid == first_rid
        assert heap.record_count == 1
        assert heap.deleted_record_count == 0


def test_insert_rejects_type_schema_and_codec_errors_without_mutation(tmp_path, schema):
    path = tmp_path / "heap.db"
    with HeapFile.create(path, schema) as heap:
        incompatible_schema = Schema(
            [Column("name", DataType.VARCHAR), Column("id", DataType.INTEGER)]
        )
        invalid_operations = (
            (InvalidTypeError, lambda: heap.insert([1, "Ada"])),
            (
                SchemaError,
                lambda: heap.insert(Record(incompatible_schema, ["Ada", 1])),
            ),
        )
        for error, operation in invalid_operations:
            with pytest.raises(error):
                operation()
        assert heap.record_count == 0
        assert heap.data_page_count == 0
        assert heap.allocated_page_count == 1

    integer_schema = Schema([Column("id", DataType.INTEGER)])
    with HeapFile.create(tmp_path / "integer.db", integer_schema) as heap:
        with pytest.raises(ValidationError):
            heap.insert(Record(integer_schema, [2**63]))
        assert heap.record_count == heap.data_page_count == 0


def test_maximum_payload_fits_and_oversized_payload_allocates_nothing(tmp_path):
    text_schema = Schema([Column("value", DataType.VARCHAR)])
    exact = Record(text_schema, ["x" * (MAX_RECORD_SIZE - 4)])
    oversized = Record(text_schema, ["x" * (MAX_RECORD_SIZE - 3)])

    with HeapFile.create(tmp_path / "exact.db", text_schema) as heap:
        assert len(RecordCodec.serialize(exact)) == MAX_RECORD_SIZE
        rid = heap.insert(exact)
        assert rid == RID(1, 0)
        assert heap.read(rid) == exact

    with HeapFile.create(tmp_path / "oversized.db", text_schema) as heap:
        with pytest.raises(ValidationError, match="exceeds page capacity"):
            heap.insert(oversized)
        assert heap.record_count == 0
        assert heap.data_page_count == 0
        assert heap.allocated_page_count == 1


def test_insert_allocates_multiple_pages_then_reuses_deleted_page(tmp_path):
    text_schema = Schema([Column("value", DataType.VARCHAR)])
    first = Record(text_schema, ["a" * 3000])
    second = Record(text_schema, ["b" * 3000])
    replacement = Record(text_schema, ["c" * 2800])

    with HeapFile.create(tmp_path / "heap.db", text_schema) as heap:
        first_rid = heap.insert(first)
        second_rid = heap.insert(second)
        assert (first_rid, second_rid) == (RID(1, 0), RID(2, 0))
        assert heap.data_page_count == 2

        heap.delete(first_rid)
        allocated_before_reuse = heap.allocated_page_count
        replacement_rid = heap.insert(replacement)

        assert replacement_rid == first_rid
        assert heap.allocated_page_count == allocated_before_reuse
        assert heap.read(replacement_rid) == replacement
        assert heap.read(second_rid) == second
        assert heap.record_count == 2
        assert heap.deleted_record_count == 0


def test_reuse_compacts_only_candidate_page_and_preserves_other_live_rids(tmp_path):
    text_schema = Schema([Column("value", DataType.VARCHAR)])
    rows = [Record(text_schema, [character * 1000]) for character in "abc"]
    replacement = Record(text_schema, ["z" * 1500])

    with HeapFile.create(tmp_path / "heap.db", text_schema) as heap:
        rids = [heap.insert(row) for row in rows]
        assert rids == [RID(1, 0), RID(1, 1), RID(1, 2)]
        heap.delete(rids[1])

        replacement_rid = heap.insert(replacement)

        assert replacement_rid == rids[1]
        assert heap.data_page_count == 1
        assert heap.read(rids[0]) == rows[0]
        assert heap.read(rids[2]) == rows[2]
        assert heap.read(replacement_rid) == replacement


def test_read_and_delete_distinguish_types_pages_slots_and_deleted_rids(
    tmp_path, schema
):
    with HeapFile.create(tmp_path / "heap.db", schema) as heap:
        rid = heap.insert(Record(schema, [1, "Ada"]))

        for operation in (heap.read, heap.delete):
            with pytest.raises(InvalidTypeError):
                operation((rid.page_id, rid.slot_id))
            with pytest.raises(InvalidReferenceError, match="not a Heap data page"):
                operation(RID(0, 0))
            with pytest.raises(InvalidReferenceError, match="not a Heap data page"):
                operation(RID(2, 0))
            with pytest.raises(InvalidReferenceError, match="Unknown slot_id"):
                operation(RID(1, 99))

        heap.delete(rid)
        writes_after_delete = heap.pages_written
        assert heap.record_count == 0
        assert heap.deleted_record_count == 1
        for operation in (heap.read, heap.delete):
            with pytest.raises(InvalidReferenceError, match="free/deleted"):
                operation(rid)
        assert heap.pages_written == writes_after_delete
        assert heap.record_count == 0
        assert heap.deleted_record_count == 1


def test_read_and_scan_reject_malformed_active_record_payload(tmp_path):
    path = tmp_path / "malformed-record.db"
    integer_schema = Schema([Column("id", DataType.INTEGER)])
    HeapFile.create(path, integer_schema).close()
    with PageManager.open(path) as manager:
        assert manager.allocate_page() == 1
        malformed = manager.read_page(1)
        assert malformed.insert(b"\x01") == 0
        manager.write_page(malformed)
    _replace_metadata(
        path,
        OrganizationMetadata(
            OrganizationType.HEAP,
            integer_schema,
            active_record_count=1,
            data_page_count=1,
        ),
    )

    with HeapFile.open(path, integer_schema) as heap:
        with pytest.raises(ValidationError):
            heap.read(RID(1, 0))
        with pytest.raises(ValidationError):
            list(heap.scan())


def test_scan_streams_each_active_pair_once_in_physical_order(tmp_path, schema):
    records = [Record(schema, [number, chr(65 + number) * 2000]) for number in range(5)]
    with HeapFile.create(tmp_path / "heap.db", schema) as heap:
        rids = [heap.insert(record) for record in records]
        heap.delete(rids[1])
        expected = [(rid, record) for rid, record in zip(rids, records) if rid != rids[1]]

        heap.reset_counters()
        rows = heap.scan()
        assert heap.pages_read == 0
        first = next(rows)
        assert heap.pages_read == 1
        result = [first, *rows]

        assert result == expected
        assert [rid for rid, _ in result] == sorted(rid for rid, _ in result)
        assert len({rid for rid, _ in result}) == len(result)
        assert heap.pages_read == heap.data_page_count


def test_closing_scan_early_does_not_close_heap_or_read_remaining_pages(
    tmp_path, schema
):
    with HeapFile.create(tmp_path / "heap.db", schema) as heap:
        for number in range(3):
            heap.insert(Record(schema, [number, "x" * 3000]))
        heap.reset_counters()

        with closing(heap.scan()) as rows:
            assert next(rows)[0] == RID(1, 0)
        assert heap.pages_read == 1
        assert not heap.closed
        assert heap.read(RID(3, 0)).values[0] == 2


def test_scan_created_before_heap_close_fails_when_consumed(tmp_path, schema):
    heap = HeapFile.create(tmp_path / "heap.db", schema)
    rows = heap.scan()
    heap.close()

    with pytest.raises(RuntimeError, match="closed"):
        next(rows)


def test_create_requires_schema(tmp_path):
    with pytest.raises(InvalidTypeError):
        HeapFile.create(tmp_path / "heap.db", [])


def test_oversized_metadata_is_rejected_before_a_file_is_created(tmp_path):
    path = tmp_path / "heap.db"
    oversized_schema = Schema(
        [Column(f"column_{position:04d}_with_a_long_name", DataType.VARCHAR)
         for position in range(180)]
    )

    with pytest.raises(ValidationError, match="does not fit"):
        HeapFile.create(path, oversized_schema)

    assert not path.exists()


def test_open_rejects_a_different_organization(tmp_path, schema):
    path = tmp_path / "heap.db"
    HeapFile.create(path, schema).close()
    sequential = OrganizationMetadata(
        OrganizationType.PAGED_SEQUENTIAL,
        schema,
        key_column="id",
        allow_duplicate_keys=True,
        reorganization_threshold=0.30,
    )
    _replace_metadata(path, sequential)

    with pytest.raises(ValidationError, match="Expected 'heap'"):
        HeapFile.open(path)


def test_open_rejects_physical_page_count_not_declared_by_metadata(tmp_path, schema):
    path = tmp_path / "heap.db"
    HeapFile.create(path, schema).close()
    with PageManager.open(path) as manager:
        assert manager.allocate_page() == 1

    with pytest.raises(ValidationError, match="page count"):
        HeapFile.open(path)


def test_open_rejects_invalid_metadata_page_layout(tmp_path):
    path = tmp_path / "bad-layout.db"
    with PageManager.create(path) as manager:
        manager.allocate_page()

    with pytest.raises(ValidationError, match="layout"):
        HeapFile.open(path)
