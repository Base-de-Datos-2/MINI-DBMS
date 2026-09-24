"""Owner-local rigorous S/X locks with FIFO waits and deadlock detection.

The condition protects only lock metadata. It is released during waits; no
storage, index, or user callback runs under it. Failed waiters retain prior
grants until abort finishes and release_all receives a terminal report.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from math import isfinite
from threading import Condition, RLock
from time import monotonic, perf_counter_ns

from .errors import (
    DeadlockVictimError, LockTimeoutError, TransactionAbortError,
    TransactionProtocolError, TransactionUnavailableError,
)
from .model import Transaction, TransactionId, TransactionReport, TransactionState
from .resources import AccessPlan, LockMode, SchemaMode, TableResource


DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class SchemaResource:
    database_identity: str


Resource = SchemaResource | TableResource


@dataclass(frozen=True, slots=True)
class WaitSnapshot:
    transaction_id: TransactionId
    resource: Resource
    mode: LockMode
    sequence: int
    blockers: tuple[TransactionId, ...]


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    resource: Resource
    holders: tuple[tuple[TransactionId, LockMode], ...]
    waiters: tuple[WaitSnapshot, ...]


@dataclass(frozen=True, slots=True)
class LockSnapshot:
    resources: tuple[ResourceSnapshot, ...]
    wait_for: tuple[tuple[TransactionId, tuple[TransactionId, ...]], ...]
    unavailable: bool


@dataclass(slots=True, eq=False)
class _Request:
    transaction_id: TransactionId
    resource: Resource
    mode: LockMode
    sequence: int
    started_ns: int
    granted: bool = False


@dataclass(slots=True)
class _Entry:
    holders: dict[TransactionId, LockMode] = field(default_factory=dict)
    queue: list[_Request] = field(default_factory=list)


def _conflicts(requested: LockMode, held: LockMode) -> bool:
    return requested is LockMode.X or held is LockMode.X


def _resource_order(resource: Resource) -> tuple[str, str, str]:
    if isinstance(resource, SchemaResource):
        return resource.database_identity, "", ""
    return resource.database_identity, "table", resource.table_identity


def resource_label(resource: Resource) -> str:
    """Return a stable diagnostic label without exposing filesystem paths."""

    if isinstance(resource, SchemaResource):
        return "schema"
    return f"table:{resource.table_identity}"


class LockManager:
    """One database's logical lock domain; transaction IDs must be registered."""

    def __init__(
        self, database_identity: str, *,
        timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        observer: Callable[..., None] | None = None,
    ) -> None:
        if not isinstance(database_identity, str) or not database_identity:
            raise ValueError("database_identity must be a nonempty string")
        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be a positive finite number")
        self.database_identity = database_identity
        self.schema_resource = SchemaResource(database_identity)
        self._default_timeout = float(timeout_seconds)
        self._condition = Condition(RLock())
        self._entries: dict[Resource, _Entry] = {}
        self._held: dict[TransactionId, dict[Resource, LockMode]] = {}
        self._sessions: dict[TransactionId, int] = {}
        self._waiting: dict[TransactionId, _Request] = {}
        self._failed: dict[TransactionId, Exception] = {}
        self._retired: set[TransactionId] = set()
        self._next_sequence = 1
        self._unavailable = False
        self._observer = observer

    def _observe(
        self,
        action: str,
        transaction_id: TransactionId,
        resource: Resource,
        mode: LockMode,
        *,
        wait_seconds: float = 0.0,
        blockers: tuple[TransactionId, ...] = (),
        detail: str | None = None,
    ) -> None:
        if self._observer is not None:
            self._observer(
                action,
                transaction_id,
                resource_label(resource),
                mode.value,
                wait_seconds,
                blockers,
                detail,
            )

    def register(self, transaction: Transaction) -> None:
        if (not isinstance(transaction, Transaction)
                or transaction.state is not TransactionState.ACTIVE):
            raise TransactionProtocolError("Only an active transaction can register locks")
        with self._condition:
            self._require_available()
            if transaction.id in self._held or transaction.id in self._retired:
                raise TransactionProtocolError(
                    "Transaction ID is already registered or completed",
                    transaction_id=transaction.id.value,
                )
            self._held[transaction.id] = {}
            self._sessions[transaction.id] = transaction.session_id

    def _require_available(self) -> None:
        if self._unavailable:
            raise TransactionUnavailableError("Lock domain is unavailable")

    def _require_active(self, transaction_id: TransactionId) -> None:
        self._require_available()
        if transaction_id not in self._held:
            raise TransactionProtocolError(
                "Transaction is not registered for locks",
                transaction_id=transaction_id.value,
            )
        failure = self._failed.get(transaction_id)
        if failure is not None:
            raise failure

    def _validate_resource(self, resource: Resource) -> None:
        if not isinstance(resource, (SchemaResource, TableResource)):
            raise TypeError("Lock resource must be a schema or table resource")
        if resource.database_identity != self.database_identity:
            raise TransactionProtocolError("Lock resource belongs to another database")

    @staticmethod
    def _blockers(request: _Request, entry: _Entry) -> set[TransactionId]:
        blockers = {
            owner for owner, mode in entry.holders.items()
            if owner != request.transaction_id and _conflicts(request.mode, mode)
        }
        for earlier in entry.queue:
            if earlier is request:
                break
            if earlier.transaction_id != request.transaction_id and _conflicts(
                request.mode, earlier.mode
            ):
                blockers.add(earlier.transaction_id)
        return blockers

    def _graph(self) -> dict[TransactionId, set[TransactionId]]:
        return {
            transaction_id: self._blockers(request, self._entries[request.resource])
            for transaction_id, request in self._waiting.items()
        }

    @staticmethod
    def _closes_cycle(
        requester: TransactionId, graph: dict[TransactionId, set[TransactionId]],
    ) -> bool:
        stack = list(graph.get(requester, ()))
        seen: set[TransactionId] = set()
        while stack:
            current = stack.pop()
            if current == requester:
                return True
            if current not in seen:
                seen.add(current)
                stack.extend(graph.get(current, ()))
        return False

    def _grant(self, request: _Request, entry: _Entry) -> None:
        prior = entry.holders.get(request.transaction_id)
        mode = LockMode.X if request.mode is LockMode.X or prior is LockMode.X else LockMode.S
        entry.holders[request.transaction_id] = mode
        self._held[request.transaction_id][request.resource] = mode
        request.granted = True
        self._waiting.pop(request.transaction_id, None)
        entry.queue.remove(request)

    def _drain(self, resource: Resource) -> None:
        entry = self._entries.get(resource)
        if entry is None:
            return
        if self._unavailable:
            if not entry.holders and not entry.queue:
                self._entries.pop(resource, None)
            self._condition.notify_all()
            return
        for request in tuple(entry.queue):
            if request.transaction_id in self._failed or request.transaction_id not in self._held:
                entry.queue.remove(request)
                self._waiting.pop(request.transaction_id, None)
                continue
            if self._blockers(request, entry):
                break
            self._grant(request, entry)
        if not entry.holders and not entry.queue:
            self._entries.pop(resource, None)
        self._condition.notify_all()

    def _fail_wait(self, transaction_id: TransactionId, error: Exception) -> None:
        self._failed[transaction_id] = error
        request = self._waiting.pop(transaction_id, None)
        if request is not None:
            entry = self._entries[request.resource]
            entry.queue.remove(request)
            self._drain(request.resource)
        self._condition.notify_all()

    def acquire(
        self, transaction_id: TransactionId, resource: Resource,
        mode: LockMode, *, timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(transaction_id, TransactionId):
            raise TypeError("transaction_id must be TransactionId")
        self._validate_resource(resource)
        if not isinstance(mode, LockMode):
            raise TypeError("mode must be LockMode")
        timeout = self._default_timeout if timeout_seconds is None else timeout_seconds
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout_seconds must be a positive finite number")
        deadline = monotonic() + timeout
        with self._condition:
            self._require_active(transaction_id)

            if (isinstance(resource, TableResource)
                    and self.schema_resource not in self._held[transaction_id]):
                raise TransactionProtocolError(
                    "Acquire schema S or X before a table lock",
                    transaction_id=transaction_id.value,
                )
            current = self._held[transaction_id].get(resource)
            if current is LockMode.X or current is mode:
                self._observe("retained", transaction_id, resource, current)
                return
            if transaction_id in self._waiting:
                raise TransactionProtocolError(
                    "Transaction already has a pending lock request",
                    transaction_id=transaction_id.value,
                )
            entry = self._entries.setdefault(resource, _Entry())
            request = _Request(
                transaction_id, resource, mode, self._next_sequence, perf_counter_ns(),
            )
            self._next_sequence += 1
            entry.queue.append(request)
            self._waiting[transaction_id] = request
            blockers = tuple(sorted(self._blockers(request, entry)))
            self._observe(
                "requested", transaction_id, resource, mode, blockers=blockers,
            )
            if not blockers:
                self._grant(request, entry)
                self._drain(resource)
                self._observe("granted", transaction_id, resource, mode)
                return
            self._observe(
                "waiting", transaction_id, resource, mode, blockers=blockers,
            )
            if self._closes_cycle(transaction_id, self._graph()):
                error = DeadlockVictimError(
                    "Lock request closed a wait-for cycle",
                    transaction_id=transaction_id.value,
                )
                elapsed = (perf_counter_ns() - request.started_ns) / 1_000_000_000
                blockers = tuple(sorted(self._blockers(request, entry)))
                self._fail_wait(transaction_id, error)
                self._observe(
                    "deadlock", transaction_id, resource, mode,
                    wait_seconds=elapsed, blockers=blockers,
                    detail=f"{type(error).__name__}: {error}",
                )
                raise error
            while not request.granted:
                self._require_active(transaction_id)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    error = LockTimeoutError(
                        "Lock wait deadline expired",
                        transaction_id=transaction_id.value,
                    )
                    elapsed = (perf_counter_ns() - request.started_ns) / 1_000_000_000
                    blockers = tuple(sorted(self._blockers(request, entry)))
                    self._fail_wait(transaction_id, error)
                    self._observe(
                        "timeout", transaction_id, resource, mode,
                        wait_seconds=elapsed, blockers=blockers,
                        detail=f"{type(error).__name__}: {error}",
                    )
                    raise error
                self._condition.wait(remaining)
            try:
                self._require_active(transaction_id)
            except BaseException as error:
                self._observe(
                    "cancelled", transaction_id, resource, mode,
                    wait_seconds=(
                        perf_counter_ns() - request.started_ns
                    ) / 1_000_000_000,
                    blockers=blockers,
                    detail=f"{type(error).__name__}: {error}",
                )
                raise
            self._observe(
                "granted", transaction_id, resource, mode,
                wait_seconds=(
                    perf_counter_ns() - request.started_ns
                ) / 1_000_000_000,
                blockers=blockers,
            )

    def acquire_plan(
        self, transaction_id: TransactionId, plan: AccessPlan, *,
        timeout_seconds: float | None = None,
    ) -> None:
        """Acquire schema first, then the plan's ordered base-table resources.

        The caller revalidates the plan under the schema grant and before data
        access after a table wait. Failed acquisition retains prior grants for
        the caller's abort path.
        """

        if not isinstance(plan, AccessPlan):
            raise TypeError("plan must be AccessPlan")
        if not isinstance(transaction_id, TransactionId):
            raise TypeError("transaction_id must be TransactionId")
        if plan.schema is SchemaMode.NONE:
            if plan.tables:
                raise TransactionProtocolError("Data intents require a schema gate")
            with self._condition:
                self._require_active(transaction_id)
            return
        ordered = tuple(sorted(plan.tables, key=lambda intent: intent.resource))
        if ordered != plan.tables or len({intent.resource for intent in ordered}) != len(ordered):
            raise TransactionProtocolError("Table intents must be distinct and ordered")
        self.acquire(
            transaction_id, self.schema_resource,
            LockMode.X if plan.schema is SchemaMode.X else LockMode.S,
            timeout_seconds=timeout_seconds,
        )
        for intent in ordered:
            self.acquire(
                transaction_id, intent.resource, intent.mode,
                timeout_seconds=timeout_seconds,
            )

    def cancel(self, transaction_id: TransactionId) -> None:
        """Stop a waiter cooperatively; held locks remain through abort cleanup."""
        with self._condition:
            if transaction_id in self._held and transaction_id not in self._failed:
                request = self._waiting.get(transaction_id)
                if request is not None:
                    entry = self._entries[request.resource]
                    blockers = tuple(sorted(self._blockers(request, entry)))
                    elapsed = (
                        perf_counter_ns() - request.started_ns
                    ) / 1_000_000_000
                    resource = request.resource
                    mode = request.mode
                else:
                    blockers = ()
                    elapsed = 0.0
                    resource = self.schema_resource
                    mode = self._held[transaction_id].get(resource, LockMode.S)
                self._fail_wait(
                    transaction_id,
                    TransactionAbortError(
                        "Lock request cancelled", transaction_id=transaction_id.value
                    ),
                )
                self._observe(
                    "cancelled", transaction_id, resource, mode,
                    wait_seconds=elapsed, blockers=blockers,
                    detail="TransactionAbortError: Lock request cancelled",
                )

    def release_all(self, report: TransactionReport) -> None:
        """Release only after completed commit or successful abort."""
        if not isinstance(report, TransactionReport) or report.state not in {
            TransactionState.COMMITTED, TransactionState.ABORTED,
        }:
            raise TransactionProtocolError("Locks require a completed terminal report")
        with self._condition:
            transaction_id = report.id
            if transaction_id in self._retired:
                return
            if transaction_id not in self._held:
                raise TransactionProtocolError(
                    "Transaction is not registered for locks",
                    transaction_id=transaction_id.value,
                )
            if report.session_id != self._sessions[transaction_id]:
                raise TransactionProtocolError(
                    "Terminal report belongs to another session",
                    transaction_id=transaction_id.value,
                )
            request = self._waiting.pop(transaction_id, None)
            if request is not None:
                self._entries[request.resource].queue.remove(request)
            held = self._held.pop(transaction_id)
            self._sessions.pop(transaction_id)
            self._failed.pop(transaction_id, None)
            self._retired.add(transaction_id)
            for resource in held:
                entry = self._entries[resource]
                entry.holders.pop(transaction_id)
                self._observe(
                    "released", transaction_id, resource, held[resource],
                )
                self._drain(resource)
            if request is not None:
                self._drain(request.resource)
            self._condition.notify_all()

    def quarantine(self) -> None:
        """Refuse future grants after an unrecoverable restore failure."""
        with self._condition:
            self._unavailable = True
            for transaction_id in tuple(self._waiting):
                self._fail_wait(
                    transaction_id,
                    TransactionUnavailableError(
                        "Lock domain is unavailable",
                        transaction_id=transaction_id.value,
                    ),
                )
            self._condition.notify_all()

    def snapshot(self) -> LockSnapshot:
        with self._condition:
            graph = self._graph()
            resources = []
            for resource, entry in sorted(
                self._entries.items(), key=lambda item: _resource_order(item[0])
            ):
                waiters = tuple(
                    WaitSnapshot(
                        request.transaction_id, resource, request.mode,
                        request.sequence,
                        tuple(sorted(self._blockers(request, entry))),
                    )
                    for request in entry.queue
                )
                resources.append(ResourceSnapshot(
                    resource, tuple(sorted(entry.holders.items())), waiters,
                ))
            return LockSnapshot(
                tuple(resources),
                tuple(sorted((key, tuple(sorted(value))) for key, value in graph.items())),
                self._unavailable,
            )
