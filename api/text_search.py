"""Read-only published-text HTTP service; never creates or modifies indexes."""
from __future__ import annotations
from dataclasses import asdict
from time import perf_counter
from typing import Any

from engine.catalog import DataType
from engine.errors import ValidationError
from engine.operators.context import cancellation_point
from .serialization import encode_value


def published_tables(database) -> list[dict[str, Any]]:
    """Only published and validated registrations are exposed."""
    return [
        {"table": table, "column": index.text_column, "id_column": index.id_column,
         "documents": index.statistics.document_count, "collection_id": index.collection_id}
        for table, index in sorted(database._text_indexes.items())
    ]


def run_published_search(database, request, *, session=None) -> dict[str, Any]:
    started = perf_counter()
    index = database._text_indexes.get(request.table)
    if index is None or index.text_column != request.column:
        raise ValidationError("No compatible published text index for table and column")
    schema = database._catalog.get_table(request.table).schema
    columns = [
        {"position": i, "name": column.name, "type": column.data_type.value,
         "encoding": {DataType.INTEGER: "int64", DataType.FLOAT: "float64",
                      DataType.VARCHAR: "string", DataType.BOOLEAN: "boolean"}[column.data_type]}
        for i, column in enumerate(schema)
    ]
    columns.append({"position": len(columns), "name": "relevancia", "type": "FLOAT", "encoding": "float64"})
    # Keep record retrieval under the same session read lock as scoring: the
    # published heap is sealed, so RIDs and content remain stable.
    storage = database._storages[request.table]
    rows = []
    def materialize(result):
        for hit in result.hits[:request.max_rows]:
            cancellation_point()
            record = storage.read(hit.rid)
            rows.append([encode_value(col.data_type, val) for col, val in zip(record.schema, record.values)] + [hit.score])
        return result
    result = database.text_search(
        request.table, request.column, request.query, model=request.model,
        order=request.order, limit=request.limit, use_indexes=request.use_indexes,
        session=session, consume=materialize,
    )
    report = asdict(result.report)
    return {
        "kind": "query", "statement": "TEXT_SEARCH", "table": request.table,
        "model": request.model, "columns": columns, "rows": rows,
        "total_rows": len(result.hits), "returned_rows": len(rows),
        "truncated": len(result.hits) > request.max_rows,
        "result_complete": len(result.hits) <= request.max_rows,
        "plan": {"operator": result.report.access, "selection": result.report.selection,
                 "model": request.model, "order": request.order, "limit": request.limit},
        "metrics": {"backend_elapsed_ms": round((perf_counter()-started)*1000, 3),
                    "ranking": report},
    }
