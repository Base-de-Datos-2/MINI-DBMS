"""Deterministic unsafe/protected lost-update demonstration.

Run from the repository root with::

    python -m demos.transactions_demo

The unsafe adapter is intentionally confined to this demonstration module. It
creates independent ``SqlEngine`` facades over one disposable database owner
without installing the transaction router. Short storage operations remain
protected by the engine's physical latches, while the logical read/replace
business operation is deliberately unprotected.
"""

from __future__ import annotations

from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock

from engine.database import Database
from engine.query import SqlEngine
from engine.transactions import DeadlockVictimError, TransactionState


COUNTER_SELECT = "SELECT value FROM counter WHERE id = 1"
JOIN_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class AttemptEvidence:
    """One complete or aborted attempt at the increment business operation."""

    worker: str
    attempt: int
    transaction_id: int | None
    read_value: int
    written_value: int
    outcome: str
    failure: str | None = None
    lock_wait_seconds: float = 0.0
    blocker_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioEvidence:
    """Observable result of one unsafe, protected, or serial schedule."""

    initial_value: int
    final_value: int
    completed_business_operations: int
    committed_business_operations: int
    aborted_attempts: int
    attempts: tuple[AttemptEvidence, ...]


@dataclass(frozen=True, slots=True)
class TransactionDemoEvidence:
    """Complete comparison against a serial execution of the same operation."""

    unsafe: ScenarioEvidence
    protected: ScenarioEvidence
    serial_oracle: ScenarioEvidence

    @property
    def protected_matches_serial_oracle(self) -> bool:
        protected_commits = sorted(
            (item.read_value, item.written_value)
            for item in self.protected.attempts
            if item.outcome == TransactionState.COMMITTED.value
        )
        oracle_commits = sorted(
            (item.read_value, item.written_value)
            for item in self.serial_oracle.attempts
            if item.outcome == TransactionState.COMMITTED.value
        )
        return (
            self.protected.final_value == self.serial_oracle.final_value
            and self.protected.committed_business_operations
            == self.serial_oracle.committed_business_operations
            and protected_commits == oracle_commits
        )

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["protected_matches_serial_oracle"] = (
            self.protected_matches_serial_oracle
        )
        return payload


class _UnsafeSqlAdapter:
    """Demo-only SQL facade that omits logical transaction coordination."""

    def __init__(self, database: Database) -> None:
        self._engine = SqlEngine(database.environment)

    def execute(self, sql: str):
        return self._engine.execute(sql)

    def close(self) -> None:
        self._engine.close()


def _prepare_counter(directory: Path) -> Database:
    database = Database.create(directory)
    database.engine.execute(
        "CREATE TABLE counter (id INT PRIMARY KEY, value INT)"
    )
    database.engine.execute("INSERT INTO counter VALUES (1, 0)")
    return database


def _read_counter(executor) -> int:
    with executor.execute(COUNTER_SELECT) as result:
        rows = result.fetchall(limit=2)
    if len(rows) != 1:
        raise RuntimeError(f"Counter table must contain exactly one row, found {len(rows)}")
    value = rows[0].values[0]
    if type(value) is not int:
        raise RuntimeError("Counter value must be an integer")
    return value


def _replace_counter(executor, value: int) -> None:
    deleted = executor.execute("DELETE FROM counter WHERE id = 1")
    if deleted.affected_rows != 1:
        raise RuntimeError("Counter replacement must delete exactly one row")
    inserted = executor.execute(f"INSERT INTO counter VALUES (1, {value})")
    if inserted.affected_rows != 1:
        raise RuntimeError("Counter replacement must insert exactly one row")


def _run_unsafe(directory: Path) -> ScenarioEvidence:
    """Force both real SQL readers to compute from zero, then replace in pairs."""

    with _prepare_counter(directory) as database:
        adapters = (_UnsafeSqlAdapter(database), _UnsafeSqlAdapter(database))
        both_read = Barrier(2)
        replace_pair = Lock()
        attempts: list[AttemptEvidence] = []
        evidence_mutex = Lock()

        def increment(worker: str, adapter: _UnsafeSqlAdapter) -> None:
            old_value = _read_counter(adapter)
            both_read.wait(timeout=JOIN_TIMEOUT_SECONDS)
            new_value = old_value + 1
            # Serialize each physical DELETE+INSERT pair. The intended race is
            # the stale business read, not concurrent page corruption.
            with replace_pair:
                _replace_counter(adapter, new_value)
            with evidence_mutex:
                attempts.append(AttemptEvidence(
                    worker, 1, None, old_value, new_value, "UNSAFE_WRITE",
                ))

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = tuple(
                    pool.submit(increment, f"unsafe-{number}", adapter)
                    for number, adapter in enumerate(adapters, start=1)
                )
                for future in futures:
                    future.result(timeout=JOIN_TIMEOUT_SECONDS)
            final_value = _read_counter(database.engine)
        finally:
            for adapter in adapters:
                adapter.close()

    return ScenarioEvidence(
        0,
        final_value,
        2,
        0,
        0,
        tuple(sorted(attempts, key=lambda item: item.worker)),
    )


def _run_protected(directory: Path) -> ScenarioEvidence:
    """Run the same operation with rigorous 2PL and whole-operation retry."""

    with _prepare_counter(directory) as database:
        sessions = (database.open_session(), database.open_session())
        first_reads = Barrier(2)
        attempts: list[AttemptEvidence] = []
        evidence_mutex = Lock()

        def record(item: AttemptEvidence) -> None:
            with evidence_mutex:
                attempts.append(item)

        def increment(worker: str, session) -> None:
            for attempt_number in range(1, 3):
                started = session.execute("BEGIN TRANSACTION")
                old_value = _read_counter(session)
                new_value = old_value + 1
                if attempt_number == 1:
                    first_reads.wait(timeout=JOIN_TIMEOUT_SECONDS)
                try:
                    _replace_counter(session, new_value)
                    terminal = session.execute("END TRANSACTION")
                except DeadlockVictimError as error:
                    metrics = database.session_coordinator.transaction_metrics(
                        started.id
                    )
                    record(AttemptEvidence(
                        worker,
                        attempt_number,
                        started.id.value,
                        old_value,
                        new_value,
                        metrics.final_outcome.value,
                        type(error).__name__,
                        metrics.lock_wait_seconds,
                        tuple(item.value for item in metrics.blocker_ids),
                    ))
                    if metrics.final_outcome is not TransactionState.ABORTED:
                        raise RuntimeError("Deadlock victim did not finish abort cleanup")
                    continue

                if terminal.state is not TransactionState.COMMITTED:
                    raise RuntimeError("Protected increment did not commit")
                metrics = terminal.metrics
                record(AttemptEvidence(
                    worker,
                    attempt_number,
                    started.id.value,
                    old_value,
                    new_value,
                    terminal.state.value,
                    None,
                    0.0 if metrics is None else metrics.lock_wait_seconds,
                    () if metrics is None else tuple(
                        item.value for item in metrics.blocker_ids
                    ),
                ))
                return
            raise RuntimeError("Protected increment exhausted its retry budget")

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = tuple(
                    pool.submit(increment, f"protected-{number}", session)
                    for number, session in enumerate(sessions, start=1)
                )
                for future in futures:
                    future.result(timeout=JOIN_TIMEOUT_SECONDS)
            final_value = _read_counter(database.engine)
        finally:
            for session in sessions:
                session.close()

    ordered = tuple(sorted(attempts, key=lambda item: (item.worker, item.attempt)))
    return ScenarioEvidence(
        0,
        final_value,
        2,
        sum(item.outcome == TransactionState.COMMITTED.value for item in ordered),
        sum(item.outcome == TransactionState.ABORTED.value for item in ordered),
        ordered,
    )


def _run_serial_oracle(directory: Path) -> ScenarioEvidence:
    """Execute the same two business operations serially through real sessions."""

    attempts: list[AttemptEvidence] = []
    with _prepare_counter(directory) as database:
        for number in range(1, 3):
            with database.open_session() as session:
                started = session.execute("BEGIN TRANSACTION")
                old_value = _read_counter(session)
                new_value = old_value + 1
                _replace_counter(session, new_value)
                terminal = session.execute("END TRANSACTION")
                attempts.append(AttemptEvidence(
                    f"serial-{number}",
                    1,
                    started.id.value,
                    old_value,
                    new_value,
                    terminal.state.value,
                    None,
                    0.0 if terminal.metrics is None
                    else terminal.metrics.lock_wait_seconds,
                    () if terminal.metrics is None else tuple(
                        item.value for item in terminal.metrics.blocker_ids
                    ),
                ))
        final_value = _read_counter(database.engine)
    return ScenarioEvidence(0, final_value, 2, 2, 0, tuple(attempts))


def run_transaction_demo(directory: str | Path) -> TransactionDemoEvidence:
    """Create three disposable databases and return reproducible evidence."""

    root = Path(directory).resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError("Transaction demo directory must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    evidence = TransactionDemoEvidence(
        unsafe=_run_unsafe(root / "unsafe"),
        protected=_run_protected(root / "protected"),
        serial_oracle=_run_serial_oracle(root / "serial_oracle"),
    )
    if evidence.unsafe.final_value != 1:
        raise RuntimeError("Unsafe schedule did not reproduce the lost update")
    if evidence.protected.final_value != 2:
        raise RuntimeError("Protected schedule did not preserve both increments")
    if not evidence.protected_matches_serial_oracle:
        raise RuntimeError("Protected schedule differs from the serial oracle")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        help="Absent or empty directory in which to retain the three demo databases",
    )
    arguments = parser.parse_args(argv)
    if arguments.directory is not None:
        evidence = run_transaction_demo(arguments.directory)
        print(json.dumps(evidence.as_dict(), indent=2, sort_keys=True))
        return 0
    with TemporaryDirectory(prefix="minidb_transactions_demo_") as temporary:
        evidence = run_transaction_demo(temporary)
        print(json.dumps(evidence.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
