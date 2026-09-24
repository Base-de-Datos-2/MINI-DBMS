"""Independent owner-scoped sessions with transaction-aware SQL execution."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import replace
from math import isfinite
from pathlib import Path
from threading import Event, Lock, RLock
from time import monotonic, perf_counter

from engine.query.ast import (
    BeginTransactionStatement,
    CreateTableStatement,
    DeleteStatement,
    EndTransactionStatement,
    InsertStatement,
    RollbackStatement,
)
from engine.query.environment import QueryEnvironment
from engine.query.executor import (
    AnalysisExecutionError,
    CommandResult,
    ExplanationResult,
    PreparedQuery,
    QueryResult,
    ResultState,
    SqlEngine,
    cancellation_scope,
)
from engine.query.parser import parse_sql
from engine.query.errors import SqlQueryError
from engine.query.planner import PhysicalPlanningOptions
from engine.storage.page_manager import physical_latch_scope

from .errors import (
    SessionBusyError,
    TransactionAbortError,
    TransactionCapacityError,
    TransactionProtocolError,
    TransactionUnavailableError,
)
from .manager import TransactionManager
from .locks import LockManager
from .model import TransactionId, TransactionReport
from .gate import MetadataGate
from .observability import TraceSnapshot, TransactionMetrics, TransactionObservability
from .resources import LockMode, ResourceCatalog, StaleAccessPlanError, TableFiles
from .completion import CompletionService
from .runtime import TableRuntime
from .undo import UndoLimits


DEFAULT_MAX_SESSIONS = 64
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 5.0


_PROTECTED_WRITE: ContextVar[tuple[object, TransactionId, str] | None] = ContextVar(
    "minidb_protected_write", default=None
)
_PROTECTED_SCHEMA: ContextVar[tuple[object, TransactionId] | None] = ContextVar(
    "minidb_protected_schema", default=None
)


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
        root: Path,
        runtime: TableRuntime,
        quarantine_owner: Callable[[], None],
        undo_limits: UndoLimits = UndoLimits(),
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer")
        if default_engine.environment is not environment:
            raise ValueError("Default engine must borrow the coordinated environment")
        self.environment = environment
        self.transactions = TransactionManager()
        self.observability = TransactionObservability()
        self.locks = LockManager(
            database_identity, observer=self.observability.lock_event,
        )
        self.metadata = MetadataGate()
        self.resources = ResourceCatalog(
            database_identity, environment.catalog, table_files, environment
        )
        self.completion = CompletionService(
            root, self.transactions, self.locks, self.resources, runtime,
            limits=undo_limits, quarantine_owner=quarantine_owner,
            observability=self.observability,
        )
        self._engine_factory = engine_factory
        self._mutex = RLock()
        self._next_session_id = 2
        self._max_sessions = max_sessions
        self._closed = False
        self._sessions: dict[int, SqlSession] = {}
        self.default_session = SqlSession(self, 1, default_engine)
        self._sessions[1] = self.default_session
        default_engine._set_execution_router(
            self.default_session.execute,
            bypass=self.protected_execution_active,
        )
        default_engine._set_metadata_guard(self._metadata_read)

    def _metadata_read(self, action: Callable[[], object]):
        with self.metadata.read():
            return action()

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
            engine._set_execution_router(
                session.execute,
                bypass=self.protected_execution_active,
            )
            engine._set_metadata_guard(self._metadata_read)
            self._next_session_id += 1
            self._sessions[session.id] = session
            return session

    def trace(
        self,
        *,
        transaction_id: TransactionId | None = None,
        session_id: int | None = None,
    ) -> TraceSnapshot:
        """Return the bounded ordered lifecycle trace."""

        return self.observability.trace(
            transaction_id=transaction_id, session_id=session_id,
        )

    def transaction_metrics(self, transaction_id: TransactionId) -> TransactionMetrics:
        """Return a live or terminal metrics snapshot for one transaction."""

        try:
            transaction = self.transactions.current(transaction_id)
        except TransactionProtocolError:
            transaction = None
        return self.observability.metrics(
            transaction_id, transaction=transaction,
        )

    def protected_write_active(self, table_name: str) -> bool:
        """Recognize the narrow dynamic capability used by the old test hook."""

        current = _PROTECTED_WRITE.get()
        return current is not None and current[0] is self and current[2] == table_name

    def protected_execution_active(self) -> bool:
        """Allow legacy fault-injection callbacks to use the local SQL core."""

        current_write = _PROTECTED_WRITE.get()
        current_schema = _PROTECTED_SCHEMA.get()
        return (
            current_write is not None and current_write[0] is self
        ) or (
            current_schema is not None and current_schema[0] is self
        )

    def protected_schema_change_active(self) -> bool:
        current = _PROTECTED_SCHEMA.get()
        return current is not None and current[0] is self

    def _release(self, session: "SqlSession") -> None:
        with self._mutex:
            if self._sessions.get(session.id) is session:
                del self._sessions[session.id]

    def close(self) -> None:
        """Fail fast when a call is active; retained for compatibility."""

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

    def shutdown(
        self,
        *,
        timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        """Cancel active work and wait a finite time before shared-file close."""

        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be a positive finite number")
        with self._mutex:
            if self._closed:
                return
            self._closed = True
            sessions = tuple(self._sessions.values())
        for session in sessions:
            session.cancel()

        deadline = monotonic() + float(timeout_seconds)
        acquired: list[SqlSession] = []
        for session in sessions:
            remaining = deadline - monotonic()
            if remaining <= 0 or not session._call.acquire(timeout=max(0.0, remaining)):
                for locked in reversed(acquired):
                    locked._call.release()
                with self._mutex:
                    self._closed = False
                raise SessionBusyError(
                    "A session did not acknowledge cancellation before shutdown deadline",
                    session_id=session.id,
                )
            acquired.append(session)

        failures: list[BaseException] = []
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
        self._state_mutex = RLock()
        self._cancel_requested = Event()
        self._running = False
        self._closed = False
        self._transaction_id: TransactionId | None = None
        self._transaction_explicit = False
        self._provisional_results: list[CommandResult] = []

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

    def cancel(self) -> bool:
        """Request cooperative cancellation without waiting for the call guard."""

        with self._state_mutex:
            transaction_id = self._transaction_id
            active = self._running or transaction_id is not None or self.active_result is not None
            if self._closed or not active:
                return False
            self._cancel_requested.set()
        if transaction_id is not None:
            self._owner.observability.event(
                transaction_id, "session", "cancellation_requested",
            )
            self._owner.locks.cancel(transaction_id)
        return True

    def _enter_call(self, *, new_work: bool) -> None:
        with self._state_mutex:
            self._running = True
            if new_work and self._transaction_id is None:
                self._cancel_requested.clear()

    def _leave_call(self) -> None:
        with self._state_mutex:
            self._running = False

    def _raise_if_cancelled(self, transaction_id: TransactionId) -> None:
        if self._cancel_requested.is_set():
            raise TransactionAbortError(
                "Transaction execution cancelled at a safe point",
                session_id=self.id,
                transaction_id=transaction_id.value,
            )

    def prepare(
        self,
        sql: str,
        *,
        use_indexes: bool = True,
        planning_options: PhysicalPlanningOptions | None = None,
    ) -> PreparedQuery:
        """Prepare without starting, committing, or aborting a transaction."""

        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Another call is already using this session", session_id=self.id)
        self._enter_call(new_work=True)
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            return self._engine.prepare(
                sql,
                use_indexes=use_indexes,
                planning_options=planning_options,
            )
        finally:
            self._leave_call()
            self._call.release()

    def describe(self, sql: str, *, use_indexes: bool = True):
        """Describe one pure prepared plan through this session's engine."""

        return self.prepare(sql, use_indexes=use_indexes).describe()

    def execute(
        self,
        query: str | PreparedQuery,
        *,
        use_indexes: bool | None = None,
        planning_options: PhysicalPlanningOptions | None = None,
    ):
        if not self._call.acquire(blocking=False):
            raise SessionBusyError(
                "Another call is already using this session", session_id=self.id,
                transaction_id=None if self._transaction_id is None else self._transaction_id.value,
            )
        self._enter_call(new_work=True)
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            try:
                statement = (
                    parse_sql(query)
                    if isinstance(query, str)
                    else query._statement
                    if isinstance(query, PreparedQuery)
                    else None
                )
            except SqlQueryError as error:
                if self.active_result is not None:
                    raise TransactionProtocolError(
                        "Close or fully consume the active SELECT result before executing another statement",
                        session_id=self.id,
                        transaction_id=None if self._transaction_id is None else self._transaction_id.value,
                    ) from error
                if self._transaction_id is not None:
                    self._abort_after_failure(error, self._transaction_id)
                raise
            if statement is None:
                # Preserve the engine's public type diagnostic without starting
                # a transaction for a value that is not a SQL submission.
                return self._engine._execute_local(
                    query,
                    use_indexes=use_indexes,
                    planning_options=planning_options,
                )
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
                transaction = self._begin(explicit=True)
                try:
                    self._raise_if_cancelled(transaction.id)
                except BaseException as error:
                    self._abort_after_failure(error, transaction.id)
                    raise
                return replace(
                    TransactionReport.from_transaction(transaction),
                    metrics=self._owner.observability.metrics(
                        transaction.id, transaction=transaction,
                    ),
                )
            if isinstance(statement, EndTransactionStatement):
                transaction_id = self._require_explicit()
                if self.active_result is not None:
                    raise TransactionProtocolError(
                        "Close the active result before END TRANSACTION",
                        session_id=self.id,
                        transaction_id=transaction_id.value,
                    )
                try:
                    self._raise_if_cancelled(transaction_id)
                except BaseException as error:
                    self._abort_after_failure(error, transaction_id)
                    raise
                try:
                    report = self._owner.completion.commit(transaction_id)
                    for result in self._provisional_results:
                        result._set_transaction_outcome(
                            transaction_id=transaction_id.value, committed=True,
                        )
                    return report
                finally:
                    if self._owner.completion.report(transaction_id) is not None:
                        self._clear_transaction()
            if isinstance(statement, RollbackStatement):
                transaction_id = self._require_explicit()
                self._engine._close_active_result()
                report = self._abort(transaction_id)
                self._clear_transaction()
                if report.state.value == "ABORT_FAILED":
                    raise TransactionUnavailableError(
                        "Transaction restoration failed; owner is quarantined",
                        session_id=self.id, transaction_id=transaction_id.value,
                    )
                return report

            if self.active_result is not None:
                raise TransactionProtocolError(
                    "Close or fully consume the active SELECT result before executing another statement",
                    session_id=self.id,
                    transaction_id=None if self._transaction_id is None else self._transaction_id.value,
                )
            if isinstance(statement, CreateTableStatement) and self._transaction_explicit:
                error = TransactionProtocolError(
                    "CREATE TABLE is not supported inside an explicit transaction",
                    session_id=self.id,
                    transaction_id=self._transaction_id.value,
                )
                self._abort_after_failure(error, self._transaction_id)
                raise error

            implicit = self._transaction_id is None
            transaction_id = (
                self._begin(explicit=False).id
                if implicit
                else self._transaction_id
            )
            if transaction_id is None:  # pragma: no cover - guarded above
                raise RuntimeError("Session lost its transaction")
            try:
                access = self._owner.resources.plan(statement)
                wait_before = self._owner.observability.metrics(
                    transaction_id,
                    transaction=self._owner.transactions.current(transaction_id),
                ).lock_wait_seconds
                self._owner.locks.acquire_plan(transaction_id, access)
                statement_lock_wait = (
                    self._owner.observability.metrics(
                        transaction_id,
                        transaction=self._owner.transactions.current(transaction_id),
                    ).lock_wait_seconds - wait_before
                )
                self._raise_if_cancelled(transaction_id)
                try:
                    self._owner.resources.validate(access)
                except StaleAccessPlanError:
                    refreshed = self._owner.resources.plan(statement)
                    before = tuple(
                        (item.resource, item.mode, item.files) for item in access.tables
                    )
                    after = tuple(
                        (item.resource, item.mode, item.files) for item in refreshed.tables
                    )
                    if access.schema is not refreshed.schema or before != after:
                        raise
                    self._owner.resources.validate(refreshed)
                    access = refreshed
                held = {"schema"} if access.schema.value != "NONE" else set()
                held.update(item.resource.table_identity for item in access.tables)
                if held:
                    self._owner.transactions.record_resources(
                        transaction_id, held=frozenset(held)
                    )
                if isinstance(statement, (InsertStatement, DeleteStatement)):
                    self._owner.completion.prepare_write(
                        transaction_id, statement.table
                    )
                executable = query
                local_use_indexes = use_indexes
                local_planning_options = planning_options
                if isinstance(query, PreparedQuery):
                    if query._engine is not self._engine:
                        # Preserve the established ownership failure under the
                        # acquired execution locks and normal abort policy.
                        executable = query
                    else:
                        executable = self._engine.prepare(
                            query._source,
                            use_indexes=query._use_indexes,
                            planning_options=query._planning_options,
                        )
                        local_use_indexes = None
                        local_planning_options = None
                execution_started = perf_counter()
                with cancellation_scope(
                    lambda: self._raise_if_cancelled(transaction_id)
                ), physical_latch_scope(
                    lambda seconds, operation: self._owner.observability.record_physical_latch(
                        transaction_id,
                        wait_seconds=seconds,
                        phase="query",
                        operation=operation,
                    )
                ):
                    if isinstance(statement, CreateTableStatement):
                        with self._owner.metadata.write():
                            token = _PROTECTED_SCHEMA.set((self._owner, transaction_id))
                            try:
                                result = self._engine._execute_local(
                                    executable,
                                    use_indexes=local_use_indexes,
                                    planning_options=local_planning_options,
                                )
                            finally:
                                _PROTECTED_SCHEMA.reset(token)
                    else:
                        result = self._engine._execute_local(
                            executable,
                            use_indexes=local_use_indexes,
                            planning_options=local_planning_options,
                        )
                    self._raise_if_cancelled(transaction_id)
                if isinstance(result, QueryResult):
                    result._attach_lifecycle(
                        self._cursor_call,
                        lambda completed: self._finish_cursor(
                            transaction_id, implicit, completed
                        ),
                    )
                    return result
                self._record_execution(
                    transaction_id,
                    result,
                    elapsed_seconds=perf_counter() - execution_started,
                )
                if isinstance(result, CommandResult):
                    result._set_transaction_outcome(
                        transaction_id=transaction_id.value,
                        committed=False,
                    )
                if implicit:
                    terminal = self._owner.completion.commit(transaction_id)
                    if isinstance(result, CommandResult):
                        result._set_transaction_outcome(
                            transaction_id=transaction_id.value,
                            committed=True,
                        )
                    if isinstance(result, ExplanationResult):
                        result._set_transaction_context(
                            transaction_id=transaction_id.value,
                            transaction_state=terminal.state.value,
                            lock_wait_seconds=statement_lock_wait,
                        )
                    self._clear_transaction()
                else:
                    if isinstance(result, CommandResult):
                        self._provisional_results.append(result)
                    if isinstance(result, ExplanationResult):
                        result._set_transaction_context(
                            transaction_id=transaction_id.value,
                            transaction_state=self._owner.transactions.current(
                                transaction_id
                            ).state.value,
                            lock_wait_seconds=statement_lock_wait,
                        )
                return result
            except BaseException as error:
                self._record_failed_analysis(
                    transaction_id,
                    error,
                    lock_wait_seconds=locals().get("statement_lock_wait", 0.0),
                )
                if self._transaction_id == transaction_id:
                    terminal = self._abort_after_failure(error, transaction_id)
                    if isinstance(error, AnalysisExecutionError):
                        error.report = replace(
                            error.report,
                            transaction_id=transaction_id.value,
                            transaction_state=terminal.state.value,
                            lock_wait_seconds=max(
                                0.0, locals().get("statement_lock_wait", 0.0)
                            ),
                        )
                raise
        finally:
            self._leave_call()
            self._call.release()

    def _begin(self, *, explicit: bool):
        transaction = self._owner.transactions.begin(self.id)
        try:
            self._owner.locks.register(transaction)
        except BaseException:
            self._owner.transactions.abort_empty(transaction.id)
            raise
        self._owner.observability.begin(transaction)
        self._transaction_id = transaction.id
        self._transaction_explicit = explicit
        self._provisional_results.clear()
        return transaction

    def _clear_transaction(self) -> None:
        self._transaction_id = None
        self._transaction_explicit = False
        self._provisional_results.clear()
        self._cancel_requested.clear()

    def _record_execution(
        self,
        transaction_id: TransactionId,
        result,
        *,
        elapsed_seconds: float,
    ) -> None:
        planning = float(getattr(result, "planning_seconds", 0.0))
        report = getattr(result, "statistics", None)
        if isinstance(result, ExplanationResult):
            execution = result.execution_seconds
            execution = max(0.0, elapsed_seconds - planning) if execution is None else execution
        elif isinstance(result, QueryResult):
            execution = 0.0 if report is None else report.elapsed_seconds
        else:
            execution = max(0.0, elapsed_seconds - planning)
        if report is not None and not hasattr(report, "base_pages_read"):
            report = getattr(report, "discovery", None)
        self._owner.observability.record_execution(
            transaction_id,
            planning_seconds=planning,
            execution_seconds=execution,
            report=report,
        )

    def _record_failed_analysis(
        self,
        transaction_id: TransactionId,
        error: BaseException,
        *,
        lock_wait_seconds: float,
    ) -> None:
        if not isinstance(error, AnalysisExecutionError):
            return
        report = error.report
        self._owner.observability.record_execution(
            transaction_id,
            planning_seconds=report.planning_seconds,
            execution_seconds=report.execution_seconds or 0.0,
            report=report.runtime,
        )
        error.report = replace(
            report,
            transaction_id=transaction_id.value,
            transaction_state=self._owner.transactions.current(transaction_id).state.value,
            lock_wait_seconds=max(0.0, lock_wait_seconds),
        )

    def _require_explicit(self) -> TransactionId:
        transaction_id = self._require_active()
        if not self._transaction_explicit:
            raise TransactionProtocolError(
                "No active explicit transaction group",
                session_id=self.id,
                transaction_id=transaction_id.value,
            )
        return transaction_id

    def _abort_after_failure(
        self, error: BaseException, transaction_id: TransactionId,
    ) -> TransactionReport:
        self._owner.observability.record_failure(transaction_id, error)
        try:
            self._engine._close_active_result()
        except BaseException as cleanup:
            if cleanup is not error:
                error.add_note(
                    f"Active result cleanup also failed: {type(cleanup).__name__}: {cleanup}"
                )
        report = self._abort(transaction_id)
        self._clear_transaction()
        error.add_note(
            f"Transaction {transaction_id.value} ended {report.state.value} after execute error"
        )
        return report

    def _cursor_call(self, action: Callable[[], object]):
        if not self._call.acquire(blocking=False):
            raise SessionBusyError(
                "Another call is already using this session",
                session_id=self.id,
                transaction_id=None if self._transaction_id is None else self._transaction_id.value,
            )
        self._enter_call(new_work=False)
        try:
            if self._closed:
                raise TransactionUnavailableError(
                    "Session is closed", session_id=self.id
                )
            transaction_id = self._transaction_id
            if transaction_id is None:
                return action()
            with cancellation_scope(
                lambda: self._raise_if_cancelled(transaction_id)
            ), physical_latch_scope(
                lambda seconds, operation: self._owner.observability.record_physical_latch(
                    transaction_id,
                    wait_seconds=seconds,
                    phase="query",
                    operation=operation,
                )
            ):
                self._raise_if_cancelled(transaction_id)
                return action()
        finally:
            self._leave_call()
            self._call.release()

    def _finish_cursor(
        self, transaction_id: TransactionId, implicit: bool, result: QueryResult,
    ) -> None:
        if self._transaction_id != transaction_id:
            return
        self._record_execution(
            transaction_id,
            result,
            elapsed_seconds=(
                0.0 if result.statistics is None
                else result.statistics.elapsed_seconds + result.planning_seconds
            ),
        )
        if self._cancel_requested.is_set():
            error = result.error or TransactionAbortError(
                "SELECT execution cancelled",
                session_id=self.id,
                transaction_id=transaction_id.value,
            )
            self._abort_after_failure(error, transaction_id)
            return
        if result.state is ResultState.FAILED:
            error = result.error or RuntimeError("SELECT cursor failed")
            self._abort_after_failure(error, transaction_id)
            return
        if implicit:
            try:
                self._owner.completion.commit(transaction_id)
            finally:
                if self._owner.completion.report(transaction_id) is not None:
                    self._clear_transaction()

    def _require_active(self) -> TransactionId:
        if self._transaction_id is None:
            raise TransactionProtocolError(
                "No active transaction group", session_id=self.id
            )
        return self._transaction_id

    def _abort(self, transaction_id: TransactionId) -> TransactionReport:
        return self._owner.completion.abort(transaction_id)

    def run_write(self, table_name: str, action: Callable[[], object]) -> object:
        """Protected internal write hook retained for fault-injection tests.

        The action must mutate only the named table through the owner's
        canonical runtime objects. It is called after complete undo capture.
        """
        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Another call is already using this session", session_id=self.id)
        self._enter_call(new_work=False)
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            if self.active_result is not None:
                raise TransactionProtocolError(
                    "Close the active result before a write", session_id=self.id,
                )
            transaction_id = self._require_active()
            try:
                self._owner.completion.prepare_write(transaction_id, table_name)
                token = _PROTECTED_WRITE.set((self._owner, transaction_id, table_name))
                try:
                    with cancellation_scope(
                        lambda: self._raise_if_cancelled(transaction_id)
                    ):
                        self._raise_if_cancelled(transaction_id)
                        result = action()
                        self._raise_if_cancelled(transaction_id)
                        return result
                finally:
                    _PROTECTED_WRITE.reset(token)
            except BaseException as error:
                self._abort_after_failure(error, transaction_id)
                raise
        finally:
            self._leave_call()
            self._call.release()

    def run_programmatic_write(
        self, table_name: str, action: Callable[[], object],
    ) -> object:
        """Apply one managed helper write under the same implicit/explicit policy."""

        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Another call is already using this session", session_id=self.id)
        self._enter_call(new_work=True)
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            if self.active_result is not None:
                raise TransactionProtocolError(
                    "Close the active result before a write", session_id=self.id,
                )
            implicit = self._transaction_id is None
            transaction_id = (
                self._begin(explicit=False).id
                if implicit
                else self._transaction_id
            )
            if transaction_id is None:  # pragma: no cover - guarded above
                raise RuntimeError("Session lost its transaction")
            try:
                self._owner.completion.prepare_write(transaction_id, table_name)
                token = _PROTECTED_WRITE.set((self._owner, transaction_id, table_name))
                try:
                    with cancellation_scope(
                        lambda: self._raise_if_cancelled(transaction_id)
                    ):
                        self._raise_if_cancelled(transaction_id)
                        result = action()
                        self._raise_if_cancelled(transaction_id)
                finally:
                    _PROTECTED_WRITE.reset(token)
                if implicit:
                    self._owner.completion.commit(transaction_id)
                    self._clear_transaction()
                return result
            except BaseException as error:
                if self._transaction_id == transaction_id:
                    self._abort_after_failure(error, transaction_id)
                raise
        finally:
            self._leave_call()
            self._call.release()

    def run_schema_change(self, action: Callable[[], object]) -> object:
        """Coordinate one owner API schema publication as standalone DDL."""

        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Another call is already using this session", session_id=self.id)
        self._enter_call(new_work=True)
        try:
            if self._closed:
                raise TransactionUnavailableError("Session is closed", session_id=self.id)
            if self.active_result is not None:
                raise TransactionProtocolError(
                    "Close the active result before CREATE", session_id=self.id,
                )
            if self._transaction_explicit:
                transaction_id = self._require_active()
                error = TransactionProtocolError(
                    "CREATE is not supported inside an explicit transaction",
                    session_id=self.id,
                    transaction_id=transaction_id.value,
                )
                self._abort_after_failure(error, transaction_id)
                raise error
            transaction_id = self._begin(explicit=False).id
            try:
                self._owner.locks.acquire(
                    transaction_id,
                    self._owner.locks.schema_resource,
                    LockMode.X,
                )
                self._owner.transactions.record_resources(
                    transaction_id, held=frozenset({"schema"}),
                )
                with cancellation_scope(
                    lambda: self._raise_if_cancelled(transaction_id)
                ), self._owner.metadata.write():
                    self._raise_if_cancelled(transaction_id)
                    token = _PROTECTED_SCHEMA.set((self._owner, transaction_id))
                    try:
                        result = action()
                    finally:
                        _PROTECTED_SCHEMA.reset(token)
                    self._raise_if_cancelled(transaction_id)
                self._owner.completion.commit(transaction_id)
                self._clear_transaction()
                return result
            except BaseException as error:
                if self._transaction_id == transaction_id:
                    self._abort_after_failure(error, transaction_id)
                raise
        finally:
            self._leave_call()
            self._call.release()

    def close(self) -> None:
        if not self._call.acquire(blocking=False):
            raise SessionBusyError("Session is executing", session_id=self.id)
        try:
            self._close_locked()
        finally:
            self._call.release()

    def shutdown(
        self,
        *,
        timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        """Cancel and close this session after a bounded safe-point wait."""

        if (isinstance(timeout_seconds, bool)
                or not isinstance(timeout_seconds, (int, float))
                or not isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise ValueError("timeout_seconds must be a positive finite number")
        self.cancel()
        if not self._call.acquire(timeout=float(timeout_seconds)):
            raise SessionBusyError(
                "Session did not acknowledge cancellation before close deadline",
                session_id=self.id,
            )
        try:
            self._close_locked()
        finally:
            self._call.release()

    def _close_locked(self) -> None:
        if self._closed:
            return
        failures: list[BaseException] = []
        try:
            self._engine._close_active_result()
        except BaseException as error:
            failures.append(error)
        if self._transaction_id is not None:
            transaction_id = self._transaction_id
            try:
                report = self._abort(transaction_id)
                self._clear_transaction()
                if report.state.value == "ABORT_FAILED":
                    failures.append(TransactionUnavailableError(
                        "Transaction restoration failed while closing the session",
                        session_id=self.id, transaction_id=transaction_id.value,
                    ))
            except BaseException as error:
                failures.append(error)
        self._closed = True
        self._owner._release(self)
        if failures:
            raise failures[0]

    def __enter__(self) -> "SqlSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False
