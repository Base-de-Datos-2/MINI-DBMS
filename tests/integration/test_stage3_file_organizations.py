from collections import Counter

from engine.catalog import Column, DataType, Schema
from engine.storage import (
    HeapFile,
    OrganizationType,
    PagedSequentialFile,
    Record,
    ReorganizationMetrics,
)


def _schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )


def _row(schema, key, label, length):
    return Record(schema, [key, label * length])


def _logical_rows(storage):
    return Counter(record.values for _, record in storage.scan())


def test_stage3_heap_end_to_end(tmp_path):
    path = tmp_path / "heap.db"
    schema = _schema()
    rows = [
        _row(schema, 7, "G", 3000),
        _row(schema, 2, "B", 3000),
        _row(schema, 9, "I", 3000),
    ]
    with HeapFile.create(path, schema) as heap:
        rids = [heap.insert(record) for record in rows]
        assert heap.data_page_count == 3
        heap.delete(rids[1])
        replacement = _row(schema, 5, "E", 2500)
        replacement_rid = heap.insert(replacement)
        assert replacement_rid == rids[1]
        expected = Counter((rows[0].values, replacement.values, rows[2].values))

    fresh_schema = _schema()
    with HeapFile.open(path, fresh_schema) as reopened:
        assert reopened.metadata.organization_type is OrganizationType.HEAP
        assert _logical_rows(reopened) == expected
        assert reopened.read(replacement_rid).values == replacement.values


def test_stage3_sequential_end_to_end(tmp_path):
    path = tmp_path / "sequential.db"
    schema = _schema()
    rows = [
        _row(schema, 8, "H", 3000),
        _row(schema, 3, "C", 3000),
        _row(schema, 5, "E", 3000),
        _row(schema, 3, "D", 3000),
        _row(schema, 1, "A", 3000),
    ]
    with PagedSequentialFile.create(
        path,
        schema,
        "id",
        reorganization_threshold=0.001,
    ) as sequential:
        for record in rows:
            sequential.insert(record)
        sequential.delete(list(sequential.search(8))[0][0])
        assert sequential.wasted_space_ratio() > 0.0
        assert sequential.should_reorganize()
        assert [record.values[0] for _, record in sequential.scan()] == [1, 3, 3, 5]

        metrics = sequential.reorganize()

        assert isinstance(metrics, ReorganizationMetrics)
        assert sequential.deleted_record_count == 0
        assert sequential.wasted_space_ratio() == 0.0

    fresh_schema = _schema()
    with PagedSequentialFile.open(path, fresh_schema, "id") as reopened:
        assert (
            reopened.metadata.organization_type
            is OrganizationType.PAGED_SEQUENTIAL
        )
        assert [record.values[0] for _, record in reopened.scan()] == [1, 3, 3, 5]
        assert [record.values[1][0] for _, record in reopened.search(3)] == [
            "C",
            "D",
        ]


def test_same_dataset_is_logically_equivalent_but_physically_independent(tmp_path):
    heap_path = tmp_path / "heap.db"
    sequential_path = tmp_path / "sequential.db"
    schema = _schema()
    initial = [
        _row(schema, 4, "D", 40),
        _row(schema, 1, "A", 40),
        _row(schema, 3, "C", 40),
        _row(schema, 2, "B", 40),
        _row(schema, 3, "E", 40),
    ]
    replacement = _row(schema, 5, "F", 40)
    extra = _row(schema, 6, "G", 40)

    with (
        HeapFile.create(heap_path, schema) as heap,
        PagedSequentialFile.create(sequential_path, schema, "id") as sequential,
    ):
        heap_rids = [heap.insert(record) for record in initial]
        for record in initial:
            sequential.insert(record)
        heap.delete(heap_rids[0])
        sequential.delete(list(sequential.search(4))[0][0])
        heap.insert(replacement)
        sequential.insert(replacement)

        assert _logical_rows(heap) == _logical_rows(sequential)
        assert [record.values[0] for _, record in heap.scan()] == [5, 1, 3, 2, 3]
        assert [record.values[0] for _, record in sequential.scan()] == [1, 2, 3, 3, 5]

        heap.flush()
        sequential.flush()
        sequential_bytes = sequential_path.read_bytes()
        heap.insert(extra)
        heap.flush()
        assert sequential_path.read_bytes() == sequential_bytes
        sequential.insert(extra)
        assert _logical_rows(heap) == _logical_rows(sequential)
        expected = _logical_rows(heap)

    with (
        HeapFile.open(heap_path, _schema()) as reopened_heap,
        PagedSequentialFile.open(sequential_path, _schema(), "id") as reopened_sequential,
    ):
        assert _logical_rows(reopened_heap) == expected
        assert _logical_rows(reopened_sequential) == expected
        assert reopened_heap.file_size == heap_path.stat().st_size
        assert reopened_sequential.file_size == sequential_path.stat().st_size
