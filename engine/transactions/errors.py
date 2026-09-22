"""Structured transaction failures independent of SQL and storage layers."""

from __future__ import annotations

from engine.errors import ValidationError


class TransactionError(ValidationError):
    code = "TRANSACTION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        session_id: int | None = None,
        transaction_id: int | None = None,
    ) -> None:
        self.session_id = session_id
        self.transaction_id = transaction_id
        super().__init__(message)


class TransactionProtocolError(TransactionError):
    code = "TRANSACTION_PROTOCOL"


class SessionBusyError(TransactionProtocolError):
    code = "SESSION_BUSY"


class LockTimeoutError(TransactionError):
    code = "LOCK_TIMEOUT"


class DeadlockVictimError(TransactionError):
    code = "DEADLOCK_VICTIM"


class TransactionAbortError(TransactionError):
    code = "TRANSACTION_ABORT"


class TransactionUnavailableError(TransactionError):
    code = "TRANSACTION_UNAVAILABLE"


class TransactionCapacityError(TransactionError):
    code = "TRANSACTION_CAPACITY"
