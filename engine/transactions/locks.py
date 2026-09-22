"""Shared lock-manager boundary awaiting Task 8.7 S/X implementation."""

from __future__ import annotations

from .errors import TransactionUnavailableError


class LockManager:
    """One owner-local lock domain; grants fail closed until Block 3."""

    def __init__(self, database_identity: str) -> None:
        self.database_identity = database_identity

    def acquire(self, *args, **kwargs) -> None:
        raise TransactionUnavailableError(
            "S/X lock granting is pending Task 8.7"
        )
