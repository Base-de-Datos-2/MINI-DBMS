"""Stage 8 Tasks 8.11-8.14: physical group undo and terminal outcomes."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from engine.database import Database, DatabaseUnavailableError
from engine.transactions import StaleAccessPlanError, TransactionState
from engine.transactions.undo import UNCLEAN_MARKER, UNDO_DIRECTORY, UndoLimits, UndoStore
from engine.transactions.resources import TableFiles
from engine.transactions.model import TransactionId
from engine.transactions.errors import (
    DeadlockVictimError, TransactionCapacityError, TransactionProtocolError,
    TransactionUnavailableError,
)
from engine.query.parser import parse_sql
from engine.catalog import Column, DataType, IndexType, Schema
from api.database import (
    Database as LegacyDatabase, DatabaseDefinition, IndexDefinition,
    TableDefinition, HEAP, SEQUENTIAL,
)


def _rows(database, table):
    with database.engine.execute(f"SELECT id FROM {table} ORDER BY id") as result:
        return [row.values for row in result]


def test_group_rollback_restores_prior_successful_statements_and_all_index_bytes(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY, value INT)")
        database.engine.execute("INSERT INTO t VALUES (1, 10)")
        with database.open_session() as session:
            files = database.session_coordinator.resources.table_files("t")
            before = tuple(path.read_bytes() for path in files.physical_files)
            prepared = database.engine.prepare("SELECT id FROM t")
            prior_replacement = files.base.with_name(
                f".{files.base.name}.{'a' * 32}.replacement"
            )
            prior_replacement.write_bytes(b"preexisting")
            stale = database.session_coordinator.resources.plan(parse_sql("SELECT id FROM t"))
            session.execute("BEGIN TRANSACTION")
            session.run_write("t", lambda: database.insert("t", (2, 20)))
            first_image = database.session_coordinator.completion.undo.images(
                session.active_transaction.id
            )
            assert len(first_image) == 1
            assert len(first_image[0].files) == 2
            owned_replacement = files.base.with_name(
                f".{files.base.name}.{'b' * 32}.replacement"
            )
            owned_replacement.write_bytes(b"interrupted rewrite")
            session.run_write("t", lambda: database.insert("t", (3, 30)))
            assert database.session_coordinator.completion.undo.images(
                session.active_transaction.id
            ) == first_image
            with session.execute("SELECT id FROM t ORDER BY id") as visible:
                assert [row.values for row in visible] == [(1,), (2,), (3,)]
            report = session.execute("ROLLBACK")
            assert report.state is TransactionState.ABORTED
            assert report.touched_tables == ("t",)
            assert tuple(path.read_bytes() for path in files.physical_files) == before
            assert prior_replacement.read_bytes() == b"preexisting"
            assert not owned_replacement.exists()
            prior_replacement.unlink()
            assert _rows(database, "t") == [(1,)]
            database.index_for("__pk__t").validate_structure()
            with pytest.raises(StaleAccessPlanError):
                database.session_coordinator.resources.validate(stale)
            with prepared.execute() as rebound:
                assert [row.values for row in rebound] == [(1,)]
            assert not (tmp_path / UNCLEAN_MARKER).exists()
    with Database.open(tmp_path) as reopened:
        assert _rows(reopened, "t") == [(1,)]


def test_commit_two_tables_and_reopen_preserves_both(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE a (id INT PRIMARY KEY)")
        database.engine.execute("CREATE TABLE b (id INT PRIMARY KEY)")
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.run_write("a", lambda: database.insert("a", (1,)))
            session.run_write("b", lambda: database.insert("b", (2,)))
            report = session.execute("END TRANSACTION")
            assert report.state is TransactionState.COMMITTED
            assert report.touched_tables == ("a", "b")
            assert report.warnings == ()
            assert database.session_coordinator.completion.retry_cleanup(report.id) == ()
    with Database.open(tmp_path) as reopened:
        assert _rows(reopened, "a") == [(1,)]
        assert _rows(reopened, "b") == [(2,)]


def test_second_write_error_aborts_first_statement_and_partial_second_write(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.run_write("t", lambda: database.insert("t", (1,)))
            transaction_id = session.active_transaction.id

            def fail_after_write():
                database.insert("t", (2,))
                raise RuntimeError("injected second statement failure")

            with pytest.raises(RuntimeError, match="second statement failure"):
                session.run_write("t", fail_after_write)
            assert session.active_transaction is None
            assert database.session_coordinator.completion.report(transaction_id).state is TransactionState.ABORTED
            assert _rows(database, "t") == []


def test_commit_flush_failure_uses_undo_before_success(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.run_write("t", lambda: database.insert("t", (1,)))
            transaction_id = session.active_transaction.id
            runtime = database.session_coordinator.completion.runtime
            original = runtime.flush

            def fail_once(files):
                monkeypatch.setattr(runtime, "flush", original)
                raise OSError("injected fsync failure")

            monkeypatch.setattr(runtime, "flush", fail_once)
            with pytest.raises(OSError, match="fsync failure"):
                session.execute("END TRANSACTION")
            assert database.session_coordinator.completion.report(transaction_id).state is TransactionState.ABORTED
            assert _rows(database, "t") == []


def test_failed_second_table_restore_quarantines_owner_and_retains_images(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE a (id INT PRIMARY KEY)")
        database.engine.execute("CREATE TABLE b (id INT PRIMARY KEY)")
        session = database.open_session()
        session.execute("BEGIN TRANSACTION")
        session.run_write("a", lambda: database.insert("a", (1,)))
        session.run_write("b", lambda: database.insert("b", (2,)))
        transaction_id = session.active_transaction.id
        coordinator = database.session_coordinator
        undo = coordinator.completion.undo
        original = undo.restore

        def fail_a(image, files):
            if files.name == "a":
                raise OSError("injected restore failure")
            return original(image, files)

        monkeypatch.setattr(undo, "restore", fail_a)
        with pytest.raises(TransactionUnavailableError, match="quarantined"):
            session.execute("ROLLBACK")
        assert coordinator.completion.report(transaction_id).state is TransactionState.ABORT_FAILED
        assert coordinator.locks.snapshot().unavailable
        assert (tmp_path / UNCLEAN_MARKER).exists()
        assert undo.images(transaction_id)
        with pytest.raises(TransactionUnavailableError, match="external inspection"):
            coordinator.completion.retry_cleanup(transaction_id)
        with pytest.raises(DatabaseUnavailableError, match="unavailable"):
            database.open_session()
    with pytest.raises(TransactionUnavailableError, match="Unresolved"):
        Database.open(tmp_path)


def test_capture_quota_and_copy_failure_leave_no_partial_image(tmp_path, monkeypatch):
    source = tmp_path / "t.heap"
    source.write_bytes(b"abcdefgh")
    files = TableFiles("t", "identity", source)
    limited = UndoStore(tmp_path, limits=UndoLimits(4, 4, 2, 1, 0))
    with pytest.raises(TransactionCapacityError):
        limited.capture(TransactionId(1), files)
    assert not (tmp_path / UNCLEAN_MARKER).exists()

    store = UndoStore(tmp_path, limits=UndoLimits(64, 64, 2, 1, 0))
    original_open = Path.open
    reads = 0

    class FailingReader:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def read(self, size):
            nonlocal reads
            reads += 1
            if reads == 2:
                raise OSError("injected copy failure")
            return self.handle.read(size)

    def injected_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode")
        return FailingReader(handle) if path == source and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", injected_open)
    with pytest.raises(OSError, match="copy failure"):
        store.capture(TransactionId(2), files)
    monkeypatch.setattr(Path, "open", original_open)
    assert source.read_bytes() == b"abcdefgh"
    assert store.images(TransactionId(2)) == ()
    assert not (tmp_path / UNCLEAN_MARKER).exists()
    assert not (tmp_path / UNDO_DIRECTORY).exists()


def test_total_undo_quota_and_free_space_reserve_are_enforced(tmp_path, monkeypatch):
    first = tmp_path / "first.heap"
    second = tmp_path / "second.heap"
    first.write_bytes(b"12345678")
    second.write_bytes(b"abcdefgh")
    store = UndoStore(tmp_path, limits=UndoLimits(16, 12, 4, 1, 0))
    store.capture(TransactionId(1), TableFiles("first", "first", first))
    with pytest.raises(TransactionCapacityError, match="quota"):
        store.capture(TransactionId(2), TableFiles("second", "second", second))
    assert store.discard(TransactionId(1)) == ()

    monkeypatch.setattr(
        "engine.transactions.undo.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=7),
    )
    with pytest.raises(TransactionCapacityError, match="free space"):
        store.capture(TransactionId(3), TableFiles("second", "second", second))
    assert store.images(TransactionId(3)) == ()
    assert not (tmp_path / UNCLEAN_MARKER).exists()


def test_read_only_group_has_no_image_and_cleanup_failure_is_committed_debt(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        coordinator = database.session_coordinator
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            transaction_id = session.active_transaction.id
            assert coordinator.completion.undo.images(transaction_id) == ()
            assert session.execute("END TRANSACTION").state is TransactionState.COMMITTED
            assert not (tmp_path / UNCLEAN_MARKER).exists()

            session.execute("BEGIN TRANSACTION")
            session.run_write("t", lambda: database.insert("t", (7,)))
            transaction_id = session.active_transaction.id
            original = coordinator.completion.undo.discard

            def fail_cleanup(_transaction_id):
                return ("injected cleanup debt",)

            monkeypatch.setattr(coordinator.completion.undo, "discard", fail_cleanup)
            report = session.execute("END TRANSACTION")
            assert report.state is TransactionState.COMMITTED
            assert report.warnings == ("injected cleanup debt",)
            assert _rows(database, "t") == [(7,)]
            assert (tmp_path / UNCLEAN_MARKER).exists()
            monkeypatch.setattr(coordinator.completion.undo, "discard", original)
    with pytest.raises(TransactionUnavailableError, match="Unresolved"):
        Database.open(tmp_path)


def test_end_rejects_open_result_and_session_close_restores_group(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        session = database.open_session()
        session.execute("BEGIN TRANSACTION")
        session.run_write("t", lambda: database.insert("t", (1,)))
        result = session._engine.execute("SELECT id FROM t")
        with pytest.raises(TransactionProtocolError, match="Close the active result"):
            session.execute("END TRANSACTION")
        assert session.active_transaction is not None
        session.close()
        assert session.closed and result.closed
        assert _rows(database, "t") == []


def test_legacy_hash_and_clustered_sequential_restore_exact_files(tmp_path):
    schema = Schema([Column("id", DataType.INTEGER)])
    definition = DatabaseDefinition("legacy", (
        TableDefinition(
            "hashed", schema, organization=HEAP,
            indexes=(IndexDefinition("h", "id", IndexType.EXTENDIBLE_HASH),),
            rows=lambda: ((1,),),
        ),
        TableDefinition(
            "ordered", schema, organization=SEQUENTIAL, key_column="id",
            indexes=(IndexDefinition("c", "id", IndexType.BPLUS, clustered=True),),
            rows=lambda: ((3,), (1,), (2,)),
        ),
    ))
    with LegacyDatabase.create(definition, tmp_path) as database:
        coordinator = database.session_coordinator
        before = {
            name: tuple(path.read_bytes() for path in coordinator.resources.table_files(name).physical_files)
            for name in ("hashed", "ordered")
        }
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            for value in range(2, 90):
                session.run_write(
                    "hashed", lambda value=value: database.engine.execute(
                        f"INSERT INTO hashed VALUES ({value})"
                    ),
                )
            session.run_write("ordered", lambda: database.engine.execute(
                "INSERT INTO ordered VALUES (0)"
            ))
            session.run_write("ordered", lambda: database._indexes["c"].reorganize())
            assert session.execute("ROLLBACK").state is TransactionState.ABORTED
        for name in ("hashed", "ordered"):
            files = coordinator.resources.table_files(name)
            assert tuple(path.read_bytes() for path in files.physical_files) == before[name]
        database._indexes["h"].validate_structure()
        database._indexes["c"].validate_structure()
        assert _rows(database, "hashed") == [(1,)]
        assert _rows(database, "ordered") == [(1,), (2,), (3,)]
    with LegacyDatabase.open(definition, tmp_path) as reopened:
        assert _rows(reopened, "hashed") == [(1,)]
        assert _rows(reopened, "ordered") == [(1,), (2,), (3,)]


def test_large_bplus_growth_and_new_pages_are_truncated_on_abort(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        files = database.session_coordinator.resources.table_files("t")
        before = tuple(path.read_bytes() for path in files.physical_files)
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")

            def grow_tree():
                for value in range(140):
                    database.insert("t", (value,))

            session.run_write("t", grow_tree)
            assert any(
                path.stat().st_size > len(original)
                for path, original in zip(files.physical_files, before)
            )
            assert session.execute("ROLLBACK").state is TransactionState.ABORTED
        assert tuple(path.read_bytes() for path in files.physical_files) == before
        assert _rows(database, "t") == []
        database.index_for("__pk__t").validate_structure()


def test_other_table_commit_survives_rollback_and_abort_is_idempotent(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE a (id INT PRIMARY KEY)")
        database.engine.execute("CREATE TABLE b (id INT PRIMARY KEY)")
        first, second = database.open_session(), database.open_session()
        first.execute("BEGIN TRANSACTION")
        first.run_write("a", lambda: database.insert("a", (1,)))
        transaction_id = first.active_transaction.id
        second.execute("BEGIN TRANSACTION")
        second.run_write("b", lambda: database.insert("b", (2,)))
        assert second.execute("END TRANSACTION").state is TransactionState.COMMITTED
        report = first.execute("ROLLBACK")
        assert database.session_coordinator.completion.abort(transaction_id) == report
        assert _rows(database, "a") == []
        assert _rows(database, "b") == [(2,)]


def test_partial_delete_and_prior_write_are_undone_together(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        for value in range(1, 5):
            database.engine.execute(f"INSERT INTO t VALUES ({value})")
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            session.run_write("t", lambda: database.insert("t", (5,)))

            def delete_then_fail():
                database.engine.execute("DELETE FROM t WHERE id < 3")
                raise RuntimeError("injected post-delete failure")

            with pytest.raises(RuntimeError, match="post-delete failure"):
                session.run_write("t", delete_then_fail)
        assert _rows(database, "t") == [(1,), (2,), (3,), (4,)]
        database.index_for("__pk__t").validate_structure()


def test_deadlock_victim_restores_earlier_write_before_waiter_proceeds(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE a (id INT PRIMARY KEY)")
        database.engine.execute("CREATE TABLE b (id INT PRIMARY KEY)")
        first, second = database.open_session(), database.open_session()
        first.execute("BEGIN TRANSACTION")
        second.execute("BEGIN TRANSACTION")
        first.run_write("a", lambda: database.insert("a", (1,)))
        second.run_write("b", lambda: database.insert("b", (2,)))
        coordinator = database.session_coordinator
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                first.run_write, "b", lambda: database.insert("b", (3,))
            )
            from time import monotonic, sleep
            deadline = monotonic() + 5
            while not any(resource.waiters for resource in coordinator.locks.snapshot().resources):
                assert monotonic() < deadline
                sleep(0.01)
            with pytest.raises(DeadlockVictimError):
                second.run_write("a", lambda: database.insert("a", (4,)))
            assert second.active_transaction is None
            future.result(timeout=5)
        assert first.execute("END TRANSACTION").state is TransactionState.COMMITTED
        assert _rows(database, "a") == [(1,)]
        assert _rows(database, "b") == [(3,)]


def test_large_copy_uses_configured_bounded_chunks(tmp_path, monkeypatch):
    source = tmp_path / "large.heap"
    source.write_bytes(b"z" * (2 << 20))
    store = UndoStore(
        tmp_path,
        limits=UndoLimits(3 << 20, 3 << 20, 4096, 1, 0),
    )
    files = TableFiles("large", "large", source)
    seen = []
    original_open = Path.open

    class RecordingReader:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.handle.__exit__(*args)
        def read(self, size):
            seen.append(size)
            return self.handle.read(size)

    def record_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode")
        return RecordingReader(handle) if path == source and mode == "rb" else handle

    monkeypatch.setattr(Path, "open", record_open)
    image = store.capture(TransactionId(1), files)
    monkeypatch.setattr(Path, "open", original_open)
    assert len(image.files) == 1
    assert seen and set(seen) == {4096}
    assert store.discard(TransactionId(1)) == ()
    assert not (tmp_path / UNCLEAN_MARKER).exists()


def test_restore_failure_cancels_waiter_before_lock_release(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        holder = database.open_session()
        waiter = database.open_session()
        holder.execute("BEGIN TRANSACTION")
        holder.run_write("t", lambda: database.insert("t", (1,)))
        waiter.execute("BEGIN TRANSACTION")
        coordinator = database.session_coordinator
        entered = Event()

        def wait_for_t():
            entered.set()
            return waiter.run_write("t", lambda: database.insert("t", (2,)))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(wait_for_t)
            assert entered.wait(5)
            # Observe an actual queued X request, not merely worker startup.
            from time import monotonic, sleep
            deadline = monotonic() + 5
            while not any(resource.waiters for resource in coordinator.locks.snapshot().resources):
                assert monotonic() < deadline
                sleep(0.01)
            monkeypatch.setattr(
                coordinator.completion.undo, "restore",
                lambda *_: (_ for _ in ()).throw(OSError("restore blocked")),
            )
            with pytest.raises(TransactionUnavailableError, match="quarantined"):
                holder.execute("ROLLBACK")
            with pytest.raises(TransactionUnavailableError):
                future.result(timeout=5)
        assert coordinator.locks.snapshot().unavailable
