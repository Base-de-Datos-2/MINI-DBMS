"""Stage 8 Tasks 8.23-8.26: controlled schedules and demo evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from time import monotonic, sleep

import pytest

from demos.transactions_demo import run_transaction_demo
from engine.database import Database
from engine.indexes import BPlusTree
from engine.maintenance import DeleteTargetSpool, MaintenanceError, MutationService
from engine.storage import HeapFile
from engine.transactions import LockMode, TransactionState


JOIN_TIMEOUT_SECONDS = 10.0


def _rows(result):
    with result:
        return [row.values for row in result]


def _wait_for_waiter(database: Database, transaction_id=None, timeout: float = 5.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = database.session_coordinator.locks.snapshot()
        waits = tuple(
            waiter
            for resource in snapshot.resources
            for waiter in resource.waiters
            if transaction_id is None or waiter.transaction_id == transaction_id
        )
        if waits:
            return snapshot, waits
        sleep(0.005)
    raise AssertionError("Expected a logical lock request to enter the wait queue")


def _wait_for_active_transaction(session, timeout: float = 5.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        transaction = session.active_transaction
        if transaction is not None:
            return transaction
        sleep(0.005)
    raise AssertionError("Expected the session to start a transaction")


def _table_resource_snapshot(database: Database, table_name: str):
    identity = database.session_coordinator.resources.table_files(table_name).identity
    return next(
        item
        for item in database.session_coordinator.locks.snapshot().resources
        if getattr(item.resource, "table_identity", None) == identity
    )


def test_compatible_readers_overlap_and_fair_writer_blocks_late_reader(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO t VALUES (1)")
        first, second, writer, late_reader = (
            database.open_session() for _ in range(4)
        )
        first.execute("BEGIN TRANSACTION")
        second.execute("BEGIN TRANSACTION")
        both_reading = Barrier(3)
        release_readers = Event()
        writer_reached_data = Event()
        release_writer = Event()
        original_insert = MutationService.insert

        def controlled_insert(service, **arguments):
            if arguments["record"].values == (2,):
                writer_reached_data.set()
                assert release_writer.wait(JOIN_TIMEOUT_SECONDS)
            return original_insert(service, **arguments)

        monkeypatch.setattr(MutationService, "insert", controlled_insert)

        def hold_reader(session):
            rows = _rows(session.execute("SELECT id FROM t"))
            both_reading.wait(timeout=JOIN_TIMEOUT_SECONDS)
            assert release_readers.wait(JOIN_TIMEOUT_SECONDS)
            terminal = session.execute("END TRANSACTION")
            return rows, terminal.state

        with ThreadPoolExecutor(max_workers=4) as pool:
            readers = (pool.submit(hold_reader, first), pool.submit(hold_reader, second))
            both_reading.wait(timeout=JOIN_TIMEOUT_SECONDS)

            held = _table_resource_snapshot(database, "t")
            assert set(held.holders) == {
                (first.active_transaction.id, LockMode.S),
                (second.active_transaction.id, LockMode.S),
            }

            pending_writer = pool.submit(writer.execute, "INSERT INTO t VALUES (2)")
            _, writer_waits = _wait_for_waiter(database)
            writer_id = writer.active_transaction.id
            assert any(wait.transaction_id == writer_id for wait in writer_waits)
            assert not writer_reached_data.is_set()

            pending_late_reader = pool.submit(
                lambda: _rows(late_reader.execute("SELECT id FROM t ORDER BY id"))
            )
            late_transaction = _wait_for_active_transaction(late_reader)
            _, late_waits = _wait_for_waiter(
                database, late_transaction.id,
            )
            late_wait = next(
                wait for wait in late_waits
                if wait.transaction_id == late_transaction.id
            )
            assert late_wait.blockers == (writer_id,)

            release_readers.set()
            assert writer_reached_data.wait(JOIN_TIMEOUT_SECONDS)
            assert not pending_late_reader.done()
            release_writer.set()

            assert pending_writer.result(timeout=JOIN_TIMEOUT_SECONDS).committed
            assert pending_late_reader.result(timeout=JOIN_TIMEOUT_SECONDS) == [(1,), (2,)]
            assert [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in readers] == [
                ([(1,)], TransactionState.COMMITTED),
                ([(1,)], TransactionState.COMMITTED),
            ]

        for session in (first, second, writer, late_reader):
            session.close()
        assert database.session_coordinator.locks.snapshot().resources == ()


def test_repeatable_range_read_prevents_phantom_and_dirty_read(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        database.engine.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, value INT)"
        )
        database.engine.execute("INSERT INTO t VALUES (1, 10)")
        reader, writer = database.open_session(), database.open_session()
        reader.execute("BEGIN TRANSACTION")
        assert _rows(reader.execute(
            "SELECT id, value FROM t WHERE id >= 1 ORDER BY id"
        )) == [(1, 10)]

        mutation_reached = Event()
        original_insert = MutationService.insert

        def observed_insert(service, **arguments):
            if arguments["record"].values == (2, 20):
                mutation_reached.set()
            return original_insert(service, **arguments)

        monkeypatch.setattr(MutationService, "insert", observed_insert)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(writer.execute, "INSERT INTO t VALUES (2, 20)")
            _, waits = _wait_for_waiter(database)
            assert waits[0].blockers == (reader.active_transaction.id,)
            assert not mutation_reached.is_set() and not pending.done()
            assert _rows(reader.execute(
                "SELECT id, value FROM t WHERE id >= 1 ORDER BY id"
            )) == [(1, 10)]
            reader.execute("END TRANSACTION")
            assert pending.result(timeout=JOIN_TIMEOUT_SECONDS).committed
        assert mutation_reached.is_set()

        writer.execute("BEGIN TRANSACTION")
        writer.execute("INSERT INTO t VALUES (3, 30)")
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending_read = pool.submit(
                lambda: _rows(reader.execute(
                    "SELECT id, value FROM t WHERE id = 3"
                ))
            )
            _, waits = _wait_for_waiter(database)
            assert waits[0].blockers == (writer.active_transaction.id,)
            assert not pending_read.done()
            writer.execute("ROLLBACK")
            assert pending_read.result(timeout=JOIN_TIMEOUT_SECONDS) == []

        assert _rows(database.engine.execute(
            "SELECT id, value FROM t ORDER BY id"
        )) == [(1, 10), (2, 20)]
        reader.close()
        writer.close()


def test_join_holds_both_sources_while_independent_table_commits(tmp_path):
    with Database.create(tmp_path) as database:
        for table in ("a", "b", "independent"):
            database.engine.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY)"
            )
            database.engine.execute(f"INSERT INTO {table} VALUES (1)")

        reader, blocked_writer, independent_writer = (
            database.open_session() for _ in range(3)
        )
        reader.execute("BEGIN TRANSACTION")
        assert _rows(reader.execute(
            "SELECT a.id FROM a JOIN b ON a.id = b.id"
        )) == [(1,)]

        with ThreadPoolExecutor(max_workers=2) as pool:
            blocked = pool.submit(
                blocked_writer.execute, "INSERT INTO a VALUES (2)"
            )
            _, waits = _wait_for_waiter(database)
            assert waits[0].blockers == (reader.active_transaction.id,)
            independent = pool.submit(
                independent_writer.execute, "INSERT INTO independent VALUES (2)"
            )
            assert independent.result(timeout=JOIN_TIMEOUT_SECONDS).committed
            assert not blocked.done()
            reader.execute("END TRANSACTION")
            assert blocked.result(timeout=JOIN_TIMEOUT_SECONDS).committed

        assert _rows(database.engine.execute("SELECT id FROM a ORDER BY id")) == [
            (1,), (2,),
        ]
        assert _rows(database.engine.execute(
            "SELECT id FROM independent ORDER BY id"
        )) == [(1,), (2,)]
        for session in (reader, blocked_writer, independent_writer):
            session.close()


def test_snapshot_failure_rolls_back_group_preserves_peer_commit_and_reopens(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database:
        for table in ("a", "b", "c"):
            database.engine.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY)"
            )
        failing, peer = database.open_session(), database.open_session()
        failing.execute("BEGIN TRANSACTION")
        failing.execute("INSERT INTO a VALUES (1)")

        with ThreadPoolExecutor(max_workers=1) as pool:
            committed = pool.submit(peer.execute, "INSERT INTO b VALUES (2)")
            assert committed.result(timeout=JOIN_TIMEOUT_SECONDS).committed

        original_capture = database.session_coordinator.completion.undo.capture

        def fail_c_capture(transaction_id, files):
            if files.name == "c":
                raise OSError("injected snapshot boundary failure")
            return original_capture(transaction_id, files)

        monkeypatch.setattr(
            database.session_coordinator.completion.undo,
            "capture",
            fail_c_capture,
        )
        with pytest.raises(OSError, match="snapshot boundary failure"):
            failing.execute("INSERT INTO c VALUES (3)")

        assert failing.active_transaction is None
        assert _rows(database.engine.execute("SELECT id FROM a")) == []
        assert _rows(database.engine.execute("SELECT id FROM b")) == [(2,)]
        assert _rows(database.engine.execute("SELECT id FROM c")) == []
        for table in ("a", "b", "c"):
            database.index_for(f"__pk__{table}").validate_structure()
        failing.close()
        peer.close()

    with Database.open(tmp_path) as reopened:
        assert _rows(reopened.engine.execute("SELECT id FROM a")) == []
        assert _rows(reopened.engine.execute("SELECT id FROM b")) == [(2,)]
        assert _rows(reopened.engine.execute("SELECT id FROM c")) == []


@pytest.mark.parametrize("failure_point", ["base", "index"])
def test_base_or_index_write_fault_rolls_back_the_complete_explicit_group(
    tmp_path, monkeypatch, failure_point,
):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, value INT)"
        )
        files = database.session_coordinator.resources.table_files("t")
        before = tuple(path.read_bytes() for path in files.physical_files)
        session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO t VALUES (1, 10)")

        if failure_point == "base":
            storage = database.storage_for("t")
            original = HeapFile.insert

            def fail_base(heap, record):
                if heap is storage and record.values == (2, 20):
                    raise OSError("injected base write failure")
                return original(heap, record)

            monkeypatch.setattr(HeapFile, "insert", fail_base)
        else:
            original = BPlusTree.insert

            def fail_index(tree, key, rid):
                if tree.header.index_name == "__pk__t" and key == 2:
                    raise OSError("injected index write failure")
                return original(tree, key, rid)

            monkeypatch.setattr(BPlusTree, "insert", fail_index)

        with pytest.raises(MaintenanceError):
            session.execute("INSERT INTO t VALUES (2, 20)")

        assert session.active_transaction is None
        assert _rows(database.engine.execute("SELECT id, value FROM t")) == []
        database.index_for("__pk__t").validate_structure()
        assert tuple(path.read_bytes() for path in files.physical_files) == before


def test_delete_spool_fault_restores_prior_statement_and_original_rows(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, value INT)"
        )
        for value in range(1, 4):
            database.engine.execute(f"INSERT INTO t VALUES ({value}, {value * 10})")
        files = database.session_coordinator.resources.table_files("t")
        before = tuple(path.read_bytes() for path in files.physical_files)
        session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO t VALUES (4, 40)")
        original = DeleteTargetSpool.append
        calls = 0

        def fail_discovery(spool, rid, record):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected spool discovery failure")
            return original(spool, rid, record)

        monkeypatch.setattr(DeleteTargetSpool, "append", fail_discovery)
        with pytest.raises(MaintenanceError, match="discovery failed"):
            session.execute("DELETE FROM t WHERE id <= 3")

        assert session.active_transaction is None
        assert _rows(database.engine.execute(
            "SELECT id, value FROM t ORDER BY id"
        )) == [(1, 10), (2, 20), (3, 30)]
        database.index_for("__pk__t").validate_structure()
        assert tuple(path.read_bytes() for path in files.physical_files) == before


def test_implicit_index_fault_aborts_statement_and_default_session_is_reusable(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        original = BPlusTree.insert
        failed = False

        def fail_once(tree, key, rid):
            nonlocal failed
            if tree.header.index_name == "__pk__t" and not failed:
                failed = True
                raise OSError("injected implicit index failure")
            return original(tree, key, rid)

        monkeypatch.setattr(BPlusTree, "insert", fail_once)
        with pytest.raises(MaintenanceError):
            database.engine.execute("INSERT INTO t VALUES (1)")

        assert database.session_coordinator.default_session.active_transaction is None
        assert database.session_coordinator.locks.snapshot().resources == ()
        assert _rows(database.engine.execute("SELECT id FROM t")) == []
        assert database.engine.execute("INSERT INTO t VALUES (2)").committed
        assert _rows(database.engine.execute("SELECT id FROM t")) == [(2,)]
        database.index_for("__pk__t").validate_structure()


def test_real_unsafe_lost_update_and_protected_serial_oracle(tmp_path):
    evidence = run_transaction_demo(tmp_path)

    assert [item.read_value for item in evidence.unsafe.attempts] == [0, 0]
    assert evidence.unsafe.final_value == 1
    assert evidence.unsafe.completed_business_operations == 2
    assert evidence.unsafe.committed_business_operations == 0

    protected_reads = sorted(item.read_value for item in evidence.protected.attempts)
    assert protected_reads == [0, 0, 1]
    assert evidence.protected.final_value == 2
    assert evidence.protected.completed_business_operations == 2
    assert evidence.protected.committed_business_operations == 2
    assert evidence.protected.aborted_attempts == 1
    assert sum(item.failure == "DeadlockVictimError"
               for item in evidence.protected.attempts) == 1
    assert any(item.lock_wait_seconds > 0 for item in evidence.protected.attempts)
    assert sorted(
        (item.read_value, item.written_value)
        for item in evidence.protected.attempts
        if item.outcome == TransactionState.COMMITTED.value
    ) == [(0, 1), (1, 2)]

    assert [item.read_value for item in evidence.serial_oracle.attempts] == [0, 1]
    assert evidence.serial_oracle.final_value == 2
    assert evidence.protected_matches_serial_oracle
