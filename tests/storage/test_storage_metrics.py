from dataclasses import FrozenInstanceError, replace
import math
from time import perf_counter

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InvalidTypeError, ValidationError
from engine.storage import (
    HeapFile,
    PagedSequentialFile,
    Record,
    ReorganizationMetrics,
)
from engine.storage.binary import FILE_HEADER_SIZE, PAGE_SIZE


def _schema():
    return Schema(
        [Column("id", DataType.INTEGER), Column("payload", DataType.VARCHAR)]
    )


def _row(schema, key, length=20):
    return Record(schema, [key, chr(64 + key) * length])


def test_metrics_are_immutable_validated_measurements():
    metrics = ReorganizationMetrics(0.25, 3, 4, 2, 20_500, 12_308)

    assert metrics.bytes_reclaimed == 8192
    with pytest.raises(FrozenInstanceError):
        metrics.pages_read = 9
    with pytest.raises(InvalidTypeError):
        replace(metrics, pages_read=True)
    with pytest.raises(ValidationError):
        replace(metrics, pages_written=-1)
    with pytest.raises(ValidationError):
        replace(metrics, elapsed_seconds=float("nan"))


def test_heap_insertion_and_scan_expose_real_size_time_and_io(tmp_path):
    schema = _schema()
    path = tmp_path / "heap.db"
    with HeapFile.create(path, schema) as heap:
        heap.reset_counters()
        started_at = perf_counter()
        rid = heap.insert(_row(schema, 1))
        elapsed_seconds = perf_counter() - started_at

        assert math.isfinite(elapsed_seconds) and elapsed_seconds >= 0.0
        assert heap.pages_written == 3
        assert heap.pages_allocated == 1
        assert heap.file_size == path.stat().st_size
        assert heap.file_size == FILE_HEADER_SIZE + 2 * PAGE_SIZE

        heap.reset_counters()
        assert list(heap.scan()) == [(rid, _row(schema, 1))]
        assert heap.pages_read == 1
        assert heap.pages_written == heap.pages_allocated == 0


def test_sequential_search_exposes_real_size_time_and_io(tmp_path):
    schema = _schema()
    path = tmp_path / "sequential.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        for key in (3, 1, 2):
            sequential.insert(_row(schema, key))
        sequential.reset_counters()

        started_at = perf_counter()
        matches = list(sequential.search(2))
        elapsed_seconds = perf_counter() - started_at

        assert math.isfinite(elapsed_seconds) and elapsed_seconds >= 0.0
        assert [record.values[0] for _, record in matches] == [2]
        assert sequential.pages_read > 0
        assert sequential.pages_written == sequential.pages_allocated == 0
        assert sequential.file_size == path.stat().st_size


def test_reorganization_returns_io_across_all_internal_manager_sessions(tmp_path):
    schema = _schema()
    path = tmp_path / "sequential.db"
    with PagedSequentialFile.create(path, schema, "id") as sequential:
        for key in (1, 2, 3):
            sequential.insert(_row(schema, key, 3000))
        sequential.delete(list(sequential.search(1))[0][0])
        size_before = sequential.file_size

        metrics = sequential.reorganize()

        assert isinstance(metrics, ReorganizationMetrics)
        assert math.isfinite(metrics.elapsed_seconds)
        assert metrics.elapsed_seconds >= 0.0
        assert metrics.pages_read > 0
        assert metrics.pages_written > 0
        assert metrics.pages_allocated > 0
        assert metrics.file_size_before == size_before
        assert metrics.file_size_after == sequential.file_size == path.stat().st_size
        assert metrics.bytes_reclaimed == PAGE_SIZE
        # The committed file belongs to a freshly reopened PageManager session;
        # the returned metrics retain the completed rewrite's aggregate I/O.
        assert sequential.pages_read == 0
        assert sequential.pages_written == 0
        assert sequential.pages_allocated == 0
