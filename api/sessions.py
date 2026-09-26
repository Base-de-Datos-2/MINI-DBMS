"""HTTP client sessions: opaque tokens bound to real Stage 8 ``SqlSession``s.

A browser tab obtains one token (``POST /api/sessions``) and sends it with
every statement in the ``X-Session-Token`` header. All of its requests then
run in the same engine session, so ``BEGIN TRANSACTION``, the statements that
follow and ``END TRANSACTION`` can arrive as separate HTTP requests and still
form one transaction group.

* The token is a random secret. It is never derived from, nor checked against,
  the engine's numeric session ID, which is only displayed.
* One HTTP call per token runs at a time; a second one gets ``SESSION_BUSY``.
  Independent tokens run concurrently and wait in the Stage 8 lock manager.
  No global mutex is held while a statement waits for a lock, so a blocked
  request never prevents its blocker's ``END``/``ROLLBACK`` from arriving.
* The registry mutex is held only to look up, add or remove entries, never
  while SQL runs or an engine session closes.
* The registry is bounded (``max_sessions``) and a token unused for
  ``idle_timeout_seconds`` expires: its engine session is closed, which aborts
  any open group and releases its locks. A missing, expired or closed token
  fails; no replacement session or transaction is ever created implicitly.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import logging
import secrets
import threading
from time import monotonic
from typing import Any

from engine.transactions.errors import (
    SessionBusyError,
    TransactionCapacityError,
    TransactionError,
    TransactionUnavailableError,
)
from engine.transactions.session import SqlSession

from .database import Database
from .errors import ServiceError
from .schemas import (
    MAX_CLIENT_SESSIONS,
    SESSION_IDLE_TIMEOUT_SECONDS,
    SHUTDOWN_TIMEOUT_SECONDS,
)


logger = logging.getLogger("minidbms.api.sessions")


@dataclass(eq=False)
class ClientSession:
    """One live token and the engine session it owns."""

    token: str
    sql_session: SqlSession
    last_used: float
    call: threading.Lock = field(default_factory=threading.Lock)
    #: Monotonic start of the HTTP call in progress, or ``None`` when idle.
    call_started: float | None = None
    #: Set when this client asked to cancel the call in progress.
    cancel_requested: bool = False
    #: Explicit group left open by the last completed call, if any.
    group_id: int | None = None

    @property
    def session_id(self) -> int:
        return self.sql_session.id


class SessionRegistry:
    """A bounded map of opaque tokens to live engine sessions."""

    def __init__(
        self,
        database: Database,
        *,
        max_sessions: int = MAX_CLIENT_SESSIONS,
        idle_timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer")
        if not idle_timeout_seconds > 0:
            raise ValueError("idle_timeout_seconds must be positive")
        self._database = database
        self._max_sessions = max_sessions
        self._idle_timeout = float(idle_timeout_seconds)
        self._clock = clock
        self._mutex = threading.Lock()
        self._sessions: dict[str, ClientSession] = {}
        self._closed = False

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    @property
    def idle_timeout_seconds(self) -> float:
        return self._idle_timeout

    def __len__(self) -> int:
        with self._mutex:
            return len(self._sessions)

    # ------------------------------------------------------------ lifecycle

    def open(self) -> ClientSession:
        """Open one engine session and return its new token."""

        self.sweep()
        with self._mutex:
            if self._closed:
                raise ServiceError(
                    "ENGINE_UNAVAILABLE", "El servidor se está cerrando; no admite sesiones nuevas."
                )
            if len(self._sessions) >= self._max_sessions:
                raise ServiceError(
                    "SESSION_LIMIT",
                    f"Hay {self._max_sessions} sesiones abiertas, el máximo del servidor. "
                    "Cierra alguna o espera a que expire.",
                )
            try:
                sql_session = self._database.open_session()
            except TransactionCapacityError:
                raise ServiceError(
                    "SESSION_LIMIT", "El motor alcanzó su límite de sesiones vivas."
                ) from None
            except TransactionUnavailableError:
                raise ServiceError(
                    "ENGINE_UNAVAILABLE", "La base no admite sesiones: reinicia el servidor."
                ) from None
            client = ClientSession(secrets.token_urlsafe(24), sql_session, self._clock())
            self._sessions[client.token] = client
            return client

    def _lookup(self, token: str | None) -> ClientSession:
        client = self._sessions.get(token) if isinstance(token, str) else None
        if client is None:
            raise ServiceError(
                "SESSION_NOT_FOUND",
                "La sesión no existe, expiró o fue cerrada; abre una nueva. "
                "Una transacción que estuviera abierta en ella ya fue abortada.",
            )
        return client

    def get(self, token: str | None) -> ClientSession:
        self.sweep()
        with self._mutex:
            return self._lookup(token)

    @contextmanager
    def call(self, token: str | None) -> Iterator[ClientSession]:
        """Own one session for the whole HTTP call, or fail with SESSION_BUSY."""

        self.sweep()
        with self._mutex:
            if self._closed:
                raise ServiceError("ENGINE_UNAVAILABLE", "El servidor se está cerrando.")
            client = self._lookup(token)
            if not client.call.acquire(blocking=False):
                raise ServiceError(
                    "SESSION_BUSY",
                    "Esta sesión ya está ejecutando otra petición: espera a que termine "
                    "o cancélala. Nada se reintentó.",
                )
            client.call_started = self._clock()
            client.cancel_requested = False
        try:
            yield client
        finally:
            # A transaction still live after a call can only be an explicit
            # group: implicit ones end with their statement.
            transaction = active_transaction(client.sql_session)
            client.group_id = None if transaction is None else transaction.id.value
            client.last_used = self._clock()
            client.call_started = None
            client.call.release()

    def cancel(self, token: str | None) -> bool:
        """Ask the engine to cancel this token's call in progress.

        Cancellation is cooperative: the call ends at the engine's next safe
        point with a ``TRANSACTION_CANCELLED`` response, and it aborts the
        whole transaction group. Nothing is cancelled when the session is idle;
        an open group is ended with ``ROLLBACK`` instead.
        """

        client = self.get(token)
        if client.call_started is None:
            return False
        client.cancel_requested = True
        return client.sql_session.cancel()

    def close(self, token: str | None, *, timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS) -> int | None:
        """Close one session, cancelling its call first; return the aborted group.

        The entry stays registered until the engine session is really closed,
        so a close that cannot finish in time leaves a usable, visible session.
        """

        client = self.get(token)
        if not client.call.acquire(blocking=False):
            client.cancel_requested = True
            client.sql_session.cancel()
            if not client.call.acquire(timeout=timeout_seconds):
                raise ServiceError(
                    "SESSION_BUSY",
                    "La petición en curso no reconoció la cancelación a tiempo; "
                    "la sesión sigue abierta.",
                )
        # From here the call lock stays held: a closed entry is never reused.
        transaction = active_transaction(client.sql_session)
        self.forget(client)
        try:
            client.sql_session.close()
        except SessionBusyError:  # pragma: no cover - the call guard excludes it
            raise ServiceError("SESSION_BUSY", "La sesión sigue ejecutando.") from None
        return None if transaction is None else transaction.id.value

    def forget(self, client: ClientSession) -> None:
        """Drop one entry without closing it (the caller closes the session)."""

        with self._mutex:
            if self._sessions.get(client.token) is client:
                del self._sessions[client.token]

    def sweep(self) -> int:
        """Close every idle session past its timeout; return how many."""

        now = self._clock()
        expired: list[ClientSession] = []
        with self._mutex:
            for token, client in list(self._sessions.items()):
                if now - client.last_used < self._idle_timeout:
                    continue
                # A session in a call is never idle; claiming its call lock
                # also keeps a request from starting on it meanwhile.
                if client.call.acquire(blocking=False):
                    del self._sessions[token]
                    expired.append(client)
        for client in expired:
            try:
                client.sql_session.close()
            except BaseException:  # noqa: BLE001 - the owner quarantines itself
                logger.exception("closing expired session %s failed", client.session_id)
            else:
                logger.info("session %s expired after inactivity", client.session_id)
        return len(expired)

    def stop(self) -> None:
        """Refuse new sessions and calls, and cancel every call in progress.

        The engine sessions themselves are closed by the owner's bounded
        ``Database.shutdown``, which waits for the cancellations to land.
        """

        with self._mutex:
            self._closed = True
            clients = list(self._sessions.values())
            self._sessions.clear()
        for client in clients:
            if client.call_started is not None:
                client.cancel_requested = True
                client.sql_session.cancel()

    # ------------------------------------------------------------ status

    def status(self, client: ClientSession) -> dict[str, Any]:
        """Describe one session without taking its call lock or any data lock."""

        transaction = active_transaction(client.sql_session)
        now = self._clock()
        busy = client.call_started is not None
        waiting = None
        if transaction is not None and busy:
            snapshot = self._database.session_coordinator.locks.snapshot()
            for resource in snapshot.resources:
                for wait in resource.waiters:
                    if wait.transaction_id == transaction.id:
                        identity = getattr(resource.resource, "table_identity", None)
                        waiting = {
                            "resource": (
                                "esquema" if identity is None
                                else self._database.table_name_for_identity(identity)
                            ),
                            "mode": wait.mode.value,
                            "blocker_ids": [blocker.value for blocker in wait.blockers],
                        }
        return {
            "session_id": client.session_id,
            "state": "IDLE" if transaction is None else "ACTIVE",
            "transaction": None if transaction is None else {
                "id": transaction.id.value,
                "state": transaction.state.value,
                "explicit": not busy or transaction.id.value == client.group_id,
                "tables": self._database.resource_names(transaction.held_resources),
            },
            "busy": busy,
            "call_elapsed_ms": None if not busy else round((now - client.call_started) * 1000, 1),
            "cancel_requested": busy and client.cancel_requested,
            "waiting": waiting,
            "expires_in_seconds": None if busy else max(
                0.0, round(self._idle_timeout - (now - client.last_used), 1)
            ),
        }


def active_transaction(session: SqlSession):
    """Return the session's live transaction, tolerating one that just ended."""

    if session.closed:
        return None
    try:
        return session.active_transaction
    except TransactionError:
        return None


class SessionSweeper:
    """A daemon thread that expires idle sessions every ``interval`` seconds."""

    def __init__(self, registry: SessionRegistry, interval_seconds: float) -> None:
        self._registry = registry
        self._interval = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="session-sweeper", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._registry.sweep()
            except BaseException:  # noqa: BLE001 - keep sweeping
                logger.exception("session sweep failed")

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=self._interval + 1)
