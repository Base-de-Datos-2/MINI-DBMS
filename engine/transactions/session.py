"""Independent owner-scoped sessions for the Stage 8 foundation.

Only control-only groups are executable now. Data execution is refused before
effects until S/X locking and complete undo are integrated in later tasks.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock, RLock

from engine.query.ast import (
    BeginTransactionStatement,
    EndTransactionStatement,
    RollbackStatement,
)
from engine.query.environment import QueryEnvironment
from engine.query.executor import SqlEngine
from engine.query.parser import parse_sql
from engine.query.errors import SqlQueryError

from .errors import (
    SessionBusyError,
    TransactionCapacityError,
    TransactionProtocolError,
    TransactionUnavailableError,
)
from .manager import TransactionManager
from .locks import LockManager
from .model import TransactionId, TransactionReport
from .resources import ResourceCatalog, TableFiles


DEFAULT_MAX_SESSIONS = 64


class SessionCoordinator:
    """One transaction model and resource map shared by all owner sessions."""

    def __init__(
        self,
        *,
        database_identity: str,
        environment: QueryEnvironment,
        table_files: tuple[TableFiles, ...],
        engine_factory: Callable[[], SqlEngine],
        default_engine: SqlEngine,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer")
        if default_engine.environment is not environment:
            raise ValueError("Default engine must borrow the coordinated environment")
        self.environment = environment
        self.transactions = TransactionManager()
        self.locks = LockManager(database_identity)
        self.resources = ResourceCatalog(
            database_identity, environment.catalog, table_files, environment
        )
        self._engine_factory = engine_factory
        self._mutex = RLock()
        self._next_session_id = 2
        self._max_sessions = max_sessions
        self._closed = False
        self._sessions: dict[int, SqlSession] = {}
        self.default_session = SqlSession(self, 1, default_engine)
        self._sessions[1] = self.default_session

    @property
    def session_count(self) -> int:
        with self._mutex:
            return len(self._sessions)

    def open_session(self) -> "SqlSession":
        with self._mutex:
            if self._closed:
                raise TransactionUnavailableError("Database session coordinator is closed")
            if len(self._sessions) >= self._max_sessions:
                raise TransactionCapacityError("Live session limit reached")
            engine = self._engine_factory()
            if engine.environment is not self.environment:
                engine.close()
                raise ValueError("Session engine must borrow the coordinated environment")
            session = SqlSession(self, self._next_session_id, engine)
            self._next_session_id += 1
            self._sessions[session.id] = session
            return session

    def _release(self, session: "SqlSession") -> None:
        with self._mutex:
            if self._sessions.get(session.id) is session:
                del self._sessions[session.id]

    def close(self) -> None:
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            sessions = tuple(self._sessions.values())
        acquired: list[SqlSession] = []
        for session in sessions:
            if not session._call.acquire(blocking=False):
                for locked in reversed(acquired):
                    locked._call.release()
                with self._mutex:
                    self._closed = False
                raise SessionBusyError(
                    "A session is executing; database close is deferred",
                    session_id=session.id,
                )
            acquired.append(session)
        failures = []
        try:
            for session in sessions:
                try:
                    session._close_locked()
                except BaseException as error:
                    failures.append(error)
        finally:
            for session in reversed(acquired):
                session._call.release()
        if failures:
            with self._mutex:
                self._closed = False
            raise failures[0]


class SqlSession:
    """Session identity and non-reentrant control execution, independent of threads."""

    def __init__(self, owner: SessionCoordinator, session_id: int, engine: SqlEngine) -> None:
        self._owner = owner
        self.id = session_id
        self._engine = engine
        self._call = Lock()
        self._closed = False
        self._transaction_id: TransactionId | None = None

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def active_transaction(self):
        transaction_id = self._transaction_id
        return None if transaction_id is None else self._owner.transactions.current(transaction_id)

    @property
    def active_result(self):
        return self._engine.active_result

    def execute(self, sql: str) -> TransactionReport:
        if not self._call.acquire(blocking=False):
            raise SessionBusyError(
                "Another call is already using this session", session_id=self.id,
                transaction_id=None if self._transaction_id is None else self._transaction_id.value,
            )
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            try:
                statement = parse_sql(sql)
            except SqlQueryError as error:
                if self._transaction_id is not None:
                    transaction_id = self._transaction_id
                    self._abort_empty(transaction_id)
                    self._transaction_id = None
                    error.add_note(
                        f"Transaction {transaction_id.value} aborted after execute error"
                    )
                raise
            if isinstance(statement, BeginTransactionStatement):
                if self.active_result is not None:
                    raise TransactionProtocolError(
                        "Close the active result before BEGIN TRANSACTION",
                        session_id=self.id,
                    )
                if self._transaction_id is not None:
                    raise TransactionProtocolError(
                        "Nested BEGIN TRANSACTION is not supported",
                        session_id=self.id,
                        transaction_id=self._transaction_id.value,
                    )
                transaction = self._owner.transactions.begin(self.id)
                try:
                    self._owner.locks.register(transaction)
                except BaseException:
                    self._owner.transactions.abort_empty(transaction.id)
                    raise
                self._transaction_id = transaction.id
                return TransactionReport.from_transaction(transaction)
            if isinstance(statement, EndTransactionStatement):
                transaction_id = self._require_active()
                if self.active_result is not None:
                    raise TransactionProtocolError(
                        "Close the active result before END TRANSACTION",
                        session_id=self.id,
                        transaction_id=transaction_id.value,
                    )
                report = self._owner.transactions.commit_empty(transaction_id)
                self._owner.locks.release_all(report)
                self._transaction_id = None
                return report
            if isinstance(statement, RollbackStatement):
                transaction_id = self._require_active()
                self._engine.close()
                report = self._abort_empty(transaction_id)
                self._transaction_id = None
                return report

            transaction_id = self._transaction_id
            if transaction_id is not None:
                self._abort_empty(transaction_id)
                self._transaction_id = None
            raise TransactionUnavailableError(
                "Coordinated data execution is pending undo and S/X integration",
                session_id=self.id,
                transaction_id=None if transaction_id is None else transaction_id.value,
            )
        finally:
            self._call.release()

    def _require_active(self) -> TransactionId:
        if self._transaction_id is None:
            raise TransactionProtocolError(
                "No active transaction group", session_id=self.id
            )
        return self._transaction_id

    def _abort_empty(self, transaction_id: TransactionId) -> TransactionReport:
        report = self._owner.transactions.abort_empty(transaction_id)
        self._owner.locks.release_all(report)
        return report

    def close(self) -> None:
        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Session is executing", session_id=self.id)
        try:
            self._close_locked()
        finally:
            self._call.release()

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._engine.close()
        if self._transaction_id is not None:
            self._abort_empty(self._transaction_id)
            self._transaction_id = None
        self._closed = True
        self._owner._release(self)

    def __enter__(self) -> "SqlSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
