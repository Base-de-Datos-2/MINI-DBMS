"""Tasks 6.7 and 6.8: storage scans and bound index access paths."""

from contextlib import closing

import pytest

from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    ValidationError,
)
from engine.indexes import (
    ClusteredBPlusIndex,
    UnclusteredBPlusIndex,
    UnclusteredHashIndex,
)
from engine.operators import (
    ColumnReference,
    Compare,
    ComparisonOperator,
    EqualitySearch,
    Filter,
    IndexScan,
    RangeSearch,
    RowProvenance,
    TableScan,
    collect,
    column,
    execute,
)
from engine.storage import HeapFile, PagedSequentialFile, Record, RID
from tests.operator_helpers import STUDENTS, STUDENT_ROWS, students


@pytest.fixture
def heap(tmp_path):
    with HeapFile.create(tmp_path / "students.heap", STUDENTS) as storage:
        for record in students():
            storage.insert(record)
        yield storage


@pytest.fixture
def sequential(tmp_path):
    with PagedSequentialFile.create(
        tmp_path / "students.seq", STUDENTS, "id"
    ) as storage:
        for record in students(reversed(STUDENT_ROWS)):
            storage.insert(record)
        yield storage


@pytest.fixture
def bplus(tmp_path, heap):
    with UnclusteredBPlusIndex.build(
        tmp_path / "students-id.bpt",
        heap=heap,
        index_name="ix_students_id",
        table_name="students",
        key_column="id",
    ) as index:
        yield index


@pytest.fixture
def hash_index(tmp_path, heap):
    with UnclusteredHashIndex.build(
        tmp_path / "students-id.hsh",
        heap=heap,
        index_name="hx_students_id",
        table_name="students",
        key_column="id",
    ) as index:
        yield index


@pytest.fixture
def clustered(tmp_path, sequential):
    with ClusteredBPlusIndex.build(
        tmp_path / "students-clustered.bpt",
        sequential=sequential,
        index_name="cx_students_id",
        table_name="students",
        key_column="id",
    ) as index:
        yield index


def values(rows):
    return [tuple(row.values) for row in rows]


def test_table_scan_streams_every_live_row_exactly_once(heap):
    scan = TableScan(heap, relation="students")

    rows = collect(scan, limit=10)

    assert sorted(values(rows)) == sorted(STUDENT_ROWS)
    assert scan.statistics.rows_examined == 4
    assert scan.statistics.rows_emitted == 4
    assert scan.storage is heap
    assert scan.relation == "students"


def test_table_scan_of_an_empty_table_yields_nothing(tmp_path):
    with HeapFile.create(tmp_path / "empty.heap", STUDENTS) as storage:
        assert collect(TableScan(storage, relation="students"), limit=5) == ()


def test_table_scan_of_a_single_row_table_yields_that_row(tmp_path):
    with HeapFile.create(tmp_path / "one.heap", STUDENTS) as storage:
        storage.insert(Record(STUDENTS, [1, "Ana", "CS", 22]))

        rows = collect(TableScan(storage, relation="students"), limit=5)

    assert values(rows) == [(1, "Ana", "CS", 22)]


def test_table_scan_spans_multiple_pages(tmp_path):
    payload = [(number, f"name-{number}", "CS", 20) for number in range(300)]
    with HeapFile.create(tmp_path / "many.heap", STUDENTS) as storage:
        for record in students(payload):
            storage.insert(record)
        assert storage.data_page_count > 1

        rows = collect(TableScan(storage, relation="students"), limit=400)

    assert sorted(values(rows)) == sorted(payload)


def test_table_scan_skips_deleted_rows_and_sees_reused_slots(heap):
    scan_before = collect(TableScan(heap, relation="students"), limit=10)
    with closing(heap.scan()) as cursor:
        target = next(rid for rid, record in cursor if record["name"] == "Luis")
    heap.delete(target)

    after_delete = collect(TableScan(heap, relation="students"), limit=10)
    heap.insert(Record(STUDENTS, [9, "Nia", "CS", 21]))
    after_reuse = collect(TableScan(heap, relation="students"), limit=10)

    assert len(scan_before) == 4
    assert len(after_delete) == 3
    assert (2, "Luis", "EE", 19) not in values(after_delete)
    assert (9, "Nia", "CS", 21) in values(after_reuse)
    assert len(after_reuse) == 4


def test_table_scan_reports_provenance_for_the_row_just_returned(heap):
    scan = TableScan(heap, relation="students")
    scan.open()
    try:
        assert scan.provenance == ()
        row = scan.next()
        (origin,) = scan.provenance

        assert isinstance(origin, RowProvenance)
        assert origin.relation == "students"
        assert heap.read(origin.rid) == row

        while scan.next() is not None:
            pass
        assert scan.provenance == ()
    finally:
        scan.close()


def test_table_scan_closes_its_cursor_without_closing_borrowed_storage(heap):
    scan = TableScan(heap, relation="students")

    with closing(execute(scan)) as stream:
        assert next(stream) is not None

    assert heap.closed is False
    assert collect(TableScan(heap, relation="students"), limit=10) != ()


def test_two_interleaved_table_scans_keep_independent_cursors(heap):
    first = TableScan(heap, relation="students")
    second = TableScan(heap, relation="students")

    first.open()
    second.open()
    try:
        first_rows = [first.next(), first.next()]
        second_rows = [second.next()]
        first_rows.append(first.next())
        second_rows.extend([second.next(), second.next(), second.next()])

        assert values(first_rows) == values(second_rows[:3])
        assert second.next() is None
    finally:
        first.close()
        second.close()


def test_heap_scan_advertises_no_ordering_while_sequential_advertises_its_key(
    heap, sequential
):
    heap_scan = TableScan(heap, relation="students")
    sequential_scan = TableScan(sequential, relation="students")

    assert heap_scan.ordering is None
    assert heap_scan.ordered is False
    assert sequential_scan.ordering == ColumnReference("id", "students")
    assert sequential_scan.ordered is True

    rows = collect(sequential_scan, limit=10)
    assert [row.values[0] for row in rows] == sorted(row[0] for row in STUDENT_ROWS)


def test_table_scan_validates_its_arguments(heap):
    with pytest.raises(InvalidTypeError, match="requires a Storage"):
        TableScan(object(), relation="students")

    scan = TableScan(heap, relation="students")
    assert scan.layout.schema is heap.schema
    assert scan.layout.relations == ("students",)


def test_table_scan_rejects_a_blank_relation_name(heap):
    with pytest.raises(ValidationError):
        TableScan(heap, relation="  ")
    with pytest.raises(InvalidTypeError):
        TableScan(heap, relation=None)


def test_index_scan_equality_returns_the_matching_rows(bplus, hash_index):
    for index in (bplus, hash_index):
        scan = IndexScan.equality(index, 3, relation="students")

        assert values(collect(scan, limit=5)) == [(3, "Sol", "CS", 24)]
        assert scan.statistics.rows_examined == 1


def test_index_scan_on_a_missing_key_returns_nothing(bplus, hash_index):
    for index in (bplus, hash_index):
        assert collect(IndexScan.equality(index, 99, relation="s"), limit=5) == ()


def test_index_scan_over_an_empty_index_returns_nothing(tmp_path):
    with HeapFile.create(tmp_path / "empty.heap", STUDENTS) as storage:
        with UnclusteredBPlusIndex.build(
            tmp_path / "empty.bpt",
            heap=storage,
            index_name="ix_empty",
            table_name="students",
            key_column="id",
        ) as index:
            assert collect(IndexScan.equality(index, 1, relation="s"), limit=5) == ()
            assert collect(IndexScan.between(index, relation="s"), limit=5) == ()


def test_index_scan_preserves_every_occurrence_of_a_duplicate_key(tmp_path):
    payload = [(7, f"name-{number}", "CS", 20) for number in range(200)]
    with HeapFile.create(tmp_path / "dup.heap", STUDENTS) as storage:
        for record in students(payload):
            storage.insert(record)
        assert storage.data_page_count > 1

        with UnclusteredBPlusIndex.build(
            tmp_path / "dup.bpt",
            heap=storage,
            index_name="ix_dup",
            table_name="students",
            key_column="id",
        ) as index:
            rows = collect(IndexScan.equality(index, 7, relation="s"), limit=250)

    assert len(rows) == 200
    assert sorted(values(rows)) == sorted(payload)


def test_index_scan_ranges_honour_inclusive_and_exclusive_bounds(bplus):
    def ids(**bounds):
        scan = IndexScan.between(bplus, relation="students", **bounds)
        return [row.values[0] for row in collect(scan, limit=10)]

    assert ids(lower=2, upper=3) == [2, 3]
    assert ids(lower=2, upper=3, include_lower=False) == [3]
    assert ids(lower=2, upper=3, include_upper=False) == [2]
    assert ids(lower=2, upper=2, include_lower=False, include_upper=False) == []
    assert ids(lower=2) == [2, 3, 4]
    assert ids(upper=2) == [1, 2]
    assert ids() == [1, 2, 3, 4]


def test_index_scan_rejects_an_inverted_range(bplus):
    with pytest.raises(ValidationError):
        collect(IndexScan.between(bplus, 4, 1, relation="students"), limit=5)


def test_a_range_over_a_hash_index_is_refused_rather_than_faked(hash_index):
    with pytest.raises(ValidationError, match="equality access only"):
        IndexScan.between(hash_index, 1, 3, relation="students")
    with pytest.raises(ValidationError, match="equality access only"):
        IndexScan(hash_index, RangeSearch(), relation="students")


def test_a_hash_index_scan_advertises_no_ordering(hash_index, bplus):
    hash_scan = IndexScan.equality(hash_index, 3, relation="students")
    range_scan = IndexScan.between(bplus, relation="students")

    assert hash_scan.ordering is None
    assert hash_scan.ordered is False
    assert range_scan.ordering == ColumnReference("id", "students")
    assert dict(hash_scan.describe().details)["access"] == "hash equality"
    assert dict(range_scan.describe().details)["access"] == "b+ range"


def test_every_compatible_access_path_agrees_with_a_filtered_scan(
    heap, bplus, hash_index, clustered
):
    predicate = Compare(column("id"), ComparisonOperator.EQUAL, 3)
    expected = values(
        collect(Filter(TableScan(heap, relation="students"), predicate), limit=5)
    )

    assert expected == [(3, "Sol", "CS", 24)]
    for index in (bplus, hash_index, clustered):
        scan = IndexScan.equality(index, 3, relation="students")
        assert values(collect(scan, limit=5)) == expected


def test_a_clustered_range_scan_returns_rows_in_key_order(clustered):
    scan = IndexScan.between(clustered, 2, 4, relation="students")

    rows = collect(scan, limit=10)

    assert [row.values[0] for row in rows] == [2, 3, 4]
    assert scan.ordering == ColumnReference("id", "students")


def test_a_stale_association_is_reported_instead_of_returning_another_row(
    heap, bplus
):
    with closing(heap.scan()) as cursor:
        target = next(rid for rid, record in cursor if record["id"] == 3)
    heap.delete(target)

    with pytest.raises(InvalidReferenceError):
        collect(IndexScan.equality(bplus, 3, relation="students"), limit=5)


def test_index_scans_work_over_reopened_storage_and_indexes(tmp_path):
    heap_path = tmp_path / "reopen.heap"
    index_path = tmp_path / "reopen.bpt"
    with HeapFile.create(heap_path, STUDENTS) as storage:
        for record in students():
            storage.insert(record)
        with UnclusteredBPlusIndex.build(
            index_path,
            heap=storage,
            index_name="ix_reopen",
            table_name="students",
            key_column="id",
        ):
            pass

    with HeapFile.open(heap_path, STUDENTS) as storage:
        with UnclusteredBPlusIndex.open(index_path, heap=storage) as index:
            equality = collect(IndexScan.equality(index, 4, relation="s"), limit=5)
            traversal = collect(IndexScan.between(index, relation="s"), limit=10)
            scanned = collect(TableScan(storage, relation="s"), limit=10)

    assert values(equality) == [(4, "Omar", "EE", 23)]
    assert [row.values[0] for row in traversal] == [1, 2, 3, 4]
    assert sorted(values(scanned)) == sorted(STUDENT_ROWS)


def test_index_scan_closes_its_cursor_without_closing_the_borrowed_index(bplus):
    scan = IndexScan.between(bplus, relation="students")

    with closing(execute(scan)) as stream:
        assert next(stream) is not None

    assert bplus.closed is False
    assert len(collect(IndexScan.between(bplus, relation="students"), limit=10)) == 4


def test_index_scan_validates_its_index_search_and_relation(bplus, heap):
    with pytest.raises(InvalidTypeError, match="requires an Index"):
        IndexScan(object(), EqualitySearch(1), relation="students")
    with pytest.raises(InvalidTypeError, match="EqualitySearch or a RangeSearch"):
        IndexScan(bplus, 3, relation="students")
    with pytest.raises(ValidationError):
        IndexScan.equality(bplus, 3, relation=" ")
    with pytest.raises(InvalidTypeError):
        RangeSearch(1, 2, include_lower="yes")


def test_index_scan_requires_an_adapter_bound_to_storage(tmp_path, heap):
    from engine.indexes import BPlusTree
    from engine.catalog import DataType

    with BPlusTree.create(
        tmp_path / "bare.bpt",
        index_name="ix_bare",
        table_name="students",
        key_column="id",
        key_type=DataType.INTEGER,
    ) as tree:
        tree.insert(1, RID(1, 0))

        with pytest.raises(ValidationError, match="bound to its storage"):
            IndexScan.equality(tree, 1, relation="students")


def test_index_scan_exposes_its_bound_search_and_index(bplus):
    scan = IndexScan(bplus, EqualitySearch(2), relation="students")

    assert scan.index is bplus
    assert scan.search == EqualitySearch(2)
    assert scan.relation == "students"
    assert dict(scan.describe().details)["key"] == "2"
