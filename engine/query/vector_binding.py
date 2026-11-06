"""Semantic binding of the bounded Part 4 SIMILAR_TO SELECT subset.

Accepted (docs/multimedia-contract.md §5): one table, ``SIMILAR_TO`` as the
entire WHERE, ``USING IVF|HNSW WITH METRIC=...``, columns / ``*`` /
``SIMILARITY_SCORE()`` in the projection, no ORDER BY or score DESC with an
optional ``id ASC`` tie-break, optional LIMIT (output ``min(k, LIMIT, N)``).
"""

from dataclasses import dataclass

from engine.catalog import Column, DataType, Schema
from engine.errors import ValidationError

from .ast import BoolAnd, BoolNot, BoolOr, ColumnRef, FunctionCall, SimilarTo, Star
from .errors import SqlBindingError, SqlUnknownColumnError


def _contains_similar(expr) -> bool:
    if isinstance(expr, SimilarTo):
        return True
    if isinstance(expr, (BoolAnd, BoolOr)):
        return _contains_similar(expr.left) or _contains_similar(expr.right)
    return isinstance(expr, BoolNot) and _contains_similar(expr.term)


def _is_score(expr) -> bool:
    return isinstance(expr, FunctionCall) and expr.function.upper() == "SIMILARITY_SCORE"


def is_vector_select(select) -> bool:
    return (select.vector_method is not None or _contains_similar(select.where)
            or any(_is_score(item.expr) for item in select.items)
            or any(_is_score(item.expr) for item in select.order_by))


@dataclass(frozen=True, slots=True)
class VectorAccess:
    collection: object
    media_key: str
    k: int
    method: str          # "IVF" | "HNSW" (requested; the scan toggle may bypass it)
    metric: str          # "euclidean" | "dot" | "cosine"
    # Each projected field is a source column name, or None for SIMILARITY_SCORE().
    fields: tuple


@dataclass(frozen=True, slots=True)
class VectorBinding:
    access: VectorAccess
    projection: tuple
    schema: Schema


def bind_vector_select(environment, statement, relation):
    from engine.multimedia.contracts import IndexMethod, Metric, media_key_modality

    def fail(node, message, cls=SqlBindingError):
        span = getattr(node, "span", None) or statement.span
        raise cls(message, **({"span": span} if span is not None else {"position": 1}))

    if statement.join is not None or statement.group_by:
        fail(statement, "SIMILAR_TO supports one table and no JOIN or GROUP BY")
    if not isinstance(statement.where, SimilarTo):
        fail(statement.where or statement, "SIMILARITY_SCORE() requires a single SIMILAR_TO condition")
    if statement.vector_method is None:
        fail(statement, "SIMILAR_TO requires USING <IVF|HNSW> WITH METRIC=<metric>")
    try:
        method = IndexMethod.from_sql(statement.vector_method).value
        metric = Metric.from_sql(statement.vector_metric).value
    except ValidationError as error:
        fail(statement, str(error))
    table = relation.metadata.name
    collection = environment.multimedia_for(table)
    if collection is None:
        fail(statement.from_table, f"Table {table!r} has no published multimedia collection")
    try:
        media_key_modality(statement.where.media.value, collection.modality)
    except ValidationError as error:
        fail(statement.where.media, str(error))
    if metric not in collection.methods.get(method, []):
        fail(statement, f"Collection {table!r} has no {method} index for metric {metric}")
    k = statement.where.k.value
    schema = relation.metadata.schema
    columns = {c.name: c for c in schema}

    def resolve(ref):
        if ref.relation is not None and ref.relation != relation.exposed_name:
            fail(ref, f"Unknown relation qualifier {ref.relation!r}")
        if ref.name not in columns:
            fail(ref, f"Unknown column {ref.name!r}", SqlUnknownColumnError)
        return ref.name

    output = []
    for item in statement.items:
        expr = item.expr
        if isinstance(expr, Star):
            if item.alias is not None or expr.relation not in (None, relation.exposed_name):
                fail(item, "Invalid star projection")
            output.extend((c.name, c.name) for c in schema)
        elif isinstance(expr, ColumnRef):
            output.append((item.alias or expr.name, resolve(expr)))
        elif _is_score(expr) and not expr.arguments:
            output.append((item.alias or "similarity_score", None))
        else:
            fail(item, "Only columns, stars and SIMILARITY_SCORE() are supported with SIMILAR_TO")
    names = [name for name, _ in output]
    if len(names) != len(set(names)):
        fail(statement, "Duplicate projected output names")
    if statement.order_by:
        keys = []
        for item in statement.order_by:
            expr = item.expr
            if _is_score(expr):
                key = "score"
            elif isinstance(expr, ColumnRef) and expr.relation is None and expr.name in names \
                    and output[names.index(expr.name)][1] is None:
                key = "score"
            elif isinstance(expr, ColumnRef) and resolve(expr) == collection.id_column:
                key = "id"
            else:
                key = "other"
            keys.append((key, item.descending))
        if keys[0] != ("score", True) or keys[1:] not in ([], [("id", False)]):
            fail(statement, "SIMILAR_TO results are ordered best-first: allow only ORDER BY score DESC "
                            "[, id ASC]")
    projection = tuple((name, DataType.FLOAT if field is None else columns[field].data_type)
                       for name, field in output)
    access = VectorAccess(collection, statement.where.media.value, k, method, metric,
                          tuple(field for _, field in output))
    return VectorBinding(access, projection, Schema([Column(name, t) for name, t in projection]))


__all__ = ["VectorAccess", "VectorBinding", "bind_vector_select", "is_vector_select"]
