"""Controlled schedules for Stage 8 Tasks 8.7–8.9."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from time import monotonic, sleep

import pytest

from engine.transactions import (
    AccessPlan, DeadlockVictimError, LockManager, LockMode, LockTimeoutError,
    SchemaMode, TableIntent,
    TableResource, TransactionAbortError, TransactionManager,
    TransactionProtocolError, TransactionUnavailableError,
)
from engine.catalog import Column, DataType, Schema
from engine.storage import HeapFile, Record


def _begin(manager, locks, session):
    transaction = manager.begin(session)
    locks.register(transaction)
    locks.acquire(transaction.id, locks.schema_resource, LockMode.S)
    return transaction.id


def _finish(manager, locks, transaction_id, *, abort=False):
    report = (manager.abort_empty(transaction_id) if abort
              else manager.commit_empty(transaction_id))
    locks.release_all(report)
    return report


def _wait_for(locks, transaction_id, resource, *, timeout=2):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        for state in locks.snapshot().resources:
            if state.resource == resource and any(
                waiter.transaction_id == transaction_id for waiter in state.waiters
            ):
                return
        sleep(0.001)
    pytest.fail(f"Transaction {transaction_id} did not queue for {resource}")


def test_compatible_readers_and_independent_tables_overlap_without_global_mutex(tmp_path):
    manager, locks = TransactionManager(), LockManager("db")
    first = _begin(manager, locks, 1)
    second = _begin(manager, locks, 2)
    third = _begin(manager, locks, 3)
    table_a, table_b = TableResource("db", "a"), TableResource("db", "b")
    schema = Schema((Column("id", DataType.INTEGER),))
    heap_a = HeapFile.create(tmp_path / "a.db", schema)
    heap_b = HeapFile.create(tmp_path / "b.db", schema)
    rid_a = heap_a.insert(Record(schema, (10,)))
    rid_b = heap_b.insert(Record(schema, (20,)))
    entered = Barrier(4)
    release = Event()

    def hold(transaction_id, table, mode, heap, rid, expected):
        locks.acquire(transaction_id, table, mode)
        assert heap.read(rid).values == (expected,)
        entered.wait(timeout=3)
        assert release.wait(3)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = (
            pool.submit(hold, first, table_a, LockMode.S, heap_a, rid_a, 10),
            pool.submit(hold, second, table_a, LockMode.S, heap_a, rid_a, 10),
            pool.submit(hold, third, table_b, LockMode.X, heap_b, rid_b, 20),
        )
        entered.wait(timeout=3)
        snapshot = locks.snapshot()
        assert snapshot.wait_for == ()
        assert len(next(item for item in snapshot.resources
                        if item.resource == table_a).holders) == 2
        release.set()
        for future in futures:
            future.result(timeout=3)
    for transaction_id in (first, second, third):
        _finish(manager, locks, transaction_id)
    heap_a.close()
    heap_b.close()
    assert locks.snapshot().resources == ()


def test_exclusive_wait_fifo_writer_prevents_later_reader_overtaking():
    manager, locks = TransactionManager(), LockManager("db")
    table = TableResource("db", "t")
    holder = _begin(manager, locks, 1)
    writer = _begin(manager, locks, 2)
    late_reader = _begin(manager, locks, 3)
    locks.acquire(holder, table, LockMode.S)
    writer_acquired = Event()
    release_writer = Event()
    reader_acquired = Event()

    def write():
        locks.acquire(writer, table, LockMode.X)
        writer_acquired.set()
        assert release_writer.wait(3)

    def read():
        locks.acquire(late_reader, table, LockMode.S)
        reader_acquired.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(write)
        _wait_for(locks, writer, table)
        reading = pool.submit(read)
        _wait_for(locks, late_reader, table)
        snapshot = next(item for item in locks.snapshot().resources
                        if item.resource == table)
        assert snapshot.waiters[1].blockers == (writer,)
        _finish(manager, locks, holder)
        assert writer_acquired.wait(3)
        assert not reader_acquired.is_set()
        release_writer.set()
        writing.result(timeout=3)
        _finish(manager, locks, writer)
        reading.result(timeout=3)
        assert reader_acquired.is_set()
    _finish(manager, locks, late_reader)
    assert locks.snapshot().wait_for == ()


def test_opposite_table_order_victim_keeps_prior_grants_until_abort_cleanup():
    manager, locks = TransactionManager(), LockManager("db")
    left, right = TableResource("db", "left"), TableResource("db", "right")
    first, second = _begin(manager, locks, 1), _begin(manager, locks, 2)
    locks.acquire(first, left, LockMode.X)
    locks.acquire(second, right, LockMode.X)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(locks.acquire, first, right, LockMode.X)
        _wait_for(locks, first, right)
        with pytest.raises(DeadlockVictimError):
            locks.acquire(second, left, LockMode.X)
        assert not pending.done()
        snapshot = locks.snapshot()
        assert snapshot.wait_for == ((first, (second,)),)
        assert any(item.resource == right and item.holders == ((second, LockMode.X),)
                   for item in snapshot.resources)
        _finish(manager, locks, second, abort=True)
        pending.result(timeout=3)
    _finish(manager, locks, first)
    assert locks.snapshot().resources == ()


def test_two_upgrades_detect_cycle_and_preserve_s_until_victim_finishes():
    manager, locks = TransactionManager(), LockManager("db")
    table = TableResource("db", "t")
    first, second = _begin(manager, locks, 1), _begin(manager, locks, 2)
    locks.acquire(first, table, LockMode.S)
    locks.acquire(second, table, LockMode.S)
    with ThreadPoolExecutor(max_workers=1) as pool:
        upgrade = pool.submit(locks.acquire, first, table, LockMode.X)
        _wait_for(locks, first, table)
        with pytest.raises(DeadlockVictimError):
            locks.acquire(second, table, LockMode.X)
        assert set(next(item for item in locks.snapshot().resources
                        if item.resource == table).holders) == {
                            (first, LockMode.S), (second, LockMode.S)
                        }
        _finish(manager, locks, second, abort=True)
        upgrade.result(timeout=3)
    assert next(item for item in locks.snapshot().resources
                if item.resource == table).holders == ((first, LockMode.X),)
    _finish(manager, locks, first)


def test_timeout_and_cancellation_are_distinct_and_remove_wait_edges():
    manager, locks = TransactionManager(), LockManager("db", timeout_seconds=0.05)
    table = TableResource("db", "t")
    holder, timeout_id, cancel_id = (
        _begin(manager, locks, 1), _begin(manager, locks, 2),
        _begin(manager, locks, 3),
    )
    locks.acquire(holder, table, LockMode.X)
    with pytest.raises(LockTimeoutError):
        locks.acquire(timeout_id, table, LockMode.S)
    with pytest.raises(LockTimeoutError):
        locks.acquire(timeout_id, table, LockMode.S)
    _finish(manager, locks, timeout_id, abort=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(locks.acquire, cancel_id, table, LockMode.S,
                              timeout_seconds=3)
        _wait_for(locks, cancel_id, table)
        locks.cancel(cancel_id)
        with pytest.raises(TransactionAbortError):
            pending.result(timeout=3)
    _finish(manager, locks, cancel_id, abort=True)
    _finish(manager, locks, holder)
    assert locks.snapshot().resources == ()


def test_cancellation_after_grant_but_before_waiter_resumes_fails_closed():
    manager, locks = TransactionManager(), LockManager("db")
    table = TableResource("db", "t")
    holder, waiter = _begin(manager, locks, 1), _begin(manager, locks, 2)
    locks.acquire(holder, table, LockMode.X)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            locks.acquire, waiter, table, LockMode.S, timeout_seconds=3
        )
        _wait_for(locks, waiter, table)
        holder_report = manager.commit_empty(holder)
        # Hold the condition while the grant and cancellation race; the
        # waiter cannot resume between these two metadata transitions.
        with locks._condition:
            locks.release_all(holder_report)
            locks.cancel(waiter)
        with pytest.raises(TransactionAbortError):
            pending.result(timeout=3)
    assert next(item for item in locks.snapshot().resources
                if item.resource == table).holders == ((waiter, LockMode.S),)
    _finish(manager, locks, waiter, abort=True)
    assert locks.snapshot().resources == ()


def test_terminal_release_idempotence_schema_order_and_quarantine():
    manager, locks = TransactionManager(), LockManager("db")
    transaction = manager.begin(1)
    locks.register(transaction)
    table = TableResource("db", "t")
    with pytest.raises(TransactionProtocolError, match="schema"):
        locks.acquire(transaction.id, table, LockMode.S)
    locks.acquire(transaction.id, locks.schema_resource, LockMode.S)
    locks.acquire(transaction.id, table, LockMode.S)
    locks.acquire(transaction.id, table, LockMode.S)
    with pytest.raises(TransactionProtocolError):
        locks.release_all(manager.current(transaction.id))
    report = manager.commit_empty(transaction.id)
    with pytest.raises(TransactionProtocolError, match="another session"):
        locks.release_all(replace(report, session_id=99))
    locks.release_all(report)
    locks.release_all(report)
    with pytest.raises(TransactionProtocolError):
        locks.acquire(transaction.id, table, LockMode.S)
    locks.quarantine()
    with pytest.raises(TransactionUnavailableError):
        locks.register(manager.begin(2))
    assert locks.snapshot().unavailable


def test_quarantine_wakes_waiter_without_grant_and_cleanup_drops_empty_entries():
    manager, locks = TransactionManager(), LockManager("db")
    table = TableResource("db", "t")
    holder, waiter = _begin(manager, locks, 1), _begin(manager, locks, 2)
    locks.acquire(holder, table, LockMode.X)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            locks.acquire, waiter, table, LockMode.S, timeout_seconds=3
        )
        _wait_for(locks, waiter, table)
        locks.quarantine()
        with pytest.raises(TransactionUnavailableError):
            pending.result(timeout=3)
    assert locks.snapshot().wait_for == ()
    _finish(manager, locks, waiter, abort=True)
    _finish(manager, locks, holder, abort=True)
    assert locks.snapshot().resources == ()


def test_access_plan_acquires_schema_before_distinct_ordered_tables():
    manager, locks = TransactionManager(), LockManager("db")
    transaction = manager.begin(1)
    locks.register(transaction)
    a, b = TableResource("db", "a"), TableResource("db", "b")
    plan = AccessPlan(
        SchemaMode.S,
        (TableIntent("a", a, LockMode.S, 0, ()),
         TableIntent("b", b, LockMode.X, 0, ())),
        0,
    )
    locks.acquire_plan(transaction.id, plan)
    snapshot = locks.snapshot()
    assert [item.resource for item in snapshot.resources] == [
        locks.schema_resource, a, b,
    ]
    assert all(item.holders[0][0] == transaction.id for item in snapshot.resources)
    _finish(manager, locks, transaction.id)
    assert locks.snapshot().resources == ()


def test_queue_order_blocker_participates_in_three_transaction_deadlock():
    manager, locks = TransactionManager(), LockManager("db")
    t, u = TableResource("db", "t"), TableResource("db", "u")
    first, writer, last = (
        _begin(manager, locks, 1), _begin(manager, locks, 2),
        _begin(manager, locks, 3),
    )
    locks.acquire(first, t, LockMode.S)
    locks.acquire(last, u, LockMode.X)
    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting_writer = pool.submit(locks.acquire, writer, t, LockMode.X)
        _wait_for(locks, writer, t)
        waiting_first = pool.submit(locks.acquire, first, u, LockMode.X)
        _wait_for(locks, first, u)
        with pytest.raises(DeadlockVictimError):
            locks.acquire(last, t, LockMode.S)
        assert not waiting_first.done() and not waiting_writer.done()
        _finish(manager, locks, last, abort=True)
        waiting_first.result(timeout=3)
        _finish(manager, locks, first)
        waiting_writer.result(timeout=3)
    _finish(manager, locks, writer)
    assert locks.snapshot().wait_for == ()


def test_spurious_notification_does_not_grant_and_schema_queue_is_fair():
    manager, locks = TransactionManager(), LockManager("db")
    holder = _begin(manager, locks, 1)
    writer = manager.begin(2)
    reader = manager.begin(3)
    locks.register(writer)
    locks.register(reader)
    granted_writer, granted_reader, release_writer = Event(), Event(), Event()

    def acquire_writer():
        locks.acquire(writer.id, locks.schema_resource, LockMode.X)
        granted_writer.set()
        assert release_writer.wait(3)

    def acquire_reader():
        locks.acquire(reader.id, locks.schema_resource, LockMode.S)
        granted_reader.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting_writer = pool.submit(acquire_writer)
        _wait_for(locks, writer.id, locks.schema_resource)
        waiting_reader = pool.submit(acquire_reader)
        _wait_for(locks, reader.id, locks.schema_resource)
        with locks._condition:
            locks._condition.notify_all()
        assert not granted_writer.is_set() and not granted_reader.is_set()
        _finish(manager, locks, holder)
        assert granted_writer.wait(3)
        assert not granted_reader.is_set()
        release_writer.set()
        waiting_writer.result(timeout=3)
        _finish(manager, locks, writer.id)
        waiting_reader.result(timeout=3)
    assert granted_reader.is_set()
    _finish(manager, locks, reader.id)
    assert locks.snapshot().resources == ()
