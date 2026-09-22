"""Stage 8 Tasks 8.3–8.4: owner-scoped IDs and honest terminal states."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from engine.transactions import (
    DeadlockVictimError,
    LockTimeoutError,
    TransactionCapacityError,
    TransactionId,
    TransactionManager,
    TransactionProtocolError,
    TransactionState,
)


def test_transaction_state_machine_and_terminal_immutability():
    manager = TransactionManager()
    started = manager.begin(7)
    assert started.state is TransactionState.ACTIVE
    assert started.finished_at is None

    committing = manager.transition(started.id, TransactionState.COMMITTING)
    assert committing.state is TransactionState.COMMITTING
    assert committing.finished_at is None
    with pytest.raises(TransactionProtocolError):
        committing.transition(TransactionState.ABORTED)

    committed = manager.transition(started.id, TransactionState.COMMITTED)
    assert committed.terminal and committed.finished_at is not None
    with pytest.raises(TransactionProtocolError):
        committed.transition(TransactionState.ABORTING)
    with pytest.raises(FrozenInstanceError):
        committed.state = TransactionState.ABORTED

    second = manager.begin(8)
    manager.transition(second.id, TransactionState.ABORTING)
    failed = manager.transition(second.id, TransactionState.ABORT_FAILED)
    assert failed.terminal
    assert failed.state is not TransactionState.ABORTED
    assert manager.active_count == 0


def test_ids_are_unique_monotonic_across_threads_and_capacity_is_enforced():
    manager = TransactionManager(max_active=32)
    with ThreadPoolExecutor(max_workers=12) as pool:
        transactions = list(pool.map(manager.begin, range(1, 25)))
    ids = sorted(transaction.id.value for transaction in transactions)
    assert ids == list(range(1, 25))
    for transaction in transactions:
        manager.abort_empty(transaction.id)
    assert manager.active_count == 0

    limited = TransactionManager(max_active=1)
    first = limited.begin(1)
    with pytest.raises(TransactionCapacityError) as caught:
        limited.begin(2)
    assert caught.value.session_id == 2
    limited.abort_empty(first.id)
    assert limited.begin(2).id == TransactionId(2)


def test_empty_completion_reports_and_structured_error_metadata():
    manager = TransactionManager()
    first = manager.begin(4)
    report = manager.commit_empty(first.id)
    assert report.id == first.id
    assert report.session_id == 4
    assert report.state is TransactionState.COMMITTED
    assert report.finished_at is not None
    with pytest.raises(TransactionProtocolError):
        manager.current(first.id)

    for error_type, code in (
        (LockTimeoutError, "LOCK_TIMEOUT"),
        (DeadlockVictimError, "DEADLOCK_VICTIM"),
    ):
        error = error_type("stopped", session_id=4, transaction_id=9)
        assert error.code == code
        assert error.session_id == 4
        assert error.transaction_id == 9
