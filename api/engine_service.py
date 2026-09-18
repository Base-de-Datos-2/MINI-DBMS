"""Own the demonstration engine: admission, statement policy, bounded output.

This is the only module that touches the engine on behalf of HTTP requests.
It implements the temporary Stage 9 execution policy of ETAPA_09.md Section 5:

* **Exclusive admission.** One engine operation runs at a time. A competing
  request is refused at once with ``ENGINE_BUSY``; nothing waits in a queue.
  Admission is held through preparation, classification, execution, preview
  conversion, the metrics snapshot and cursor cleanup, and it is acquired and
  released by the thread that does the synchronous engine work.
* **Statement policy.** Only SELECT runs by default. The decision uses the
  statement kind of the handwritten parser's prepared statement, which is
  obtained without executing anything; text matching is never used.
* **Bounded preview.** At most ``max_rows + 1`` rows are consumed. The extra
  row only proves that more results exist. Rows are also bounded in encoded
  bytes, and the result is closed before admission is released.

This guard is server admission control. It is **not** transaction grouping,
isolation, a lock manager, or the Stage 8 concurrency demonstration.
"""

from __future__ import annotations

from contextlib import contextmanager
import threading
from time import perf_counter
from typing import Any

from engine.errors import UnknownTableError, ValidationError
from engine.maintenance import MaintenanceError
from engine.query import (
    JoinPlanningStrategy,
    PhysicalPlanningOptions,
    SqlQueryError,
    StatementKind,
)

from .database import Database
from .schemas import (
    ERROR_STATUS,
    MAX_RESPONSE_BYTES,
    MAX_SQL_BYTES,
    READ_ONLY,
    SERIALIZED_WRITES,
    QueryRequest,
)
from .serialization import (
    column_descriptors,
    encode_row,
    encoded_size,
    error_message,
    prepared_json,
    runtime_json,
    sql_location,
    table_detail_json,
    table_summary_json,
)


READY = "ready"
CLOSING = "closing"
UNAVAILABLE = "unavailable"
CLOSED = "closed"

#: What the backend elapsed time covers. It excludes the final JSON encoding
#: done by the web framework and the browser round trip.
ELAPSED_SCOPE = "backend: prepare through cursor cleanup, including preview conversion"


class ServiceError(Exception):
    """A failure with a stable code, safe to show to the user as-is."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        location: dict[str, Any] | None = None,
        statement: str | None = None,
        execution_plan: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = ERROR_STATUS[code]
        self.message = message
        self.location = location
        self.statement = statement
        self.execution_plan = execution_plan
        self.details = details


class EngineService:
    """The single owner of the demonstration engine inside one server process."""

    __slots__ = ("_database", "_allow_writes", "_writes_suspended", "_admission",
                 "_state", "_static_health")

    def __init__(self, database: Database, *, allow_writes: bool = False) -> None:
        if not isinstance(database, Database):
            raise TypeError("EngineService requires an open Database")
        if database.closed:
            raise ValidationError("EngineService requires an open Database")
        if type(allow_writes) is not bool:
            raise TypeError("allow_writes must be a bool")
        self._database = database
        self._allow_writes = allow_writes
        self._writes_suspended = False
        self._admission = threading.Lock()
        self._state = READY
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
    def mode(self) -> str:
        """Return the presentation mode reported with every response."""

        if self._allow_writes and not self._writes_suspended:
            return SERIALIZED_WRITES
        return READ_ONLY

    def _allowed(self) -> frozenset[StatementKind]:
        if self.mode == SERIALIZED_WRITES:
            return frozenset(StatementKind)
        return frozenset({StatementKind.SELECT})

    def health(self) -> dict[str, Any]:
        """Return cached readiness without touching storage or the engine."""

        return {
            "status": self._state,
            "mode": self.mode,
            "writes_enabled": self.mode == SERIALIZED_WRITES,
            **self._static_health,
        }

    @contextmanager
    def _admitted(self):
        """Hold exclusive engine admission, or refuse immediately."""

        if self._state != READY:
            raise ServiceError(
                "ENGINE_UNAVAILABLE",
                "El motor no está disponible; reinicia el servidor de la demo.",
            )
        if not self._admission.acquire(blocking=False):
            raise ServiceError(
                "ENGINE_BUSY",
                "El motor está ejecutando otra operación; inténtalo cuando termine.",
            )
        try:
            if self._state != READY:
                raise ServiceError(
                    "ENGINE_UNAVAILABLE",
                    "El motor no está disponible; reinicia el servidor de la demo.",
                )
            yield self._database.engine
        finally:
            self._admission.release()

    def list_tables(self) -> list[dict[str, Any]]:
        """Summarize every loaded table without reading their rows."""

        with self._admitted():
            return [
                table_summary_json(self._database.describe_table(name))
                for name in self._database.table_names()
            ]

    def describe_table(self, table_id: str) -> dict[str, Any]:
        """Describe one table by its Catalog identifier."""

        with self._admitted():
            try:
                summary = self._database.describe_table(table_id)
            except (UnknownTableError, StopIteration):
                raise ServiceError(
                    "NOT_FOUND", f"No existe la tabla {table_id!r} en el catálogo."
                ) from None
            return table_detail_json(summary)

    def execute(self, request: QueryRequest, request_id: str) -> dict[str, Any]:
        """Run one statement under the presentation policy and bound its output."""

        if len(request.sql.encode("utf-8")) > MAX_SQL_BYTES:
            raise ServiceError(
                "REQUEST_TOO_LARGE",
                f"El SQL excede el límite de {MAX_SQL_BYTES} bytes UTF-8.",
            )
        started = perf_counter()
        with self._admitted() as engine:
            try:
                prepared = engine.prepare(
                    request.sql,
                    use_indexes=request.use_indexes,
                    planning_options=PhysicalPlanningOptions(
                        join_strategy=JoinPlanningStrategy[request.join_strategy]
                    ),
                )
            except SqlQueryError as error:
                raise ServiceError(
                    "SQL_ERROR", error_message(error), location=sql_location(error)
                ) from None

            statement = prepared.kind.value
            plan = {"prepared": prepared_json(prepared.describe()), "runtime": None}
            if prepared.kind not in self._allowed():
                raise ServiceError(
                    "STATEMENT_DISABLED",
                    f"{statement} no está habilitado en el modo {self.mode}; "
                    "la sentencia se validó y planificó, pero no se ejecutó.",
                    statement=statement,
                    execution_plan=plan,
                )
            try:
                if prepared.kind is StatementKind.SELECT:
                    body = self._run_select(prepared, request, plan)
                else:
                    body = self._run_command(prepared, plan)
            finally:
                self._verify_engine_idle(engine)
            body["statement"] = statement
            body["metrics"]["backend_elapsed_ms"] = round(
                (perf_counter() - started) * 1000, 3
            )
        body["request_id"] = request_id
        body["mode"] = self.mode
        return self._fit(body)

    def _verify_engine_idle(self, engine) -> None:
        # The engine admits one active result. If cleanup left one behind, no
        # later statement can run safely, so the service stops accepting work.
        if engine.active_result is not None:
            self._state = UNAVAILABLE

    def _run_select(self, prepared, request: QueryRequest, plan) -> dict[str, Any]:
        try:
            result = prepared.execute()
        except ValidationError as error:
            raise ServiceError(
                "EXECUTION_REFUSED", error_message(error), statement="SELECT", execution_plan=plan
            ) from None

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
        except ValidationError as error:
            plan["runtime"] = self._runtime_tree(result)
            raise ServiceError(
                "EXECUTION_REFUSED", error_message(error), statement="SELECT", execution_plan=plan
            ) from None

        report = result.report
        complete = reason is None and report.fully_consumed
        engine_metrics = self._attach_runtime(plan, result)
        return {
            "kind": "rows",
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

    def _run_command(self, prepared, plan) -> dict[str, Any]:
        statement = prepared.kind.value
        try:
            # A command executes synchronously, exactly once, inside execute().
            result = prepared.execute()
        except MaintenanceError as error:
            if error.unavailable_indexes:
                # Base/index consistency is no longer certain: stop writing.
                self._writes_suspended = True
            raise ServiceError(
                "EXECUTION_REFUSED",
                error_message(error),
                statement=statement,
                execution_plan=plan,
                details={
                    "completed_rows": error.completed_rows,
                    "unavailable_indexes": list(error.unavailable_indexes),
                    "writes_suspended": self._writes_suspended,
                },
            ) from None
        except ValidationError as error:
            raise ServiceError(
                "EXECUTION_REFUSED", error_message(error), statement=statement,
                execution_plan=plan,
            ) from None
        statistics = result.statistics
        discovery = getattr(statistics, "discovery", None)
        engine_metrics = None
        if discovery is not None:
            runtime = runtime_json(discovery)
            plan["runtime"] = {"root": runtime["root"], "truncated": runtime["truncated"]}
            engine_metrics = _engine_metrics(runtime)
        return {
            "kind": "command",
            "columns": [],
            "rows": [],
            "returned_rows": 0,
            "truncated": False,
            "truncation_reason": None,
            "result_complete": True,
            "total_rows": None,
            "affected_rows": result.affected_rows,
            "execution_plan": plan,
            "plan_status": "execution-observed" if plan["runtime"] else "prepared",
            "metrics": {
                "scope": ELAPSED_SCOPE,
                "partial": False,
                "engine": engine_metrics,
                "maintenance": {
                    "indexes_maintained": statistics.indexes_maintained,
                    "index_association_updates": statistics.index_association_updates,
                    "indexes_rebuilt": statistics.indexes_rebuilt,
                    "targets_spooled": statistics.targets_spooled,
                    "spool_bytes": statistics.spool_bytes,
                },
            },
        }

    @staticmethod
    def _runtime_tree(result) -> dict[str, Any] | None:
        runtime = result.report.runtime
        if runtime is None:
            return None
        serialized = runtime_json(runtime)
        return {"root": serialized["root"], "truncated": serialized["truncated"]}

    def _attach_runtime(self, plan, result) -> dict[str, Any] | None:
        runtime = result.report.runtime
        if runtime is None:
            return None
        serialized = runtime_json(runtime)
        plan["runtime"] = {"root": serialized["root"], "truncated": serialized["truncated"]}
        return _engine_metrics(serialized)

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

    def close(self) -> None:
        """Stop admission, wait for admitted work, then close every file."""

        if self._state == CLOSED:
            return
        self._state = CLOSING
        with self._admission:
            self._database.close()
        self._state = CLOSED


def _engine_metrics(runtime: dict[str, Any]) -> dict[str, Any]:
    """Measured, execution-local engine counters of one run."""

    return {
        key: runtime[key]
        for key in ("rows_produced", "elapsed_ms", "memory", "pages", "temporary")
    }
