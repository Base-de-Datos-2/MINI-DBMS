"""Owner-scoped transaction IDs and state transitions.

Only empty groups can complete in Block 2. Lock release, undo, and durable
commit are added before data statements are admitted to coordinated sessions.
"""

from __future__ import annotations

from threading import RLock

from .errors import TransactionCapacityError, TransactionProtocolError, TransactionUnavailableError
from .model import Transaction, TransactionId, TransactionReport, TransactionState


DEFAULT_MAX_ACTIVE_TRANSACTIONS = 32


class TransactionManager:
    def __init__(self, *, max_active: int = DEFAULT_MAX_ACTIVE_TRANSACTIONS) -> None:
        if type(max_active) is not int or max_active < 1:
            raise ValueError("max_active must be a positive integer")
        self._mutex = RLock()
        self._next_id = 1
        self._active: dict[TransactionId, Transaction] = {}
        self._max_active = max_active

    @property
    def active_count(self) -> int:
        with self._mutex:
            return len(self._active)

    def begin(self, session_id: int) -> Transaction:
        with self._mutex:
            if len(self._active) >= self._max_active:
                raise TransactionCapacityError(
                    "Active transaction limit reached", session_id=session_id
                )
            transaction = Transaction.begin(TransactionId(self._next_id), session_id)
            self._next_id += 1
            self._active[transaction.id] = transaction
            return transaction

    def current(self, transaction_id: TransactionId) -> Transaction:
        with self._mutex:
            try:
                return self._active[transaction_id]
            except KeyError as error:
                raise TransactionProtocolError(
                    "Transaction is no longer active",
                    transaction_id=transaction_id.value,
                ) from error

    def transition(self, transaction_id: TransactionId, target: TransactionState) -> Transaction:
        with self._mutex:
            transaction = self.current(transaction_id).transition(target)
            self._active[transaction_id] = transaction
            if transaction.terminal:
                del self._active[transaction_id]
            return transaction

    def _require_empty(self, transaction: Transaction) -> None:
        if (transaction.held_resources or transaction.touched_tables
                or transaction.undo_references):
            raise TransactionUnavailableError(
                "Data-bearing transaction completion needs locking and undo integration",
                session_id=transaction.session_id,
                transaction_id=transaction.id.value,
            )

    def commit_empty(self, transaction_id: TransactionId) -> TransactionReport:
        with self._mutex:
            transaction = self.current(transaction_id)
            self._require_empty(transaction)
            self.transition(transaction_id, TransactionState.COMMITTING)
            completed = self.transition(transaction_id, TransactionState.COMMITTED)
            return TransactionReport.from_transaction(completed)

    def abort_empty(self, transaction_id: TransactionId) -> TransactionReport:
        with self._mutex:
            transaction = self.current(transaction_id)
            self._require_empty(transaction)
            self.transition(transaction_id, TransactionState.ABORTING)
            completed = self.transition(transaction_id, TransactionState.ABORTED)
            return TransactionReport.from_transaction(completed)
