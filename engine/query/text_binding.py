"""Semantic binding of the intentionally bounded textual SELECT subset."""
from dataclasses import dataclass

from engine.catalog import Column, DataType, Schema
from .ast import (TextMatch, FunctionCall, ColumnRef, Star, BoolAnd, BoolOr, BoolNot)
from .errors import SqlBindingError, SqlUnknownColumnError


def is_text_select(select):
    def match(expr):
        if isinstance(expr, TextMatch):
            return True
        if isinstance(expr, (BoolAnd, BoolOr)):
            return match(expr.left) or match(expr.right)
        return isinstance(expr, BoolNot) and match(expr.term)
    return (select.text_model is not None or match(select.where) or
            any(isinstance(item.expr, FunctionCall) and item.expr.function.upper() == 'SCORE'
                for item in select.items))


@dataclass(frozen=True, slots=True)
class TextAccess:
    index: object
    column: str
    query: str
    model: str
    order: str
    # Each projected field is a source column name, or None for SCORE().
    fields: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class TextBinding:
    """Text facts returned to the general binder, without importing it back."""
    access: TextAccess
    projection: tuple[tuple[str, DataType], ...]
    schema: Schema


def bind_text_select(environment, statement, relation):
    def fail(node, message, cls=SqlBindingError):
        span = node.span or statement.span
        raise cls(message, **({'span': span} if span is not None else {'position': 1}))
    if statement.join is not None or statement.group_by:
        fail(statement, 'Textual SELECT supports one table and no GROUP BY/JOIN')
    if not isinstance(statement.where, TextMatch):
        fail(statement.where or statement, 'Textual SELECT requires a single MATCH condition')
    if statement.text_model not in ('TF_IDF', 'BM25'):
        fail(statement, 'Text ranking model must be TF_IDF or BM25')
    schema = relation.metadata.schema
    columns = {c.name: c for c in schema}
    def resolve(ref):
        if ref.relation is not None and ref.relation != relation.exposed_name:
            fail(ref, f'Unknown relation qualifier {ref.relation!r}')
        if ref.name not in columns:
            fail(ref, f'Unknown column {ref.name!r}', SqlUnknownColumnError)
        return ref.name
    column = resolve(statement.where.column)
    if columns[column].data_type != DataType.VARCHAR:
        fail(statement.where.column, 'MATCH column must be VARCHAR')
    index = environment.text_for(relation.metadata.name)
    if index is None or index.text_column != column:
        fail(statement.where, 'No compatible published text index for this table and field')
    output = []
    for item in statement.items:
        expr = item.expr
        if isinstance(expr, Star):
            if item.alias is not None or expr.relation not in (None, relation.exposed_name):
                fail(item, 'Invalid textual star projection')
            output.extend((c.name, c.name) for c in schema)
        elif isinstance(expr, ColumnRef):
            output.append((item.alias or expr.name, resolve(expr)))
        elif isinstance(expr, FunctionCall) and expr.function.upper() == 'SCORE' and not expr.arguments:
            output.append((item.alias or 'score', None))
        else:
            fail(item, 'Only columns, stars and SCORE() are supported in textual projection')
    names = [name for name, _ in output]
    if len(names) != len(set(names)):
        fail(statement, 'Duplicate projected output names')
    order = 'score_desc'
    if statement.order_by:
        keys = []
        for item in statement.order_by:
            ref = item.expr
            if not isinstance(ref, ColumnRef):
                fail(item, 'ORDER BY requires the SCORE alias or document ID')
            if ref.relation is None and ref.name in names:
                field = output[names.index(ref.name)][1]
                key = 'score' if field is None else 'id' if field == index.id_column else 'other'
            else:
                key = 'id' if resolve(ref) == index.id_column else 'other'
            keys.append((key, item.descending))
        if keys[0][0] == 'score' and (len(keys) == 1 or keys[1:] == [('id', False)]):
            order = 'score_desc' if keys[0][1] else 'score_asc'
        elif len(keys) == 1 and keys[0][0] == 'id':
            order = 'id_desc' if keys[0][1] else 'id_asc'
        else:
            fail(statement, 'Unsupported textual ORDER BY')
    projection = tuple((name, DataType.FLOAT if field is None else columns[field].data_type)
                       for name, field in output)
    return TextBinding(TextAccess(index, column, statement.where.query.value, statement.text_model,
                                   order, tuple(field for _, field in output)),
                       projection, Schema([Column(name, data_type) for name, data_type in projection]))
