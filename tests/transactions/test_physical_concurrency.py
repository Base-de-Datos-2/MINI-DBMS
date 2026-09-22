"""Short physical latches and registry generations for Stage 8 Task 8.10."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from engine.catalog import Column, DataType, Schema
from engine.database import Database
from engine.indexes import BPlusTree, ExtendibleHashIndex
from engine.query import parse_sql
from engine.storage import HeapFile, PageManager, Record, RID
from engine.transactions import StaleAccessPlanError
from engine.storage.binary import PAGE_SIZE


def test_seek_and_full_read_cannot_interleave_with_another_reader_or_close(tmp_path):
    manager = PageManager.create(tmp_path / "pages.db")
    manager.allocate_page()
    manager.allocate_page()
    entered, release, second_started, close_started = (
        Event(), Event(), Event(), Event()
    )
    original = manager._file

    class PausingFile:
        def __init__(self):
            self.seeks = []
            self.paused = False

        def __getattr__(self, name):
            return getattr(original, name)

        def seek(self, offset, *args):
            self.seeks.append(offset)
            return original.seek(offset, *args)

        def read(self, size):
            if size == PAGE_SIZE and not self.paused:
                self.paused = True
                entered.set()
                assert release.wait(3)
            return original.read(size)

    proxy = PausingFile()
    manager._file = proxy

    def second_read():
        second_started.set()
        return manager.read_page(1)

    def close():
        close_started.set()
        manager.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(manager.read_page, 0)
        assert entered.wait(3)
        second = pool.submit(second_read)
        assert second_started.wait(3)
        closing = pool.submit(close)
        assert close_started.wait(3)
        # Both operations have started, but neither can move the shared offset.
        assert len(proxy.seeks) == 1
        assert not second.done() and not closing.done()
        release.set()
        assert first.result(timeout=3).page_id == 0
        # Either the waiting reader or close may win after the first read.
        try:
            assert second.result(timeout=3).page_id == 1
        except RuntimeError as error:
            assert "closed" in str(error)
        closing.result(timeout=3)
    assert manager.closed


def test_replacement_waits_for_inflight_read_before_swapping_handle(tmp_path):
    manager = PageManager.create(tmp_path / "replace.db")
    manager.allocate_page()
    candidate_path = manager.temporary_replacement_path()
    with PageManager.create(candidate_path) as candidate:
        candidate.allocate_page()
        replacement = candidate.read_page(0)
        replacement.insert(b"new")
        candidate.write_page(replacement)

    entered, release, replacing = Event(), Event(), Event()
    original = manager._file

    class PausingFile:
        def __init__(self):
            self.paused = False

        def __getattr__(self, name):
            return getattr(original, name)

        def read(self, size):
            if size == PAGE_SIZE and not self.paused:
                self.paused = True
                entered.set()
                assert release.wait(3)
            return original.read(size)

    manager._file = PausingFile()

    def replace():
        replacing.set()
        manager.commit_replacement(candidate_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(manager.read_page, 0)
        assert entered.wait(3)
        swapping = pool.submit(replace)
        assert replacing.wait(3)
        assert not swapping.done()
        release.set()
        assert reading.result(timeout=3).active_record_count == 0
        swapping.result(timeout=3)
    assert manager.read_page(0).read(0) == b"new"
    manager.close()


def test_concurrent_heap_bplus_and_hash_reads_keep_counters_and_results(tmp_path):
    schema = Schema((Column("id", DataType.INTEGER),))
    with HeapFile.create(tmp_path / "rows.db", schema) as heap:
        rid = heap.insert(Record(schema, (7,)))
        with BPlusTree.create(
            tmp_path / "ordered.idx", index_name="ordered", table_name="rows",
            key_column="id", key_type=DataType.INTEGER,
        ) as tree, ExtendibleHashIndex.create(
            tmp_path / "hash.idx", index_name="hash", table_name="rows",
            key_column="id", key_type=DataType.INTEGER,
        ) as hashed:
            tree.insert(7, rid)
            hashed.insert(7, rid)
            heap.reset_counters()
            tree.reset_counters()
            hashed.reset_counters()

            def read_many():
                for _ in range(40):
                    assert heap.read(rid).values == (7,)
                    assert list(tree.search(7)) == [rid]
                    assert list(hashed.search(7)) == [rid]

            with ThreadPoolExecutor(max_workers=4) as pool:
                for future in (pool.submit(read_many) for _ in range(4)):
                    future.result(timeout=10)
            assert heap.pages_read == 160
            assert hashed.metrics.directory_page_reads == 160
            assert hashed.metrics.bucket_page_reads == 160
            assert hashed.metrics.associations_inspected == 160
            assert tree.pages_read >= 160


def test_registry_replacement_invalidates_access_plan_even_with_same_handle(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT)")
        resources = database.session_coordinator.resources
        plan = resources.plan(parse_sql("SELECT id FROM t"))
        resources.validate(plan)
        storage = database.environment.unregister_storage("t")
        database.environment.register_storage("t", storage)
        with pytest.raises(StaleAccessPlanError, match="registry"):
            resources.validate(plan)
        resources.validate(resources.plan(parse_sql("SELECT id FROM t")))
