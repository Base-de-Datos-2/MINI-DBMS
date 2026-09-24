"""Stage 8 Task 8.27: bounded, seeded transaction stress evidence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from random import Random
from threading import Barrier
from time import monotonic, sleep

import pytest

from engine.database import Database
from engine.maintenance import MaintenanceError
from engine.transactions.undo import UNDO_DIRECTORY, UNCLEAN_MARKER, UndoLimits


STRESS_SEED = 827_2026
WORKER_COUNT = 4
INSERTS_PER_WORKER = 6
DELETES_PER_WORKER = 2
JOIN_TIMEOUT_SECONDS = 15.0
MEMORY_BUDGET_BYTES = 64 << 10


@dataclass(frozen=True, slots=True)
class _WorkerPlan:
    worker: int
    table: str
    rows: tuple[tuple[int, int], ...]
    deleted_keys: tuple[int, ...]
    rollback_row: tuple[int, int]
    failed_row: tuple[int, int]


def _rows(result) -> list[tuple[object, ...]]:
    with result:
        return [row.values for row in result]


def _plans() -> tuple[_WorkerPlan, ...]:
    random = Random(STRESS_SEED)
    plans = []
    for worker in range(WORKER_COUNT):
        base = (worker + 1) * 100
        keys = random.sample(range(base, base + 40), INSERTS_PER_WORKER)
        rows = tuple((key, random.randrange(1, 10_000)) for key in keys)
        deleted = tuple(sorted(random.sample(keys, DELETES_PER_WORKER)))
        plans.append(_WorkerPlan(
            worker=worker,
            table="table_a" if worker % 2 == 0 else "table_b",
            rows=rows,
            deleted_keys=deleted,
            rollback_row=(base + 50, random.randrange(1, 10_000)),
            failed_row=(base + 51, random.randrange(1, 10_000)),
        ))
    return tuple(plans)


def _expected_rows(plans: tuple[_WorkerPlan, ...], table: str):
    return sorted(
        row
        for plan in plans
        if plan.table == table
        for row in plan.rows
        if row[0] not in plan.deleted_keys
    )


def _wait_for_lock_waiter(database: Database, timeout: float = 5.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = database.session_coordinator.locks.snapshot()
        waiters = tuple(
            waiter
            for resource in snapshot.resources
            for waiter in resource.waiters
        )
        if waiters:
            return waiters
        sleep(0.005)
    raise AssertionError("Expected the bounded workload to expose a lock waiter")


def _run_worker(database: Database, plan: _WorkerPlan, start: Barrier):
    with database.open_session() as session:
        start.wait(timeout=JOIN_TIMEOUT_SECONDS)

        session.execute("BEGIN TRANSACTION")
        for key, value in plan.rows:
            session.execute(
                f"INSERT INTO {plan.table} VALUES ({key}, {value})"
            )
        observed = _rows(session.execute(
            f"SELECT id, value FROM {plan.table} "
            f"WHERE id >= {plan.worker + 1}00 "
            f"AND id < {plan.worker + 1}40 ORDER BY id"
        ))
        assert observed == sorted(plan.rows)
        committed = session.execute("END TRANSACTION")
        assert committed.state.value == "COMMITTED"

        session.execute("BEGIN TRANSACTION")
        session.execute(
            f"INSERT INTO {plan.table} VALUES "
            f"({plan.rollback_row[0]}, {plan.rollback_row[1]})"
        )
        assert session.execute("ROLLBACK").state.value == "ABORTED"

        session.execute("BEGIN TRANSACTION")
        session.execute(
            f"INSERT INTO {plan.table} VALUES "
            f"({plan.failed_row[0]}, {plan.failed_row[1]})"
        )
        duplicate_key, duplicate_value = plan.rows[0]
        with pytest.raises(MaintenanceError):
            session.execute(
                f"INSERT INTO {plan.table} VALUES "
                f"({duplicate_key}, {duplicate_value})"
            )
        assert session.active_transaction is None

        for key in plan.deleted_keys:
            deleted = session.execute(
                f"DELETE FROM {plan.table} WHERE id = {key}"
            )
            assert deleted.committed and deleted.affected_rows == 1

        return plan.worker


def _assert_table_matches_oracle(
    database: Database,
    table: str,
    expected: list[tuple[int, int]],
    absent_keys: tuple[int, ...],
) -> None:
    sql_rows = _rows(database.engine.execute(
        f"SELECT id, value FROM {table} ORDER BY id"
    ))
    assert sql_rows == expected
    assert len({row[0] for row in sql_rows}) == len(sql_rows)

    storage = database.storage_for(table)
    base_rows = sorted(record.values for _, record in storage.scan())
    assert base_rows == expected

    index = database.index_for(f"__pk__{table}")
    report = index.validate_structure()
    assert report.entry_count == len(expected)
    assert index.entry_count == len(expected)
    for row in expected:
        matches = list(index.search(row[0]))
        assert len(matches) == 1
        assert storage.read(matches[0]).values == row
    for key in absent_keys:
        assert list(index.search(key)) == []


def test_seeded_bounded_workload_preserves_oracle_indexes_and_resources(tmp_path):
    plans = _plans()
    expected = {
        table: _expected_rows(plans, table)
        for table in ("table_a", "table_b")
    }
    absent = {
        table: tuple(
            key
            for plan in plans
            if plan.table == table
            for key in (
                *plan.deleted_keys,
                plan.rollback_row[0],
                plan.failed_row[0],
            )
        )
        for table in ("table_a", "table_b")
    }
    limits = UndoLimits(
        per_transaction_bytes=4 << 20,
        total_bytes=16 << 20,
        chunk_bytes=4096,
        concurrent_captures=2,
        free_reserve_bytes=0,
    )

    with Database.create(
        tmp_path,
        memory_budget_bytes=MEMORY_BUDGET_BYTES,
        max_open_handles=4,
        materialization_limit=16,
        undo_limits=limits,
    ) as database:
        for table in ("table_a", "table_b", "wait_table"):
            database.engine.execute(
                f"CREATE TABLE {table} (id INT PRIMARY KEY, value INT)"
            )
        database.engine.execute("INSERT INTO wait_table VALUES (0, 0)")

        start = Barrier(WORKER_COUNT)
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as pool:
            futures = [
                pool.submit(_run_worker, database, plan, start)
                for plan in plans
            ]
            assert sorted(
                future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures
            ) == list(range(WORKER_COUNT))

        holder, waiter = database.open_session(), database.open_session()
        holder.execute("BEGIN TRANSACTION")
        holder.execute("INSERT INTO wait_table VALUES (1, 10)")
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                waiter.execute, "INSERT INTO wait_table VALUES (2, 20)"
            )
            waits = _wait_for_lock_waiter(database)
            assert waits[0].blockers == (holder.active_transaction.id,)
            assert not pending.done()
            assert holder.execute("ROLLBACK").state.value == "ABORTED"
            assert pending.result(timeout=JOIN_TIMEOUT_SECONDS).committed
        holder.close()
        waiter.close()

        for table in ("table_a", "table_b"):
            _assert_table_matches_oracle(
                database, table, expected[table], absent[table]
            )
        assert _rows(database.engine.execute(
            "SELECT id, value FROM wait_table ORDER BY id"
        )) == [(0, 0), (2, 20)]
        database.index_for("__pk__wait_table").validate_structure()

        coordinator = database.session_coordinator
        assert coordinator.transactions.active_count == 0
        assert coordinator.locks.snapshot().resources == ()
        assert coordinator.session_count == 1
        assert not (tmp_path / UNCLEAN_MARKER).exists()
        undo_root = tmp_path / UNDO_DIRECTORY
        assert not undo_root.exists() or not any(undo_root.iterdir())

    with Database.open(
        tmp_path,
        memory_budget_bytes=MEMORY_BUDGET_BYTES,
        max_open_handles=4,
        materialization_limit=16,
        undo_limits=limits,
    ) as reopened:
        for table in ("table_a", "table_b"):
            _assert_table_matches_oracle(
                reopened, table, expected[table], absent[table]
            )
        assert _rows(reopened.engine.execute(
            "SELECT id, value FROM wait_table ORDER BY id"
        )) == [(0, 0), (2, 20)]
        assert reopened.session_coordinator.transactions.active_count == 0
        assert reopened.session_coordinator.locks.snapshot().resources == ()
