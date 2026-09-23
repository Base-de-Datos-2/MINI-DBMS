"""Stage 8 Task 8.4: shared owner, separate sessions and fail-closed calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from api.database import Database as LegacyDatabase
from tests.api_helpers import small_demo
from engine.database import Database
from engine.query.errors import SqlSyntaxError
from engine.transactions import (
    SessionBusyError,
    TransactionProtocolError,
    TransactionState,
    TransactionUnavailableError,
)
from engine.transactions import session as session_module


def test_independent_control_sessions_share_one_owner_and_preserve_default_engine(tmp_path):
    with Database.create(tmp_path) as database:
        first = database.open_session()
        second = database.open_session()
        assert first.id != second.id
        assert first._engine is not second._engine
        assert first._engine.environment is second._engine.environment is database.environment
        assert database.session_coordinator.default_session._engine is database.engine
        assert database.session_coordinator.locks.database_identity == database.identity
        assert database.session_coordinator.locks.snapshot().resources == ()
        assert database.session_coordinator.session_count == 3

        started_first = first.execute("BEGIN TRANSACTION")
        started_second = second.execute("-- comment\nBEGIN TRANSACTION;")
        assert started_first.state is started_second.state is TransactionState.ACTIVE
        assert started_first.id != started_second.id
        assert first.execute("END TRANSACTION").state is TransactionState.COMMITTED
        assert second.execute("ROLLBACK").state is TransactionState.ABORTED

        first.close()
        assert database.session_coordinator.session_count == 2
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO t VALUES (1)")
        with database.engine.execute("SELECT id FROM t") as result:
            assert [row.values for row in result] == [(1,)]
        assert not second.closed
        second.close()


def test_separate_session_facades_have_independent_result_slots(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT)")
        first = database.open_session()
        second = database.open_session()
        # The raw facades are used sequentially here only to verify ownership;
        # coordinated data execution remains gated until undo and lock integration.
        first_result = first._engine.execute("SELECT id FROM t")
        second_result = second._engine.execute("SELECT id FROM t")
        assert first.active_result is first_result
        assert second.active_result is second_result
        first_result.close()
        assert first.active_result is None
        assert second.active_result is second_result
        second_result.close()


def test_protocol_errors_data_execution_and_one_statement_boundary(tmp_path):
    with Database.create(tmp_path) as database, database.open_session() as session:
        with pytest.raises(SqlSyntaxError):
            session.execute("BEGIN TRANSACTION; INSERT INTO t VALUES (1)")
        assert session.active_transaction is None

        with pytest.raises(TransactionProtocolError):
            session.execute("END TRANSACTION")
        session.execute("BEGIN TRANSACTION")
        with pytest.raises(TransactionProtocolError, match="Nested"):
            session.execute("BEGIN TRANSACTION")
        assert session.active_transaction is not None

        with pytest.raises(SqlSyntaxError):
            session.execute("ROLLBACK; SELECT * FROM t")
        assert session.active_transaction is None
        with pytest.raises(TransactionProtocolError):
            session.execute("END TRANSACTION")

        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        session.execute("BEGIN TRANSACTION")
        inserted = session.execute("INSERT INTO t VALUES (1)")
        assert inserted.provisional and not inserted.committed
        assert session.active_transaction is not None
        assert session.execute("END TRANSACTION").state is TransactionState.COMMITTED
        assert inserted.committed and not inserted.provisional


def test_same_session_call_rejected_while_another_session_progresses(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        first = database.open_session()
        second = database.open_session()
        entered = Event()
        release = Event()
        original_parse = session_module.parse_sql

        def blocking_parse(sql):
            if sql == "BEGIN TRANSACTION" and not entered.is_set():
                entered.set()
                assert release.wait(5)
            return original_parse(sql)

        monkeypatch.setattr(session_module, "parse_sql", blocking_parse)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(first.execute, "BEGIN TRANSACTION")
            assert entered.wait(5)
            with pytest.raises(SessionBusyError):
                first.execute("ROLLBACK")
            assert second.execute("BEGIN TRANSACTION").state is TransactionState.ACTIVE
            release.set()
            assert pending.result(timeout=5).state is TransactionState.ACTIVE
        first.close()
        second.close()
        assert database.session_coordinator.transactions.active_count == 0


def test_duplicate_in_process_owner_is_rejected_and_lease_released(tmp_path):
    with Database.create(tmp_path) as database:
        with pytest.raises(TransactionUnavailableError, match="already holds"):
            Database.open(tmp_path)
        with pytest.raises(TransactionUnavailableError, match="already holds"):
            LegacyDatabase.open(small_demo(), tmp_path)
        session = database.open_session()
        session.execute("BEGIN TRANSACTION")
    assert session.closed
    with Database.open(tmp_path) as reopened:
        assert reopened.session_coordinator.transactions.active_count == 0


def test_legacy_owner_has_same_coordinator_and_independent_control_sessions(tmp_path):
    with LegacyDatabase.create(small_demo(), tmp_path) as database:
        first = database.open_session()
        second = database.open_session()
        assert first._engine.environment is second._engine.environment
        assert database.session_coordinator.resources.database_identity == str(tmp_path.resolve())
        assert first.execute("BEGIN TRANSACTION").state is TransactionState.ACTIVE
        assert second.execute("BEGIN TRANSACTION").state is TransactionState.ACTIVE
        first.close()
        assert not second.closed
        second.close()


def test_owner_close_preflights_busy_sessions_before_closing_default(tmp_path, monkeypatch):
    with Database.create(tmp_path) as database:
        session = database.open_session()
        entered, release = Event(), Event()
        original_parse = session_module.parse_sql

        def blocking_parse(sql):
            if sql == "BEGIN TRANSACTION":
                entered.set()
                assert release.wait(5)
            return original_parse(sql)

        monkeypatch.setattr(session_module, "parse_sql", blocking_parse)
        with ThreadPoolExecutor(max_workers=1) as pool:
            executing = pool.submit(session.execute, "BEGIN TRANSACTION")
            assert entered.wait(5)
            with pytest.raises(SessionBusyError, match="deferred"):
                database.close()
            assert not database.closed
            assert not database.session_coordinator.default_session.closed
            assert database.session_coordinator.session_count == 2
            release.set()
            executing.result(timeout=5)
        database.close()
        assert database.closed and session.closed
