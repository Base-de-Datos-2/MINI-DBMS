"""Regressions from the independent review of tasks 6.5/6.11/6.15/6.16."""

from pathlib import Path

import pytest

from engine.catalog import Column, DataType, Schema
from engine.errors import InsufficientBudgetError, OversizedRowError, ValidationError
from engine.operators import Count, ExecutionContext, ExternalHashGroup, ExternalSort, SortSpec, collect
from engine.operators.context import row_footprint_bytes
from engine.operators.temp_files import TemporaryWorkspace
from engine.operators.temp_stream import TemporaryRowReader, TemporaryRowWriter
from engine.operators.sorting import MINIMUM_SORT_BUDGET_BYTES
from engine.operators.run_catalog import RunCatalog
from engine.storage.page_manager import PageManager
from engine.storage import Record
from tests.operator_helpers import RowSource


SCHEMA = Schema([Column("key", DataType.INTEGER), Column("text", DataType.VARCHAR)])


@pytest.mark.parametrize("label", ["../outside", "..\\outside", "/outside", "C:\\outside", "a/b", "a\\b"])
def test_allocation_rejects_paths_before_registering_them(tmp_path, label):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        with pytest.raises(ValidationError):
            workspace.allocate(label)
        assert workspace.tracked_paths == ()


def test_allocation_never_adopts_an_existing_unrelated_file(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    intruder = workspace.directory / "run-000000.tmp"
    intruder.write_bytes(b"unrelated")
    try:
        with pytest.raises(ValidationError):
            workspace.allocate("run")
        assert workspace.tracked_paths == ()
        assert intruder.read_bytes() == b"unrelated"
    finally:
        intruder.unlink()
        workspace.close()


def test_cleanup_failure_preserves_the_original_error(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    intruder = workspace.directory / "unrelated.dat"
    intruder.write_bytes(b"keep")
    original = OSError("original write failure")
    try:
        with pytest.raises(OSError) as raised:
            with workspace:
                raise original
        assert raised.value is original
        assert workspace.unreclaimed_paths
        assert any("cleanup" in note.lower() for note in original.__notes__)
    finally:
        intruder.unlink()
        if workspace.directory.exists():
            workspace.directory.rmdir()


def test_wide_merge_does_not_retain_more_than_its_grant():
    rows = [Record(SCHEMA, [n, "x" * 7000]) for n in range(31, -1, -1)]
    grant = 128 * 1024
    operator = ExternalSort(RowSource(rows), SortSpec.ascending("key"),
                            memory_budget_bytes=grant, max_fan_in=2)
    with ExecutionContext(memory_budget_bytes=2 * grant) as context:
        try:
            operator.open(context)
            first = operator.next()
            assert first is not None
            assert operator._owned_context.reserved_bytes > 0
            assert operator._owned_context.reserved_bytes <= grant
            frame = operator._output.gi_frame.f_locals
            retained = [entry[2] for entry in frame["heap"]] + [frame["row"]]
            assert sum(map(row_footprint_bytes, retained)) <= operator._owned_context.reserved_bytes
            output = [first]
            while (row := operator.next()) is not None:
                output.append(row)
            assert output == list(reversed(rows))
            assert operator.metrics.initial_runs > 2
            assert operator.metrics.merge_passes >= 2
        finally:
            operator.close()
        assert context.reserved_bytes == context.open_handle_count == 0


def test_a_wide_row_needs_a_grant_that_can_merge_two_heads():
    operator = ExternalSort(
        RowSource([Record(SCHEMA, [1, "x" * 7000])]),
        SortSpec.ascending("key"), memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
    )
    with pytest.raises(OversizedRowError, match="per row"):
        collect(operator, limit=1)


def test_temporary_stream_handles_are_visible_and_bounded(tmp_path):
    with ExecutionContext(memory_budget_bytes=65536, max_open_handles=1) as context:
        with TemporaryWorkspace(parent_directory=tmp_path, context=context) as workspace:
            writer = TemporaryRowWriter(workspace, SCHEMA)
            assert context.open_handle_count == 1
            writer.write(Record(SCHEMA, [1, "a"]))
            run = writer.finish()
            assert context.open_handle_count == 0
            reader = TemporaryRowReader(workspace, run)
            try:
                assert context.open_handle_count == 1
                with pytest.raises(InsufficientBudgetError):
                    TemporaryRowReader(workspace, run)
            finally:
                reader.close()
            assert context.open_handle_count == 0


def test_workspace_closes_live_streams_before_deleting_files(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    writer = TemporaryRowWriter(workspace, SCHEMA)
    writer.write(Record(SCHEMA, [1, "a"]))
    workspace.close()
    assert writer._manager.closed
    assert not workspace.directory.exists()


def test_workspace_metadata_does_not_keep_one_python_object_per_file(tmp_path):
    with ExecutionContext(memory_budget_bytes=16384) as context:
        with TemporaryWorkspace(parent_directory=tmp_path, context=context) as workspace:
            before = context.reserved_bytes
            for _ in range(500):
                workspace.allocate()
            assert context.reserved_bytes == before
            assert not isinstance(getattr(workspace, "_files", None), dict)
            assert len(workspace.tracked_paths) == 500


def test_merge_buffers_and_handles_are_released_on_read_failure(monkeypatch):
    operator = ExternalSort(
        RowSource([Record(SCHEMA, [n, "x" * 200]) for n in range(300)]),
        SortSpec.ascending("key"), memory_budget_bytes=32768, max_fan_in=2,
    )
    with ExecutionContext(memory_budget_bytes=65536) as context:
        original = TemporaryRowReader.next_row
        def fail(reader):
            if reader.rows_read == 2:
                raise OSError("merge read failure")
            return original(reader)
        monkeypatch.setattr(TemporaryRowReader, "next_row", fail)
        with pytest.raises(OSError, match="merge read failure"):
            collect(operator, context, limit=300)
        assert context.reserved_bytes == context.open_handle_count == 0


def test_context_owns_and_closes_a_live_workspace(tmp_path):
    context = ExecutionContext(memory_budget_bytes=65536)
    workspace = TemporaryWorkspace(parent_directory=tmp_path, context=context)
    writer = TemporaryRowWriter(workspace, SCHEMA)
    writer.write(Record(SCHEMA, [1, "row"]))
    context.close()
    assert writer._manager.closed
    assert not workspace.directory.exists()
    assert context.reserved_bytes == context.open_handle_count == 0


def test_preflight_refuses_nested_grants_before_consuming_a_source():
    source = RowSource([Record(SCHEMA, [n, "a"]) for n in range(100)])
    inner = ExternalSort(source, SortSpec.ascending("key"),
                         memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES)
    root = ExternalSort(inner, SortSpec.ascending("key"),
                        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES)
    with ExecutionContext(memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES) as context:
        with pytest.raises(InsufficientBudgetError, match="simultaneously"):
            collect(root, context, limit=100)
        assert source.opens == 0
        assert source.statistics.rows_emitted == 0
        assert context.reserved_bytes == 0


def test_closed_child_contexts_do_not_accumulate_on_the_parent():
    with ExecutionContext(memory_budget_bytes=65536) as context:
        for _ in range(100):
            context.child(8192).close()
        assert context._children == []
        assert context.reserved_bytes == 0


def test_multipass_sort_bounds_loaded_descriptors_and_preserves_stability():
    rows = [Record(SCHEMA, [n % 11, str(n) + "x" * 800]) for n in range(500)]
    expected = sorted(rows, key=lambda row: row.values[0])
    for grant in (MINIMUM_SORT_BUDGET_BYTES, 65536):
        root = ExternalSort(RowSource(rows), SortSpec.ascending("key"),
                            memory_budget_bytes=grant, max_fan_in=2)
        with ExecutionContext(memory_budget_bytes=2 * grant, max_open_handles=3) as context:
            assert list(collect(root, context, limit=500)) == expected
            assert context.statistics.peak_open_handles <= 3
            assert context.reserved_bytes == context.open_handle_count == 0
        assert root.metrics.initial_runs > 2
        assert root.metrics.merge_passes >= 2
        assert root.metrics.max_active_descriptors <= 2
        assert root.metrics.metadata_writes > 0


def test_real_data_handles_never_exceed_reported_permits(monkeypatch):
    streams = []
    context = ExecutionContext(memory_budget_bytes=65536, max_open_handles=3)
    original_open = Path.open
    def watch(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        streams.append(stream)
        # Count actual metadata and row-file handles, not only PageManagers.
        live = sum(not item.closed for item in streams)
        assert live <= context.open_handle_count <= 3
        return stream
    monkeypatch.setattr(Path, "open", watch)
    root = ExternalSort(
        RowSource([Record(SCHEMA, [n, "x" * 500]) for n in range(100)]),
        SortSpec.ascending("key"), memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=2,
    )
    try:
        collect(root, context, limit=100)
        assert all(stream.closed for stream in streams)
    finally:
        context.close()


def test_sort_uses_real_page_write_counters(monkeypatch):
    original = PageManager.close
    writes = []
    def close(manager):
        if not manager.closed:
            writes.append(manager.pages_written)
        return original(manager)
    monkeypatch.setattr(PageManager, "close", close)
    root = ExternalSort(RowSource([Record(SCHEMA, [1, "a"])]), SortSpec.ascending("key"))
    collect(root, limit=1)
    assert root.metrics.temporary_pages_written == sum(writes) == 4


def test_failed_workspace_creation_returns_its_reservation(tmp_path, monkeypatch):
    original_open = Path.open
    original_rmdir = Path.rmdir
    created = []
    def fail_open(path, *args, **kwargs):
        if path.name == "ownership.registry":
            created.append(path.parent)
            raise OSError("registry creation failed")
        return original_open(path, *args, **kwargs)
    def fail_rmdir(path):
        if path in created:
            raise OSError("directory cleanup failed")
        return original_rmdir(path)
    with ExecutionContext(memory_budget_bytes=65536) as context:
        try:
            with monkeypatch.context() as injected:
                injected.setattr(Path, "open", fail_open)
                injected.setattr(Path, "rmdir", fail_rmdir)
                with pytest.raises(OSError, match="registry creation failed") as raised:
                    TemporaryWorkspace(parent_directory=tmp_path, context=context)
                assert context.reserved_bytes == context.open_handle_count == 0
                assert any(str(created[0]) in note for note in raised.value.__notes__)
        finally:
            for directory in created:
                directory.rmdir()


def test_registry_read_failure_reports_unreclaimed_paths(tmp_path, monkeypatch):
    with ExecutionContext(memory_budget_bytes=65536) as context:
        workspace = TemporaryWorkspace(parent_directory=tmp_path, context=context)
        path = workspace.allocate()
        path.write_bytes(b"owned")
        original_open = Path.open
        def fail_read(candidate, mode="r", *args, **kwargs):
            if candidate == workspace._registry and mode == "rb":
                raise OSError("registry read failed")
            return original_open(candidate, mode, *args, **kwargs)
        try:
            with monkeypatch.context() as injected:
                injected.setattr(Path, "open", fail_read)
                with pytest.raises(ValidationError, match="left files behind"):
                    workspace.close()
            assert workspace.directory in workspace.unreclaimed_paths
            assert workspace._registry in workspace.unreclaimed_paths
            assert path.exists()
            assert context.reserved_bytes == context.open_handle_count == 0
        finally:
            path.unlink()
            workspace._registry.unlink()
            workspace.directory.rmdir()


@pytest.mark.parametrize("size", [10, 300])
def test_catalog_read_failure_releases_both_passes_and_their_reservations(
    tmp_path, monkeypatch, size,
):
    directories = []
    original_init = TemporaryWorkspace.__init__
    def track(workspace, *args, **kwargs):
        kwargs["parent_directory"] = tmp_path
        original_init(workspace, *args, **kwargs)
        directories.append(workspace.directory)
    def fail_read(catalog, index):
        raise OSError("run catalog read failure")
    monkeypatch.setattr(TemporaryWorkspace, "__init__", track)
    monkeypatch.setattr(RunCatalog, "read", fail_read)
    root = ExternalSort(
        RowSource([Record(SCHEMA, [n, "x" * 500]) for n in range(size)]),
        SortSpec.ascending("key"), memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=2,
    )
    with ExecutionContext(memory_budget_bytes=65536) as context:
        with pytest.raises(OSError, match="run catalog read failure"):
            collect(root, context, limit=size)
        assert context.reserved_bytes == context.open_handle_count == 0
        assert all(not directory.exists() for directory in directories)


def test_group_fallback_can_use_a_larger_grant_for_wide_sort_rows(monkeypatch):
    monkeypatch.setattr(
        "engine.operators.partitioning.partition_hash",
        lambda values, data_types, *, level=0: 0,
    )
    rows = [Record(SCHEMA, [n, f"{n:02d}" + "x" * 3000]) for n in range(24)]
    root = ExternalHashGroup(
        RowSource(rows), ["text"], [Count()],
        memory_budget_bytes=65536, partition_count=2,
    )
    output = collect(root, limit=24)
    assert sorted(row.values for row in output) == sorted(
        (row.values[1], 1) for row in rows)
    assert root.metrics.fallback_partitions > 0


def test_collect_preserves_its_result_limit_error_when_closing_also_fails():
    class FailingCloseSource(RowSource):
        def _close(self):
            super()._close()
            raise OSError("cursor cleanup failed")

    source = FailingCloseSource([Record(SCHEMA, [1, "row"])])
    with pytest.raises(ValidationError, match="more than the requested 0") as raised:
        collect(source, limit=0)
    assert any("cursor cleanup failed" in note for note in raised.value.__notes__)
    assert source.closes == 1
