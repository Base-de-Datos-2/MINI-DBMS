"""Immutable point parameters resolved into syntax, never interpolated SQL."""

from collections.abc import Mapping
from dataclasses import replace
import re
from types import MappingProxyType

from engine.errors import ValidationError
from engine.spatial.geometry import Point

from .ast import (
    BoolAnd, BoolNot, BoolOr, ColumnRef, Comparison, ExplainStatement,
    FloatLiteral, FunctionCall, SelectStatement,
)
from .errors import SqlBindingError


def snapshot_parameters(parameters):
    if parameters is None:
        return None
    if not isinstance(parameters, Mapping) or len(parameters) > 32:
        raise SqlBindingError("Parameters must be a mapping with at most 32 points", position=1)
    result = {}
    for name, coordinates in parameters.items():
        if type(name) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,63}", name) is None:
            raise SqlBindingError("Invalid point parameter name", position=1)
        if not isinstance(coordinates, (tuple, list)) or len(coordinates) != 2:
            raise SqlBindingError("Point parameters require latitude and longitude", position=1)
        try:
            point = Point(*coordinates)
        except ValidationError as error:
            raise SqlBindingError(str(error), position=1) from error
        result[name] = (point.latitude, point.longitude)
    return MappingProxyType(result)


def _resolve_expression(node, parameters):
    if isinstance(node, FunctionCall):
        arguments = list(node.arguments)
        if node.function in {"DISTANCIA", "DISTANCE"} and len(arguments) >= 2:
            parameter = arguments[1]
            if isinstance(parameter, ColumnRef) and parameter.relation is None:
                if parameter.name not in parameters:
                    raise SqlBindingError(f"Missing point parameter {parameter.name!r}",
                                          **({"span": parameter.span} if parameter.span else {"position": 1}))
                arguments[1] = FunctionCall("POINT", tuple(FloatLiteral(value) for value in parameters[parameter.name]),
                                            span=parameter.span)
        return replace(node, arguments=tuple(_resolve_expression(arg, parameters) for arg in arguments))
    if isinstance(node, (BoolAnd, BoolOr, Comparison)):
        return replace(node, left=_resolve_expression(node.left, parameters),
                       right=_resolve_expression(node.right, parameters))
    if isinstance(node, BoolNot):
        return replace(node, term=_resolve_expression(node.term, parameters))
    return node


def resolve_parameters(statement, parameters):
    if isinstance(statement, ExplainStatement):
        return replace(statement, select=resolve_parameters(statement.select, parameters))
    if not isinstance(statement, SelectStatement):
        if parameters:
            raise SqlBindingError("Point parameters apply only to SELECT or EXPLAIN", position=1)
        return statement
    parameters = {} if parameters is None else parameters
    return replace(statement,
                   items=tuple(replace(item, expr=_resolve_expression(item.expr, parameters)) for item in statement.items),
                   where=_resolve_expression(statement.where, parameters),
                   order_by=tuple(replace(item, expr=_resolve_expression(item.expr, parameters)) for item in statement.order_by))
