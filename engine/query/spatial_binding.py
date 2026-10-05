"""Resolve logical locations without I/O or ownership of spatial indexes."""

from dataclasses import dataclass, replace
import math

from engine.catalog import DataType
from engine.errors import ValidationError
from engine.operators.compute import computed_layout
from engine.operators.rows import ColumnReference
from engine.spatial.expressions import Distance
from engine.spatial.geometry import Metric, Point
from engine.spatial.index import SpatialIndex

from .ast import (
    AggregateCall, BoolAnd, BoolNot, BoolOr, ColumnRef, Comparison,
    FloatLiteral, FunctionCall, IntegerLiteral, OrderItem, SelectItem, Star,
    StringLiteral,
)
from .errors import SqlBindingError


@dataclass(frozen=True, slots=True)
class SpatialAccess:
    index: SpatialIndex
    expression: Distance
    kind: str
    value: float | int
    inclusive: bool = False


def _error(node, message):
    return SqlBindingError(message, span=node.span) if node.span else SqlBindingError(message, position=1)


def _point(node):
    if not isinstance(node, FunctionCall) or node.function != "POINT" or len(node.arguments) != 2:
        raise _error(node, "Distance requires POINT(latitude, longitude) or a supplied point parameter")
    if any(not isinstance(arg, (IntegerLiteral, FloatLiteral)) for arg in node.arguments):
        raise _error(node, "POINT requires two numeric literals")
    try:
        return Point(*(arg.value for arg in node.arguments))
    except ValidationError as error:
        raise _error(node, str(error)) from error


def _threshold(node):
    try:
        value = float(node.value)
        if not math.isfinite(value):
            raise OverflowError
    except OverflowError as error:
        raise _error(node, "Distance threshold must be finite") from error
    return FloatLiteral(value, span=node.span)


def _distance(environment, relations, node):
    if node.function not in {"DISTANCIA", "DISTANCE"} or len(node.arguments) not in (2, 3):
        raise _error(node, "Expected distancia(location, POINT(latitude, longitude), optional metric)")
    location = node.arguments[0]
    if not isinstance(location, ColumnRef):
        raise _error(location, "Distance requires a registered logical location")
    matches = []
    for relation in relations:
        index = environment.spatial_for(relation.metadata.name)
        if index is not None and location.name == index.mapping.location_name and (
            location.relation is None or location.relation == relation.exposed_name
        ):
            matches.append((relation, index))
    if len(matches) != 1:
        raise _error(location, "Logical location is unknown or ambiguous")
    relation, index = matches[0]
    metric = Metric.HAVERSINE
    if len(node.arguments) == 3:
        value = node.arguments[2]
        if not isinstance(value, StringLiteral):
            raise _error(value, "Distance metric must be a string literal")
        try:
            metric = Metric(value.value.lower())
        except ValueError as error:
            raise _error(value, "Distance metric must be haversine or euclidean") from error
    mapping = index.mapping
    expression = Distance(
        ColumnReference(mapping.latitude_column, relation.exposed_name),
        ColumnReference(mapping.longitude_column, relation.exposed_name),
        _point(node.arguments[1]), metric,
    )
    return expression, index


class _Rewrite:
    def __init__(self, environment, relations, layout):
        self.environment, self.relations, self.layout = environment, relations, layout
        self.computed = {}
        self.indexes = {}

    def expression(self, node):
        if isinstance(node, FunctionCall):
            expression, index = _distance(self.environment, self.relations, node)
            if expression not in self.computed:
                number = len(self.computed)
                name = f"__distance_{number}"
                while name in {field.name for field in self.layout} | set(self.computed.values()):
                    number += 1
                    name = f"__distance_{number}"
                self.computed[expression] = name
                self.indexes[name] = index
            return ColumnRef(self.computed[expression], span=node.span)
        if isinstance(node, Comparison):
            left, right = self.expression(node.left), self.expression(node.right)
            if isinstance(node.left, FunctionCall) and isinstance(right, IntegerLiteral):
                right = _threshold(right)
            if isinstance(node.right, FunctionCall) and isinstance(left, IntegerLiteral):
                left = _threshold(left)
            return replace(node, left=left, right=right)
        if isinstance(node, (BoolAnd, BoolOr)):
            return replace(node, left=self.expression(node.left), right=self.expression(node.right))
        if isinstance(node, BoolNot):
            return replace(node, term=self.expression(node.term))
        return node

    def access(self, node):
        if isinstance(node, BoolAnd):
            return self.access(node.left) or self.access(node.right)
        if not isinstance(node, Comparison):
            return None
        left, right, operator = node.left, node.right, node.operator
        if isinstance(right, ColumnRef) and right.name in self.indexes:
            left, right = right, left
            operator = {">": "<", ">=": "<="}.get(operator, "")
        if not isinstance(left, ColumnRef) or left.name not in self.indexes:
            return None
        if operator not in {"<", "<="} or not isinstance(right, FloatLiteral) or right.value < 0:
            return None
        expression = next(expr for expr, name in self.computed.items() if name == left.name)
        return SpatialAccess(self.indexes[left.name], expression, "radius", right.value, operator == "<=")


def bind_spatial_expressions(environment, relations, layout, statement):
    rewrite = _Rewrite(environment, relations, layout)
    items = tuple(replace(item, expr=rewrite.expression(item.expr), alias=(
        item.alias or "distancia" if isinstance(item.expr, FunctionCall) else item.alias
    )) for item in statement.items)
    where = rewrite.expression(statement.where)
    order = tuple(replace(item, expr=rewrite.expression(item.expr)) for item in statement.order_by)
    if not rewrite.computed:
        return statement, layout, (), None
    if statement.join is not None:
        raise _error(statement, "Spatial expressions in JOIN queries are not supported")
    if statement.group_by or any(isinstance(item.expr, AggregateCall) for item in items):
        raise _error(statement, "Spatial expressions in grouped queries are not supported")
    expanded = []
    for item in items:
        if isinstance(item.expr, Star):
            if item.alias is not None:
                raise _error(item, "A star expansion cannot have one alias")
            matching = [field for field in layout if item.expr.relation is None or field.relation == item.expr.relation]
            if not matching:
                raise _error(item, "Unknown relation qualifier")
            expanded.extend(SelectItem(ColumnRef(field.name, field.relation, span=item.expr.span),
                                       span=item.span) for field in matching)
        else:
            expanded.append(item)
    aliases = {item.alias: item.expr for item in items if item.alias is not None}
    order_expression = aliases.get(order[0].expr.name, order[0].expr) if (
        len(order) == 1 and isinstance(order[0].expr, ColumnRef) and order[0].expr.relation is None
    ) else (order[0].expr if len(order) == 1 else None)
    access = rewrite.access(where)
    if isinstance(order_expression, ColumnRef) and order_expression.name in rewrite.indexes and not order[0].descending:
        index = rewrite.indexes[order_expression.name]
        expression = next(expr for expr, name in rewrite.computed.items() if name == order_expression.name)
        if where is None and statement.limit is not None:
            access = SpatialAccess(index, expression, "knn", statement.limit)
        order = (*order, OrderItem(ColumnRef(index.mapping.identity_column, relations[0].exposed_name)))
    expressions = tuple((name, expr) for expr, name in rewrite.computed.items())
    return replace(statement, items=tuple(expanded), where=where, order_by=order), computed_layout(layout, expressions), expressions, access
