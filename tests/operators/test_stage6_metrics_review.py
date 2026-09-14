"""Regressions for Stage 6 partition cleanup and physical-plan measurements."""

from contextlib import closing

import pytest

from engine.catalog import Column, DataType, Schema
from engine.operators import (
    Count, ExternalHashGroup, ExternalSort, GraceHashJoin, JoinSpec,
    PhysicalPlan, SortSpec, run_plan,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.temp_stream import TemporaryRowWriter
from engine.storage import Record
from engine.storage.page_manager import PageManager
from tests.operator_helpers import RowSource


SCHEMA = Schema([Column("key", DataType.INTEGER), Column("text", DataType.VARCHAR)])


def test_completed_report_has_exclusive_real_temp_io_and_no_live_files():
    rows = [Record(SCHEMA, [1, "one"])]
    output, report = run_plan(
        ExternalSort(RowSource(rows), SortSpec.ascending("key")), limit=1,
    )
    assert output == tuple(rows)
    assert report.temporary_pages_written == 4
    assert report.temporary_pages_read == 2
    assert report.base_pages_read == report.index_pages_read == 0
    assert report.bytes_spilled > 0
    assert report.temporary_metadata_writes > 0
    assert report.peak_live_temporary_bytes > 0
    assert report.live_temporary_bytes == 0


def test_report_is_per_run_even_when_an_operator_instance_is_reused():
    rows = [Record(SCHEMA, [n, str(n)]) for n in range(3)]
    root = ExternalSort(RowSource(rows), SortSpec.ascending("key"))
    first, first_report = run_plan(root, limit=3)
    second, second_report = run_plan(root, limit=3)
    assert first == second == tuple(rows)
    assert first_report.rows_produced == second_report.rows_produced == 3
    assert first_report.root.rows_emitted == second_report.root.rows_emitted == 3
    assert first_report.temporary_pages_written == second_report.temporary_pages_written
    assert first_report.bytes_spilled == second_report.bytes_spilled
    assert root.describe().rows_emitted == 6  # live descriptor remains cumulative


def test_closed_plan_descriptor_stays_fixed_after_root_is_reused():
    rows = [Record(SCHEMA, [n, str(n)]) for n in range(3)]
    root = ExternalSort(RowSource(rows), SortSpec.ascending("key"))
    first = PhysicalPlan(root)
    with first:
        assert len(list(first.rows())) == 3
    snapshot = first.report()
    with PhysicalPlan(root) as second:
        assert len(list(second.rows())) == 3
    assert first.report() == snapshot
    assert snapshot.root.rows_emitted == 3


def test_partial_report_counts_io_already_done_and_survives_close():
    rows = [Record(SCHEMA, [n, "x" * 200]) for n in range(40)]
    plan = PhysicalPlan(
        ExternalSort(RowSource(rows), SortSpec.ascending("key")),
    )
    with plan:
        with closing(plan.rows()) as stream:
            assert next(stream) is not None
        partial = plan.report()
        assert partial.rows_produced == 1
        assert partial.temporary_pages_written > 0
        assert partial.temporary_pages_read > 0
        assert partial.live_temporary_bytes > 0
    closed = plan.report()
    assert closed.rows_produced == 1
    assert closed.temporary_pages_written == partial.temporary_pages_written
    assert closed.live_temporary_bytes == 0
    assert closed.peak_live_temporary_bytes >= partial.live_temporary_bytes


def test_fallback_io_is_counted_once_across_group_and_internal_sort(monkeypatch):
    monkeypatch.setattr(
        "engine.operators.partitioning.partition_hash",
        lambda values, data_types, *, level=0: 0,
    )
    close_original = PageManager.close
    reads, writes = [], []

    def observed_close(manager):
        if not manager.closed:
            reads.append(manager.pages_read)
            writes.append(manager.pages_written)
        return close_original(manager)

    monkeypatch.setattr(PageManager, "close", observed_close)
    rows = [Record(SCHEMA, [n, "x" * 500]) for n in range(300)]
    root = ExternalHashGroup(
        RowSource(rows), ["key"], [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
        partition_count=2, max_level=1,
    )
    result, report = run_plan(root, memory_budget_bytes=131072, limit=300)
    assert len(result) == 300
    assert root.metrics.fallback_partitions > 0
    assert report.temporary_pages_read == sum(reads)
    assert report.temporary_pages_written == sum(writes)
    assert root.metrics.temporary_pages_read == report.temporary_pages_read
    assert root.metrics.temporary_pages_written == report.temporary_pages_written
    assert report.live_temporary_bytes == 0


def test_partition_finish_failure_preserves_cause_through_plan_cleanup(monkeypatch):
    original = TemporaryRowWriter.finish
    triggered = False

    def fail_once(writer):
        nonlocal triggered
        if not triggered:
            triggered = True
            raise OSError("partition finish injected")
        return original(writer)

    monkeypatch.setattr(TemporaryRowWriter, "finish", fail_once)
    root = ExternalHashGroup(
        RowSource([Record(SCHEMA, [n, "x"]) for n in range(8)]),
        ["key"], [Count()], partition_count=2,
    )
    plan = PhysicalPlan(root)
    with pytest.raises(OSError, match="partition finish injected"):
        with plan:
            list(plan.rows())
    report = plan.report()
    assert report.rows_produced == 0
    assert report.live_temporary_bytes == 0
    assert plan.context is None


def test_grace_fallback_reports_exact_temp_io_and_actual_strategy(monkeypatch):
    original_close = PageManager.close
    reads, writes = [], []

    def observed_close(manager):
        if not manager.closed:
            reads.append(manager.pages_read)
            writes.append(manager.pages_written)
        return original_close(manager)

    monkeypatch.setattr(PageManager, "close", observed_close)
    left = [Record(SCHEMA, [1, "l" * 1000]) for _ in range(40)]
    right = [Record(SCHEMA, [1, "r" * 1000]) for _ in range(40)]
    root = GraceHashJoin(
        RowSource(left, relation="left"), RowSource(right, relation="right"),
        JoinSpec.on(("key", "key")),
        memory_budget_bytes=32768, partition_count=2, max_level=1,
    )
    result, report = run_plan(root, memory_budget_bytes=65536, limit=1600)
    assert len(result) == 1600
    assert root.metrics.fallback_pairs > 0
    assert "fallback" in dict(report.root.details)["strategy"]
    assert report.temporary_pages_read == sum(reads)
    assert report.temporary_pages_written == sum(writes)
    assert root.metrics.temporary_pages_read == report.temporary_pages_read
    assert root.metrics.temporary_pages_written == report.temporary_pages_written
    assert report.live_temporary_bytes == 0
