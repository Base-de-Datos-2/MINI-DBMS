"""Read-only semantic binding for the Stage 7 SQL subset.

Binding resolves every name and type before physical planning.  It borrows
Catalog/runtime objects from :mod:`engine.query.environment`, reuses the
Stage 6 expression and aggregate contracts, and never mutates table rows or
index associations. INSERT validation may perform read-only uniqueness probes;
execution must repeat those checks immediately before its first write.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass

from engine.catalog import (
    Column,
    ColumnConstraint,
    DataType,
    IndexMetadata,
    Schema,
    TableMetadata,
)
from engine.errors import (
    InvalidTypeError,
    UnknownColumnError,
    UnknownTableError,
    ValidationError,
)
from engine.indexes import Index
from engine.indexes.bplus_codec import BPlusKeyCodec
from engine.operators import (
    Aggregate,
    And,
    Avg,
    BoundExpression,
    ColumnReference,
    ColumnValue,
    Compare,
    ComparisonOperator,
    Count,
    CountColumn,
    Expression,
    Literal,
    Max,
    Min,
    Not,
    Or,
    RowLayout,
    Sum,
)
from engine.maintenance.validation import validate_record
from engine.storage import PagedSequentialFile, Record, Storage, ValueCodec
from engine.storage.record import RecordValue

from .ast import (
    AggregateCall,
    BoolAnd,
    BoolNot,
    BoolOr,
    BooleanLiteral,
    ColumnRef,
    Comparison,
    CreateTableStatement,
    DeleteStatement,
    FloatLiteral,
    InsertStatement,
    IntegerLiteral,
    SelectItem,
    SelectStatement,
    SqlExpr,
    Star,
    Statement,
    StringLiteral,
    SyntaxNode,
    TableRef,
)
from .environment import QueryEnvironment
from .errors import (
    SqlBindingError,
    SqlUnknownColumnError,
    SqlUnknownTableError,
)


@dataclass(frozen=True, slots=True)
class BoundRelation:
    """One distinct relation occurrence in a statement scope."""

    instance_id: int
    metadata: TableMetadata
    exposed_name: str
    storage: Storage
    layout: RowLayout


@dataclass(frozen=True, slots=True)
class BoundIndexCondition:
    """A safe exact-type column/literal condition usable for index selection."""

    column: ColumnReference
    operator: ComparisonOperator
    value: RecordValue
    data_type: DataType


@dataclass(frozen=True, slots=True)
class BoundPredicate:
    """A Stage 6 expression validated once against its source layout."""

    expression: Expression
    bound: BoundExpression
    references: tuple[ColumnReference, ...]
    index_conditions: tuple[BoundIndexCondition, ...]


@dataclass(frozen=True, slots=True)
class BoundJoinKey:
    """One equal-typed equality key crossing the two join inputs."""

    left: ColumnReference
    right: ColumnReference
    data_type: DataType


@dataclass(frozen=True, slots=True)
class BoundProjectionItem:
    """One output column after star expansion and aggregate resolution."""

    output_name: str
    data_type: DataType
    source: ColumnReference | None = None
    source_position: int | None = None
    group_key_index: int | None = None
    aggregate_index: int | None = None


@dataclass(frozen=True, slots=True)
class BoundOrderItem:
    """One validated sort dependency.

    ``output_position`` identifies an approved SELECT alias/output.  A source
    reference is retained when the sort must happen before final projection;
    ``hidden`` tells the planner that the dependency is not part of SELECT.
    NULL ordering is absent because Stage 7's row model has no NULL value.
    """

    data_type: DataType
    descending: bool
    output_position: int | None
    source: ColumnReference | None
    hidden: bool


@dataclass(frozen=True, slots=True)
class BoundSelect:
    """Complete semantic SELECT result, with no live operator instances."""

    relations: tuple[BoundRelation, ...]
    source_layout: RowLayout
    join_predicate: BoundPredicate | None
    join_keys: tuple[BoundJoinKey, ...]
    where: BoundPredicate | None
    group_keys: tuple[ColumnReference, ...]
    aggregates: tuple[Aggregate, ...]
    projection: tuple[BoundProjectionItem, ...]
    order_by: tuple[BoundOrderItem, ...]
    output_schema: Schema

    @property
    def grouped(self) -> bool:
        """Return whether a Stage 6 grouping operator is required."""

        return bool(self.group_keys or self.aggregates)


@dataclass(frozen=True, slots=True)
class BoundIndexMutation:
    """One index association the maintenance operation must update."""

    metadata: IndexMetadata
    index: Index
    key: RecordValue | None
    requires_unique_check: bool


@dataclass(frozen=True, slots=True)
class BoundInsert:
    """A fully validated insert row; constructing it performs no write."""

    table: TableMetadata
    storage: Storage
    record: Record
    indexes: tuple[BoundIndexMutation, ...]
    storage_may_move_rids: bool
    storage_key: RecordValue | None
    requires_storage_unique_check: bool


@dataclass(frozen=True, slots=True)
class BoundCreate:
    """A validated logical table definition with no created physical objects."""

    table: TableMetadata
    primary_index_name: str | None


@dataclass(frozen=True, slots=True)
class BoundDelete:
    """A validated deletion target that still requires scan-produced RIDs."""

    table: TableMetadata
    storage: Storage
    layout: RowLayout
    where: BoundPredicate | None
    indexes: tuple[BoundIndexMutation, ...]
    requires_stable_rid: bool
    storage_may_move_rids: bool


_LITERAL_NODES = (IntegerLiteral, FloatLiteral, StringLiteral, BooleanLiteral)
_REVERSED_OPERATORS = {
    ComparisonOperator.EQUAL: ComparisonOperator.EQUAL,
    ComparisonOperator.NOT_EQUAL: ComparisonOperator.NOT_EQUAL,
    ComparisonOperator.LESS: ComparisonOperator.GREATER,
    ComparisonOperator.LESS_OR_EQUAL: ComparisonOperator.GREATER_OR_EQUAL,
    ComparisonOperator.GREATER: ComparisonOperator.LESS,
    ComparisonOperator.GREATER_OR_EQUAL: ComparisonOperator.LESS_OR_EQUAL,
}


def _binding_error(node: SyntaxNode, message: str) -> SqlBindingError:
    if node.span is None:
        return SqlBindingError(message, position=1)
    return SqlBindingError(message, span=node.span)


def _domain_message(error: Exception) -> str:
    """Avoid KeyError's extra repr quotes in user-facing SQL diagnostics."""

    return str(error.args[0]) if error.args else str(error)


def _literal_value(node: SqlExpr) -> RecordValue:
    if isinstance(node, _LITERAL_NODES):
        return node.value
    raise _binding_error(node, "Expected a scalar literal")


def _canonical_reference(layout: RowLayout, node: ColumnRef) -> ColumnReference:
    try:
        field = layout.field(ColumnReference(node.name, node.relation))
    except UnknownColumnError as error:
        if node.span is None:
            raise SqlUnknownColumnError(_domain_message(error), position=1) from error
        raise SqlUnknownColumnError(_domain_message(error), span=node.span) from error
    except ValidationError as error:
        raise _binding_error(node, str(error)) from error
    return field.reference


def _deduplicate_references(
    references: tuple[ColumnReference, ...],
) -> tuple[ColumnReference, ...]:
    ordered: list[ColumnReference] = []
    for reference in references:
        if reference not in ordered:
            ordered.append(reference)
    return tuple(ordered)


def _flatten_boolean(node: SqlExpr, node_type: type) -> tuple[SqlExpr, ...]:
    """Flatten long left-deep AND/OR trees without consuming recursion depth."""

    pending = [node]
    terms: list[SqlExpr] = []
    while pending:
        current = pending.pop()
        if isinstance(current, node_type):
            pending.append(current.right)
            pending.append(current.left)
        else:
            terms.append(current)
    return tuple(terms)


def _translate_expression(
    node: SqlExpr,
    layout: RowLayout,
) -> tuple[Expression, tuple[ColumnReference, ...]]:
    """Translate AST structure into Stage 6 expressions with canonical names."""

    if isinstance(node, _LITERAL_NODES):
        value = _literal_value(node)
        try:
            literal = Literal(value)
            ValueCodec.encode(literal.data_type, value)
        except (InvalidTypeError, ValidationError) as error:
            raise _binding_error(node, str(error)) from error
        return literal, ()

    if isinstance(node, ColumnRef):
        reference = _canonical_reference(layout, node)
        return ColumnValue(reference), (reference,)

    if isinstance(node, Comparison):
        left, left_references = _translate_expression(node.left, layout)
        right, right_references = _translate_expression(node.right, layout)
        try:
            expression = Compare(
                left,
                ComparisonOperator(node.operator),
                right,
            )
            expression.bind(layout)
        except (InvalidTypeError, ValidationError, ValueError) as error:
            raise _binding_error(node, str(error)) from error
        return expression, _deduplicate_references(
            left_references + right_references
        )

    if isinstance(node, (BoolAnd, BoolOr)):
        node_type = BoolAnd if isinstance(node, BoolAnd) else BoolOr
        expressions = []
        references: tuple[ColumnReference, ...] = ()
        for term in _flatten_boolean(node, node_type):
            expression, term_references = _translate_expression(term, layout)
            expressions.append(expression)
            references += term_references
        try:
            combined = And(*expressions) if node_type is BoolAnd else Or(*expressions)
            combined.bind(layout)
        except (InvalidTypeError, ValidationError) as error:
            raise _binding_error(node, str(error)) from error
        return combined, _deduplicate_references(references)

    if isinstance(node, BoolNot):
        term, references = _translate_expression(node.term, layout)
        try:
            expression = Not(term)
            expression.bind(layout)
        except (InvalidTypeError, ValidationError) as error:
            raise _binding_error(node, str(error)) from error
        return expression, references

    if isinstance(node, AggregateCall):
        raise _binding_error(node, "Aggregates are not allowed in predicates")
    if isinstance(node, Star):
        raise _binding_error(node, "'*' is not a scalar predicate expression")
    raise _binding_error(node, f"Unsupported predicate node: {type(node).__name__}")


def _safe_index_conditions(
    node: SqlExpr,
    layout: RowLayout,
) -> tuple[BoundIndexCondition, ...]:
    """Extract only top-level conjunctive, exact-type column/literal terms."""

    terms = _flatten_boolean(node, BoolAnd) if isinstance(node, BoolAnd) else (node,)
    conditions: list[BoundIndexCondition] = []
    for term in terms:
        if not isinstance(term, Comparison):
            continue
        operator = ComparisonOperator(term.operator)
        column_node: ColumnRef | None = None
        literal_node: SqlExpr | None = None
        if isinstance(term.left, ColumnRef) and isinstance(term.right, _LITERAL_NODES):
            column_node, literal_node = term.left, term.right
        elif isinstance(term.right, ColumnRef) and isinstance(term.left, _LITERAL_NODES):
            column_node, literal_node = term.right, term.left
            operator = _REVERSED_OPERATORS[operator]
        if column_node is None or literal_node is None:
            continue
        if operator is ComparisonOperator.NOT_EQUAL:
            # One <> comparison is not one contiguous B+ range and hashing
            # cannot enforce it. The complete residual still executes it.
            continue
        field = layout.field(
            ColumnReference(column_node.name, column_node.relation)
        )
        value = _literal_value(literal_node)
        # The full predicate has already established exact type compatibility.
        # Canonicalize signed zero exactly as the Extendible Hash codec does.
        if field.data_type is DataType.FLOAT and value == 0.0:
            value = 0.0
        conditions.append(
            BoundIndexCondition(field.reference, operator, value, field.data_type)
        )
    return tuple(conditions)


def _bind_predicate(node: SqlExpr, layout: RowLayout) -> BoundPredicate:
    expression, references = _translate_expression(node, layout)
    try:
        bound = expression.bind(layout)
    except (InvalidTypeError, ValidationError) as error:
        raise _binding_error(node, str(error)) from error
    if bound.data_type is not DataType.BOOLEAN:
        raise _binding_error(node, "A predicate must produce BOOLEAN")
    return BoundPredicate(
        expression,
        bound,
        references,
        _safe_index_conditions(node, layout),
    )


def _bind_relation(
    environment: QueryEnvironment,
    table: TableRef,
    instance_id: int,
) -> BoundRelation:
    try:
        metadata = environment.catalog.get_table(table.name)
    except UnknownTableError as error:
        # Preserve the domain error type while adding the SQL source location.
        if table.span is None:
            raise SqlUnknownTableError(_domain_message(error), position=1) from error
        raise SqlUnknownTableError(_domain_message(error), span=table.span) from error
    storage = environment.storage_for(table.name)
    exposed_name = table.alias if table.alias is not None else table.name
    return BoundRelation(
        instance_id,
        metadata,
        exposed_name,
        storage,
        RowLayout(metadata.schema, relation=exposed_name),
    )


def _join_keys(
    node: SqlExpr,
    layout: RowLayout,
    left_relation: str,
    right_relation: str,
) -> tuple[BoundJoinKey, ...]:
    terms = _flatten_boolean(node, BoolAnd) if isinstance(node, BoolAnd) else (node,)
    keys: list[BoundJoinKey] = []
    for term in terms:
        if (
            not isinstance(term, Comparison)
            or term.operator != "="
            or not isinstance(term.left, ColumnRef)
            or not isinstance(term.right, ColumnRef)
        ):
            continue
        left_field = layout.field(
            ColumnReference(term.left.name, term.left.relation)
        )
        right_field = layout.field(
            ColumnReference(term.right.name, term.right.relation)
        )
        relation_pair = {left_field.relation, right_field.relation}
        if relation_pair != {left_relation, right_relation}:
            continue
        if left_field.data_type is not right_field.data_type:
            raise _binding_error(
                term,
                "Join equality keys must have the same declared type",
            )
        if left_field.relation == left_relation:
            key = BoundJoinKey(
                left_field.reference,
                right_field.reference,
                left_field.data_type,
            )
        else:
            key = BoundJoinKey(
                right_field.reference,
                left_field.reference,
                left_field.data_type,
            )
        if key not in keys:
            keys.append(key)
    return tuple(keys)


def _aggregate_for(
    node: AggregateCall,
    alias: str | None,
    layout: RowLayout,
) -> tuple[Aggregate, DataType]:
    try:
        if node.function == "COUNT" and node.star:
            aggregate: Aggregate = Count(alias) if alias is not None else Count()
        else:
            if not isinstance(node.argument, ColumnRef):
                raise _binding_error(
                    node,
                    f"{node.function} requires exactly one column argument",
                )
            reference = _canonical_reference(layout, node.argument)
            factories = {
                "COUNT": CountColumn,
                "SUM": Sum,
                "AVG": Avg,
                "MIN": Min,
                "MAX": Max,
            }
            factory = factories.get(node.function)
            if factory is None:
                raise _binding_error(
                    node,
                    f"Unknown aggregate function {node.function!r}",
                )
            aggregate = factory(reference, alias)
        bound = aggregate.bind(layout)
    except SqlBindingError:
        raise
    except (InvalidTypeError, ValidationError) as error:
        raise _binding_error(node, str(error)) from error
    return aggregate, bound.output_type


def _projection_items(
    items: tuple[SelectItem, ...],
    layout: RowLayout,
    group_keys: tuple[ColumnReference, ...],
) -> tuple[tuple[BoundProjectionItem, ...], tuple[Aggregate, ...]]:
    has_aggregate = any(isinstance(item.expr, AggregateCall) for item in items)
    grouped = bool(group_keys or has_aggregate)
    projection: list[BoundProjectionItem] = []
    aggregates: list[Aggregate] = []

    for item in items:
        if isinstance(item.expr, Star):
            if item.alias is not None:
                raise _binding_error(item, "A star expansion cannot have one alias")
            if grouped:
                raise _binding_error(
                    item,
                    "SELECT * is not valid in an aggregate/grouped query",
                )
            matching = tuple(
                field
                for field in layout.fields
                if item.expr.relation is None
                or field.relation == item.expr.relation
            )
            if not matching:
                message = f"Unknown relation qualifier: {item.expr.relation!r}"
                if item.expr.span is None:
                    raise SqlUnknownColumnError(message, position=1)
                raise SqlUnknownColumnError(message, span=item.expr.span)
            for field in matching:
                projection.append(
                    BoundProjectionItem(
                        layout.published_name(field),
                        field.data_type,
                        source=field.reference,
                        source_position=field.position,
                    )
                )
            continue

        if isinstance(item.expr, AggregateCall):
            aggregate, output_type = _aggregate_for(item.expr, item.alias, layout)
            aggregate_index = len(aggregates)
            aggregates.append(aggregate)
            projection.append(
                BoundProjectionItem(
                    aggregate.alias,
                    output_type,
                    aggregate_index=aggregate_index,
                )
            )
            continue

        if not isinstance(item.expr, ColumnRef):
            raise _binding_error(item, "SELECT accepts columns, stars, or aggregates")
        reference = _canonical_reference(layout, item.expr)
        field = layout.field(reference)
        if grouped and reference not in group_keys:
            raise _binding_error(
                item,
                f"Selected column {reference.qualified_name!r} is not a GROUP BY key",
            )
        projection.append(
            BoundProjectionItem(
                item.alias if item.alias is not None else layout.published_name(field),
                field.data_type,
                source=reference,
                source_position=field.position,
                group_key_index=(
                    group_keys.index(reference) if grouped else None
                ),
            )
        )

    if group_keys and not aggregates:
        raise _binding_error(
            items[0],
            "GROUP BY requires at least one aggregate in the adopted Stage 7 subset",
        )
    if has_aggregate and not group_keys:
        plain = [item for item in projection if item.aggregate_index is None]
        if plain:
            raise _binding_error(
                items[0],
                "Global aggregation cannot select non-aggregate source columns",
            )
    return tuple(projection), tuple(aggregates)


def _output_schema(
    statement: SelectStatement,
    projection: tuple[BoundProjectionItem, ...],
) -> Schema:
    names: set[str] = set()
    for item in projection:
        if item.output_name in names:
            raise _binding_error(
                statement,
                f"Duplicate SELECT output name {item.output_name!r}; use distinct aliases",
            )
        names.add(item.output_name)
    try:
        return Schema([Column(item.output_name, item.data_type) for item in projection])
    except ValidationError as error:
        raise _binding_error(statement, str(error)) from error


def _bind_group_keys(
    statement: SelectStatement,
    layout: RowLayout,
) -> tuple[ColumnReference, ...]:
    group_keys: list[ColumnReference] = []
    for node in statement.group_by:
        reference = _canonical_reference(layout, node)
        if reference in group_keys:
            raise _binding_error(
                node,
                f"Duplicate GROUP BY key {reference.qualified_name!r}",
            )
        group_keys.append(reference)
    return tuple(group_keys)


def _bind_order_by(
    statement: SelectStatement,
    layout: RowLayout,
    projection: tuple[BoundProjectionItem, ...],
    group_keys: tuple[ColumnReference, ...],
) -> tuple[BoundOrderItem, ...]:
    output_positions = {
        item.output_name: position for position, item in enumerate(projection)
    }
    selected_sources = {
        item.source for item in projection if item.source is not None
    }
    grouped = bool(group_keys or any(item.aggregate_index is not None for item in projection))
    result: list[BoundOrderItem] = []

    for item in statement.order_by:
        expression = item.expr
        if not isinstance(expression, ColumnRef):
            if isinstance(expression, IntegerLiteral):
                message = "Positional ORDER BY is not supported; name a column or alias"
            else:
                message = "ORDER BY expressions are not supported"
            raise _binding_error(item, message)

        if expression.relation is None and expression.name in output_positions:
            position = output_positions[expression.name]
            output = projection[position]
            result.append(
                BoundOrderItem(
                    output.data_type,
                    item.descending,
                    output_position=position,
                    source=output.source,
                    hidden=False,
                )
            )
            continue

        reference = _canonical_reference(layout, expression)
        field = layout.field(reference)
        if grouped and reference not in group_keys:
            raise _binding_error(
                item,
                "Grouped ORDER BY must use a group key or aggregate output alias",
            )
        result.append(
            BoundOrderItem(
                field.data_type,
                item.descending,
                output_position=None,
                source=reference,
                hidden=reference not in selected_sources,
            )
        )
    return tuple(result)


def bind_select(
    environment: QueryEnvironment,
    statement: SelectStatement,
) -> BoundSelect:
    """Resolve a SELECT completely without instantiating physical operators."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("bind_select requires a QueryEnvironment")
    if not isinstance(statement, SelectStatement):
        raise InvalidTypeError("bind_select requires a SelectStatement")
    if not statement.items:
        raise _binding_error(statement, "SELECT requires at least one output item")

    first = _bind_relation(environment, statement.from_table, 0)
    relations = [first]
    source_layout = first.layout
    join_predicate = None
    join_keys: tuple[BoundJoinKey, ...] = ()

    if statement.join is not None:
        second = _bind_relation(environment, statement.join.table, 1)
        if second.exposed_name == first.exposed_name:
            raise _binding_error(
                statement.join.table,
                f"Duplicate relation alias {second.exposed_name!r}",
            )
        relations.append(second)
        try:
            source_layout = RowLayout.combine(first.layout, second.layout)
        except ValidationError as error:
            raise _binding_error(statement.join, str(error)) from error
        join_predicate = _bind_predicate(statement.join.on, source_layout)
        join_keys = _join_keys(
            statement.join.on,
            source_layout,
            first.exposed_name,
            second.exposed_name,
        )
        if not join_keys:
            raise _binding_error(
                statement.join.on,
                "INNER JOIN requires an equal-typed column equality across its inputs",
            )

    where = (
        _bind_predicate(statement.where, source_layout)
        if statement.where is not None
        else None
    )
    group_keys = _bind_group_keys(statement, source_layout)
    projection, aggregates = _projection_items(
        statement.items,
        source_layout,
        group_keys,
    )
    output_schema = _output_schema(statement, projection)
    order_by = _bind_order_by(
        statement,
        source_layout,
        projection,
        group_keys,
    )
    return BoundSelect(
        tuple(relations),
        source_layout,
        join_predicate,
        join_keys,
        where,
        group_keys,
        aggregates,
        projection,
        order_by,
        output_schema,
    )


def _mutation_indexes(
    environment: QueryEnvironment,
    table: TableMetadata,
    record: Record | None,
    statement: InsertStatement | DeleteStatement,
) -> tuple[BoundIndexMutation, ...]:
    indexes: list[BoundIndexMutation] = []
    for registered in environment.require_indexes_for(table.name):
        value = record[registered.metadata.column_name] if record is not None else None
        if value is not None:
            try:
                BPlusKeyCodec.validate(
                    table.schema.column(registered.metadata.column_name).data_type,
                    value,
                )
            except (InvalidTypeError, ValidationError) as error:
                raise _binding_error(statement, str(error)) from error
            if registered.metadata.unique:
                with closing(registered.index.search(value)) as matches:
                    if next(matches, None) is not None:
                        raise _binding_error(
                            statement,
                            f"Unique index {registered.metadata.name!r} already "
                            f"contains key {value!r}",
                        )
        indexes.append(
            BoundIndexMutation(
                registered.metadata,
                registered.index,
                value,
                registered.metadata.unique,
            )
        )
    return tuple(indexes)


def _mutation_table(
    environment: QueryEnvironment,
    table_name: str,
    statement: InsertStatement | DeleteStatement,
) -> TableMetadata:
    try:
        return environment.catalog.get_table(table_name)
    except UnknownTableError as error:
        if statement.span is None:
            raise SqlUnknownTableError(_domain_message(error), position=1) from error
        raise SqlUnknownTableError(
            _domain_message(error), span=statement.span
        ) from error


def bind_insert(
    environment: QueryEnvironment,
    statement: InsertStatement,
) -> BoundInsert:
    """Validate one INSERT row and all affected index keys without writing."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("bind_insert requires a QueryEnvironment")
    if not isinstance(statement, InsertStatement):
        raise InvalidTypeError("bind_insert requires an InsertStatement")
    if not statement.values:
        raise _binding_error(statement, "INSERT VALUES requires at least one value")
    table = _mutation_table(environment, statement.table, statement)
    storage = environment.storage_for(statement.table)
    schema_names = tuple(column.name for column in table.schema)

    if statement.columns is None:
        input_names = schema_names
    else:
        input_names = statement.columns
        if len(set(input_names)) != len(input_names):
            raise _binding_error(statement, "INSERT column list contains duplicates")
        for name in input_names:
            try:
                table.schema.column(name)
            except UnknownColumnError as error:
                if statement.span is None:
                    raise SqlUnknownColumnError(
                        _domain_message(error), position=1
                    ) from error
                raise SqlUnknownColumnError(
                    _domain_message(error), span=statement.span
                ) from error
        missing = tuple(name for name in schema_names if name not in input_names)
        if missing:
            raise _binding_error(
                statement,
                "INSERT must provide every column because defaults and NULL are "
                f"not supported; missing: {', '.join(repr(name) for name in missing)}",
            )

    if len(input_names) != len(statement.values):
        raise _binding_error(
            statement,
            f"INSERT column/value count mismatch: {len(input_names)} columns, "
            f"{len(statement.values)} values",
        )

    supplied: dict[str, RecordValue] = {}
    for name, node in zip(input_names, statement.values):
        value = _literal_value(node)
        column = table.schema.column(name)
        try:
            ValueCodec.encode(column.data_type, value)
        except (InvalidTypeError, ValidationError) as error:
            raise _binding_error(
                node,
                f"Invalid value for column {name!r}: {error}",
            ) from error
        supplied[name] = value

    try:
        record = Record(table.schema, [supplied[name] for name in schema_names])
        validate_record(table, record)
    except (InvalidTypeError, ValidationError) as error:
        raise _binding_error(statement, str(error)) from error

    storage_key: RecordValue | None = None
    requires_storage_unique_check = False
    if isinstance(storage, PagedSequentialFile):
        storage_key = record[storage.key_column]
        requires_storage_unique_check = not storage.allow_duplicate_keys
        if requires_storage_unique_check:
            with closing(storage.search(storage_key)) as matches:
                if next(matches, None) is not None:
                    raise _binding_error(
                        statement,
                        f"Paged Sequential key {storage_key!r} already exists",
                    )

    indexes = _mutation_indexes(environment, table, record, statement)
    return BoundInsert(
        table,
        storage,
        record,
        indexes,
        isinstance(storage, PagedSequentialFile),
        storage_key,
        requires_storage_unique_check,
    )


def bind_delete(
    environment: QueryEnvironment,
    statement: DeleteStatement,
) -> BoundDelete:
    """Validate a DELETE target/predicate while preserving RID requirements."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("bind_delete requires a QueryEnvironment")
    if not isinstance(statement, DeleteStatement):
        raise InvalidTypeError("bind_delete requires a DeleteStatement")
    table = _mutation_table(environment, statement.table, statement)
    storage = environment.storage_for(statement.table)
    layout = RowLayout(table.schema, relation=table.name)
    where = (
        _bind_predicate(statement.where, layout)
        if statement.where is not None
        else None
    )
    indexes = _mutation_indexes(environment, table, None, statement)
    return BoundDelete(
        table,
        storage,
        layout,
        where,
        indexes,
        requires_stable_rid=True,
        storage_may_move_rids=isinstance(storage, PagedSequentialFile),
    )


def bind_create(
    environment: QueryEnvironment,
    statement: CreateTableStatement,
) -> BoundCreate:
    """Resolve one CREATE definition without allocating or registering files."""

    if not isinstance(environment, QueryEnvironment):
        raise InvalidTypeError("bind_create requires a QueryEnvironment")
    if not isinstance(statement, CreateTableStatement):
        raise InvalidTypeError("bind_create requires a CreateTableStatement")

    try:
        columns: list[Column] = []
        constraints: list[ColumnConstraint] = []
        for definition in statement.columns:
            if definition.data_type.name == "INTEGER":
                data_type = DataType.INTEGER
                varchar_length = None
            elif definition.data_type.name == "VARCHAR":
                data_type = DataType.VARCHAR
                varchar_length = definition.data_type.length
            else:  # pragma: no cover - parser owns accepted type spellings
                raise _binding_error(
                    definition.data_type,
                    f"Unsupported CREATE type {definition.data_type.name!r}",
                )
            columns.append(Column(definition.name, data_type))
            if varchar_length is not None or definition.primary_key:
                constraints.append(
                    ColumnConstraint(
                        definition.name,
                        varchar_length=varchar_length,
                        primary_key=definition.primary_key,
                    )
                )
        table = TableMetadata(
            statement.table,
            Schema(columns),
            tuple(constraints),
        )
    except (InvalidTypeError, ValidationError) as error:
        raise _binding_error(statement, str(error)) from error

    if environment.catalog.has_table(table.name):
        raise _binding_error(statement, f"Duplicate table name: {table.name!r}")
    primary_index_name = (
        f"__pk__{table.name}" if table.primary_key is not None else None
    )
    if (
        primary_index_name is not None
        and environment.catalog.has_index(primary_index_name)
    ):
        raise _binding_error(
            statement,
            f"Duplicate index name: {primary_index_name!r}",
        )
    return BoundCreate(table, primary_index_name)


def bind_statement(
    environment: QueryEnvironment,
    statement: Statement,
) -> BoundSelect | BoundInsert | BoundDelete | BoundCreate:
    """Dispatch one parsed statement to the matching read-only binder."""

    if isinstance(statement, SelectStatement):
        return bind_select(environment, statement)
    if isinstance(statement, InsertStatement):
        return bind_insert(environment, statement)
    if isinstance(statement, DeleteStatement):
        return bind_delete(environment, statement)
    if isinstance(statement, CreateTableStatement):
        return bind_create(environment, statement)
    raise InvalidTypeError("bind_statement requires a supported SQL statement AST")


__all__ = [
    "BoundDelete",
    "BoundCreate",
    "BoundIndexCondition",
    "BoundIndexMutation",
    "BoundInsert",
    "BoundJoinKey",
    "BoundOrderItem",
    "BoundPredicate",
    "BoundProjectionItem",
    "BoundRelation",
    "BoundSelect",
    "bind_delete",
    "bind_create",
    "bind_insert",
    "bind_select",
    "bind_statement",
]
