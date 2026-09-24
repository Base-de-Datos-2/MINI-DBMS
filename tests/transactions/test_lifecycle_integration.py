"""Stage 8 Tasks 8.19-8.22: DDL, explanation, telemetry and shutdown."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest

from engine.database import Database
from engine.catalog import Column, DataType, Schema, TableMetadata
from engine.query.errors import SqlBindingError
from engine.query.executor import AnalysisExecutionError
from engine.query.planner import SelectPlanSpec
from engine.transactions import (
    TransactionAbortError,
    TransactionId,
    TransactionObservability,
    TransactionProtocolError,
    TransactionState,
)
from tests.operator_helpers import FailingOpen


def _rows(result):
    with result:
        return [row.values for row in result]


def _wait_for_waiter(database: Database, timeout: float = 5.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = database.session_coordinator.locks.snapshot()
        waits = tuple(
            waiter
            for resource in snapshot.resources
            for waiter in resource.waiters
        )
        if waits:
            return waits
        sleep(0.005)
    raise AssertionError("Expected a logical lock waiter")


def test_create_waits_for_schema_reader_and_duplicate_publication_is_atomic(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE seed (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO seed VALUES (1)")
        reader = database.open_session()
        creator = database.open_session()
        reader.execute("BEGIN TRANSACTION")
        assert _rows(reader.execute("SELECT id FROM seed")) == [(1,)]

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                creator.execute, "CREATE TABLE added (id INT PRIMARY KEY)",
            )
            waits = _wait_for_waiter(database)
            assert waits[0].mode.value == "X"
            assert not pending.done()
            assert _rows(reader.execute("SELECT id FROM seed")) == [(1,)]
            reader.execute("END TRANSACTION")
            assert pending.result(timeout=5).table_name == "added"

        before_files = {path.name for path in tmp_path.iterdir()}
        first, second = database.open_session(), database.open_session()
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [
                pool.submit(session.execute, "CREATE TABLE only_once (id INT)")
                for session in (first, second)
            ]
            outcomes = []
            for attempt in attempts:
                try:
                    outcomes.append(attempt.result(timeout=5).table_name)
                except SqlBindingError:
                    outcomes.append("duplicate")
        assert sorted(outcomes) == ["duplicate", "only_once"]
        assert database.table_names().count("only_once") == 1
        assert len({path.name for path in tmp_path.iterdir()} - before_files) == 1
        direct = database.create_table(TableMetadata(
            "direct_api", Schema([Column("id", DataType.INTEGER)]),
        ))
        assert direct.table_name == "direct_api"
        assert _rows(database.engine.execute("SELECT id FROM direct_api")) == []
        reader.close()
        creator.close()
        first.close()
        second.close()


def test_create_rejection_aborts_prior_group_and_prepare_waits_for_publication(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE seed (id INT PRIMARY KEY)")
        session = database.open_session()
        session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO seed VALUES (1)")
        with pytest.raises(TransactionProtocolError, match="explicit transaction"):
            session.execute("CREATE TABLE forbidden (id INT)")
        assert _rows(database.engine.execute("SELECT id FROM seed")) == []

        entered, release, attempted = Event(), Event(), Event()
        original = Database.create_table

        def blocking_create(owner, table):
            if table.name == "published_together":
                entered.set()
                assert release.wait(5)
            return original(owner, table)

        monkeypatch.setattr(Database, "create_table", blocking_create)
        creator, inspector = database.open_session(), database.open_session()
        with ThreadPoolExecutor(max_workers=2) as pool:
            creating = pool.submit(
                creator.execute, "CREATE TABLE published_together (id INT)",
            )
            assert entered.wait(5)

            def prepare():
                attempted.set()
                return inspector.prepare("SELECT id FROM seed")

            inspecting = pool.submit(prepare)
            assert attempted.wait(5)
            assert not inspecting.done()
            release.set()
            assert creating.result(timeout=5).table_name == "published_together"
            assert "seed" in inspecting.result(timeout=5).describe().render()
        session.close()
        creator.close()
        inspector.close()


def test_analyze_uses_transaction_locks_and_reports_separate_timings(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        writer, analyzer = database.open_session(), database.open_session()
        writer.execute("BEGIN TRANSACTION")
        writer.execute("INSERT INTO t VALUES (1)")

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                analyzer.execute, "EXPLAIN ANALYZE SELECT id FROM t",
            )
            waits = _wait_for_waiter(database)
            assert waits[0].blockers == (writer.active_transaction.id,)
            writer.execute("END TRANSACTION")
            analyzed = pending.result(timeout=5)

        report = analyzed.report
        assert report.executed and report.complete and report.output_rows == 1
        assert report.lock_wait_seconds > 0
        assert report.planning_seconds >= 0
        assert report.execution_seconds is not None
        assert report.transaction_state == TransactionState.COMMITTED.value
        metrics = database.session_coordinator.transaction_metrics(
            TransactionId(report.transaction_id)
        )
        assert metrics.query_io.base_pages_read > 0
        assert metrics.lock_wait_seconds >= report.lock_wait_seconds

        analyzer.execute("BEGIN TRANSACTION")
        analyzer.execute("INSERT INTO t VALUES (2)")
        own = analyzer.execute("EXPLAIN ANALYZE SELECT id FROM t ORDER BY id")
        assert own.output_rows == 2
        assert own.report.transaction_state == TransactionState.ACTIVE.value
        assert analyzer.active_transaction is not None
        assert database.session_coordinator.locks.snapshot().resources
        analyzer.execute("ROLLBACK")
        writer.close()
        analyzer.close()


def test_failed_analysis_keeps_partial_report_and_final_abort(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO t VALUES (1)")
        prepared = session.prepare("EXPLAIN ANALYZE SELECT id FROM t")
        failing = FailingOpen()
        monkeypatch.setattr(SelectPlanSpec, "instantiate", lambda _spec: failing)

        with pytest.raises(AnalysisExecutionError) as captured:
            session.execute(prepared)

        report = captured.value.report
        assert report.executed and not report.complete
        assert report.transaction_state == TransactionState.ABORTED.value
        assert report.transaction_id is not None
        assert report.error_type == "ValueError"
        metrics = database.session_coordinator.transaction_metrics(
            TransactionId(report.transaction_id)
        )
        assert metrics.final_outcome is TransactionState.ABORTED
        assert "ValueError" in metrics.failure_cause
        assert session.active_transaction is None
        assert failing.closes == 1


def test_trace_separates_lock_query_and_undo_evidence_and_is_bounded(tmp_path):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        started = session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO t VALUES (1)")
        terminal = session.execute("ROLLBACK")

        metrics = terminal.metrics
        assert metrics is not None
        assert metrics.transaction_id == started.id
        assert metrics.final_outcome is TransactionState.ABORTED
        assert metrics.undo.bytes_captured > 0
        assert metrics.undo.bytes_restored == metrics.undo.bytes_captured
        assert metrics.query_io.base_pages_read == 0
        assert metrics.completion_seconds is not None

        trace = database.session_coordinator.trace(transaction_id=started.id)
        assert [event.sequence for event in trace.events] == sorted(
            event.sequence for event in trace.events
        )
        categories = {event.category for event in trace.events}
        assert {"transaction", "logical_lock", "undo_io"} <= categories

    bounded = TransactionObservability(max_events=2)
    from engine.transactions.model import Transaction

    transaction = Transaction.begin(TransactionId(1), 1)
    bounded.begin(transaction)
    bounded.event(transaction.id, "test", "one")
    bounded.event(transaction.id, "test", "two")
    snapshot = bounded.trace()
    assert len(snapshot.events) == 2
    assert snapshot.truncated and snapshot.truncated_events == 1


def test_wait_and_stream_cancellation_abort_without_harming_peer(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        holder, waiter = database.open_session(), database.open_session()
        holder.execute("BEGIN TRANSACTION")
        holder.execute("INSERT INTO t VALUES (1)")

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(waiter.execute, "INSERT INTO t VALUES (2)")
            _wait_for_waiter(database)
            waiting_id = waiter.active_transaction.id
            assert waiter.cancel()
            with pytest.raises(TransactionAbortError):
                pending.result(timeout=5)
        cancelled = database.session_coordinator.transaction_metrics(waiting_id)
        assert cancelled.final_outcome is TransactionState.ABORTED
        assert "cancel" in cancelled.failure_cause.lower()
        holder.execute("END TRANSACTION")
        assert _rows(waiter.execute("SELECT id FROM t")) == [(1,)]

        cursor = waiter.execute("SELECT id FROM t")
        assert next(cursor).values == (1,)
        assert waiter.cancel()
        with pytest.raises(TransactionAbortError):
            next(cursor)
        assert cursor.closed and waiter.active_transaction is None
        assert database.session_coordinator.locks.snapshot().resources == ()
        holder.close()
        waiter.close()


def test_orderly_shutdown_aborts_group_before_shared_handles_close(tmp_path):
    database = Database.create(tmp_path)
    database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
    session = database.open_session()
    session.execute("BEGIN TRANSACTION")
    session.execute("INSERT INTO t VALUES (1)")

    database.shutdown(timeout_seconds=5)

    assert database.closed and session.closed
    with Database.open(tmp_path) as reopened:
        assert _rows(reopened.engine.execute("SELECT id FROM t")) == []
