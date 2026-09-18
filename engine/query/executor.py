"""Streaming Stage 7 execution and result ownership over Stage 6 plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.catalog import Schema
from engine.errors import InvalidTypeError, UnsupportedAccessError, ValidationError
from engine.operators import PhysicalPlan, PlanReport
from engine.operators.context import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_MAX_OPEN_HANDLES,
    MINIMUM_BUDGET_BYTES,
)
from engine.storage import Record

from .environment import QueryEnvironment
from .parser import parse_sql
from .planner import (
    DeletePlanSpec,
    InsertPlanSpec,
    PhysicalPlanningOptions,
    PlanSpecDescriptor,
    SelectPlanSpec,
    prepare_plan,
)


DEFAULT_MATERIALIZATION_LIMIT = 10_000


class StatementKind(Enum):
    """The prepared statement family without exposing AST implementation data."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    DELETE = "DELETE"


class ResultKind(Enum):
    """Public result shape; command results are reserved for Tasks 7.23-7.25."""

    ROWS = "ROWS"
    COMMAND = "COMMAND"


class ResultState(Enum):
    """Observable lifecycle state of one fresh execution."""

    CREATED = "CREATED"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class QueryExecutionReport:
    """Prepared facts beside measured evidence from one physical execution."""

    prepared: PlanSpecDescriptor
    runtime: PlanReport | None
    state: ResultState
    fully_consumed: bool
    rows_delivered: int
    error_type: str | None = None
    error_message: str | None = None


PlanSpec = SelectPlanSpec | InsertPlanSpec | DeletePlanSpec


class PreparedQuery:
    """Reusable parse/bind/plan result with no live cursor or execution context."""

    __slots__ = ("_engine", "_spec", "_kind")

    def __init__(self, engine: "SqlEngine", spec: PlanSpec) -> None:
        if not isinstance(engine, SqlEngine):
            raise InvalidTypeError("PreparedQuery requires a SqlEngine")
        if not isinstance(spec, (SelectPlanSpec, InsertPlanSpec, DeletePlanSpec)):
            raise InvalidTypeError("PreparedQuery requires a supported plan specification")
        self._engine = engine
        self._spec = spec
        if isinstance(spec, SelectPlanSpec):
            self._kind = StatementKind.SELECT
        elif isinstance(spec, InsertPlanSpec):
            self._kind = StatementKind.INSERT
        else:
            self._kind = StatementKind.DELETE

    @property
    def kind(self) -> StatementKind:
        return self._kind

    @property
    def schema(self) -> Schema | None:
        if isinstance(self._spec, SelectPlanSpec):
            return self._spec.output_schema
        return None

    @property
    def reusable(self) -> bool:
        """Prepared queries always create fresh physical state per execution."""

        return True

    def describe(self) -> PlanSpecDescriptor:
        """Inspect the physical specification without opening or mutating data."""

        return self._spec.describe()

    def execute(self) -> "QueryResult":
        """Create one fresh execution through the owning single-session engine."""

        return self._engine.execute(self)


class QueryResult:
    """One bounded, streaming SELECT execution and its owned transient state.

    The result owns its physical operator tree and ``ExecutionContext`` but
    borrows permanent table/index managers through ``QueryEnvironment``. Normal
    exhaustion closes owned resources and records ``COMPLETE``. Explicit early
    close records ``CLOSED``; operator or cleanup errors record ``FAILED``.
    """

    __slots__ = (
        "_engine",
        "_prepared",
        "_prepared_description",
        "_state",
        "_plan",
        "_plan_open",
        "_stream",
        "_error",
        "_rows_delivered",
        "_materialization_limit",
        "_cached_rows",
    )

    def __init__(
        self,
        engine: "SqlEngine",
        prepared: PreparedQuery,
        *,
        materialization_limit: int,
    ) -> None:
        if not isinstance(engine, SqlEngine):
            raise InvalidTypeError("QueryResult requires a SqlEngine")
        if not isinstance(prepared, PreparedQuery):
            raise InvalidTypeError("QueryResult requires a PreparedQuery")
        if prepared.kind is not StatementKind.SELECT:
            raise UnsupportedAccessError("QueryResult can stream only SELECT plans")
        self._engine = engine
        self._prepared = prepared
        self._prepared_description = prepared.describe()
        self._state = ResultState.CREATED
        self._plan: PhysicalPlan | None = None
        self._plan_open = False
        self._stream = None
        self._error: BaseException | None = None
        self._rows_delivered = 0
        self._materialization_limit = materialization_limit
        self._cached_rows: tuple[Record, ...] | None = None

    @property
    def kind(self) -> ResultKind:
        return ResultKind.ROWS

    @property
    def state(self) -> ResultState:
        return self._state

    @property
    def schema(self) -> Schema:
        schema = self._prepared.schema
        if schema is None:  # pragma: no cover - guarded by the constructor
            raise RuntimeError("A row result lost its output schema")
        return schema

    @property
    def rows_delivered(self) -> int:
        return self._rows_delivered

    @property
    def fully_consumed(self) -> bool:
        return self._state is ResultState.COMPLETE

    @property
    def completed(self) -> bool:
        return self.fully_consumed

    @property
    def closed(self) -> bool:
        return self._state in {
            ResultState.COMPLETE,
            ResultState.CLOSED,
            ResultState.FAILED,
        }

    @property
    def partial(self) -> bool:
        return self._rows_delivered > 0 and not self.fully_consumed

    @property
    def error(self) -> BaseException | None:
        return self._error

    @property
    def affected_rows(self) -> None:
        """SELECT has no command count; mutation results arrive in later tasks."""

        return None

    @property
    def rows(self) -> tuple[Record, ...]:
        """Bounded compatibility materialization; streaming remains primary."""

        if self._cached_rows is None:
            self._cached_rows = self.fetchall(limit=self._materialization_limit)
        return self._cached_rows

    @property
    def statistics(self) -> PlanReport | None:
        """Return measured Stage 6 evidence, if execution has started."""

        if self._plan is None:
            return None
        return self._plan.report()

    @property
    def report(self) -> QueryExecutionReport:
        error = self._error
        return QueryExecutionReport(
            prepared=self._prepared_description,
            runtime=self.statistics,
            state=self._state,
            fully_consumed=self.fully_consumed,
            rows_delivered=self._rows_delivered,
            error_type=None if error is None else type(error).__name__,
            error_message=None if error is None else str(error),
        )

    def _release_session(self) -> None:
        self._engine._release_result(self)

    def _preserve_cleanup_error(
        self,
        original: BaseException,
        cleanup: BaseException,
    ) -> None:
        if cleanup is original:
            return
        try:
            original.add_note(
                f"Additional result cleanup failure: {type(cleanup).__name__}: {cleanup}"
            )
        except AttributeError:  # pragma: no cover - Python 3.11+ provides add_note
            pass

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.close()

    def _close_owned(self, original: BaseException | None = None) -> None:
        """Attempt every owned cleanup, preserving the first relevant error."""

        failure = original
        was_open, self._plan_open = self._plan_open, False
        try:
            self._close_stream()
        except BaseException as cleanup:
            if failure is None:
                failure = cleanup
            else:
                self._preserve_cleanup_error(failure, cleanup)
        if was_open and self._plan is not None:
            try:
                self._plan.__exit__(
                    None if failure is None else type(failure),
                    failure,
                    None if failure is None else failure.__traceback__,
                )
            except BaseException as cleanup:
                if failure is None:
                    failure = cleanup
                else:
                    self._preserve_cleanup_error(failure, cleanup)
        if original is None and failure is not None:
            raise failure

    def _fail(self, error: BaseException) -> None:
        try:
            self._close_owned(error)
        finally:
            self._state = ResultState.FAILED
            self._error = error
            self._release_session()

    def open(self) -> "QueryResult":
        """Instantiate and open one fresh physical plan and execution context."""

        if self._state is not ResultState.CREATED:
            if self._state is ResultState.OPEN:
                return self
            raise RuntimeError(f"Cannot open a result in state {self._state.value}")
        spec = self._prepared._spec
        if not isinstance(spec, SelectPlanSpec):  # pragma: no cover - constructor guard
            raise RuntimeError("A row result lost its SELECT plan")
        try:
            root = spec.instantiate()
            self._plan = PhysicalPlan(
                root,
                memory_budget_bytes=self._engine.memory_budget_bytes,
                max_open_handles=self._engine.max_open_handles,
                label="sql-select",
            )
            self._plan.__enter__()
            self._plan_open = True
            self._stream = self._plan.rows()
            self._state = ResultState.OPEN
            return self
        except BaseException as error:
            self._fail(error)
            raise

    def _complete(self) -> None:
        try:
            self._close_owned()
        except BaseException as error:
            self._state = ResultState.FAILED
            self._error = error
            self._release_session()
            raise
        self._state = ResultState.COMPLETE
        self._release_session()

    def close(self) -> None:
        """Close early and release all execution-owned resources; idempotent."""

        if self._state in {
            ResultState.COMPLETE,
            ResultState.CLOSED,
            ResultState.FAILED,
        }:
            return
        if self._state is ResultState.CREATED:
            self._state = ResultState.CLOSED
            self._release_session()
            return
        try:
            self._close_owned()
        except BaseException as error:
            self._state = ResultState.FAILED
            self._error = error
            self._release_session()
            raise
        self._state = ResultState.CLOSED
        self._release_session()

    def __enter__(self) -> "QueryResult":
        return self.open()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_value is None:
            self.close()
            return False
        try:
            self._close_owned(exc_value)
        finally:
            self._state = ResultState.CLOSED
            self._release_session()
        return False

    def __iter__(self) -> "QueryResult":
        return self

    def __next__(self) -> Record:
        if self._state is ResultState.CREATED:
            self.open()
        if self._state is ResultState.COMPLETE:
            raise StopIteration
        if self._state is ResultState.CLOSED:
            raise RuntimeError("Cannot continue a result that was closed early")
        if self._state is ResultState.FAILED:
            raise RuntimeError("Cannot continue a failed query result") from self._error
        try:
            row = next(self._stream)
        except StopIteration:
            self._complete()
            raise
        except BaseException as error:
            self._fail(error)
            raise
        self._rows_delivered += 1
        return row

    def fetchmany(self, size: int) -> tuple[Record, ...]:
        """Read at most ``size`` rows without materializing the remaining stream."""

        if type(size) is not int:
            raise InvalidTypeError("fetchmany size must be an int")
        if size < 0:
            raise ValidationError("fetchmany size must be non-negative")
        rows = []
        for _ in range(size):
            try:
                rows.append(next(self))
            except StopIteration:
                break
        return tuple(rows)

    def fetchall(self, *, limit: int) -> tuple[Record, ...]:
        """Materialize one untouched result under an explicit hard row bound."""

        if type(limit) is not int:
            raise InvalidTypeError("fetchall limit must be an int")
        if limit < 0:
            raise ValidationError("fetchall limit must be non-negative")
        if self._rows_delivered:
            raise ValidationError(
                "fetchall is available only before streaming rows from this result"
            )
        rows = []
        while True:
            try:
                row = next(self)
            except StopIteration:
                materialized = tuple(rows)
                self._cached_rows = materialized
                return materialized
            if len(rows) == limit:
                self.close()
                raise ValidationError(
                    f"The query produced more than the requested {limit} rows"
                )
            rows.append(row)


class SqlEngine:
    """Single-session SQL facade independent from HTTP and UI frameworks.

    One unconsumed SELECT result owns the session at a time. This is a Stage 7
    lifecycle rule, not a concurrency guarantee; Stage 8 will define concurrent
    transactions and cursor interactions.
    """

    __slots__ = (
        "_environment",
        "_memory_budget_bytes",
        "_max_open_handles",
        "_materialization_limit",
        "_planning_options",
        "_active_result",
    )

    def __init__(
        self,
        environment: QueryEnvironment,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
        planning_options: PhysicalPlanningOptions | None = None,
    ) -> None:
        if not isinstance(environment, QueryEnvironment):
            raise InvalidTypeError("SqlEngine requires a QueryEnvironment")
        if type(memory_budget_bytes) is not int:
            raise InvalidTypeError("memory_budget_bytes must be an int")
        if memory_budget_bytes < MINIMUM_BUDGET_BYTES:
            raise ValidationError(
                f"memory_budget_bytes must be at least {MINIMUM_BUDGET_BYTES}"
            )
        if type(max_open_handles) is not int:
            raise InvalidTypeError("max_open_handles must be an int")
        if max_open_handles < 1:
            raise ValidationError("max_open_handles must be positive")
        if type(materialization_limit) is not int:
            raise InvalidTypeError("materialization_limit must be an int")
        if materialization_limit < 0:
            raise ValidationError("materialization_limit must be non-negative")
        if planning_options is None:
            planning_options = PhysicalPlanningOptions()
        elif not isinstance(planning_options, PhysicalPlanningOptions):
            raise InvalidTypeError(
                "planning_options must be PhysicalPlanningOptions or None"
            )
        self._environment = environment
        self._memory_budget_bytes = memory_budget_bytes
        self._max_open_handles = max_open_handles
        self._materialization_limit = materialization_limit
        self._planning_options = planning_options
        self._active_result: QueryResult | None = None

    @property
    def environment(self) -> QueryEnvironment:
        return self._environment

    @property
    def memory_budget_bytes(self) -> int:
        return self._memory_budget_bytes

    @property
    def max_open_handles(self) -> int:
        return self._max_open_handles

    @property
    def active_result(self) -> QueryResult | None:
        return self._active_result

    def _release_result(self, result: QueryResult) -> None:
        if self._active_result is result:
            self._active_result = None

    def _require_idle(self) -> None:
        active = self._active_result
        if active is not None and not active.closed:
            raise ValidationError(
                "Close or fully consume the active SELECT result before executing "
                "another statement"
            )

    def prepare(
        self,
        sql: str,
        *,
        use_indexes: bool = True,
        planning_options: PhysicalPlanningOptions | None = None,
    ) -> PreparedQuery:
        """Parse, bind, and plan without opening cursors or applying mutations."""

        options = self._planning_options if planning_options is None else planning_options
        if not isinstance(options, PhysicalPlanningOptions):
            raise InvalidTypeError(
                "planning_options must be PhysicalPlanningOptions or None"
            )
        statement = parse_sql(sql)
        spec = prepare_plan(
            self._environment,
            statement,
            use_indexes=use_indexes,
            options=options,
        )
        return PreparedQuery(self, spec)

    def execute(self, query: str | PreparedQuery) -> QueryResult:
        """Return a streaming SELECT result; mutation execution is still closed."""

        self._require_idle()
        if isinstance(query, str):
            prepared = self.prepare(query)
        elif isinstance(query, PreparedQuery):
            prepared = query
            if prepared._engine is not self:
                raise ValidationError("PreparedQuery belongs to another SqlEngine")
        else:
            raise InvalidTypeError("execute requires SQL text or PreparedQuery")
        if prepared.kind is not StatementKind.SELECT:
            raise UnsupportedAccessError(
                "INSERT/DELETE execution requires the Stage 7 maintenance block "
                "(Tasks 7.23-7.25); inspection remains read-only"
            )
        result = QueryResult(
            self,
            prepared,
            materialization_limit=self._materialization_limit,
        )
        self._active_result = result
        return result

    def describe(self, sql: str, *, use_indexes: bool = True) -> PlanSpecDescriptor:
        return self.prepare(sql, use_indexes=use_indexes).describe()

    def close(self) -> None:
        active = self._active_result
        if active is not None:
            active.close()

    def __enter__(self) -> "SqlEngine":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_value is None:
            self.close()
            return False
        active = self._active_result
        if active is not None:
            active.__exit__(exc_type, exc_value, traceback)
        return False


def prepare_sql(
    environment: QueryEnvironment,
    sql: str,
    *,
    use_indexes: bool = True,
    memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
    max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
    materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
    planning_options: PhysicalPlanningOptions | None = None,
) -> PreparedQuery:
    """Create an independently usable prepared query over one environment."""

    engine = SqlEngine(
        environment,
        memory_budget_bytes=memory_budget_bytes,
        max_open_handles=max_open_handles,
        materialization_limit=materialization_limit,
        planning_options=planning_options,
    )
    return engine.prepare(sql, use_indexes=use_indexes)


def run_sql(
    environment: QueryEnvironment,
    sql: str,
    *,
    use_indexes: bool = True,
    memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
    max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
    materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
    planning_options: PhysicalPlanningOptions | None = None,
) -> QueryResult:
    """Return a lazy streaming SELECT result with a bounded ``rows`` shortcut."""

    prepared = prepare_sql(
        environment,
        sql,
        use_indexes=use_indexes,
        memory_budget_bytes=memory_budget_bytes,
        max_open_handles=max_open_handles,
        materialization_limit=materialization_limit,
        planning_options=planning_options,
    )
    return prepared.execute()


__all__ = [
    "PreparedQuery",
    "QueryExecutionReport",
    "QueryResult",
    "ResultKind",
    "ResultState",
    "SqlEngine",
    "StatementKind",
    "prepare_sql",
    "run_sql",
]
