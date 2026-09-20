"""Streaming Stage 7 execution and result ownership over Stage 6 plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import perf_counter

from engine.catalog import Schema
from engine.errors import (
    DatabaseError,
    InvalidTypeError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.maintenance import (
    DeleteTargetSpool,
    MaintenanceError,
    MaintenanceIndex,
    MutationReport,
    MutationService,
)
from engine.operators import ExecutionOperator, PhysicalPlan, PlanReport
from engine.operators.context import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_MAX_OPEN_HANDLES,
    MINIMUM_BUDGET_BYTES,
)
from engine.storage import Record

from .ast import (
    CreateTableStatement,
    DeleteStatement,
    InsertStatement,
)
from .environment import QueryEnvironment
from .ddl import CreatedTable, DdlService
from .errors import (
    SqlBindingError,
    SqlUnknownColumnError,
    SqlUnknownTableError,
    SqlUnsupportedError,
)
from .parser import parse_sql
from .planner import (
    CreatePlanSpec,
    DeletePlanSpec,
    ExplainPlanSpec,
    InsertPlanSpec,
    PhysicalPlanningOptions,
    PlanSpecDescriptor,
    SelectPlanSpec,
    prepare_plan,
)


DEFAULT_MATERIALIZATION_LIMIT = 10_000


def _reject_unavailable_extension(
    statement,
    source: str,
    ddl_service: DdlService | None,
) -> None:
    """Reject CREATE when no manifest-backed DDL service was injected."""

    if isinstance(statement, CreateTableStatement) and ddl_service is None:
        feature = "CREATE TABLE execution"
        offending = "CREATE"
    else:
        return
    if statement.span is None:
        raise RuntimeError("Parser-created extension statement lacks a span")
    raise SqlUnsupportedError(
        f"{feature} requires a manifest-backed database service",
        span=statement.span,
        source=source,
        offending=offending,
    )


class StatementKind(Enum):
    """The prepared statement family without exposing AST implementation data."""

    SELECT = "SELECT"
    INSERT = "INSERT"
    DELETE = "DELETE"
    CREATE = "CREATE"
    EXPLAIN = "EXPLAIN"
    EXPLAIN_ANALYZE = "EXPLAIN_ANALYZE"


class ResultKind(Enum):
    """Public result shape for every supported single-statement family."""

    ROWS = "ROWS"
    COMMAND = "COMMAND"
    DEFINITION = "DEFINITION"
    EXPLANATION = "EXPLANATION"


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
    runtime: PlanReport | MutationReport | None
    state: ResultState
    fully_consumed: bool
    rows_delivered: int
    error_type: str | None = None
    error_message: str | None = None
    affected_rows: int | None = None


@dataclass(frozen=True, slots=True)
class CommandExecutionReport(MutationReport):
    """Mutation measurements plus the real DELETE discovery plan, if any."""

    discovery: PlanReport | None = None

    @classmethod
    def combine(
        cls,
        maintenance: MutationReport,
        discovery: PlanReport | None = None,
    ) -> "CommandExecutionReport":
        return cls(
            operation=maintenance.operation,
            affected_rows=maintenance.affected_rows,
            indexes_maintained=maintenance.indexes_maintained,
            index_association_updates=maintenance.index_association_updates,
            indexes_rebuilt=maintenance.indexes_rebuilt,
            targets_spooled=maintenance.targets_spooled,
            spool_bytes=maintenance.spool_bytes,
            discovery=discovery,
        )


@dataclass(frozen=True, slots=True)
class DefinitionExecutionReport:
    """Prepared CREATE facts and the identity durably published by execution."""

    prepared: PlanSpecDescriptor
    state: ResultState
    table_name: str
    primary_index_name: str | None


@dataclass(frozen=True, slots=True)
class ExplanationExecutionReport:
    """Prepared plan and optional evidence from one complete analysis run."""

    prepared: PlanSpecDescriptor
    runtime: PlanReport | None
    state: ResultState
    executed: bool
    complete: bool
    output_rows: int | None
    planning_seconds: float
    execution_seconds: float | None
    error_type: str | None = None
    error_message: str | None = None


class AnalysisExecutionError(DatabaseError, RuntimeError):
    """EXPLAIN ANALYZE failed after cleanup, with its partial evidence."""

    def __init__(
        self,
        report: ExplanationExecutionReport,
        cause: BaseException,
    ) -> None:
        if not isinstance(report, ExplanationExecutionReport):
            raise InvalidTypeError(
                "AnalysisExecutionError requires an ExplanationExecutionReport"
            )
        if not isinstance(cause, BaseException):
            raise InvalidTypeError("AnalysisExecutionError requires an exception")
        self.report = report
        self.cause = cause
        super().__init__(
            "EXPLAIN ANALYZE failed after "
            f"{report.output_rows or 0} output rows: "
            f"{type(cause).__name__}: {cause}"
        )


PlanSpec = (
    SelectPlanSpec
    | InsertPlanSpec
    | DeletePlanSpec
    | CreatePlanSpec
    | ExplainPlanSpec
)


class PreparedQuery:
    """Reusable parse/bind/plan result with no live cursor or execution context."""

    __slots__ = ("_engine", "_spec", "_kind", "_planning_seconds")

    def __init__(
        self,
        engine: "SqlEngine",
        spec: PlanSpec,
        *,
        planning_seconds: float = 0.0,
    ) -> None:
        if not isinstance(engine, SqlEngine):
            raise InvalidTypeError("PreparedQuery requires a SqlEngine")
        if not isinstance(
            spec,
            (
                SelectPlanSpec,
                InsertPlanSpec,
                DeletePlanSpec,
                CreatePlanSpec,
                ExplainPlanSpec,
            ),
        ):
            raise InvalidTypeError("PreparedQuery requires a supported plan specification")
        if type(planning_seconds) is not float:
            raise InvalidTypeError("planning_seconds must be a float")
        if planning_seconds < 0:
            raise ValidationError("planning_seconds must be non-negative")
        self._engine = engine
        self._spec = spec
        self._planning_seconds = planning_seconds
        if isinstance(spec, SelectPlanSpec):
            self._kind = StatementKind.SELECT
        elif isinstance(spec, InsertPlanSpec):
            self._kind = StatementKind.INSERT
        elif isinstance(spec, DeletePlanSpec):
            self._kind = StatementKind.DELETE
        elif isinstance(spec, CreatePlanSpec):
            self._kind = StatementKind.CREATE
        elif spec.analyze:
            self._kind = StatementKind.EXPLAIN_ANALYZE
        else:
            self._kind = StatementKind.EXPLAIN

    @property
    def kind(self) -> StatementKind:
        return self._kind

    @property
    def schema(self) -> Schema | None:
        if isinstance(self._spec, SelectPlanSpec):
            return self._spec.output_schema
        return None

    @property
    def planning_seconds(self) -> float:
        """Return parse/bind/plan wall time measured for this preparation."""

        return self._planning_seconds

    @property
    def reusable(self) -> bool:
        """Prepared queries always create fresh physical state per execution."""

        return self._kind is not StatementKind.CREATE

    def describe(self) -> PlanSpecDescriptor:
        """Inspect the physical specification without opening or mutating data."""

        return self._spec.describe()

    def execute(
        self,
    ) -> "QueryResult | CommandResult | DefinitionResult | ExplanationResult":
        """Create one fresh execution through the owning single-session engine."""

        return self._engine.execute(self)


class CommandResult:
    """One already-completed INSERT or DELETE result with no row stream."""

    __slots__ = ("_prepared_description", "_statistics", "_statement_kind")

    def __init__(self, prepared: PreparedQuery, statistics: MutationReport) -> None:
        if not isinstance(prepared, PreparedQuery):
            raise InvalidTypeError("CommandResult requires a PreparedQuery")
        if prepared.kind not in {StatementKind.INSERT, StatementKind.DELETE}:
            raise ValidationError("CommandResult requires an INSERT or DELETE plan")
        if not isinstance(statistics, MutationReport):
            raise InvalidTypeError("CommandResult requires a MutationReport")
        self._prepared_description = prepared.describe()
        self._statistics = statistics
        self._statement_kind = prepared.kind

    @property
    def kind(self) -> ResultKind:
        return ResultKind.COMMAND

    @property
    def statement_kind(self) -> StatementKind:
        return self._statement_kind

    @property
    def state(self) -> ResultState:
        return ResultState.COMPLETE

    @property
    def schema(self) -> None:
        return None

    @property
    def affected_rows(self) -> int:
        return self._statistics.affected_rows

    @property
    def rows_delivered(self) -> int:
        return 0

    @property
    def fully_consumed(self) -> bool:
        return True

    @property
    def completed(self) -> bool:
        return True

    @property
    def closed(self) -> bool:
        return True

    @property
    def partial(self) -> bool:
        return False

    @property
    def error(self) -> None:
        return None

    @property
    def rows(self):
        raise UnsupportedAccessError("Command results do not contain rows")

    @property
    def statistics(self) -> MutationReport:
        return self._statistics

    @property
    def report(self) -> QueryExecutionReport:
        return QueryExecutionReport(
            prepared=self._prepared_description,
            runtime=self._statistics,
            state=ResultState.COMPLETE,
            fully_consumed=True,
            rows_delivered=0,
            affected_rows=self.affected_rows,
        )

    def fetchmany(self, size: int):
        raise UnsupportedAccessError("Command results do not contain rows")

    def fetchall(self, *, limit: int):
        raise UnsupportedAccessError("Command results do not contain rows")

    def close(self) -> None:
        """Command execution is synchronous, so there are no live resources."""

    def __iter__(self):
        raise UnsupportedAccessError("Command results are not iterable")

    def __enter__(self) -> "CommandResult":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class DefinitionResult:
    """One completed CREATE result with no row stream or affected-row count."""

    __slots__ = ("_prepared_description", "_created")

    def __init__(self, prepared: PreparedQuery, created: CreatedTable) -> None:
        if not isinstance(prepared, PreparedQuery):
            raise InvalidTypeError("DefinitionResult requires a PreparedQuery")
        if prepared.kind is not StatementKind.CREATE:
            raise ValidationError("DefinitionResult requires a CREATE plan")
        if not isinstance(created, CreatedTable):
            raise InvalidTypeError("DefinitionResult requires a CreatedTable")
        self._prepared_description = prepared.describe()
        self._created = created

    @property
    def kind(self) -> ResultKind:
        return ResultKind.DEFINITION

    @property
    def statement_kind(self) -> StatementKind:
        return StatementKind.CREATE

    @property
    def state(self) -> ResultState:
        return ResultState.COMPLETE

    @property
    def schema(self) -> None:
        return None

    @property
    def table_name(self) -> str:
        return self._created.table_name

    @property
    def primary_index_name(self) -> str | None:
        return self._created.primary_index_name

    @property
    def rows_delivered(self) -> int:
        return 0

    @property
    def fully_consumed(self) -> bool:
        return True

    @property
    def completed(self) -> bool:
        return True

    @property
    def closed(self) -> bool:
        return True

    @property
    def partial(self) -> bool:
        return False

    @property
    def error(self) -> None:
        return None

    @property
    def rows(self):
        raise UnsupportedAccessError("Definition results do not contain rows")

    @property
    def report(self) -> DefinitionExecutionReport:
        return DefinitionExecutionReport(
            prepared=self._prepared_description,
            state=ResultState.COMPLETE,
            table_name=self.table_name,
            primary_index_name=self.primary_index_name,
        )

    def fetchmany(self, size: int):
        raise UnsupportedAccessError("Definition results do not contain rows")

    def fetchall(self, *, limit: int):
        raise UnsupportedAccessError("Definition results do not contain rows")

    def close(self) -> None:
        """CREATE execution is synchronous, so there are no live resources."""

    def __iter__(self):
        raise UnsupportedAccessError("Definition results are not iterable")

    def __enter__(self) -> "DefinitionResult":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


class ExplanationResult:
    """Completed plan inspection, optionally with one measured SELECT run."""

    __slots__ = ("_statement_kind", "_report")

    def __init__(
        self,
        prepared: PreparedQuery,
        *,
        runtime: PlanReport | None = None,
        execution_seconds: float | None = None,
    ) -> None:
        if not isinstance(prepared, PreparedQuery):
            raise InvalidTypeError("ExplanationResult requires a PreparedQuery")
        if prepared.kind not in {
            StatementKind.EXPLAIN,
            StatementKind.EXPLAIN_ANALYZE,
        }:
            raise ValidationError("ExplanationResult requires an EXPLAIN plan")
        analyzed = prepared.kind is StatementKind.EXPLAIN_ANALYZE
        if analyzed:
            if not isinstance(runtime, PlanReport):
                raise InvalidTypeError(
                    "EXPLAIN ANALYZE requires a measured PlanReport"
                )
            if type(execution_seconds) is not float:
                raise InvalidTypeError(
                    "EXPLAIN ANALYZE execution_seconds must be a float"
                )
            if execution_seconds < 0:
                raise ValidationError("execution_seconds must be non-negative")
        elif runtime is not None or execution_seconds is not None:
            raise ValidationError("Plain EXPLAIN cannot contain runtime evidence")
        self._statement_kind = prepared.kind
        self._report = ExplanationExecutionReport(
            prepared=prepared.describe(),
            runtime=runtime,
            state=ResultState.COMPLETE,
            executed=analyzed,
            complete=True,
            output_rows=None if runtime is None else runtime.rows_produced,
            planning_seconds=prepared.planning_seconds,
            execution_seconds=execution_seconds,
        )

    @property
    def kind(self) -> ResultKind:
        return ResultKind.EXPLANATION

    @property
    def statement_kind(self) -> StatementKind:
        return self._statement_kind

    @property
    def state(self) -> ResultState:
        return self._report.state

    @property
    def schema(self) -> None:
        return None

    @property
    def plan(self) -> PlanSpecDescriptor:
        return self._report.prepared

    @property
    def statistics(self) -> PlanReport | None:
        return self._report.runtime

    @property
    def executed(self) -> bool:
        return self._report.executed

    @property
    def complete(self) -> bool:
        return self._report.complete

    @property
    def output_rows(self) -> int | None:
        return self._report.output_rows

    @property
    def planning_seconds(self) -> float:
        return self._report.planning_seconds

    @property
    def execution_seconds(self) -> float | None:
        return self._report.execution_seconds

    @property
    def rows_delivered(self) -> int:
        return 0

    @property
    def fully_consumed(self) -> bool:
        return True

    @property
    def completed(self) -> bool:
        return True

    @property
    def closed(self) -> bool:
        return True

    @property
    def partial(self) -> bool:
        return False

    @property
    def error(self) -> None:
        return None

    @property
    def rows(self):
        raise UnsupportedAccessError("Explanation results do not contain rows")

    @property
    def report(self) -> ExplanationExecutionReport:
        return self._report

    def fetchmany(self, size: int):
        raise UnsupportedAccessError("Explanation results do not contain rows")

    def fetchall(self, *, limit: int):
        raise UnsupportedAccessError("Explanation results do not contain rows")

    def close(self) -> None:
        """Explanations are synchronous and retain no live resources."""

    def __iter__(self):
        raise UnsupportedAccessError("Explanation results are not iterable")

    def __enter__(self) -> "ExplanationResult":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


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
    def statement_kind(self) -> StatementKind:
        return StatementKind.SELECT

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
        """SELECT has no command count; only command results expose one."""

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
            affected_rows=None,
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
        "_ddl_service",
    )

    def __init__(
        self,
        environment: QueryEnvironment,
        *,
        memory_budget_bytes: int = DEFAULT_BUDGET_BYTES,
        max_open_handles: int = DEFAULT_MAX_OPEN_HANDLES,
        materialization_limit: int = DEFAULT_MATERIALIZATION_LIMIT,
        planning_options: PhysicalPlanningOptions | None = None,
        ddl_service: DdlService | None = None,
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
        if ddl_service is not None and not isinstance(ddl_service, DdlService):
            raise InvalidTypeError("ddl_service must implement DdlService or be None")
        self._environment = environment
        self._memory_budget_bytes = memory_budget_bytes
        self._max_open_handles = max_open_handles
        self._materialization_limit = materialization_limit
        self._planning_options = planning_options
        self._active_result: QueryResult | None = None
        self._ddl_service = ddl_service

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

        started = perf_counter()
        options = self._planning_options if planning_options is None else planning_options
        if not isinstance(options, PhysicalPlanningOptions):
            raise InvalidTypeError(
                "planning_options must be PhysicalPlanningOptions or None"
            )
        statement = parse_sql(sql)
        _reject_unavailable_extension(statement, sql, self._ddl_service)
        spec = prepare_plan(
            self._environment,
            statement,
            use_indexes=use_indexes,
            options=options,
            ddl_service=self._ddl_service,
        )
        return PreparedQuery(
            self,
            spec,
            planning_seconds=perf_counter() - started,
        )

    @staticmethod
    def _maintenance_indexes(spec: InsertPlanSpec | DeletePlanSpec):
        return tuple(
            MaintenanceIndex(
                item.metadata.name,
                item.metadata.column_name,
                item.metadata.unique,
                item.index,
            )
            for item in spec.bound.indexes
        )

    def _execute_explanation(self, prepared: PreparedQuery) -> ExplanationResult:
        spec = prepared._spec
        if not isinstance(spec, ExplainPlanSpec):
            raise RuntimeError("An EXPLAIN prepared query lost its plan")
        if not spec.analyze:
            spec.validate()
            return ExplanationResult(prepared)

        plan: PhysicalPlan | None = None
        started = perf_counter()
        try:
            root = spec.select.instantiate()
            plan = PhysicalPlan(
                root,
                memory_budget_bytes=self._memory_budget_bytes,
                max_open_handles=self._max_open_handles,
                label="sql-explain-analyze",
            )
            with plan:
                for _ in plan.rows():
                    pass
            runtime = plan.report()
        except BaseException as error:
            elapsed = perf_counter() - started
            runtime = None
            if plan is not None:
                try:
                    runtime = plan.report()
                except BaseException as reporting_error:
                    try:
                        error.add_note(
                            "EXPLAIN ANALYZE could not capture its partial report: "
                            f"{type(reporting_error).__name__}: {reporting_error}"
                        )
                    except AttributeError:  # pragma: no cover - Python 3.11+
                        pass
            output_rows = (
                runtime.rows_produced
                if runtime is not None
                else (0 if plan is None else plan.rows_produced)
            )
            report = ExplanationExecutionReport(
                prepared=prepared.describe(),
                runtime=runtime,
                state=ResultState.FAILED,
                executed=True,
                complete=False,
                output_rows=output_rows,
                planning_seconds=prepared.planning_seconds,
                execution_seconds=elapsed,
                error_type=type(error).__name__,
                error_message=str(error),
            )
            raise AnalysisExecutionError(report, error) from error
        return ExplanationResult(
            prepared,
            runtime=runtime,
            execution_seconds=perf_counter() - started,
        )

    def execute(
        self,
        query: str | PreparedQuery,
        *,
        use_indexes: bool | None = None,
        planning_options: PhysicalPlanningOptions | None = None,
    ) -> QueryResult | CommandResult | DefinitionResult | ExplanationResult:
        """Execute one statement under the single-session lifecycle contract."""

        self._require_idle()
        if use_indexes is not None and type(use_indexes) is not bool:
            raise InvalidTypeError("use_indexes must be a bool or None")
        if planning_options is not None and not isinstance(
            planning_options, PhysicalPlanningOptions
        ):
            raise InvalidTypeError(
                "planning_options must be PhysicalPlanningOptions or None"
            )
        if isinstance(query, str):
            planning_started = perf_counter()
            indexes_enabled = True if use_indexes is None else use_indexes
            options = (
                self._planning_options
                if planning_options is None
                else planning_options
            )
            statement = parse_sql(query)
            _reject_unavailable_extension(statement, query, self._ddl_service)
            try:
                spec = prepare_plan(
                    self._environment,
                    statement,
                    use_indexes=indexes_enabled,
                    options=options,
                    ddl_service=self._ddl_service,
                )
            except SqlBindingError as error:
                if isinstance(statement, (InsertStatement, DeleteStatement)) and not isinstance(
                    error, (SqlUnknownTableError, SqlUnknownColumnError)
                ):
                    operation = "INSERT" if isinstance(statement, InsertStatement) else "DELETE"
                    raise MaintenanceError(
                        f"{operation} validation failed before the first write",
                        operation=operation,
                        table_name=statement.table,
                        completed_rows=0,
                        failures=(error,),
                    ) from error
                raise
            prepared = PreparedQuery(
                self,
                spec,
                planning_seconds=perf_counter() - planning_started,
            )
        elif isinstance(query, PreparedQuery):
            prepared = query
            if prepared._engine is not self:
                raise ValidationError("PreparedQuery belongs to another SqlEngine")
            if use_indexes is not None or planning_options is not None:
                raise ValidationError(
                    "A PreparedQuery already has fixed planning options; prepare a "
                    "new query to change them"
                )
        else:
            raise InvalidTypeError("execute requires SQL text or PreparedQuery")
        if prepared.kind in {
            StatementKind.EXPLAIN,
            StatementKind.EXPLAIN_ANALYZE,
        }:
            return self._execute_explanation(prepared)
        if prepared.kind is StatementKind.CREATE:
            spec = prepared._spec
            if not isinstance(spec, CreatePlanSpec):
                raise RuntimeError("A CREATE prepared query lost its plan")
            spec.validate()
            created = spec.service.create_table(spec.bound.table)
            return DefinitionResult(prepared, created)
        if prepared.kind is not StatementKind.SELECT:
            spec = prepared._spec
            if not isinstance(spec, (InsertPlanSpec, DeletePlanSpec)):
                raise RuntimeError("A mutation prepared query lost its plan")
            service = MutationService()
            indexes = self._maintenance_indexes(spec)
            if isinstance(spec, InsertPlanSpec):
                bound = spec.bound
                spec.validate()
                maintenance = service.insert(
                    table_name=bound.table.name,
                    table_metadata=bound.table,
                    storage=bound.storage,
                    record=bound.record,
                    indexes=indexes,
                    storage_may_move_rids=bound.storage_may_move_rids,
                    storage_key=bound.storage_key,
                    requires_storage_unique_check=bound.requires_storage_unique_check,
                )
                statistics = CommandExecutionReport.combine(maintenance)
            else:
                bound = spec.bound
                spec.validate()
                with DeleteTargetSpool() as spool:
                    try:
                        root = spec.instantiate_candidates()
                        if not isinstance(root, ExecutionOperator):
                            raise InvalidTypeError(
                                "DELETE discovery requires an ExecutionOperator"
                            )
                        plan = PhysicalPlan(
                            root,
                            memory_budget_bytes=self._memory_budget_bytes,
                            max_open_handles=self._max_open_handles,
                            label="sql-delete-discovery",
                        )
                        with plan:
                            for record in plan.rows():
                                provenance = root.provenance
                                if (
                                    len(provenance) != 1
                                    or provenance[0].relation != bound.table.name
                                ):
                                    raise ValidationError(
                                        "DELETE discovery lost exact base-row provenance"
                                    )
                                spool.append(provenance[0].rid, record)
                        discovery = plan.report()
                        spool.seal()
                    except BaseException as error:
                        raise MaintenanceError(
                            "DELETE target discovery failed before the first write",
                            operation="DELETE",
                            table_name=bound.table.name,
                            completed_rows=0,
                            failures=(error,),
                        ) from error
                    # Discovery holds only borrowed handles and is fully closed.
                    # Recheck the prepared mutation snapshot before the first write.
                    spec.validate()
                    maintenance = service.delete(
                        table_name=bound.table.name,
                        storage=bound.storage,
                        indexes=indexes,
                        targets=spool.targets(bound.table.schema),
                        target_count=spool.count,
                        spool_bytes=spool.size,
                    )
                    statistics = CommandExecutionReport.combine(
                        maintenance,
                        discovery,
                    )
            return CommandResult(prepared, statistics)
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
    ddl_service: DdlService | None = None,
) -> PreparedQuery:
    """Create an independently usable prepared query over one environment."""

    engine = SqlEngine(
        environment,
        memory_budget_bytes=memory_budget_bytes,
        max_open_handles=max_open_handles,
        materialization_limit=materialization_limit,
        planning_options=planning_options,
        ddl_service=ddl_service,
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
    ddl_service: DdlService | None = None,
) -> QueryResult | CommandResult | DefinitionResult | ExplanationResult:
    """Execute SQL and return its explicit public result variant."""

    engine = SqlEngine(
        environment,
        memory_budget_bytes=memory_budget_bytes,
        max_open_handles=max_open_handles,
        materialization_limit=materialization_limit,
        planning_options=planning_options,
        ddl_service=ddl_service,
    )
    return engine.execute(
        sql,
        use_indexes=use_indexes,
        planning_options=planning_options,
    )


__all__ = [
    "AnalysisExecutionError",
    "CommandExecutionReport",
    "CommandResult",
    "DefinitionExecutionReport",
    "DefinitionResult",
    "ExplanationExecutionReport",
    "ExplanationResult",
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
