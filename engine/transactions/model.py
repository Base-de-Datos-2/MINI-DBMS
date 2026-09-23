"""Immutable transaction records and the Stage 8 lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from time import perf_counter

from .errors import TransactionProtocolError


class TransactionState(Enum):
    ACTIVE = "ACTIVE"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    ABORT_FAILED = "ABORT_FAILED"


_NEXT: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.ACTIVE: frozenset(
        {TransactionState.COMMITTING, TransactionState.ABORTING}
    ),
    TransactionState.COMMITTING: frozenset(
        {TransactionState.COMMITTED, TransactionState.ABORTING}
    ),
    TransactionState.ABORTING: frozenset(
        {TransactionState.ABORTED, TransactionState.ABORT_FAILED}
    ),
}


@dataclass(frozen=True, slots=True, order=True)
class TransactionId:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or self.value < 1:
            raise ValueError("Transaction ID must be a positive integer")


@dataclass(frozen=True, slots=True)
class Transaction:
    id: TransactionId
    session_id: int
    state: TransactionState
    started_at: float
    finished_at: float | None = None
    held_resources: frozenset[str] = frozenset()
    touched_tables: frozenset[str] = frozenset()
    undo_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, TransactionId):
            raise TypeError("Transaction.id must be TransactionId")
        if type(self.session_id) is not int or self.session_id < 1:
            raise ValueError("Session ID must be a positive integer")
        if not isinstance(self.state, TransactionState):
            raise TypeError("Transaction.state must be TransactionState")
        if self.terminal != (self.finished_at is not None):
            raise ValueError("Only completed terminal transactions have a finish time")

    @classmethod
    def begin(cls, transaction_id: TransactionId, session_id: int) -> "Transaction":
        if type(session_id) is not int or session_id < 1:
            raise ValueError("Session ID must be a positive integer")
        return cls(transaction_id, session_id, TransactionState.ACTIVE, perf_counter())

    @property
    def terminal(self) -> bool:
        return self.state in {
            TransactionState.COMMITTED,
            TransactionState.ABORTED,
            TransactionState.ABORT_FAILED,
        }

    def transition(self, target: TransactionState) -> "Transaction":
        if not isinstance(target, TransactionState) or target not in _NEXT.get(
            self.state, frozenset()
        ):
            raise TransactionProtocolError(
                f"Invalid transaction transition {self.state.value} -> {getattr(target, 'value', target)}",
                session_id=self.session_id,
                transaction_id=self.id.value,
            )
        return replace(
            self,
            state=target,
            finished_at=perf_counter() if target in {
                TransactionState.COMMITTED,
                TransactionState.ABORTED,
                TransactionState.ABORT_FAILED,
            } else None,
        )

    def with_resources(
        self,
        *,
        held: frozenset[str] | None = None,
        touched: frozenset[str] | None = None,
        undo: tuple[str, ...] | None = None,
    ) -> "Transaction":
        if self.state is not TransactionState.ACTIVE:
            raise TransactionProtocolError(
                "Only an active transaction can add resources",
                session_id=self.session_id,
                transaction_id=self.id.value,
            )
        return replace(
            self,
            held_resources=self.held_resources | (frozenset() if held is None else held),
            touched_tables=self.touched_tables | (frozenset() if touched is None else touched),
            undo_references=self.undo_references + (() if undo is None else undo),
        )


@dataclass(frozen=True, slots=True)
class TransactionReport:
    id: TransactionId
    session_id: int
    state: TransactionState
    started_at: float
    finished_at: float | None
    held_resources: tuple[str, ...]
    touched_tables: tuple[str, ...]
    undo_references: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_transaction(cls, transaction: Transaction) -> "TransactionReport":
        return cls(
            transaction.id,
            transaction.session_id,
            transaction.state,
            transaction.started_at,
            transaction.finished_at,
            tuple(sorted(transaction.held_resources)),
            tuple(sorted(transaction.touched_tables)),
            transaction.undo_references,
        )
