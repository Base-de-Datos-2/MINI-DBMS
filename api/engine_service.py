"""Own the demonstration engine: sessions, statement policy, bounded output.

This is the only module that touches the engine on behalf of HTTP requests.
Statements take one of two paths:

* **Session path** (``X-Session-Token``). The statement runs in that client's
  own Stage 8 ``SqlSession`` (see :mod:`api.sessions`). ``BEGIN``/``END``/
  ``ROLLBACK`` group separate requests into one transaction. Independent
  sessions execute concurrently and wait in the engine's lock manager; no
  global mutex is held while a statement waits, so a blocked request never
  prevents its blocker's ``END`` or ``ROLLBACK``.
* **Sessionless path** (compatibility, e.g. ``curl``). The statement runs in
  the owner's default session as one implicit transaction, one call at a time:
  a competing sessionless call is refused with ``ENGINE_BUSY``. Transaction
  control is refused here, because a group in the shared default session would
  leak across unrelated clients.

On both paths:

* **Statement policy.** The family comes from the handwritten parser's AST,
  which only parses; text matching is never used. Read-only mode allows
  SELECT, EXPLAIN and EXPLAIN ANALYZE; write mode adds INSERT and DELETE.
  Transaction control needs a session. Anything else fails closed. A refused
  statement never reaches ``execute``, so it cannot touch an open group.
* **Engine semantics.** An allowed statement is handed to ``execute`` as SQL,
  so the engine's own contract applies: an execute error inside an explicit
  group (a constraint, a lock timeout, a deadlock, even malformed SQL) aborts
  the whole group, and the error response says so.
* **Bounded preview.** At most ``max_rows + 1`` rows are consumed, rows are
  bounded in encoded bytes, and the cursor is closed before the response is
  built. An explicit group keeps its locks until END/ROLLBACK.

Catalog metadata routes read under the engine's metadata gate and take no
execution admission.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import threading
from time import monotonic, perf_counter
from typing import Any, Callable

from engine.catalog import DataType, IndexType
from engine.errors import DuplicateError, UnknownTableError, ValidationError
from engine.maintenance import MaintenanceError
from engine.query import (
    JoinPlanningStrategy,
    PhysicalPlanningOptions,
    SqlQueryError,
    parse_sql,
)
from engine.query.ast import (
    BeginTransactionStatement,
    CreateTableStatement,
    DeleteStatement,
    EndTransactionStatement,
    ExplainStatement,
    InsertStatement,
    RollbackStatement,
    SelectStatement,
)
from engine.query.executor import (
    AnalysisExecutionError,
    CommandResult,
    DefinitionResult,
    ExplanationResult,
    QueryResult,
)
from engine.transactions.errors import (
    DeadlockVictimError,
    LockTimeoutError,
    SessionBusyError,
    TransactionAbortError,
    TransactionCapacityError,
    TransactionError,
    TransactionProtocolError,
    TransactionUnavailableError,
)
from engine.transactions.locks import DEFAULT_LOCK_TIMEOUT_SECONDS
from engine.transactions.model import TransactionReport

from .database import Database, NewIndex, NewTable
from .errors import ServiceError
from .schemas import (
    MAX_CLIENT_SESSIONS,
    MAX_RESPONSE_BYTES,
    MAX_SQL_BYTES,
    READ_ONLY,
    SERIALIZED_WRITES,
    SESSION_IDLE_TIMEOUT_SECONDS,
    SHUTDOWN_TIMEOUT_SECONDS,
    CreateTableRequest,
    CsvPreviewRequest,
    QueryRequest,
)
from .serialization import (
    column_descriptors,
    encode_row,
    encoded_size,
    error_message,
    explanation_json,
    prepared_json,
    runtime_json,
    sql_location,
    table_detail_json,
    table_summary_json,
    transaction_report_json,
)
from .sessions import ClientSession, SessionRegistry, active_transaction
from .table_import import CsvError, DefinitionError, convert_rows, parse_csv, preview


__all__ = ["EngineService", "ServiceError"]

logger = logging.getLogger("minidbms.api")

READY = "ready"
CLOSING = "closing"
UNAVAILABLE = "unavailable"
CLOSED = "closed"

#: What the backend elapsed time covers. It excludes the final JSON encoding
#: done by the web framework and the browser round trip.
ELAPSED_SCOPE = (
    "backend: parse through cursor cleanup, including lock waits and preview conversion"
)

# Keep authorization closed over the statement families this adapter actually
# knows how to serialize. A future engine statement stays refused until it has
# an explicit policy and result-dispatch branch here.
_READ_ONLY_STATEMENTS = frozenset({"SELECT", "EXPLAIN", "EXPLAIN_ANALYZE"})
_WRITE_STATEMENTS = _READ_ONLY_STATEMENTS | {"INSERT", "DELETE"}
_CONTROL_STATEMENTS = frozenset({"BEGIN", "END", "ROLLBACK"})

_FAMILIES = (
    (SelectStatement, "SELECT"),
    (InsertStatement, "INSERT"),
    (DeleteStatement, "DELETE"),
    (CreateTableStatement, "CREATE"),
    (BeginTransactionStatement, "BEGIN"),
    (EndTransactionStatement, "END"),
    (RollbackStatement, "ROLLBACK"),
)

_UNAVAILABLE_MESSAGE = "El motor no está disponible; reinicia el servidor de la demo."
_QUARANTINE_MESSAGE = "La base quedó en cuarentena; reinicia el servidor de la demo."


def _family(statement: object) -> str | None:
    """Name the statement family from the parsed AST, or ``None`` if unknown."""

    if isinstance(statement, ExplainStatement):
        return "EXPLAIN_ANALYZE" if statement.analyze else "EXPLAIN"
    for syntax, family in _FAMILIES:
        if isinstance(statement, syntax):
            return family
    return None


@dataclass(frozen=True, slots=True)
class _Runner:
    """Where one statement runs: a client session or the default session."""

    execute: Callable[..., Any]
    prepare: Callable[..., Any]
    session: Any
    client: ClientSession | None


class _FailedWithPlan(Exception):
    """Carries an engine failure together with the plan observed so far."""

    def __init__(self, error: BaseException, plan: dict[str, Any]) -> None:
        super().__init__(str(error))
        self.error = error
        self.plan = plan


class EngineService:
    """The single owner of the demonstration engine inside one server process."""

    __slots__ = ("_database", "_allow_writes", "_writes_suspended", "_admission",
                 "_state", "_static_health", "_sessions")

    def __init__(
        self,
        database: Database,
        *,
        allow_writes: bool = False,
        max_sessions: int = MAX_CLIENT_SESSIONS,
        idle_timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not isinstance(database, Database):
            raise TypeError("EngineService requires an open Database")
        if database.closed:
            raise ValidationError("EngineService requires an open Database")
        if type(allow_writes) is not bool:
            raise TypeError("allow_writes must be a bool")
        self._database = database
        self._allow_writes = allow_writes
        self._writes_suspended = False
        # Serializes the sessionless path only: the shared default session.
        self._admission = threading.Lock()
        self._state = READY
        self._sessions = SessionRegistry(
            database,
            max_sessions=max_sessions,
            idle_timeout_seconds=idle_timeout_seconds,
            clock=clock,
        )
        # Captured once at startup: health must never touch engine state.
        self._static_health = {
            "database": database.name,
            "tables": list(database.table_names()),
            "memory_budget_bytes": database.engine.memory_budget_bytes,
        }

    @property
    def state(self) -> str:
        """Return ``ready``, ``closing``, ``unavailable`` or ``closed``."""

        return self._state

    @property
    def sessions(self) -> SessionRegistry:
        return self._sessions

    @property
    def mode(self) -> str:
        """Return the presentation mode reported with every response."""

        if self._allow_writes and not self._writes_suspended:
            return SERIALIZED_WRITES
        return READ_ONLY

    def _allowed(self) -> frozenset[str]:
        if self.mode == SERIALIZED_WRITES:
            return _WRITE_STATEMENTS
        return _READ_ONLY_STATEMENTS

    def health(self) -> dict[str, Any]:
        """Return cached readiness without touching storage or the engine."""

        return {
            "status": self._state,
            "mode": self.mode,
            "writes_enabled": self.mode == SERIALIZED_WRITES,
            **self._static_health,
            "sessions": {
                "open": len(self._sessions),
                "max": self._sessions.max_sessions,
                "idle_timeout_seconds": self._sessions.idle_timeout_seconds,
                "lock_timeout_seconds": DEFAULT_LOCK_TIMEOUT_SECONDS,
            },
        }

    # ------------------------------------------------------------ readiness

    def _require_ready(self) -> None:
        if self._state != READY:
            raise ServiceError("ENGINE_UNAVAILABLE", _UNAVAILABLE_MESSAGE)
        if not self._database.available:
            # The owner quarantined itself after an unrecoverable cleanup.
            self._state = UNAVAILABLE
            raise ServiceError("ENGINE_UNAVAILABLE", _QUARANTINE_MESSAGE)

    @contextmanager
    def _admitted(self):
        """Own the default session for one sessionless call, or refuse at once."""

        self._require_ready()
        if not self._admission.acquire(blocking=False):
            raise ServiceError(
                "ENGINE_BUSY",
                "Otra petición sin sesión está usando la sesión por defecto; "
                "inténtalo cuando termine o abre una sesión propia.",
            )
        try:
            self._require_ready()
            try:
                engine = self._database.engine
            except TransactionUnavailableError:
                self._state = UNAVAILABLE
                raise ServiceError("ENGINE_UNAVAILABLE", _QUARANTINE_MESSAGE) from None
            yield engine
        finally:
            self._admission.release()

    def _safe(self, message: str) -> str:
        """Never let the data directory path reach a response."""

        return message.replace(str(self._database.directory), "<datos>")

    # ------------------------------------------------------------ metadata

    def list_tables(self) -> list[dict[str, Any]]:
        """Summarize every loaded table without reading their rows.

        Counts are the current physical ones and may include provisional
        changes of a transaction that is still open.
        """

        self._require_ready()
        return [
            table_summary_json(self._database.describe_table(name))
            for name in self._database.table_names()
        ]

    def describe_table(self, table_id: str) -> dict[str, Any]:
        """Describe one table by its Catalog identifier."""

        self._require_ready()
        try:
            summary = self._database.describe_table(table_id)
        except (UnknownTableError, KeyError):
            raise ServiceError(
                "NOT_FOUND", f"No existe la tabla {table_id!r} en el catálogo."
            ) from None
        return table_detail_json(summary)

    # ------------------------------------------------------------ sessions

    def open_session(self) -> dict[str, Any]:
        self._require_ready()
        client = self._sessions.open()
        return {"token": client.token, "session": self._sessions.status(client)}

    def session_status(self, token: str | None) -> dict[str, Any]:
        return self._sessions.status(self._sessions.get(token))

    def cancel_session(self, token: str | None) -> dict[str, Any]:
        requested = self._sessions.cancel(token)
        return {
            "cancel_requested": requested,
            "session": self._sessions.status(self._sessions.get(token)),
        }

    def close_session(self, token: str | None) -> dict[str, Any]:
        try:
            aborted = self._sessions.close(token)
        except TransactionUnavailableError:
            self._state = UNAVAILABLE
            raise ServiceError("ENGINE_UNAVAILABLE", _QUARANTINE_MESSAGE) from None
        return {"closed": True, "aborted_transaction_id": aborted}

    @contextmanager
    def _runner(self, session_token: str | None):
        """Yield where the call runs; attach the final session status to errors."""

        if session_token is None:
            with self._admitted() as engine:
                yield _Runner(
                    engine.execute, engine.prepare,
                    self._database.session_coordinator.default_session, None,
                )
            return
        self._require_ready()
        client: ClientSession | None = None
        try:
            with self._sessions.call(session_token) as client:
                session = client.sql_session
                yield _Runner(session.execute, session.prepare, session, client)
        except ServiceError as error:
            if client is not None:
                error.session = self._sessions.status(client)
            raise

    # ------------------------------------------------------------ CSV and CREATE

    def preview_csv(self, request: CsvPreviewRequest) -> dict[str, Any]:
        """Describe a CSV upload. Pure parsing: it never touches the engine."""

        try:
            return preview(
                request.text,
                filename=request.filename,
                delimiter=request.delimiter,
                taken_names=set(self._static_health["tables"]),
            )
        except CsvError as error:
            raise _csv_error(error) from None

    def create_table(
        self,
        request: CreateTableRequest,
        request_id: str,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        """Create one table from the Files panel, optionally loading a CSV.

        Creating a table writes to the database, so it follows the same
        server-enforced policy as INSERT/DELETE: it runs only in write mode.
        The CSV is parsed and converted before the engine is involved, so a
        malformed file never holds a session or a lock.
        """

        if self.mode != SERIALIZED_WRITES:
            raise ServiceError(
                "WRITES_DISABLED",
                "Crear tablas es una escritura: arranca el servidor con --allow-writes.",
            )
        columns = tuple((column.name, DataType(column.type)) for column in request.columns)
        spec = NewTable(
            name=request.name,
            columns=columns,
            organization=request.organization,
            key_column=request.key_column,
            indexes=tuple(
                NewIndex(index.column, IndexType(index.type), index.unique)
                for index in request.indexes
            ),
        )
        rows: list = []
        lines = None
        if request.csv is not None:
            try:
                parsed = parse_csv(request.csv.text, request.csv.delimiter)
                rows = convert_rows(parsed, columns)
                lines = parsed.lines
            except CsvError as error:
                raise _csv_error(error) from None
            except DefinitionError as error:
                raise ServiceError("DEFINITION_ERROR", error_message(error)) from None

        started = perf_counter()
        with self._runner(session_token) as runner:
            if runner.client is not None and active_transaction(runner.session) is not None:
                # CREATE inside a group would abort it; refuse before touching it.
                raise ServiceError(
                    "TRANSACTION_PROTOCOL",
                    "Termina la transacción abierta (END TRANSACTION o ROLLBACK) antes "
                    "de crear una tabla. La transacción no se modificó.",
                )
            since = self._trace_mark(runner.session)
            try:
                summary = self._database.create_gui_table(
                    spec,
                    rows,
                    lines=lines,
                    origin="empty" if request.csv is None else "csv",
                    source_filename=None if request.csv is None else request.csv.filename,
                    session=runner.session,
                )
            except CsvError as error:
                raise _csv_error(error) from None
            except DefinitionError as error:
                raise ServiceError("DEFINITION_ERROR", error_message(error)) from None
            except DuplicateError as error:
                raise ServiceError("TABLE_EXISTS", error_message(error)) from None
            except TransactionError as error:
                raise self._failure(error, "CREATE", runner, since, None) from None
            except ValidationError as error:
                raise ServiceError("DEFINITION_ERROR", self._safe(error_message(error))) from None
            finally:
                if not self._database.available:
                    self._state = UNAVAILABLE
            self._static_health["tables"] = list(self._database.table_names())
        body = {
            "request_id": request_id,
            "mode": self.mode,
            "table": table_detail_json(summary),
            "loaded_rows": len(rows),
            "backend_elapsed_ms": round((perf_counter() - started) * 1000, 3),
        }
        if runner.client is not None:
            body["session"] = self._sessions.status(runner.client)
        return body

    # ------------------------------------------------------------ statements

    def execute(
        self,
        request: QueryRequest,
        request_id: str,
        session_token: str | None = None,
    ) -> dict[str, Any]:
        """Run one statement under the presentation policy and bound its output."""

        if len(request.sql.encode("utf-8")) > MAX_SQL_BYTES:
            raise ServiceError(
                "REQUEST_TOO_LARGE",
                f"El SQL excede el límite de {MAX_SQL_BYTES} bytes UTF-8.",
            )
        started = perf_counter()
        with self._runner(session_token) as runner:
            body = self._run_statement(request, runner)
            body["metrics"]["backend_elapsed_ms"] = round(
                (perf_counter() - started) * 1000, 3
            )
        body["request_id"] = request_id
        body["mode"] = self.mode
        if runner.client is not None:
            body["session"] = self._sessions.status(runner.client)
        return self._fit(body)

    def _run_statement(self, request: QueryRequest, runner: _Runner) -> dict[str, Any]:
        options = {
            "use_indexes": request.use_indexes,
            "planning_options": PhysicalPlanningOptions(
                join_strategy=JoinPlanningStrategy[request.join_strategy]
            ),
        }
        try:
            family = _family(parse_sql(request.sql))
        except SqlQueryError:
            # Let the engine report it: inside an explicit group, its contract
            # is that malformed SQL submitted to execute aborts the group.
            family = None
        else:
            self._enforce_policy(family, request, runner, options)

        since = self._trace_mark(runner.session)
        group_before = None if runner.client is None else runner.client.group_id
        try:
            result = runner.execute(request.sql, **options)
            body = self._dispatch(result, request)
        except ServiceError:
            raise
        except _FailedWithPlan as failure:
            raise self._failure(
                failure.error, family, runner, since, group_before, plan=failure.plan,
            ) from None
        except Exception as error:
            raise self._failure(error, family, runner, since, group_before) from None
        finally:
            self._verify_idle(runner)
        body["statement"] = family or body.get("statement")
        return body

    def _enforce_policy(self, family, request, runner, options) -> None:
        if family in _CONTROL_STATEMENTS:
            if runner.client is None:
                raise ServiceError(
                    "TRANSACTION_PROTOCOL",
                    f"{family} necesita una sesión: ábrela con POST /api/sessions y envía "
                    "su token en X-Session-Token. Sin sesión, cada sentencia es una "
                    "transacción implícita.",
                    statement=family,
                )
            return
        if family in self._allowed():
            return
        if family == "CREATE":
            raise ServiceError(
                "STATEMENT_DISABLED",
                "CREATE TABLE en SQL requiere el owner manifest-backed; en esta demo las "
                "tablas se crean desde el panel Archivos (Nueva tabla).",
                statement=family,
            )
        plan = None
        if family is not None:
            try:
                # A pure prepare: it never starts, commits or aborts anything.
                plan = {
                    "prepared": prepared_json(runner.prepare(request.sql, **options).describe()),
                    "runtime": None,
                }
            except (SqlQueryError, ValidationError):
                plan = None
        raise ServiceError(
            "STATEMENT_DISABLED",
            f"{family or 'La sentencia'} no está habilitada en el modo {self.mode}; "
            + ("se validó y planificó, pero no se ejecutó." if plan else "no se ejecutó."),
            statement=family,
            execution_plan=plan,
        )

    def _verify_idle(self, runner: _Runner) -> None:
        # Every result is closed before a response is built. If one is left
        # behind, the session cannot run another statement safely.
        if runner.session.active_result is None:
            return
        if runner.client is None:
            self._state = UNAVAILABLE
        else:
            logger.error("session %s kept an open result; closing it", runner.client.session_id)
            self._sessions.forget(runner.client)
            try:
                runner.session.close()
            except BaseException:  # noqa: BLE001 - owner quarantines itself if needed
                logger.exception("closing session %s failed", runner.client.session_id)

    # ------------------------------------------------------------ results

    def _dispatch(self, result, request: QueryRequest) -> dict[str, Any]:
        """Serialize every engine result family, or fail closed."""

        if isinstance(result, TransactionReport):
            return self._transaction_body(result)
        if isinstance(result, QueryResult):
            return self._select_body(result, request)
        if isinstance(result, CommandResult):
            return self._command_body(result)
        if isinstance(result, ExplanationResult):
            return self._explanation_body(result)
        if isinstance(result, DefinitionResult):
            return self._definition_body(result)
        raise ServiceError(
            "INTERNAL_ERROR",
            f"No existe un adaptador de resultado para {type(result).__name__}.",
        )

    @staticmethod
    def _empty_body(kind: str, statement: str, plan, plan_status: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "statement": statement,
            "columns": [],
            "rows": [],
            "returned_rows": 0,
            "truncated": False,
            "truncation_reason": None,
            "result_complete": True,
            "total_rows": None,
            "affected_rows": None,
            "execution_plan": plan,
            "plan_status": plan_status,
            "metrics": {"scope": ELAPSED_SCOPE, "partial": False, "engine": None},
        }

    def _select_body(self, result: QueryResult, request: QueryRequest) -> dict[str, Any]:
        plan = {"prepared": prepared_json(result.report.prepared), "runtime": None}
        # A soft, early stop: the executed plan mirrors the prepared tree plus
        # counters, so twice the prepared size approximates the metadata. The
        # exact decision is made afterwards on the real encoded response.
        soft_budget = MAX_RESPONSE_BYTES - 2 * encoded_size(plan["prepared"])
        rows: list[list[object]] = []
        row_bytes = 2  # the enclosing []
        reason: str | None = None
        try:
            with result:
                columns = column_descriptors(result.schema)
                while True:
                    batch = result.fetchmany(1)
                    if not batch:
                        break
                    if len(rows) == request.max_rows:
                        # This lookahead row only proves more output exists.
                        reason = "row_limit"
                        break
                    encoded = encode_row(batch[0])
                    size = encoded_size(encoded) + 1
                    # The first row is always kept for the exact check below.
                    if rows and row_bytes + size > soft_budget:
                        reason = "byte_limit"
                        break
                    rows.append(encoded)
                    row_bytes += size
        except Exception as error:
            plan["runtime"] = _runtime_tree(result.report.runtime)
            raise _FailedWithPlan(error, plan) from None

        report = result.report
        complete = reason is None and report.fully_consumed
        engine_metrics = _attach_runtime(plan, report.runtime)
        return {
            "kind": "rows",
            "statement": "SELECT",
            "columns": columns,
            "rows": rows,
            "returned_rows": len(rows),
            "truncated": reason is not None,
            "truncation_reason": reason,
            "result_complete": complete,
            "total_rows": len(rows) if complete else None,
            "affected_rows": None,
            "execution_plan": plan,
            "plan_status": "execution-observed" if plan["runtime"] else "prepared",
            "metrics": {
                "scope": ELAPSED_SCOPE,
                "partial": not complete,
                "engine": engine_metrics,
            },
        }

    def _command_body(self, result: CommandResult) -> dict[str, Any]:
        statistics = result.statistics
        plan = {"prepared": prepared_json(result.report.prepared), "runtime": None}
        discovery = getattr(statistics, "discovery", None)
        engine_metrics = None if discovery is None else _attach_runtime(plan, discovery)
        body = self._empty_body(
            "command", result.statement_kind.value, plan,
            "execution-observed" if plan["runtime"] else "prepared",
        )
        body["affected_rows"] = result.affected_rows
        # An implicit command is committed before it returns; inside an
        # explicit group its count stays provisional until END succeeds.
        body["transaction"] = {
            "id": result.transaction_id,
            "committed": result.committed,
            "provisional": result.provisional,
        }
        body["metrics"]["engine"] = engine_metrics
        body["metrics"]["maintenance"] = {
            "indexes_maintained": statistics.indexes_maintained,
            "index_association_updates": statistics.index_association_updates,
            "indexes_rebuilt": statistics.indexes_rebuilt,
            "targets_spooled": statistics.targets_spooled,
            "spool_bytes": statistics.spool_bytes,
        }
        return body

    def _explanation_body(self, result: ExplanationResult) -> dict[str, Any]:
        plan = {"prepared": prepared_json(result.plan), "runtime": None}
        engine_metrics = _attach_runtime(plan, result.statistics)
        body = self._empty_body(
            "explanation", result.statement_kind.value, plan,
            "execution-observed" if plan["runtime"] else "prepared",
        )
        body["explanation"] = explanation_json(result.report)
        body["metrics"]["engine"] = engine_metrics
        return body

    def _definition_body(self, result: DefinitionResult) -> dict[str, Any]:
        # Unreachable under the current policy (SQL CREATE stays disabled in
        # the legacy owner); serialized so dispatch stays exhaustive.
        plan = {"prepared": prepared_json(result.report.prepared), "runtime": None}
        body = self._empty_body("definition", "CREATE", plan, "prepared")
        body["definition"] = {
            "table_name": result.table_name,
            "primary_index_name": result.primary_index_name,
        }
        return body

    def _transaction_body(self, report: TransactionReport) -> dict[str, Any]:
        body = self._empty_body("transaction", "", None, "unavailable")
        body["transaction_report"] = transaction_report_json(
            report, self._database.resource_names
        )
        return body

    # ------------------------------------------------------------ failures

    def _trace_mark(self, session) -> int:
        events = self._database.session_coordinator.trace(session_id=session.id).events
        return events[-1].sequence if events else 0

    def _outcome(self, session, since: int) -> dict[str, Any] | None:
        """The transaction this call ended, read from the engine's own trace."""

        events = self._database.session_coordinator.trace(session_id=session.id).events
        for event in reversed(events):
            if event.sequence <= since:
                break
            if event.category == "transaction" and event.action == "complete":
                return {"id": event.transaction_id.value, "state": event.detail}
        return None

    def _failure(
        self,
        error: BaseException,
        family: str | None,
        runner: _Runner,
        since: int,
        group_before: int | None,
        *,
        plan: dict[str, Any] | None = None,
    ) -> ServiceError:
        """Map one engine failure to a truthful, path-free error envelope."""

        outcome = self._outcome(runner.session, since)
        details: dict[str, Any] = {}
        if outcome is not None:
            details["transaction"] = outcome
        if group_before is not None:
            details["group_aborted"] = active_transaction(runner.session) is None
        message = self._safe(error_message(error))
        client = runner.client

        def fail(code: str, text: str = message, **extra) -> ServiceError:
            return ServiceError(
                code, text, statement=family, execution_plan=plan,
                details={**details, **extra} or None, **(
                    {"location": sql_location(error)} if isinstance(error, SqlQueryError) else {}
                ),
            )

        if isinstance(error, SessionBusyError):
            return fail("SESSION_BUSY")
        if isinstance(error, TransactionProtocolError):
            return fail("TRANSACTION_PROTOCOL")
        if isinstance(error, LockTimeoutError):
            return fail(
                "LOCK_TIMEOUT",
                f"Se agotó la espera de un lock ({DEFAULT_LOCK_TIMEOUT_SECONDS:g} s): "
                "la transacción se abortó y no se confirmó nada.",
                cause="timeout",
            )
        if isinstance(error, DeadlockVictimError):
            return fail(
                "TRANSACTION_ABORTED",
                "Deadlock: esta transacción cerró un ciclo de espera y fue elegida víctima. "
                "Se abortó el grupo completo; puedes reintentarlo desde BEGIN.",
                cause="deadlock",
            )
        if isinstance(error, TransactionAbortError):
            if self._state == CLOSING:
                return fail(
                    "TRANSACTION_CANCELLED",
                    "Cancelada porque el servidor se está deteniendo; la transacción se "
                    "abortó y no se confirmó nada.",
                    cause="shutdown",
                )
            if client is not None and client.cancel_requested:
                return fail(
                    "TRANSACTION_CANCELLED",
                    "Cancelada a petición del cliente en un punto seguro; la transacción "
                    "se abortó y sus recursos se liberaron.",
                    cause="cancelled",
                )
            return fail("TRANSACTION_ABORTED", cause="aborted")
        if isinstance(error, TransactionUnavailableError):
            self._state = UNAVAILABLE
            return fail("ENGINE_UNAVAILABLE", _QUARANTINE_MESSAGE)
        if isinstance(error, TransactionCapacityError):
            return fail("SESSION_LIMIT")
        if isinstance(error, SqlQueryError):
            return fail("SQL_ERROR")
        if isinstance(error, MaintenanceError):
            causes = "; ".join(self._safe(error_message(cause)) for cause in error.failures)
            if causes:
                message = f"{message}: {causes}"
            rolled_back = outcome is not None and outcome["state"] == "ABORTED"
            if error.unavailable_indexes and not rolled_back:
                # Consistency is uncertain unless the group was restored.
                self._writes_suspended = True
            return fail(
                "EXECUTION_REFUSED",
                message,
                completed_rows=error.completed_rows,
                unavailable_indexes=list(error.unavailable_indexes),
                rolled_back=rolled_back,
                writes_suspended=self._writes_suspended,
            )
        if isinstance(error, AnalysisExecutionError):
            partial = {
                "prepared": prepared_json(error.report.prepared),
                "runtime": _runtime_tree(error.report.runtime),
            }
            return ServiceError(
                "EXECUTION_REFUSED", message, statement=family, execution_plan=partial,
                details={**details, "explanation": explanation_json(error.report)},
            )
        if isinstance(error, ValidationError):
            return fail("EXECUTION_REFUSED")
        raise error

    @staticmethod
    def _fit(body: dict[str, Any]) -> dict[str, Any]:
        """Enforce the exact response byte cap on the real encoded response.

        Trailing rows are dropped until the response fits; values are never
        shortened or altered. If not even one row, or not even the metadata,
        fits, the caller gets a structured error instead of a misleading empty
        success. Dropping rows after the engine reached EOF keeps the total
        exact: the result was complete, only the preview is shortened.
        """

        if encoded_size(body) <= MAX_RESPONSE_BYTES:
            return body
        rows = body["rows"]
        had_rows = bool(rows)
        while rows and encoded_size(body) > MAX_RESPONSE_BYTES:
            rows.pop()
            body["returned_rows"] = len(rows)
            body["truncated"] = True
            body["truncation_reason"] = "byte_limit"
        if encoded_size(body) > MAX_RESPONSE_BYTES:
            raise ServiceError(
                "RESULT_TOO_LARGE",
                "El plan y los metadatos exceden el límite de la respuesta.",
                statement=body.get("statement"),
            )
        if had_rows and not rows:
            raise ServiceError(
                "RESULT_TOO_LARGE",
                "Ni una sola fila cabe en el límite de la respuesta.",
                statement=body.get("statement"),
            )
        return body

    # ------------------------------------------------------------ shutdown

    def begin_shutdown(self) -> None:
        """Refuse new work and cancel every running statement, without waiting.

        Called as soon as the server is asked to stop, so a statement waiting
        for a lock answers ``TRANSACTION_CANCELLED`` while its connection is
        still open instead of being cut off by the web server.
        """

        if self._state != READY:
            return
        self._state = CLOSING
        self._sessions.stop()
        try:
            self._database.session_coordinator.default_session.cancel()
        except TransactionError:  # pragma: no cover - already closed
            pass

    def close(self, *, timeout_seconds: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Stop admission, cancel running work, then shut the owner down.

        Every client session is cancelled first, so a statement waiting for a
        lock ends promptly. The owner's bounded ``shutdown`` then waits for
        the cancellations to land, aborts open groups and closes the files.
        If that cannot finish in time, the service stays ``unavailable``
        instead of closing files under running work.
        """

        if self._state == CLOSED:
            return
        self._state = CLOSING
        self._sessions.stop()
        if not self._admission.acquire(timeout=timeout_seconds):
            self._state = UNAVAILABLE
            raise RuntimeError("A sessionless call did not finish before shutdown")
        try:
            self._database.shutdown(timeout_seconds=timeout_seconds)
        except BaseException:
            self._state = UNAVAILABLE
            raise
        finally:
            self._admission.release()
        self._state = CLOSED


def _runtime_tree(report) -> dict[str, Any] | None:
    if report is None:
        return None
    serialized = runtime_json(report)
    return {"root": serialized["root"], "truncated": serialized["truncated"]}


def _attach_runtime(plan: dict[str, Any], report) -> dict[str, Any] | None:
    """Put the executed tree in ``plan`` and return its measured counters."""

    if report is None:
        return None
    serialized = runtime_json(report)
    plan["runtime"] = {"root": serialized["root"], "truncated": serialized["truncated"]}
    return {
        key: serialized[key]
        for key in ("rows_produced", "elapsed_ms", "memory", "pages", "temporary")
    }


def _csv_error(error: CsvError) -> ServiceError:
    location = {
        key: value
        for key, value in (("line", error.line), ("column", error.column))
        if value is not None
    }
    return ServiceError("CSV_ERROR", error_message(error), details=location or None)
