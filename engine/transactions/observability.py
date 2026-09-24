"""Bounded, synchronized transaction metrics and event tracing."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
from threading import RLock
from time import perf_counter

from .model import (
    QueryIoMetrics,
    Transaction,
    TransactionId,
    TransactionMetrics,
    TransactionReport,
    TransactionState,
    UndoIoMetrics,
)


@dataclass(frozen=True, slots=True)
class TransactionEvent:
    sequence: int
    timestamp: float
    transaction_id: TransactionId
    session_id: int
    category: str
    action: str
    resource: str | None = None
    mode: str | None = None
    wait_seconds: float | None = None
    blocker_ids: tuple[TransactionId, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class TraceSnapshot:
    events: tuple[TransactionEvent, ...]
    truncated_events: int
    capacity: int

    @property
    def truncated(self) -> bool:
        return self.truncated_events > 0


@dataclass(slots=True)
class _MutableMetrics:
    transaction_id: TransactionId
    session_id: int
    state: TransactionState
    held: set[str] = field(default_factory=set)
    requested: list[str] = field(default_factory=list)
    wait_seconds: float = 0.0
    blockers: set[TransactionId] = field(default_factory=set)
    failure: str | None = None
    undo_captured: int = 0
    undo_restored: int = 0
    undo_files_captured: int = 0
    undo_files_restored: int = 0
    completion_seconds: float | None = None
    final_outcome: TransactionState | None = None
    planning_seconds: float = 0.0
    execution_seconds: float = 0.0
    physical_latch_wait_seconds: float = 0.0
    query_io: QueryIoMetrics = QueryIoMetrics()


def _add_io(left: QueryIoMetrics, right: QueryIoMetrics) -> QueryIoMetrics:
    return QueryIoMetrics(*(
        getattr(left, name) + getattr(right, name)
        for name in QueryIoMetrics.__dataclass_fields__
    ))


class TransactionObservability:
    """Collect real lifecycle evidence without reading shared global counters."""

    def __init__(self, *, max_events: int = 4096) -> None:
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        self._mutex = RLock()
        self._events: deque[TransactionEvent] = deque(maxlen=max_events)
        self._max_events = max_events
        self._truncated = 0
        self._next_sequence = 1
        self._metrics: dict[TransactionId, _MutableMetrics] = {}

    def begin(self, transaction: Transaction) -> None:
        with self._mutex:
            self._metrics[transaction.id] = _MutableMetrics(
                transaction.id, transaction.session_id, transaction.state,
            )
            self._append(transaction.id, "transaction", "begin")

    def _append(
        self,
        transaction_id: TransactionId,
        category: str,
        action: str,
        *,
        resource: str | None = None,
        mode: str | None = None,
        wait_seconds: float | None = None,
        blocker_ids: tuple[TransactionId, ...] = (),
        detail: str | None = None,
    ) -> None:
        metrics = self._metrics.get(transaction_id)
        if metrics is None:
            return
        if len(self._events) == self._max_events:
            self._truncated += 1
        self._events.append(TransactionEvent(
            self._next_sequence, perf_counter(), transaction_id,
            metrics.session_id, category, action, resource, mode,
            wait_seconds, blocker_ids, detail,
        ))
        self._next_sequence += 1

    def event(self, transaction_id: TransactionId, category: str, action: str, **facts) -> None:
        with self._mutex:
            self._append(transaction_id, category, action, **facts)

    def lock_event(
        self,
        action: str,
        transaction_id: TransactionId,
        resource: str,
        mode: str,
        wait_seconds: float,
        blocker_ids: tuple[TransactionId, ...],
        detail: str | None,
    ) -> None:
        with self._mutex:
            metrics = self._metrics.get(transaction_id)
            if metrics is None:
                return
            if resource not in metrics.requested:
                metrics.requested.append(resource)
            metrics.wait_seconds += max(0.0, wait_seconds)
            metrics.blockers.update(blocker_ids)
            if action == "granted":
                metrics.held.add(resource)
            elif action in {"deadlock", "timeout", "cancelled", "unavailable"}:
                metrics.failure = detail or action
            self._append(
                transaction_id, "logical_lock", action,
                resource=resource, mode=mode, wait_seconds=max(0.0, wait_seconds),
                blocker_ids=blocker_ids, detail=detail,
            )

    def record_failure(self, transaction_id: TransactionId, error: BaseException) -> None:
        with self._mutex:
            metrics = self._metrics.get(transaction_id)
            if metrics is None:
                return
            metrics.failure = f"{type(error).__name__}: {error}"
            self._append(
                transaction_id, "transaction", "failure", detail=metrics.failure,
            )

    def record_undo_capture(self, transaction_id: TransactionId, *, bytes_count: int, files: int) -> None:
        with self._mutex:
            metrics = self._metrics[transaction_id]
            metrics.undo_captured += bytes_count
            metrics.undo_files_captured += files
            self._append(
                transaction_id, "undo_io", "capture",
                detail=f"{bytes_count} bytes across {files} files",
            )

    def record_undo_restore(self, transaction_id: TransactionId, *, bytes_count: int, files: int) -> None:
        with self._mutex:
            metrics = self._metrics[transaction_id]
            metrics.undo_restored += bytes_count
            metrics.undo_files_restored += files
            self._append(
                transaction_id, "undo_io", "restore",
                detail=f"{bytes_count} bytes across {files} files",
            )

    def record_execution(
        self,
        transaction_id: TransactionId,
        *,
        planning_seconds: float = 0.0,
        execution_seconds: float = 0.0,
        report: object | None = None,
    ) -> None:
        io = QueryIoMetrics() if report is None else QueryIoMetrics(
            report.base_pages_read,
            report.base_pages_written,
            report.index_pages_read,
            report.index_pages_written,
            report.temporary_pages_read,
            report.temporary_pages_written,
            report.temporary_metadata_reads,
            report.temporary_metadata_writes,
            report.bytes_spilled,
        )
        with self._mutex:
            metrics = self._metrics.get(transaction_id)
            if metrics is None:
                return
            metrics.planning_seconds += max(0.0, planning_seconds)
            metrics.execution_seconds += max(0.0, execution_seconds)
            metrics.query_io = _add_io(metrics.query_io, io)
            self._append(
                transaction_id, "query_io", "execution",
                detail=(
                    f"planning={max(0.0, planning_seconds):.9f}s "
                    f"execution={max(0.0, execution_seconds):.9f}s"
                ),
            )

    def record_physical_latch(
        self,
        transaction_id: TransactionId,
        *,
        wait_seconds: float,
        phase: str,
        operation: str,
    ) -> None:
        with self._mutex:
            metrics = self._metrics.get(transaction_id)
            if metrics is None:
                return
            metrics.physical_latch_wait_seconds += max(0.0, wait_seconds)
            self._append(
                transaction_id,
                "physical_latch",
                "acquired",
                wait_seconds=max(0.0, wait_seconds),
                detail=f"{phase}:{operation}",
            )

    def complete(
        self,
        report: TransactionReport,
        *,
        completion_seconds: float,
    ) -> TransactionReport:
        with self._mutex:
            metrics = self._metrics[report.id]
            metrics.state = report.state
            metrics.held.update(report.held_resources)
            metrics.completion_seconds = max(0.0, completion_seconds)
            metrics.final_outcome = report.state
            self._append(
                report.id, "transaction", "complete",
                detail=report.state.value,
            )
            return replace(report, metrics=self._freeze(metrics))

    def metrics(
        self,
        transaction_id: TransactionId,
        *,
        transaction: Transaction | None = None,
    ) -> TransactionMetrics:
        with self._mutex:
            metrics = self._metrics[transaction_id]
            if transaction is not None:
                metrics.state = transaction.state
                metrics.held.update(transaction.held_resources)
            return self._freeze(metrics)

    @staticmethod
    def _freeze(metrics: _MutableMetrics) -> TransactionMetrics:
        return TransactionMetrics(
            metrics.transaction_id,
            metrics.session_id,
            metrics.state,
            tuple(sorted(metrics.held)),
            tuple(metrics.requested),
            metrics.wait_seconds,
            tuple(sorted(metrics.blockers)),
            metrics.failure,
            UndoIoMetrics(
                metrics.undo_captured,
                metrics.undo_restored,
                metrics.undo_files_captured,
                metrics.undo_files_restored,
            ),
            metrics.completion_seconds,
            metrics.final_outcome,
            metrics.planning_seconds,
            metrics.execution_seconds,
            metrics.physical_latch_wait_seconds,
            metrics.query_io,
        )

    def trace(
        self,
        *,
        transaction_id: TransactionId | None = None,
        session_id: int | None = None,
    ) -> TraceSnapshot:
        with self._mutex:
            events = tuple(
                event for event in self._events
                if (transaction_id is None or event.transaction_id == transaction_id)
                and (session_id is None or event.session_id == session_id)
            )
            return TraceSnapshot(events, self._truncated, self._max_events)


__all__ = [
    "QueryIoMetrics",
    "TraceSnapshot",
    "TransactionEvent",
    "TransactionMetrics",
    "TransactionObservability",
    "UndoIoMetrics",
]
