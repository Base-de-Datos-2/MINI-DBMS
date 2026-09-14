"""Task 6.29: persistence boundaries, scoped cleanup, and failure safety.

The boundary these tests police is deliberate: reopening persisted sources and
completed temporary files is required, while resuming an interrupted query
after a process crash is explicitly out of scope and is not simulated here.
"""

from contextlib import closing
import random

import pytest

from engine.catalog import (
    Catalog,
    Column,
    DataType,
    IndexMetadata,
    IndexType,
    Schema,
    TableMetadata,
)
from engine.errors import (
    CorruptTemporaryError,
    InsufficientBudgetError,
    ValidationError,
)
from engine.indexes import UnclusteredBPlusIndex, UnclusteredHashIndex
from engine.operators import (
    ColumnReference,
    Count,
    ExternalHashGroup,
    ExternalSort,
    Filter,
    GraceHashJoin,
    IndexScan,
    JoinSpec,
    Literal,
    SortSpec,
    TableScan,
    TemporaryRowReader,
    TemporaryRowWriter,
    TemporaryWorkspace,
    collect,
    execute,
    run_plan,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.sorting import MINIMUM_FAN_IN, MINIMUM_SORT_BUDGET_BYTES
from engine.operators.temp_stream import DESCRIPTOR_PAGE_ID, DESCRIPTOR_SLOT_ID
from engine.storage import HeapFile, Page, PageManager, Record
from tests.operator_helpers import RowSource


SALES = Schema(
    [Column("region", DataType.VARCHAR), Column("amount", DataType.INTEGER)]
)


def build_database(tmp_path, rows=400):
    """Create, fill, flush and close a table and its two indexes."""

    heap_path = tmp_path / "sales.heap"
    bplus_path = tmp_path / "sales.bpt"
    hash_path = tmp_path / "sales.hsh"
    with HeapFile.create(heap_path, SALES) as heap:
        for number in range(rows):
            heap.insert(Record(SALES, [f"r{number % 20}", number]))
        with UnclusteredBPlusIndex.build(
            bplus_path, heap=heap, index_name="ix_amount",
            table_name="sales", key_column="amount",
        ) as index:
            index.flush()
        with UnclusteredHashIndex.build(
            hash_path, heap=heap, index_name="hx_amount",
            table_name="sales", key_column="amount",
        ) as index:
            index.flush()
    return heap_path, bplus_path, hash_path


def test_operators_run_over_sources_reopened_through_the_catalog(tmp_path):
    heap_path, bplus_path, hash_path = build_database(tmp_path)

    # Every manager from the build phase is gone; rebuild the catalog and open
    # fresh objects, exactly as a new process would.
    catalog = Catalog()
    catalog.register_table(TableMetadata("sales", SALES))
    catalog.register_index(
        IndexMetadata("ix_amount", "sales", "amount", IndexType.BPLUS,
                      file_path=str(bplus_path))
    )
    catalog.register_index(
        IndexMetadata("hx_amount", "sales", "amount",
                      IndexType.EXTENDIBLE_HASH, file_path=str(hash_path))
    )

    metadata = catalog.get_table("sales")
    fresh_schema = Schema(list(metadata.schema.columns))
    with HeapFile.open(heap_path, fresh_schema) as heap:
        with UnclusteredBPlusIndex.open(bplus_path, heap=heap) as bplus, \
                UnclusteredHashIndex.open(hash_path, heap=heap) as hashed:
            scanned = collect(TableScan(heap, relation="sales"), limit=500)
            by_bplus = collect(
                IndexScan.equality(bplus, 7, relation="sales"), limit=10
            )
            by_hash = collect(
                IndexScan.equality(hashed, 7, relation="sales"), limit=10
            )
            grouped, _ = run_plan(
                ExternalSort(
                    ExternalHashGroup(
                        TableScan(heap, relation="sales"), ["region"], [Count()]
                    ),
                    SortSpec.ascending("region"),
                ),
                limit=100,
            )

    assert len(scanned) == 400
    assert [tuple(row.values) for row in by_bplus] == [("r7", 7)]
    assert [tuple(row.values) for row in by_hash] == [("r7", 7)]
    assert len(grouped) == 20
    assert all(row.values[1] == 20 for row in grouped)


def test_a_completed_temporary_file_reopens_with_fresh_readers(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        writer = TemporaryRowWriter(workspace, SALES, label="run")
        rows = [Record(SALES, [f"r{n}", n]) for n in range(300)]
        with writer:
            for row in rows:
                writer.write(row)
            run = writer.finish()

        # The writing handle is gone; every later reader opens the file anew.
        for _ in range(3):
            reader = TemporaryRowReader(workspace, run)
            with reader:
                recovered = []
                while (row := reader.next_row()) is not None:
                    recovered.append(row)
            assert recovered == rows


def test_a_truncated_temporary_file_fails_through_a_domain_error(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        writer = TemporaryRowWriter(workspace, SALES, label="run")
        with writer:
            for number in range(400):
                writer.write(Record(SALES, [f"region-{number}", number]))
            run = writer.finish()

        with PageManager.open(run.path) as manager:
            last = manager.allocated_page_count - 1
            payload = manager.read_page(last).read(DESCRIPTOR_SLOT_ID)
            damaged = Page(last)
            damaged.insert(payload[: len(payload) // 3])
            manager.write_page(damaged)

        reader = TemporaryRowReader(workspace, run)
        with reader:
            with pytest.raises(CorruptTemporaryError):
                while reader.next_row() is not None:
                    pass


def test_an_unsupported_temporary_format_is_refused(tmp_path):
    with TemporaryWorkspace(parent_directory=tmp_path) as workspace:
        writer = TemporaryRowWriter(workspace, SALES, label="run")
        with writer:
            writer.write(Record(SALES, ["r", 1]))
            run = writer.finish()

        with PageManager.open(run.path) as manager:
            page = manager.read_page(DESCRIPTOR_PAGE_ID)
            document = page.read(DESCRIPTOR_SLOT_ID).replace(
                b'"version":1', b'"version":7'
            )
            replacement = Page(DESCRIPTOR_PAGE_ID)
            replacement.insert(document)
            manager.write_page(replacement)

        with pytest.raises(CorruptTemporaryError, match="Unsupported"):
            TemporaryRowReader(workspace, run)


def _sort_over(rows):
    return ExternalSort(
        RowSource(rows, relation="sales"),
        SortSpec.ascending("amount"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )


def test_a_read_failure_in_the_final_merge_releases_every_temporary(monkeypatch):
    rows = [Record(SALES, [f"r{n}", n]) for n in range(800)]
    root = _sort_over(rows)
    root.open()
    directory = root._workspace.directory
    assert any(directory.iterdir())

    # The final merge is a lazy generator: it only opens readers on the first
    # next(), so a failure injected into the reader now surfaces mid-stream.
    def failing(self):
        raise OSError("injected temporary read failure")

    monkeypatch.setattr(TemporaryRowReader, "next_row", failing)
    try:
        with pytest.raises(OSError, match="injected temporary read failure"):
            root.next()
    finally:
        monkeypatch.undo()
        root.close()

    assert not directory.exists()


def test_a_read_failure_in_an_intermediate_pass_releases_every_temporary(
    monkeypatch,
):
    rows = [Record(SALES, [f"r{n}", n]) for n in range(800)]
    root = _sort_over(rows)
    created = []
    original_init = TemporaryWorkspace.__init__

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self.directory)

    def failing(self):
        raise OSError("injected intermediate read failure")

    monkeypatch.setattr(TemporaryWorkspace, "__init__", tracking_init)
    monkeypatch.setattr(TemporaryRowReader, "next_row", failing)

    # Many runs and a fan-in of two force merge passes inside open(), so the
    # failure strikes before the operator ever returns a row.
    with pytest.raises(OSError, match="injected intermediate read failure"):
        root.open()

    assert created
    assert all(not directory.exists() for directory in created)
    assert root.state.value == "CLOSED"


def test_a_write_failure_while_spilling_releases_every_temporary(monkeypatch):
    rows = [Record(SALES, [f"r{n}", n]) for n in range(800)]
    root = _sort_over(rows)
    created = []
    original_init = TemporaryWorkspace.__init__
    original_write = TemporaryRowWriter.write
    calls = {"count": 0}

    def tracking_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created.append(self.directory)

    def failing_write(self, record):
        calls["count"] += 1
        if calls["count"] == 150:
            raise OSError("injected temporary write failure")
        return original_write(self, record)

    monkeypatch.setattr(TemporaryWorkspace, "__init__", tracking_init)
    monkeypatch.setattr(TemporaryRowWriter, "write", failing_write)

    with pytest.raises(OSError, match="injected temporary write failure"):
        root.open()

    assert all(not directory.exists() for directory in created)


def test_stopping_after_a_few_sorted_rows_leaves_nothing_behind(tmp_path):
    rows = [Record(SALES, [f"r{n % 7}", (n * 31) % 900]) for n in range(900)]
    root = ExternalSort(
        RowSource(rows, relation="sales"),
        SortSpec.ascending("amount"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    with closing(execute(root)) as stream:
        produced = [next(stream) for _ in range(3)]
        directory = root._workspace.directory
        assert directory.exists()

    assert [row.values[1] for row in produced] == sorted(
        row.values[1] for row in rows
    )[:3]
    assert not directory.exists()


def test_stopping_after_a_few_grouped_or_joined_rows_leaves_nothing_behind():
    rows = [Record(SALES, [f"r{n % 120}", n]) for n in range(1200)]
    grouping = ExternalHashGroup(
        RowSource(rows, relation="sales"), ["region"], [Count()],
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES, partition_count=2,
    )
    joining = GraceHashJoin(
        RowSource(rows, relation="left"),
        RowSource(rows, relation="right"),
        JoinSpec.on(("region", "region")),
        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES, partition_count=2,
    )

    for operator in (grouping, joining):
        with closing(execute(operator)) as stream:
            assert next(stream) is not None
            directory = operator._workspace.directory
            assert directory.exists()
        assert not directory.exists()


def test_a_parent_failing_after_a_child_created_temporaries_cleans_up_both():
    rows = [Record(SALES, [f"r{n % 50}", n]) for n in range(600)]
    child = ExternalSort(
        RowSource(rows, relation="sales"),
        SortSpec.ascending("amount"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )
    parent = Filter(child, Literal(True))
    parent.open()
    child_directory = child._workspace.directory
    assert child_directory.exists()

    original = parent._next

    def failing():
        raise ValueError("injected parent failure")

    parent._next = failing
    try:
        with pytest.raises(ValueError, match="injected parent failure"):
            parent.next()
    finally:
        parent._next = original
        parent.close()

    assert not child_directory.exists()
    assert child.state.value == "CLOSED"


def test_a_read_only_query_does_not_modify_its_base_files(tmp_path):
    heap_path, bplus_path, hash_path = build_database(tmp_path, rows=300)
    before = {
        path: path.read_bytes()
        for path in (heap_path, bplus_path, hash_path)
    }

    fresh_schema = Schema(list(SALES.columns))
    with HeapFile.open(heap_path, fresh_schema) as heap:
        with UnclusteredBPlusIndex.open(bplus_path, heap=heap) as bplus:
            run_plan(
                ExternalSort(
                    ExternalHashGroup(
                        Filter(
                            TableScan(heap, relation="sales"), Literal(True)
                        ),
                        ["region"],
                        [Count()],
                        memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES,
                        partition_count=2,
                    ),
                    SortSpec.ascending("region"),
                    memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
                ),
                limit=100,
            )
            collect(IndexScan.between(bplus, 10, 20, relation="sales"), limit=50)

    after = {path: path.read_bytes() for path in before}

    assert after == before


def test_cleanup_is_scoped_to_the_execution_directory(tmp_path):
    bystander = tmp_path / "not-ours.dat"
    bystander.write_bytes(b"a file nobody in this query created")
    permanent = tmp_path / "sales.heap"
    with HeapFile.create(permanent, SALES) as heap:
        for number in range(400):
            heap.insert(Record(SALES, [f"r{number % 9}", number]))
        snapshot = permanent.read_bytes()

        root = ExternalSort(
            TableScan(heap, relation="sales"),
            SortSpec.ascending("amount"),
            memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
            max_fan_in=MINIMUM_FAN_IN,
        )
        rows, _ = run_plan(root, limit=500)

    assert len(rows) == 400
    assert bystander.exists()
    assert bystander.read_bytes() == b"a file nobody in this query created"
    assert permanent.read_bytes() == snapshot


def test_every_owned_handle_and_path_is_released_after_a_full_pipeline():
    random.seed(41)
    rows = [Record(SALES, [f"r{random.randrange(80)}", n]) for n in range(1500)]
    root = ExternalSort(
        ExternalHashGroup(
            RowSource(rows, relation="sales"), ["region"], [Count()],
            memory_budget_bytes=MINIMUM_GROUP_BUDGET_BYTES, partition_count=2,
        ),
        SortSpec.ascending("region"),
        memory_budget_bytes=MINIMUM_SORT_BUDGET_BYTES,
        max_fan_in=MINIMUM_FAN_IN,
    )

    produced, report = run_plan(root, memory_budget_bytes=256 * 4096, limit=200)

    assert len(produced) == 80
    assert report.peak_reserved_bytes <= report.memory_budget_bytes
    assert root._workspace is None
    assert root.child._workspace is None


def test_a_cleanup_failure_is_reported_with_its_exact_paths(tmp_path):
    workspace = TemporaryWorkspace(parent_directory=tmp_path)
    tracked = workspace.allocate("run")
    tracked.write_bytes(b"owned")
    intruder = workspace.directory / "left-behind.dat"
    intruder.write_bytes(b"not tracked")

    with pytest.raises(ValidationError, match="left files behind"):
        workspace.close()

    assert workspace.unreclaimed_paths == (workspace.directory,)
    assert intruder.exists()
    assert not tracked.exists()

    intruder.unlink()
    workspace.directory.rmdir()


def test_nested_blocking_operators_without_explicit_budgets_share_the_grant():
    """Regression: the first blocking operator to open used to take everything.

    Children open before their parents. When every blocking operator claimed
    the whole parent budget, the inner grouping consumed it and the sort above
    failed with zero bytes left. Each now takes half of what remains.
    """

    rows = [Record(SALES, [f"r{n % 40}", n]) for n in range(800)]
    root = ExternalSort(
        ExternalHashGroup(RowSource(rows, relation="sales"), ["region"], [Count()]),
        SortSpec.ascending("region"),
    )

    produced, report = run_plan(root, limit=100)

    assert len(produced) == 40
    assert report.peak_reserved_bytes <= report.memory_budget_bytes
    assert report.reservations_refused == 0


def test_three_nested_blocking_operators_fit_one_default_budget():
    rows = [Record(SALES, [f"r{n % 30}", n % 11]) for n in range(900)]
    root = ExternalSort(
        ExternalHashGroup(
            GraceHashJoin(
                RowSource(rows, relation="left"),
                RowSource(rows[:60], relation="right"),
                JoinSpec.on(("amount", "amount")),
            ),
            [ColumnReference("region", "left")],
            [Count()],
        ),
        SortSpec.ascending("region"),
    )

    produced, report = run_plan(root, limit=100)

    assert len(produced) == 30
    assert report.reservations_refused == 0


def test_blocking_operators_that_cannot_fit_together_fail_before_reading():
    rows = [Record(SALES, [f"r{n % 40}", n]) for n in range(200)]
    source = RowSource(rows, relation="sales")
    root = ExternalSort(
        ExternalHashGroup(
            source, ["region"], [Count()], memory_budget_bytes=40 * 4096,
        ),
        SortSpec.ascending("region"),
        memory_budget_bytes=40 * 4096,
    )

    with pytest.raises(InsufficientBudgetError, match="do not fit simultaneously"):
        run_plan(root, memory_budget_bytes=64 * 4096, limit=100)

    # Preflight rejects the complete grant request before opening any source.
    assert source.opens == source.closes == 0
    assert source.statistics.rows_emitted == 0


def test_the_root_context_sees_and_bounds_every_nested_handle():
    rows = [Record(SALES, [f"r{n % 200}", n]) for n in range(2000)]
    root = ExternalHashGroup(
        RowSource(rows, relation="sales"),
        ["region"],
        [Count()],
        memory_budget_bytes=64 * 4096,
        partition_count=6,
    )

    _, report = run_plan(root, memory_budget_bytes=256 * 4096, limit=300)

    # The partitioner's handles are leased on a nested context; the root must
    # still observe them, which it did not before handles propagated upward.
    assert report.peak_open_handles >= 6


def test_a_handle_ceiling_on_the_root_reaches_nested_operators():
    rows = [Record(SALES, [f"r{n % 200}", n]) for n in range(2000)]
    source = RowSource(rows, relation="sales")
    root = ExternalHashGroup(
        source,
        ["region"],
        [Count()],
        memory_budget_bytes=64 * 4096,
        partition_count=6,
    )

    # Six partitions need six handles plus one for input; a root ceiling of
    # four reaches the nested grouping context, which refuses the fan-out up
    # front instead of discovering the limit after opening some handles.
    with pytest.raises(InsufficientBudgetError, match="allow \\(3\\)"):
        run_plan(root, memory_budget_bytes=256 * 4096, max_open_handles=4,
                 limit=300)

    assert source.closes == 1
    assert root._workspace is None
