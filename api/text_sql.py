"""Bounded SQL presentation adapter for immutable published text collections.

The existing relational SQL engine does not yet accept TextMatch in its binder;
this module provides an explicit, strictly validated SQL path at the API owner.
It never guesses a collection or mutates persistent storage.
"""
from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from engine.catalog import DataType
from engine.query.ast import (SelectStatement, ExplainStatement, TextMatch, Star,
                              ColumnRef, FunctionCall, BoolAnd, BoolOr, BoolNot)
from engine.query.errors import SqlBindingError, SqlUnknownColumnError, SqlUnknownTableError
from .serialization import encode_value


def is_text_statement(statement):
    select = statement.select if isinstance(statement, ExplainStatement) else statement
    if not isinstance(select, SelectStatement):
        return False
    def contains_match(expr):
        if isinstance(expr, TextMatch):
            return True
        if isinstance(expr, (BoolAnd, BoolOr)):
            return contains_match(expr.left) or contains_match(expr.right)
        if isinstance(expr, BoolNot):
            return contains_match(expr.term)
        return False
    return (select.text_model is not None or contains_match(select.where)
            or any(isinstance(item.expr, FunctionCall) and item.expr.function.upper() == 'SCORE'
                   for item in select.items))


def run_text_sql(database, statement, *, source, session, use_indexes, max_rows):
    """Validate the frozen text subset and return the regular /api/query shape."""
    started = perf_counter()
    explain = isinstance(statement, ExplainStatement)
    analyze = explain and statement.analyze
    select = statement.select if explain else statement

    def fail(node, message, cls=SqlBindingError):
        raise cls(message, span=node.span or select.span, source=source)

    if select.join is not None or select.group_by:
        fail(select, 'Textual SELECT supports one table and no GROUP BY/JOIN')
    if not isinstance(select.where, TextMatch):
        fail(select.where or select, 'Textual SELECT requires a single MATCH condition')
    if select.text_model not in ('TF_IDF', 'BM25'):
        fail(select, 'Text ranking model must be TF_IDF or BM25')
    table = select.from_table.name
    if table not in database._tables:
        fail(select.from_table, f'Unknown table {table!r}', SqlUnknownTableError)
    schema = database._catalog.get_table(table).schema
    fields = {c.name: c for c in schema}
    alias = select.from_table.alias or table

    def resolve(ref):
        if ref.relation is not None and ref.relation != alias:
            fail(ref, f'Unknown relation qualifier {ref.relation!r}')
        if ref.name not in fields:
            fail(ref, f'Unknown column {ref.name!r}', SqlUnknownColumnError)
        return ref.name

    match_column = resolve(select.where.column)
    if fields[match_column].data_type != DataType.VARCHAR:
        fail(select.where.column, 'MATCH column must be VARCHAR')
    index = database._text_indexes.get(table)
    if index is None or index.text_column != match_column:
        fail(select.where, 'No compatible published text index for this table and field')

    output = []  # (output name, schema column or None for SCORE)
    for item in select.items:
        expr = item.expr
        if isinstance(expr, Star):
            if item.alias is not None:
                fail(item, 'Star cannot have an alias')
            if expr.relation is not None and expr.relation != alias:
                fail(expr, 'Unknown star qualifier')
            output.extend((c.name, c) for c in schema)
        elif isinstance(expr, ColumnRef):
            name = resolve(expr)
            output.append((item.alias or name, fields[name]))
        elif isinstance(expr, FunctionCall) and expr.function.upper() == 'SCORE' and not expr.arguments:
            output.append((item.alias or 'score', None))
        else:
            fail(item, 'Only columns, stars and SCORE() are supported in textual projection')
    names = [name for name, _ in output]
    if len(set(names)) != len(names):
        fail(select, 'Duplicate projected output names')

    # Resolve ORDER BY against output aliases first, then source ID.
    order = 'score_desc'
    if select.order_by:
        if len(select.order_by) > 2:
            fail(select, 'Unsupported textual ORDER BY')
        keys = []
        for item in select.order_by:
            if not isinstance(item.expr, ColumnRef):
                fail(item, 'ORDER BY SCORE() directly is unsupported; use its output alias')
            ref = item.expr
            if ref.relation is None and ref.name in names:
                column = output[names.index(ref.name)][1]
                key = 'score' if column is None else ('id' if column.name == index.id_column else 'other')
            else:
                key = 'id' if resolve(ref) == index.id_column else 'other'
            keys.append((key, item.descending))
        if keys[0] == ('score', True):
            if len(keys) != 1 and keys[1:] != [('id', False)]:
                fail(select, 'Only ID ASC may follow SCORE DESC')
            order = 'score_desc'
        elif keys[0] == ('score', False):
            if len(keys) != 1 and keys[1:] != [('id', False)]:
                fail(select, 'Only ID ASC may follow SCORE ASC')
            order = 'score_asc'
        elif len(keys) == 1 and keys[0][0] == 'id':
            order = 'id_desc' if keys[0][1] else 'id_asc'
        else:
            fail(select, 'Unsupported textual ORDER BY key')

    strategy = 'TextIndex' if use_indexes else 'TextScan'
    plan = {
        'prepared': {'root': {'name': 'TextTopK' if order == 'score_desc' and select.limit is not None else 'TextRank',
                              'output_columns': names,
                              'details': [{'key': 'model', 'value': select.text_model},
                                          {'key': 'access', 'value': strategy},
                                          {'key': 'table', 'value': table},
                                          {'key': 'column', 'value': match_column},
                                          {'key': 'order', 'value': order},
                                          {'key': 'limit', 'value': select.limit}],
                              'ordered_by': order, 'children': []}, 'truncated': False},
        'runtime': None,
    }
    columns = [{'position': i, 'name': name,
                'type': 'FLOAT' if col is None else col.data_type.value,
                'encoding': 'float64' if col is None else {
                    DataType.INTEGER: 'int64', DataType.FLOAT: 'float64',
                    DataType.VARCHAR: 'string', DataType.BOOLEAN: 'boolean'}[col.data_type]}
               for i, (name, col) in enumerate(output)]
    body = {
        'kind': 'explanation' if explain else 'rows',
        'statement': 'EXPLAIN_ANALYZE' if analyze else 'EXPLAIN' if explain else 'SELECT',
        'columns': [] if explain else columns,
        'rows': [], 'returned_rows': 0, 'truncated': False,
        'truncation_reason': None, 'result_complete': True,
        'total_rows': None if explain else 0, 'affected_rows': None,
        'execution_plan': plan, 'plan_status': 'prepared',
        'metrics': {'scope': 'backend textual SQL', 'partial': False, 'engine': None},
    }
    if explain and not analyze:
        body['explanation'] = {'model': select.text_model, 'access': strategy,
                               'order': order, 'limit': select.limit, 'table': table}
        return body

    result = database.text_search(table, match_column, select.where.query.value,
                                  model=select.text_model, order=order, limit=select.limit,
                                  use_indexes=use_indexes, session=session)
    storage = database._storages[table]
    for hit in result.hits[:max_rows]:
        record = storage.read(hit.rid)
        row = [hit.score if col is None else encode_value(col.data_type, record[col.name])
               for _, col in output]
        body['rows'].append(row)
    if not explain:
        body['returned_rows'] = len(body['rows'])
        body['truncated'] = len(result.hits) > max_rows
        body['truncation_reason'] = 'row_limit' if body['truncated'] else None
        body['result_complete'] = not body['truncated']
        body['total_rows'] = len(result.hits) if not body['truncated'] else None
    else:
        body['explanation'] = {'model': select.text_model, 'access': result.report.access,
                               'order': order, 'limit': select.limit,
                               'rows_returned': len(result.hits)}
    body['execution_plan']['runtime'] = {'name': result.report.access,
                                          'rows_returned': len(result.hits),
                                          'elapsed_seconds': result.report.elapsed_seconds}
    body['plan_status'] = 'execution-observed'
    body['metrics']['engine'] = {'text_ranking': asdict(result.report)}
    body['metrics']['backend_text_elapsed_ms'] = round((perf_counter()-started)*1000, 3)
    return body
