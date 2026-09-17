"""Conservative physical planning over the reviewed Stage 6 operators.

The semantic binder owns SQL meaning. This module chooses a physical access
path and stores immutable construction data; it never opens an operator or
touches a table/index cursor. A prepared SELECT therefore creates a fresh
mutable Stage 6 operator tree for every execution.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from engine.catalog import IndexMetadata, Schema, TableMetadata
from engine.errors import (
    InvalidReferenceError,
    InvalidTypeError,
    UnsupportedAccessError,
    ValidationError,
)
from engine.indexes import BPlusKeyCodec, OrderedIndex
from engine.operators import (
    ColumnReference,
    ComparisonOperator,
    EqualitySearch,
    ExecutionOperator,
    Filter,
    IndexScan,
    Projection,
    RangeSearch,
    TableScan,
    compare_values,
)
from engine.storage import PagedSequentialFile, Storage
from engine.storage.record import RecordValue

from .ast import DeleteStatement, InsertStatement, SelectStatement, Statement
from .binder import (
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
from .environment import QueryEnvironment, RegisteredIndex


class StalePlanError(ValidationError):
    """A prepared plan no longer matches its Catalog/runtime identities."""


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

    def __post_init__(self) -> None:
        if any(item.source is None for item in self.items):
            raise UnsupportedAccessError(
                "Aggregate projection requires the grouped-query planner"
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
        selections = tuple(item.source for item in self.items)
        aliases: list[str | None] = []
        for item in self.items:
            field = child.layout.field(item.source)
            published = child.layout.published_name(field)
            aliases.append(None if item.output_name == published else item.output_name)
        operator = Projection(child, selections, aliases)
        if operator.output_schema != self.schema:
            raise StalePlanError("Prepared projection no longer has its bound schema")
        return operator


@dataclass(frozen=True, slots=True)
class SelectPlanSpec:
    """Complete reusable SELECT plan with no live operator/cursor state."""

    environment: QueryEnvironment
    bound: BoundSelect
    root: PhysicalPlanSpec
    indexes_enabled: bool

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
    """Complete no-write INSERT plan consumed by the future write executor."""

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
        return PlanSpecDescriptor(
            "Insert",
            (),
            (
                ("table", self.bound.table.name),
                ("indexes", str(len(self.bound.indexes))),
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
        return PlanSpecDescriptor(
            "Delete",
            (),
            (
                ("table", self.bound.table.name),
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


def _require_basic_select(bound: BoundSelect) -> None:
    if len(bound.relations) != 1:
        raise UnsupportedAccessError("JOIN physical planning is not implemented yet")
    if bound.grouped:
        raise UnsupportedAccessError(
            "Grouped and aggregate physical planning is not implemented yet"
        )
    if bound.order_by:
        raise UnsupportedAccessError("ORDER BY physical planning is not implemented yet")


def prepare_select_plan(
    environment: QueryEnvironment,
    statement: SelectStatement | BoundSelect,
    *,
    use_indexes: bool = True,
) -> SelectPlanSpec:
    """Bind and prepare one reusable basic SELECT without opening cursors."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("prepare_select_plan requires a QueryEnvironment")
    if type(use_indexes) is not bool:
        raise InvalidTypeError("use_indexes must be a bool")
    if isinstance(statement, SelectStatement):
        bound = bind_select(environment, statement)
    elif isinstance(statement, BoundSelect):
        bound = statement
    else:
        raise InvalidTypeError(
            "prepare_select_plan requires SelectStatement or BoundSelect"
        )

    _require_basic_select(bound)
    for relation in bound.relations:
        _validate_relation(environment, relation)
    relation = bound.relations[0]
    root = _source_spec(
        environment,
        relation,
        bound.where,
        use_indexes=use_indexes,
    )
    if bound.where is not None:
        # Keep the complete predicate even when the leaf index enforces one or
        # more conjuncts. Every index is a candidate source, never a rewrite of
        # SQL Boolean meaning.
        root = FilterSpec(root, bound.where)
    root = ProjectionSpec(root, bound.projection, bound.output_schema)
    return SelectPlanSpec(environment, bound, root, use_indexes)


def build_select_plan(
    environment: QueryEnvironment,
    statement: SelectStatement | BoundSelect,
    *,
    use_indexes: bool = True,
) -> ExecutionOperator:
    """Return one fresh closed Stage 6 tree for a basic SELECT."""

    return prepare_select_plan(
        environment,
        statement,
        use_indexes=use_indexes,
    ).instantiate()


def prepare_plan(
    environment: QueryEnvironment,
    statement: Statement | BoundSelect | BoundInsert | BoundDelete,
    *,
    use_indexes: bool = True,
) -> SelectPlanSpec | InsertPlanSpec | DeletePlanSpec:
    """Prepare a SELECT/INSERT/DELETE without retaining raw SQL semantics."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("prepare_plan requires a QueryEnvironment")
    if type(use_indexes) is not bool:
        raise InvalidTypeError("use_indexes must be a bool")
    if isinstance(statement, (SelectStatement, InsertStatement, DeleteStatement)):
        bound = bind_statement(environment, statement)
    elif isinstance(statement, (BoundSelect, BoundInsert, BoundDelete)):
        bound = statement
    else:
        raise InvalidTypeError("prepare_plan requires a supported statement")

    if isinstance(bound, BoundSelect):
        return prepare_select_plan(environment, bound, use_indexes=use_indexes)
    if isinstance(bound, BoundInsert):
        plan = InsertPlanSpec(environment, bound)
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
    "FilterSpec",
    "IndexScanSpec",
    "InsertPlanSpec",
    "PhysicalPlanSpec",
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
