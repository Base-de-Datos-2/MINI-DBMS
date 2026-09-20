"""Conservative physical planning over the reviewed Stage 6 operators.

The semantic binder owns SQL meaning. This module chooses a physical access
path and stores immutable construction data; it never opens an operator or
touches a table/index cursor. A prepared SELECT therefore creates a fresh
mutable Stage 6 operator tree for every execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from engine.catalog import IndexMetadata, Schema, TableMetadata
from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.indexes import BPlusKeyCodec, OrderedIndex
from engine.operators import (
    Aggregate,
    Avg,
    ColumnReference,
    ComparisonOperator,
    Count,
    CountColumn,
    EqualitySearch,
    ExecutionOperator,
    ExternalHashGroup,
    ExternalSort,
    Filter,
    GraceHashJoin,
    IndexNestedLoopJoin,
    IndexScan,
    JoinKey,
    JoinSpec,
    Max,
    Min,
    NestedLoopJoin,
    Projection,
    RangeSearch,
    SortKey,
    SortSpec,
    Sum,
    TableScan,
    build_grouped_layout,
    compare_values,
)
from engine.operators.aggregation import MINIMUM_GROUP_BUDGET_BYTES
from engine.operators.join import MINIMUM_JOIN_BUDGET_BYTES
from engine.operators.partitioning import (
    DEFAULT_PARTITION_COUNT,
    MAX_PARTITION_LEVEL,
)
from engine.operators.sorting import (
    DEFAULT_MAX_FAN_IN,
    MINIMUM_FAN_IN,
    MINIMUM_SORT_BUDGET_BYTES,
)
from engine.storage import PagedSequentialFile, Storage
from engine.storage.record import RecordValue

from .ast import (
    CreateTableStatement,
    DeleteStatement,
    InsertStatement,
    SelectStatement,
    Statement,
)
from .binder import (
    BoundCreate,
    BoundDelete,
    BoundIndexCondition,
    BoundIndexMutation,
    BoundInsert,
    BoundPredicate,
    BoundProjectionItem,
    BoundRelation,
    BoundSelect,
    bind_select,
    bind_statement,
)
from .ddl import DdlService
from .environment import QueryEnvironment, RegisteredIndex


class StalePlanError(ValidationError):
    """A prepared plan no longer matches its Catalog/runtime identities."""


class JoinPlanningStrategy(Enum):
    """Explicit join route policy; AUTO may use one exact inner index."""

    AUTO = "AUTO"
    GRACE_HASH = "GRACE_HASH"
    NESTED_LOOP = "NESTED_LOOP"


@dataclass(frozen=True, slots=True)
class PhysicalPlanningOptions:
    """Resource/strategy controls copied into reusable physical specs.

    ``None`` budgets let a future executor grant resources through its shared
    ``ExecutionContext``. Tests may set exact Stage 6 minimums to force real
    external behavior without adding alternate SQL-layer algorithms.
    """

    sort_memory_budget_bytes: int | None = None
    sort_max_fan_in: int = DEFAULT_MAX_FAN_IN
    group_memory_budget_bytes: int | None = None
    group_partition_count: int = DEFAULT_PARTITION_COUNT
    group_max_level: int = MAX_PARTITION_LEVEL
    join_memory_budget_bytes: int | None = None
    join_partition_count: int = DEFAULT_PARTITION_COUNT
    join_max_level: int = MAX_PARTITION_LEVEL
    join_strategy: JoinPlanningStrategy = JoinPlanningStrategy.AUTO

    def __post_init__(self) -> None:
        budgets = (
            ("sort_memory_budget_bytes", self.sort_memory_budget_bytes,
             MINIMUM_SORT_BUDGET_BYTES),
            ("group_memory_budget_bytes", self.group_memory_budget_bytes,
             MINIMUM_GROUP_BUDGET_BYTES),
            ("join_memory_budget_bytes", self.join_memory_budget_bytes,
             MINIMUM_JOIN_BUDGET_BYTES),
        )
        for name, value, minimum in budgets:
            if value is not None and type(value) is not int:
                raise InvalidTypeError(f"{name} must be an int or None")
            if value is not None and value < minimum:
                raise ValidationError(f"{name} must be at least {minimum} bytes")
        if type(self.sort_max_fan_in) is not int:
            raise InvalidTypeError("sort_max_fan_in must be an int")
        if self.sort_max_fan_in < MINIMUM_FAN_IN:
            raise ValidationError(
                f"sort_max_fan_in must be at least {MINIMUM_FAN_IN}"
            )
        for name, value in (
            ("group_partition_count", self.group_partition_count),
            ("join_partition_count", self.join_partition_count),
        ):
            if type(value) is not int:
                raise InvalidTypeError(f"{name} must be an int")
            if value < 2:
                raise ValidationError(f"{name} must be at least 2")
        for name, value in (
            ("group_max_level", self.group_max_level),
            ("join_max_level", self.join_max_level),
        ):
            if type(value) is not int:
                raise InvalidTypeError(f"{name} must be an int")
            if value < 1:
                raise ValidationError(f"{name} must be positive")
        if not isinstance(self.join_strategy, JoinPlanningStrategy):
            raise InvalidTypeError(
                "join_strategy must be a JoinPlanningStrategy member"
            )


@dataclass(frozen=True, slots=True)
class PlanCapabilities:
    """Properties a physical specification can safely promise to its parent."""

    preserves_occurrences: bool = True
    complete_candidate_set: bool = True
    ordered_by: ColumnReference | None = None


@dataclass(frozen=True, slots=True)
class PlanSpecDescriptor:
    """Read-only description of a prepared physical tree."""

    name: str
    output_columns: tuple[tuple[str, str], ...]
    details: tuple[tuple[str, str], ...] = ()
    capabilities: PlanCapabilities = PlanCapabilities()
    children: tuple["PlanSpecDescriptor", ...] = ()

    def render(self, indent: int = 0) -> str:
        """Render this specification without constructing live operators."""

        prefix = "  " * indent
        detail = ", ".join(f"{key}={value}" for key, value in self.details)
        head = f"{prefix}{self.name}" + (f"({detail})" if detail else "")
        lines = [head]
        for child in self.children:
            lines.append(child.render(indent + 1))
        return "\n".join(lines)

    def walk(self):
        """Yield this descriptor and all descendants, parents first."""

        yield self
        for child in self.children:
            yield from child.walk()


class PhysicalPlanSpec(ABC):
    """Immutable factory input for one Stage 6 physical-operator subtree."""

    @property
    @abstractmethod
    def children(self) -> tuple["PhysicalPlanSpec", ...]:
        """Return child specifications in operator input order."""

    @property
    @abstractmethod
    def output_schema(self) -> Schema:
        """Return the schema this subtree will publish."""

    @property
    @abstractmethod
    def capabilities(self) -> PlanCapabilities:
        """Return conservatively tracked physical properties."""

    @property
    @abstractmethod
    def operator_name(self) -> str:
        """Return the real Stage 6 operator class name this spec creates."""

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        """Return non-estimated construction facts for inspection."""

        return ()

    @abstractmethod
    def instantiate(self) -> ExecutionOperator:
        """Construct a fresh, closed Stage 6 operator subtree."""

    def describe(self) -> PlanSpecDescriptor:
        """Describe the prepared tree without creating operator instances."""

        return PlanSpecDescriptor(
            self.operator_name,
            tuple(
                (column.name, column.data_type.value)
                for column in self.output_schema
            ),
            self.details,
            self.capabilities,
            tuple(child.describe() for child in self.children),
        )


def _validate_relation(
    environment: QueryEnvironment,
    relation: BoundRelation,
) -> None:
    try:
        current_table = environment.catalog.get_table(relation.metadata.name)
        current_storage = environment.storage_for(relation.metadata.name)
    except (InvalidReferenceError, ValidationError, RuntimeError) as error:
        raise StalePlanError(
            f"Prepared relation {relation.metadata.name!r} is no longer available"
        ) from error
    if current_table is not relation.metadata:
        raise StalePlanError(
            f"Catalog definition changed for table {relation.metadata.name!r}"
        )
    if current_storage is not relation.storage:
        raise StalePlanError(
            f"Runtime storage changed for table {relation.metadata.name!r}"
        )


def _validate_index(
    environment: QueryEnvironment,
    registered: RegisteredIndex,
) -> None:
    try:
        current_metadata = environment.catalog.get_index(registered.metadata.name)
        current_index = environment.index_for(registered.metadata.name)
    except (InvalidReferenceError, ValidationError, RuntimeError) as error:
        raise StalePlanError(
            f"Prepared index {registered.metadata.name!r} is no longer usable"
        ) from error
    if current_metadata is not registered.metadata:
        raise StalePlanError(
            f"Catalog definition changed for index {registered.metadata.name!r}"
        )
    if current_index is not registered.index:
        raise StalePlanError(
            f"Runtime object changed for index {registered.metadata.name!r}"
        )


@dataclass(frozen=True, slots=True)
class TableScanSpec(PhysicalPlanSpec):
    """Reusable construction data for a complete storage scan."""

    environment: QueryEnvironment
    relation: BoundRelation

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return ()

    @property
    def output_schema(self) -> Schema:
        return self.relation.metadata.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        ordering = None
        if isinstance(self.relation.storage, PagedSequentialFile):
            ordering = ColumnReference(
                self.relation.storage.key_column,
                self.relation.exposed_name,
            )
        return PlanCapabilities(ordered_by=ordering)

    @property
    def operator_name(self) -> str:
        return "TableScan"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("relation", self.relation.exposed_name),
            ("table", self.relation.metadata.name),
            ("storage", type(self.relation.storage).__name__),
            ("access", "sequential scan"),
        )

    def instantiate(self) -> ExecutionOperator:
        _validate_relation(self.environment, self.relation)
        return TableScan(
            self.relation.storage,
            relation=self.relation.exposed_name,
        )


@dataclass(frozen=True, slots=True)
class IndexScanSpec(PhysicalPlanSpec):
    """Reusable construction data for one verified index lookup."""

    environment: QueryEnvironment
    relation: BoundRelation
    registered: RegisteredIndex
    search: EqualitySearch | RangeSearch

    def __post_init__(self) -> None:
        if not isinstance(self.search, (EqualitySearch, RangeSearch)):
            raise InvalidTypeError(
                "IndexScanSpec search must be EqualitySearch or RangeSearch"
            )
        metadata = self.registered.metadata
        if metadata.table_name != self.relation.metadata.name:
            raise ValidationError("IndexScanSpec index belongs to another table")
        if isinstance(self.search, RangeSearch) and not metadata.supports_range:
            raise UnsupportedAccessError("A hash index cannot serve a range scan")

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return ()

    @property
    def output_schema(self) -> Schema:
        return self.relation.metadata.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        ordering = None
        if isinstance(self.registered.index, OrderedIndex):
            ordering = ColumnReference(
                self.registered.metadata.column_name,
                self.relation.exposed_name,
            )
        return PlanCapabilities(ordered_by=ordering)

    @property
    def operator_name(self) -> str:
        return "IndexScan"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        if isinstance(self.search, EqualitySearch):
            access = f"equality {self.search.key!r}"
        else:
            left = "[" if self.search.include_lower else "("
            right = "]" if self.search.include_upper else ")"
            access = f"range {left}{self.search.lower!r}, {self.search.upper!r}{right}"
        return (
            ("relation", self.relation.exposed_name),
            ("table", self.relation.metadata.name),
            ("storage", type(self.relation.storage).__name__),
            ("index", self.registered.metadata.name),
            ("access", access),
        )

    def instantiate(self) -> ExecutionOperator:
        _validate_relation(self.environment, self.relation)
        _validate_index(self.environment, self.registered)
        return IndexScan(
            self.registered.index,
            self.search,
            relation=self.relation.exposed_name,
        )


@dataclass(frozen=True, slots=True)
class FilterSpec(PhysicalPlanSpec):
    """Reusable full residual filter above one complete candidate source."""

    child: PhysicalPlanSpec
    predicate: BoundPredicate

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.child,)

    @property
    def output_schema(self) -> Schema:
        return self.child.output_schema

    @property
    def capabilities(self) -> PlanCapabilities:
        return self.child.capabilities

    @property
    def operator_name(self) -> str:
        return "Filter"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (("predicate", repr(self.predicate.expression)),)

    def instantiate(self) -> ExecutionOperator:
        return Filter(self.child.instantiate(), self.predicate.expression)


@dataclass(frozen=True, slots=True)
class ProjectionSpec(PhysicalPlanSpec):
    """Reusable final projection, kept after every source dependency."""

    child: PhysicalPlanSpec
    items: tuple[BoundProjectionItem, ...]
    schema: Schema
    selectors: tuple[ColumnReference, ...] | None = None

    def __post_init__(self) -> None:
        selectors = self.selectors
        if selectors is None:
            if any(item.source is None for item in self.items):
                raise UnsupportedAccessError(
                    "Aggregate projection requires resolved grouped selectors"
                )
            selectors = tuple(item.source for item in self.items)
            object.__setattr__(self, "selectors", selectors)
        if len(selectors) != len(self.items):
            raise ValidationError(
                "ProjectionSpec requires one selector per output item"
            )
        if not all(isinstance(selector, ColumnReference) for selector in selectors):
            raise InvalidTypeError(
                "ProjectionSpec selectors must be ColumnReference objects"
            )

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.child,)

    @property
    def output_schema(self) -> Schema:
        return self.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        # Projection preserves row occurrences. Ordering is deliberately not
        # promised here because an output alias changes column identity; the
        # constructed Stage 6 operator computes any surviving identity exactly.
        return PlanCapabilities()

    @property
    def operator_name(self) -> str:
        return "Projection"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (("columns", ", ".join(item.output_name for item in self.items)),)

    def instantiate(self) -> ExecutionOperator:
        child = self.child.instantiate()
        selections = self.selectors
        aliases: list[str | None] = []
        for item, selector in zip(self.items, selections):
            field = child.layout.field(selector)
            published = child.layout.published_name(field)
            aliases.append(None if item.output_name == published else item.output_name)
        operator = Projection(child, selections, aliases)
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared projection no longer has its bound schema")
        return operator


@dataclass(frozen=True, slots=True)
class ExternalSortSpec(PhysicalPlanSpec):
    """Reusable construction data for the mandatory SQL ordering route."""

    child: PhysicalPlanSpec
    keys: tuple[SortKey, ...]
    memory_budget_bytes: int | None = None
    max_fan_in: int = DEFAULT_MAX_FAN_IN

    def __post_init__(self) -> None:
        SortSpec(self.keys)

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.child,)

    @property
    def output_schema(self) -> Schema:
        return self.child.output_schema

    @property
    def capabilities(self) -> PlanCapabilities:
        ordered_by = None
        if self.keys and not self.keys[0].descending:
            ordered_by = self.keys[0].column
        return PlanCapabilities(ordered_by=ordered_by)

    @property
    def operator_name(self) -> str:
        return "ExternalSort"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        ordering = ", ".join(
            f"{key.column.qualified_name} "
            f"{'DESC' if key.descending else 'ASC'}"
            for key in self.keys
        )
        return (
            ("keys", ordering),
            ("strategy", "disk-backed k-way merge"),
        )

    def instantiate(self) -> ExecutionOperator:
        operator = ExternalSort(
            self.child.instantiate(),
            SortSpec(self.keys),
            memory_budget_bytes=self.memory_budget_bytes,
            max_fan_in=self.max_fan_in,
        )
        if operator.output_schema != self.output_schema:
            raise StalePlanError("Prepared sort output schema changed")
        return operator


@dataclass(frozen=True, slots=True)
class ExternalHashGroupSpec(PhysicalPlanSpec):
    """Reusable construction data for Stage 6 external hash grouping."""

    child: PhysicalPlanSpec
    group_keys: tuple[ColumnReference, ...]
    aggregates: tuple[Aggregate, ...]
    schema: Schema
    memory_budget_bytes: int | None = None
    partition_count: int = DEFAULT_PARTITION_COUNT
    max_level: int = MAX_PARTITION_LEVEL

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.child,)

    @property
    def output_schema(self) -> Schema:
        return self.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        return PlanCapabilities()

    @property
    def operator_name(self) -> str:
        return "ExternalHashGroup"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        keys = ", ".join(key.qualified_name for key in self.group_keys)
        return (
            ("keys", keys if keys else "(global)"),
            ("aggregates", ", ".join(item.alias for item in self.aggregates)),
            ("strategy", "external hash partitions"),
        )

    def instantiate(self) -> ExecutionOperator:
        operator = ExternalHashGroup(
            self.child.instantiate(),
            self.group_keys,
            self.aggregates,
            memory_budget_bytes=self.memory_budget_bytes,
            partition_count=self.partition_count,
            max_level=self.max_level,
        )
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared grouping output schema changed")
        return operator


@dataclass(frozen=True, slots=True)
class GraceHashJoinSpec(PhysicalPlanSpec):
    """Reusable default optimized inner-join specification."""

    left: PhysicalPlanSpec
    right: PhysicalPlanSpec
    join: JoinSpec
    residual: BoundPredicate | None
    schema: Schema
    memory_budget_bytes: int | None = None
    partition_count: int = DEFAULT_PARTITION_COUNT
    max_level: int = MAX_PARTITION_LEVEL

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.left, self.right)

    @property
    def output_schema(self) -> Schema:
        return self.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        return PlanCapabilities()

    @property
    def operator_name(self) -> str:
        return "GraceHashJoin"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self.join)),
            ("strategy", "grace hash join"),
        )

    def instantiate(self) -> ExecutionOperator:
        operator = GraceHashJoin(
            self.left.instantiate(),
            self.right.instantiate(),
            self.join,
            residual=(None if self.residual is None else self.residual.expression),
            memory_budget_bytes=self.memory_budget_bytes,
            partition_count=self.partition_count,
            max_level=self.max_level,
        )
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared join output schema changed")
        return operator


@dataclass(frozen=True, slots=True)
class NestedLoopJoinSpec(PhysicalPlanSpec):
    """Reusable independent correctness baseline for one inner join."""

    left: PhysicalPlanSpec
    right: PhysicalPlanSpec
    join: JoinSpec
    residual: BoundPredicate | None
    schema: Schema
    memory_budget_bytes: int | None = None

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.left, self.right)

    @property
    def output_schema(self) -> Schema:
        return self.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        return PlanCapabilities()

    @property
    def operator_name(self) -> str:
        return "NestedLoopJoin"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self.join)),
            ("strategy", "nested-loop baseline"),
        )

    def instantiate(self) -> ExecutionOperator:
        operator = NestedLoopJoin(
            self.left.instantiate(),
            self.right.instantiate(),
            self.join,
            residual=(None if self.residual is None else self.residual.expression),
            memory_budget_bytes=self.memory_budget_bytes,
        )
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared baseline join output schema changed")
        return operator


@dataclass(frozen=True, slots=True)
class IndexNestedLoopJoinSpec(PhysicalPlanSpec):
    """Reusable single-key inner-index join when exact preconditions hold."""

    environment: QueryEnvironment
    outer: PhysicalPlanSpec
    inner_relation: BoundRelation
    registered: RegisteredIndex
    join: JoinSpec
    residual: BoundPredicate | None
    schema: Schema

    @property
    def children(self) -> tuple[PhysicalPlanSpec, ...]:
        return (self.outer,)

    @property
    def output_schema(self) -> Schema:
        return self.schema

    @property
    def capabilities(self) -> PlanCapabilities:
        return PlanCapabilities()

    @property
    def operator_name(self) -> str:
        return "IndexNestedLoopJoin"

    @property
    def details(self) -> tuple[tuple[str, str], ...]:
        return (
            ("condition", repr(self.join)),
            ("index", self.registered.metadata.name),
            ("strategy", "index nested loop"),
        )

    def instantiate(self) -> ExecutionOperator:
        _validate_relation(self.environment, self.inner_relation)
        _validate_index(self.environment, self.registered)
        operator = IndexNestedLoopJoin(
            self.outer.instantiate(),
            self.registered.index,
            self.join,
            relation=self.inner_relation.exposed_name,
            residual=(None if self.residual is None else self.residual.expression),
        )
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared index join output schema changed")
        return operator


@dataclass(frozen=True, slots=True)
class SelectPlanSpec:
    """Complete reusable SELECT plan with no live operator/cursor state."""

    environment: QueryEnvironment
    bound: BoundSelect
    root: PhysicalPlanSpec
    indexes_enabled: bool
    options: PhysicalPlanningOptions

    @property
    def output_schema(self) -> Schema:
        return self.bound.output_schema

    def describe(self) -> PlanSpecDescriptor:
        return self.root.describe()

    def instantiate(self) -> ExecutionOperator:
        for relation in self.bound.relations:
            _validate_relation(self.environment, relation)
        operator = self.root.instantiate()
        if operator.output_schema != self.bound.output_schema:
            raise StalePlanError("Prepared SELECT output schema changed")
        return operator


def _validate_mutation_snapshot(
    environment: QueryEnvironment,
    table_name: str,
    table_metadata: TableMetadata,
    storage: Storage,
    indexes: tuple[BoundIndexMutation, ...],
) -> None:
    try:
        current_table = environment.catalog.get_table(table_name)
        current_storage = environment.storage_for(table_name)
    except (InvalidReferenceError, ValidationError, RuntimeError) as error:
        raise StalePlanError(
            f"Prepared mutation target {table_name!r} is no longer available"
        ) from error
    if current_table is not table_metadata or current_storage is not storage:
        raise StalePlanError(f"Prepared mutation target {table_name!r} changed")

    current_definitions = environment.catalog.get_indexes(table_name)
    if tuple(item.metadata for item in indexes) != current_definitions:
        raise StalePlanError(f"Index definitions changed for table {table_name!r}")
    for item in indexes:
        _validate_index(
            environment,
            RegisteredIndex(item.metadata, item.index),
        )


@dataclass(frozen=True, slots=True)
class InsertPlanSpec:
    """Complete no-write INSERT plan consumed by mutation maintenance."""

    environment: QueryEnvironment
    bound: BoundInsert

    def validate(self) -> None:
        _validate_mutation_snapshot(
            self.environment,
            self.bound.table.name,
            self.bound.table,
            self.bound.storage,
            self.bound.indexes,
        )

    def describe(self) -> PlanSpecDescriptor:
        index_names = ", ".join(
            item.metadata.name for item in self.bound.indexes
        ) or "(none)"
        return PlanSpecDescriptor(
            "Insert",
            (),
            (
                ("table", self.bound.table.name),
                ("storage", type(self.bound.storage).__name__),
                ("indexes", index_names),
            ),
        )


@dataclass(frozen=True, slots=True)
class CreatePlanSpec:
    """Side-effect-free CREATE definition owned by an injected database service."""

    environment: QueryEnvironment
    bound: BoundCreate
    service: DdlService

    def validate(self) -> None:
        table = self.bound.table
        if self.environment.catalog.has_table(table.name):
            raise StalePlanError(f"Table {table.name!r} now exists")
        if (
            self.bound.primary_index_name is not None
            and self.environment.catalog.has_index(self.bound.primary_index_name)
        ):
            raise StalePlanError(
                f"Index {self.bound.primary_index_name!r} now exists"
            )
        self.service.validate_create(table)

    def describe(self) -> PlanSpecDescriptor:
        columns = ", ".join(
            f"{column.name}:{column.data_type.value}"
            for column in self.bound.table.schema
        )
        return PlanSpecDescriptor(
            "CreateTable",
            (),
            (
                ("table", self.bound.table.name),
                ("organization", "HEAP"),
                ("columns", columns),
                ("primary_key", self.bound.table.primary_key or "(none)"),
                (
                    "primary_index",
                    self.bound.primary_index_name or "(none)",
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class DeletePlanSpec:
    """Complete DELETE target plus a fresh RID-producing candidate factory."""

    environment: QueryEnvironment
    bound: BoundDelete
    candidates: PhysicalPlanSpec

    def validate(self) -> None:
        _validate_mutation_snapshot(
            self.environment,
            self.bound.table.name,
            self.bound.table,
            self.bound.storage,
            self.bound.indexes,
        )

    def instantiate_candidates(self) -> ExecutionOperator:
        self.validate()
        return self.candidates.instantiate()

    def describe(self) -> PlanSpecDescriptor:
        child = self.candidates.describe()
        index_names = ", ".join(
            item.metadata.name for item in self.bound.indexes
        ) or "(none)"
        return PlanSpecDescriptor(
            "Delete",
            (),
            (
                ("table", self.bound.table.name),
                ("storage", type(self.bound.storage).__name__),
                ("indexes", index_names),
                ("requires_stable_rid", str(self.bound.requires_stable_rid)),
            ),
            children=(child,),
        )


@dataclass(frozen=True, slots=True)
class _AccessCandidate:
    rank: int
    index_name: str
    registered: RegisteredIndex
    search: EqualitySearch | RangeSearch


def _usable_indexes(
    environment: QueryEnvironment,
    table_name: str,
) -> tuple[RegisteredIndex, ...]:
    """Return currently valid read indexes; absent/incomplete ones fall back."""

    available: list[RegisteredIndex] = []
    for metadata in environment.catalog.get_indexes(table_name):
        try:
            index = environment.index_for(metadata.name)
        except (InvalidReferenceError, ValidationError, RuntimeError):
            continue
        available.append(RegisteredIndex(metadata, index))
    return tuple(available)


def _matching_conditions(
    relation: BoundRelation,
    metadata: IndexMetadata,
    where: BoundPredicate,
) -> tuple[BoundIndexCondition, ...]:
    return tuple(
        condition
        for condition in where.index_conditions
        if condition.column.relation == relation.exposed_name
        and condition.column.name == metadata.column_name
        and condition.data_type
        is relation.metadata.schema.column(metadata.column_name).data_type
    )


def _validated_key(condition: BoundIndexCondition) -> RecordValue:
    return BPlusKeyCodec.validate(condition.data_type, condition.value)


def _stronger_lower(
    current: tuple[RecordValue, bool] | None,
    value: RecordValue,
    inclusive: bool,
    condition: BoundIndexCondition,
) -> tuple[RecordValue, bool]:
    if current is None:
        return value, inclusive
    ordering = compare_values(condition.data_type, value, current[0])
    if ordering > 0:
        return value, inclusive
    if ordering == 0:
        return value, current[1] and inclusive
    return current


def _stronger_upper(
    current: tuple[RecordValue, bool] | None,
    value: RecordValue,
    inclusive: bool,
    condition: BoundIndexCondition,
) -> tuple[RecordValue, bool]:
    if current is None:
        return value, inclusive
    ordering = compare_values(condition.data_type, value, current[0])
    if ordering < 0:
        return value, inclusive
    if ordering == 0:
        return value, current[1] and inclusive
    return current


def _candidate_for_index(
    relation: BoundRelation,
    registered: RegisteredIndex,
    where: BoundPredicate,
) -> _AccessCandidate | None:
    metadata = registered.metadata
    conditions = _matching_conditions(relation, metadata, where)
    if not conditions:
        return None

    equalities = [
        condition
        for condition in conditions
        if condition.operator is ComparisonOperator.EQUAL
    ]
    if equalities and metadata.supports_equality:
        try:
            key = _validated_key(equalities[0])
        except (InvalidTypeError, ValidationError):
            return None
        return _AccessCandidate(
            0,
            metadata.name,
            registered,
            EqualitySearch(key),
        )

    if not metadata.supports_range or not isinstance(registered.index, OrderedIndex):
        return None

    lower: tuple[RecordValue, bool] | None = None
    upper: tuple[RecordValue, bool] | None = None
    try:
        for condition in conditions:
            value = _validated_key(condition)
            if condition.operator is ComparisonOperator.GREATER:
                lower = _stronger_lower(lower, value, False, condition)
            elif condition.operator is ComparisonOperator.GREATER_OR_EQUAL:
                lower = _stronger_lower(lower, value, True, condition)
            elif condition.operator is ComparisonOperator.LESS:
                upper = _stronger_upper(upper, value, False, condition)
            elif condition.operator is ComparisonOperator.LESS_OR_EQUAL:
                upper = _stronger_upper(upper, value, True, condition)
    except (InvalidTypeError, ValidationError):
        return None
    if lower is None and upper is None:
        return None

    if lower is not None and upper is not None:
        ordering = compare_values(conditions[0].data_type, lower[0], upper[0])
        if ordering > 0 or (ordering == 0 and not (lower[1] and upper[1])):
            return None

    return _AccessCandidate(
        1,
        metadata.name,
        registered,
        RangeSearch(
            None if lower is None else lower[0],
            None if upper is None else upper[0],
            True if lower is None else lower[1],
            True if upper is None else upper[1],
        ),
    )


def _source_spec(
    environment: QueryEnvironment,
    relation: BoundRelation,
    where: BoundPredicate | None,
    *,
    use_indexes: bool,
) -> PhysicalPlanSpec:
    if not use_indexes or where is None:
        return TableScanSpec(environment, relation)

    candidates = []
    for registered in _usable_indexes(environment, relation.metadata.name):
        candidate = _candidate_for_index(relation, registered, where)
        if candidate is not None:
            candidates.append(candidate)
    if not candidates:
        return TableScanSpec(environment, relation)

    # Exact lookup is the first stable class, followed by a bounded range;
    # names break ties. This is a deterministic rule, not a cost estimate.
    chosen = min(candidates, key=lambda candidate: (candidate.rank, candidate.index_name))
    return IndexScanSpec(
        environment,
        relation,
        chosen.registered,
        chosen.search,
    )


def _clone_aggregate(aggregate: Aggregate, alias: str) -> Aggregate:
    """Copy one Stage 6 aggregate with an internal collision-free alias."""

    if type(aggregate) is Count:
        return Count(alias)
    if type(aggregate) is CountColumn:
        return CountColumn(aggregate.column, alias)
    if type(aggregate) is Sum:
        return Sum(aggregate.column, alias)
    if type(aggregate) is Avg:
        return Avg(aggregate.column, alias)
    if type(aggregate) is Max:
        return Max(aggregate.column, alias)
    if type(aggregate) is Min:
        return Min(aggregate.column, alias)
    raise UnsupportedAccessError(
        f"Unsupported aggregate specification: {type(aggregate).__name__}"
    )


@dataclass(frozen=True, slots=True)
class _PhysicalGroupBinding:
    aggregates: tuple[Aggregate, ...]
    aggregate_references: tuple[ColumnReference, ...]
    schema: Schema


def _physical_group_binding(bound: BoundSelect) -> _PhysicalGroupBinding:
    """Assign intermediate aggregate names that cannot collide with keys."""

    occupied = {
        bound.source_layout.published_name(bound.source_layout.field(key))
        for key in bound.group_keys
    }
    physical: list[Aggregate] = []
    references: list[ColumnReference] = []
    for position, aggregate in enumerate(bound.aggregates):
        alias = aggregate.alias
        if alias in occupied:
            suffix = 0
            alias = f"__sql_aggregate_{position}"
            while alias in occupied:
                suffix += 1
                alias = f"__sql_aggregate_{position}_{suffix}"
        occupied.add(alias)
        physical_aggregate = (
            aggregate
            if alias == aggregate.alias
            else _clone_aggregate(aggregate, alias)
        )
        physical.append(physical_aggregate)
        references.append(ColumnReference(alias))
    grouped_layout = build_grouped_layout(
        bound.source_layout,
        bound.group_keys,
        physical,
    )
    return _PhysicalGroupBinding(
        tuple(physical),
        tuple(references),
        grouped_layout.schema,
    )


def _projection_selectors(
    bound: BoundSelect,
    aggregate_references: tuple[ColumnReference, ...] = (),
) -> tuple[ColumnReference, ...]:
    selectors: list[ColumnReference] = []
    for item in bound.projection:
        if not bound.grouped:
            if item.source is None:
                raise ValidationError("Ungrouped projection lost its source")
            selectors.append(item.source)
            continue
        if item.group_key_index is not None:
            selectors.append(bound.group_keys[item.group_key_index])
            continue
        if item.aggregate_index is not None:
            selectors.append(aggregate_references[item.aggregate_index])
            continue
        raise ValidationError("Grouped projection has no physical source")
    return tuple(selectors)


def _sort_keys(
    bound: BoundSelect,
    projection_selectors: tuple[ColumnReference, ...],
) -> tuple[SortKey, ...]:
    keys: list[SortKey] = []
    seen: set[ColumnReference] = set()
    for item in bound.order_by:
        selector = (
            projection_selectors[item.output_position]
            if item.output_position is not None
            else item.source
        )
        if selector is None:
            raise ValidationError("ORDER BY has no physical input selector")
        # Repeating a key cannot refine the order; the first direction wins.
        if selector in seen:
            continue
        seen.add(selector)
        keys.append(SortKey(selector, item.descending))
    return tuple(keys)


def _stage6_join_spec(bound: BoundSelect) -> JoinSpec:
    return JoinSpec(
        tuple(JoinKey(key.left, key.right) for key in bound.join_keys)
    )


def _eligible_inner_join_index(
    environment: QueryEnvironment,
    bound: BoundSelect,
) -> RegisteredIndex | None:
    if len(bound.join_keys) != 1:
        return None
    inner = bound.relations[1]
    key = bound.join_keys[0].right
    eligible = [
        registered
        for registered in _usable_indexes(environment, inner.metadata.name)
        if registered.metadata.supports_equality
        and registered.metadata.column_name == key.name
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda registered: registered.metadata.name)


def _joined_source_spec(
    environment: QueryEnvironment,
    bound: BoundSelect,
    *,
    use_indexes: bool,
    options: PhysicalPlanningOptions,
) -> PhysicalPlanSpec:
    left_relation, right_relation = bound.relations
    left = _source_spec(
        environment,
        left_relation,
        bound.where,
        use_indexes=use_indexes,
    )
    right = _source_spec(
        environment,
        right_relation,
        bound.where,
        use_indexes=use_indexes,
    )
    join = _stage6_join_spec(bound)

    if options.join_strategy is JoinPlanningStrategy.NESTED_LOOP:
        return NestedLoopJoinSpec(
            left,
            right,
            join,
            bound.join_predicate,
            bound.source_layout.schema,
            options.join_memory_budget_bytes,
        )

    registered = (
        _eligible_inner_join_index(environment, bound)
        if use_indexes and options.join_strategy is JoinPlanningStrategy.AUTO
        else None
    )
    if registered is not None:
        return IndexNestedLoopJoinSpec(
            environment,
            left,
            right_relation,
            registered,
            join,
            bound.join_predicate,
            bound.source_layout.schema,
        )

    return GraceHashJoinSpec(
        left,
        right,
        join,
        bound.join_predicate,
        bound.source_layout.schema,
        options.join_memory_budget_bytes,
        options.join_partition_count,
        options.join_max_level,
    )


def _relational_source_spec(
    environment: QueryEnvironment,
    bound: BoundSelect,
    *,
    use_indexes: bool,
    options: PhysicalPlanningOptions,
) -> PhysicalPlanSpec:
    if len(bound.relations) == 1:
        root = _source_spec(
            environment,
            bound.relations[0],
            bound.where,
            use_indexes=use_indexes,
        )
    else:
        root = _joined_source_spec(
            environment,
            bound,
            use_indexes=use_indexes,
            options=options,
        )
    if bound.where is not None:
        root = FilterSpec(root, bound.where)
    return root


def prepare_select_plan(
    environment: QueryEnvironment,
    statement: SelectStatement | BoundSelect,
    *,
    use_indexes: bool = True,
    options: PhysicalPlanningOptions | None = None,
) -> SelectPlanSpec:
    """Bind and prepare one reusable SELECT without opening cursors."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("prepare_select_plan requires a QueryEnvironment")
    if type(use_indexes) is not bool:
        raise InvalidTypeError("use_indexes must be a bool")
    if options is None:
        options = PhysicalPlanningOptions()
    elif not isinstance(options, PhysicalPlanningOptions):
        raise InvalidTypeError("options must be PhysicalPlanningOptions or None")
    if isinstance(statement, SelectStatement):
        bound = bind_select(environment, statement)
    elif isinstance(statement, BoundSelect):
        bound = statement
    else:
        raise InvalidTypeError(
            "prepare_select_plan requires SelectStatement or BoundSelect"
        )

    for relation in bound.relations:
        _validate_relation(environment, relation)
    root = _relational_source_spec(
        environment,
        bound,
        use_indexes=use_indexes,
        options=options,
    )

    aggregate_references: tuple[ColumnReference, ...] = ()
    if bound.grouped:
        group = _physical_group_binding(bound)
        aggregate_references = group.aggregate_references
        root = ExternalHashGroupSpec(
            root,
            bound.group_keys,
            group.aggregates,
            group.schema,
            options.group_memory_budget_bytes,
            options.group_partition_count,
            options.group_max_level,
        )

    selectors = _projection_selectors(bound, aggregate_references)
    if bound.order_by:
        root = ExternalSortSpec(
            root,
            _sort_keys(bound, selectors),
            options.sort_memory_budget_bytes,
            options.sort_max_fan_in,
        )
    root = ProjectionSpec(
        root,
        bound.projection,
        bound.output_schema,
        selectors,
    )
    return SelectPlanSpec(environment, bound, root, use_indexes, options)


def build_select_plan(
    environment: QueryEnvironment,
    statement: SelectStatement | BoundSelect,
    *,
    use_indexes: bool = True,
    options: PhysicalPlanningOptions | None = None,
) -> ExecutionOperator:
    """Return one fresh closed Stage 6 tree for a SELECT."""

    return prepare_select_plan(
        environment,
        statement,
        use_indexes=use_indexes,
        options=options,
    ).instantiate()


def prepare_plan(
    environment: QueryEnvironment,
    statement: Statement | BoundSelect | BoundInsert | BoundDelete | BoundCreate,
    *,
    use_indexes: bool = True,
    options: PhysicalPlanningOptions | None = None,
    ddl_service: DdlService | None = None,
) -> SelectPlanSpec | InsertPlanSpec | DeletePlanSpec | CreatePlanSpec:
    """Prepare one supported statement without performing its effects."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("prepare_plan requires a QueryEnvironment")
    if type(use_indexes) is not bool:
        raise InvalidTypeError("use_indexes must be a bool")
    if options is not None and not isinstance(options, PhysicalPlanningOptions):
        raise InvalidTypeError("options must be PhysicalPlanningOptions or None")
    if ddl_service is not None and not isinstance(ddl_service, DdlService):
        raise InvalidTypeError("ddl_service must implement DdlService or be None")
    if isinstance(
        statement,
        (SelectStatement, InsertStatement, DeleteStatement, CreateTableStatement),
    ):
        bound = bind_statement(environment, statement)
    elif isinstance(statement, (BoundSelect, BoundInsert, BoundDelete, BoundCreate)):
        bound = statement
    else:
        raise InvalidTypeError("prepare_plan requires a supported statement")

    if isinstance(bound, BoundSelect):
        return prepare_select_plan(
            environment,
            bound,
            use_indexes=use_indexes,
            options=options,
        )
    if isinstance(bound, BoundInsert):
        plan = InsertPlanSpec(environment, bound)
        plan.validate()
        return plan
    if isinstance(bound, BoundCreate):
        if ddl_service is None:
            raise UnsupportedAccessError(
                "CREATE TABLE requires a manifest-backed DDL service"
            )
        plan = CreatePlanSpec(environment, bound, ddl_service)
        plan.validate()
        return plan

    relation = BoundRelation(
        0,
        bound.table,
        bound.table.name,
        bound.storage,
        bound.layout,
    )
    candidates: PhysicalPlanSpec = TableScanSpec(environment, relation)
    if bound.where is not None:
        candidates = FilterSpec(candidates, bound.where)
    plan = DeletePlanSpec(environment, bound, candidates)
    plan.validate()
    return plan


__all__ = [
    "DeletePlanSpec",
    "CreatePlanSpec",
    "ExternalHashGroupSpec",
    "ExternalSortSpec",
    "FilterSpec",
    "GraceHashJoinSpec",
    "IndexScanSpec",
    "IndexNestedLoopJoinSpec",
    "InsertPlanSpec",
    "JoinPlanningStrategy",
    "NestedLoopJoinSpec",
    "PhysicalPlanSpec",
    "PhysicalPlanningOptions",
    "PlanCapabilities",
    "PlanSpecDescriptor",
    "ProjectionSpec",
    "SelectPlanSpec",
    "StalePlanError",
    "TableScanSpec",
    "build_select_plan",
    "prepare_plan",
    "prepare_select_plan",
]
