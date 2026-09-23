"""Stage 8 Tasks 8.15-8.18: coordinated SQL and cursor integration."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import pytest

from api.database import (
    Database as LegacyDatabase,
    DatabaseDefinition,
    HEAP,
    SEQUENTIAL,
    IndexDefinition,
    TableDefinition,
)
from api.demo import DEMO_MEMORY_BUDGET_BYTES
from engine.catalog import Column, DataType, IndexType, Schema
from engine.database import Database
from engine.maintenance import MaintenanceError
from engine.query.planner import SelectPlanSpec
from engine.transactions import SessionBusyError, TransactionState
from tests.api_helpers import small_demo
from tests.operator_helpers import FailingOpen


def _values(result):
    with result:
        return [row.values for row in result]


def _wait_for_waiter(database, timeout=5):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = database.session_coordinator.locks.snapshot()
        if any(resource.waiters for resource in snapshot.resources):
            return snapshot
        sleep(0.01)
    raise AssertionError("A conflicting statement never entered the lock queue")


def test_default_engine_and_explicit_session_share_commit_semantics(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY, value INT)")

        database.engine.execute("BEGIN TRANSACTION")
        inserted = database.engine.execute("INSERT INTO t VALUES (1, 10)")
        assert inserted.affected_rows == 1
        assert inserted.provisional and not inserted.committed
        assert _values(database.engine.execute("SELECT id, value FROM t")) == [(1, 10)]
        report = database.engine.execute("END TRANSACTION")

        assert report.state is TransactionState.COMMITTED
        assert inserted.committed and not inserted.provisional
        implicit = database.engine.execute("INSERT INTO t VALUES (2, 20)")
        assert implicit.committed and not implicit.provisional
        assert implicit.transaction_id is not None
        assert _values(database.engine.execute("SELECT id FROM t ORDER BY id")) == [
            (1,), (2,),
        ]


def test_rollback_undoes_prior_sql_and_preserves_own_write_visibility(tmp_path):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        session.execute("BEGIN TRANSACTION")
        inserted = session.execute("INSERT INTO t VALUES (7)")
        assert inserted.provisional
        assert _values(session.execute("SELECT id FROM t")) == [(7,)]
        transaction_id = inserted.transaction_id

        report = session.execute("ROLLBACK")
        assert report.state is TransactionState.ABORTED
        assert transaction_id == report.id.value
        assert not inserted.committed
        assert _values(database.engine.execute("SELECT id FROM t")) == []


def test_second_sql_failure_aborts_the_prior_successful_statement(tmp_path):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute(
            "CREATE TABLE t (id INT PRIMARY KEY, label VARCHAR(3))"
        )
        session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO t VALUES (1, 'ok')")

        with pytest.raises(MaintenanceError, match="before the first write"):
            session.execute("INSERT INTO t VALUES (2, 'long')")

        assert session.active_transaction is None
        assert _values(database.engine.execute("SELECT id FROM t")) == []


def test_implicit_cursor_holds_s_until_close_then_releases_writer(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO t VALUES (1)")
        reader, writer = database.open_session(), database.open_session()
        cursor = reader.execute("SELECT id FROM t ORDER BY id")
        assert next(cursor).values == (1,)

        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(writer.execute, "INSERT INTO t VALUES (2)")
            _wait_for_waiter(database)
            assert not waiting.done()
            cursor.close()
            inserted = waiting.result(timeout=5)

        assert cursor.closed
        assert inserted.committed
        assert reader.active_transaction is None
        assert _values(database.engine.execute("SELECT id FROM t ORDER BY id")) == [
            (1,), (2,),
        ]
        reader.close()
        writer.close()


def test_explicit_eof_keeps_s_until_end_and_cursor_calls_are_serialized(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("INSERT INTO t VALUES (1)")
        reader, writer = database.open_session(), database.open_session()
        reader.execute("BEGIN TRANSACTION")
        cursor = reader.execute("SELECT id FROM t")

        assert cursor.fetchall(limit=10)[0].values == (1,)
        assert cursor.fully_consumed
        assert reader.active_transaction is not None
        reader._call.acquire()
        try:
            with pytest.raises(SessionBusyError):
                next(cursor)
        finally:
            reader._call.release()

        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(writer.execute, "INSERT INTO t VALUES (2)")
            _wait_for_waiter(database)
            assert not waiting.done()
            assert reader.execute("END TRANSACTION").state is TransactionState.COMMITTED
            assert waiting.result(timeout=5).committed
        reader.close()
        writer.close()


@pytest.mark.parametrize("finish, second_succeeds", [
    ("END TRANSACTION", False),
    ("ROLLBACK", True),
])
def test_competing_primary_key_check_runs_after_x_lock(
    tmp_path, finish, second_succeeds,
):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        first, second = database.open_session(), database.open_session()
        first.execute("BEGIN TRANSACTION")
        first.execute("INSERT INTO t VALUES (1)")

        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(second.execute, "INSERT INTO t VALUES (1)")
            _wait_for_waiter(database)
            first.execute(finish)
            if second_succeeds:
                assert waiting.result(timeout=5).committed
            else:
                with pytest.raises(MaintenanceError):
                    waiting.result(timeout=5)

        expected = [(1,)]
        assert _values(database.engine.execute("SELECT id FROM t")) == expected
        assert second.active_transaction is None
        first.close()
        second.close()


def test_cursor_operator_failure_aborts_the_whole_explicit_group(
    tmp_path, monkeypatch,
):
    with Database.create(tmp_path) as database, database.open_session() as session:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        session.execute("BEGIN TRANSACTION")
        session.execute("INSERT INTO t VALUES (1)")
        prepared = session.prepare("SELECT id FROM t")
        failing = FailingOpen()
        monkeypatch.setattr(SelectPlanSpec, "instantiate", lambda _spec: failing)
        cursor = session.execute(prepared)

        with pytest.raises(ValueError, match="injected open failure"):
            cursor.open()

        assert cursor.closed
        assert session.active_transaction is None
        assert failing.closes == 1
        monkeypatch.undo()
        assert _values(database.engine.execute("SELECT id FROM t")) == []


def test_delete_rollback_restores_heap_sequential_bplus_and_hash(tmp_path):
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("value", DataType.INTEGER),
    ])
    definition = DatabaseDefinition("adapters", (
        TableDefinition(
            "heap_rows",
            schema,
            organization=HEAP,
            indexes=(
                IndexDefinition("heap_hash", "id", IndexType.EXTENDIBLE_HASH, unique=True),
                IndexDefinition("heap_bplus", "value", IndexType.BPLUS),
            ),
            rows=lambda: ((1, 10), (2, 20), (3, 30)),
        ),
        TableDefinition(
            "ordered_rows",
            schema,
            organization=SEQUENTIAL,
            key_column="id",
            indexes=(
                IndexDefinition(
                    "ordered_clustered", "id", IndexType.BPLUS,
                    unique=True, clustered=True,
                ),
            ),
            rows=lambda: ((3, 30), (1, 10), (2, 20)),
        ),
    ))
    with LegacyDatabase.create(definition, tmp_path) as database:
        with database.open_session() as session:
            session.execute("BEGIN TRANSACTION")
            assert session.execute("DELETE FROM heap_rows WHERE id <= 2").affected_rows == 2
            assert session.execute("DELETE FROM ordered_rows WHERE id >= 2").affected_rows == 2
            assert _values(session.execute("SELECT id FROM heap_rows ORDER BY id")) == [(3,)]
            assert _values(session.execute("SELECT id FROM ordered_rows ORDER BY id")) == [(1,)]
            assert session.execute("ROLLBACK").state is TransactionState.ABORTED

        for table in ("heap_rows", "ordered_rows"):
            assert _values(database.engine.execute(
                f"SELECT id FROM {table} ORDER BY id"
            )) == [(1,), (2,), (3,)]
        for name in ("heap_hash", "heap_bplus", "ordered_clustered"):
            database._indexes[name].validate_structure()


def test_external_sort_remains_bounded_under_implicit_cursor(tmp_path):
    with LegacyDatabase.create(
        small_demo(), tmp_path, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES,
    ) as database:
        result = database.engine.execute(
            "SELECT id, student_id, grade FROM enrollments_big "
            "ORDER BY grade DESC, id"
        )
        rows = _values(result)

        assert len(rows) == 180
        assert result.statistics.temporary_pages_written > 0
        assert result.statistics.live_temporary_bytes == 0
        assert database.session_coordinator.transactions.active_count == 0


def test_programmatic_insert_joins_default_explicit_group(tmp_path):
    with Database.create(tmp_path) as database:
        database.engine.execute("CREATE TABLE t (id INT PRIMARY KEY)")
        database.engine.execute("BEGIN TRANSACTION")
        assert database.insert("t", (1,)).affected_rows == 1
        assert _values(database.engine.execute("SELECT id FROM t")) == [(1,)]
        database.engine.execute("ROLLBACK")
        assert _values(database.engine.execute("SELECT id FROM t")) == []
