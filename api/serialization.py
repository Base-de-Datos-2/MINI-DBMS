"""Convert engine objects into JSON-ready values without inventing facts.

Every field is copied from an engine object: a prepared plan comes from
``PreparedQuery.describe()`` and an executed plan from the ``PlanReport`` of the
run that produced the rows. Nothing is estimated or decorated.

Values are encoded losslessly and every column declares its encoding:

* ``int64``: a JSON number within JavaScript's exact range, otherwise a
  decimal string, so the browser never rounds a large INTEGER;
* ``float64``: a JSON number when finite, otherwise ``"Infinity"``,
  ``"-Infinity"`` or ``"NaN"``, because JSON has no non-finite numbers;
* ``boolean`` and ``string``: the JSON value itself.

The engine has no SQL NULL, so no value is ever encoded as ``null``.
"""

from __future__ import annotations

import json
import math
from typing import Any

from engine.catalog import DataType, Schema
from engine.operators import OperatorDescriptor, PlanReport
from engine.query import PlanSpecDescriptor, SqlQueryError
from engine.storage import Record

from .database import IndexSummary, TableSummary
from .schemas import JS_SAFE_INTEGER, MAX_PLAN_DEPTH, MAX_PLAN_NODES


ENCODINGS = {
    DataType.INTEGER: "int64",
    DataType.FLOAT: "float64",
    DataType.BOOLEAN: "boolean",
    DataType.VARCHAR: "string",
}


def encoded_size(value: object) -> int:
    """Return the exact UTF-8 size of ``value`` as compact JSON."""

    return len(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    )


def encode_value(data_type: DataType, value: object) -> object:
    """Encode one value under its column's declared encoding."""

    if data_type is DataType.INTEGER and abs(value) > JS_SAFE_INTEGER:
        return str(value)
    if data_type is DataType.FLOAT and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    return value


def column_descriptors(schema: Schema) -> list[dict[str, Any]]:
    """Describe output columns by position, keeping duplicate names apart."""

    return [
        {
            "position": position,
            "name": column.name,
            "type": column.data_type.value,
            "encoding": ENCODINGS[column.data_type],
        }
        for position, column in enumerate(schema)
    ]


def encode_row(record: Record) -> list[object]:
    """Serialize one row positionally, matching ``column_descriptors``."""

    return [
        encode_value(column.data_type, value)
        for column, value in zip(record.schema, record.values)
    ]


def _pairs(pairs) -> list[dict[str, str]]:
    return [{"key": key, "value": value} for key, value in pairs]


def _columns(pairs) -> list[dict[str, str]]:
    return [{"name": name, "type": data_type} for name, data_type in pairs]


class _PlanBudget:
    """Shared node allowance while one plan tree is serialized."""

    def __init__(self) -> None:
        self.remaining = MAX_PLAN_NODES
        self.truncated = False


def _bounded_children(children, depth, budget, convert) -> list[dict[str, Any]]:
    serialized = []
    for child in children:
        if budget.remaining <= 0 or depth >= MAX_PLAN_DEPTH:
            budget.truncated = True
            break
        serialized.append(convert(child, depth + 1, budget))
    return serialized


def _prepared_node(descriptor, depth, budget) -> dict[str, Any]:
    budget.remaining -= 1
    ordered_by = descriptor.capabilities.ordered_by
    return {
        "name": descriptor.name,
        "output_columns": _columns(descriptor.output_columns),
        "details": _pairs(descriptor.details),
        "ordered_by": None if ordered_by is None else ordered_by.qualified_name,
        "children": _bounded_children(
            descriptor.children, depth, budget, _prepared_node
        ),
    }


def prepared_json(descriptor: PlanSpecDescriptor) -> dict[str, Any]:
    """Serialize what the planner chose, before anything ran."""

    budget = _PlanBudget()
    root = _prepared_node(descriptor, 1, budget)
    return {"root": root, "truncated": budget.truncated}


def _operator_node(descriptor, depth, budget) -> dict[str, Any]:
    budget.remaining -= 1
    return {
        "id": descriptor.operator_id,
        "name": descriptor.name,
        "output_columns": _columns(descriptor.output_columns),
        "details": _pairs(descriptor.details),
        "ordered_by": descriptor.ordered_by,
        "rows_examined": descriptor.rows_examined,
        "rows_emitted": descriptor.rows_emitted,
        "elapsed_ms": round(descriptor.elapsed_seconds * 1000, 3),
        "children": _bounded_children(
            descriptor.children, depth, budget, _operator_node
        ),
    }


def runtime_json(report: PlanReport) -> dict[str, Any]:
    """Serialize the operator tree that executed and its measured counters.

    Row counters are local to each operator; elapsed times include child work
    and are never added together.
    """

    budget = _PlanBudget()
    root = _operator_node(report.root, 1, budget)
    return {
        "root": root,
        "truncated": budget.truncated,
        "rows_produced": report.rows_produced,
        "elapsed_ms": round(report.elapsed_seconds * 1000, 3),
        "memory": {
            "budget_bytes": report.memory_budget_bytes,
            "peak_reserved_bytes": report.peak_reserved_bytes,
            "reservations_granted": report.reservations_granted,
            "reservations_refused": report.reservations_refused,
        },
        "pages": {
            "base_read": report.base_pages_read,
            "base_written": report.base_pages_written,
            "index_read": report.index_pages_read,
            "index_written": report.index_pages_written,
            "temporary_read": report.temporary_pages_read,
            "temporary_written": report.temporary_pages_written,
        },
        "temporary": {
            "bytes_spilled": report.bytes_spilled,
            "peak_live_bytes": report.peak_live_temporary_bytes,
            "live_bytes_after": report.live_temporary_bytes,
            "peak_open_handles": report.peak_open_handles,
        },
    }


def index_json(summary: IndexSummary) -> dict[str, Any]:
    """Serialize the structure of one index for the Files panel."""

    return {
        "name": summary.name,
        "column": summary.column,
        "type": summary.index_type,
        "unique": summary.unique,
        "clustered": summary.clustered,
        "supports_range": summary.supports_range,
        "entry_count": summary.entry_count,
        "file_bytes": summary.file_bytes,
    }


def table_summary_json(summary: TableSummary) -> dict[str, Any]:
    """Serialize one table for the Files-panel list."""

    return {
        "id": summary.name,
        "name": summary.name,
        "organization": summary.organization,
        "row_count": summary.row_count,
        "column_count": len(summary.columns),
        # Indexes of this table only: TableSummary is built per table.
        "index_count": len(summary.indexes),
        "origin": summary.origin,
    }


def table_detail_json(summary: TableSummary) -> dict[str, Any]:
    """Serialize one table's full structure for the Files panel."""

    return {
        "id": summary.name,
        "name": summary.name,
        "organization": summary.organization,
        "key_column": summary.key_column,
        "columns": [
            # The row model has no NULL, so every column is non-nullable.
            {"position": position, "name": name, "type": data_type, "nullable": False}
            for position, (name, data_type) in enumerate(summary.columns)
        ],
        "row_count": summary.row_count,
        "data_pages": summary.data_pages,
        "file_bytes": summary.file_bytes,
        "indexes": [index_json(index) for index in summary.indexes],
        "origin": summary.origin,
        "source_filename": summary.source_filename,
    }


def error_message(error: BaseException) -> str:
    """Return an exception's message without Python's KeyError quoting.

    Several engine errors (unknown table/column, stale references) derive from
    ``KeyError``, whose ``str()`` wraps the message in quotes.
    """

    if isinstance(error, KeyError) and error.args:
        return str(error.args[0])
    return str(error)


def sql_location(error: BaseException) -> dict[str, Any] | None:
    """Return the source location a handwritten-parser error carries, if any."""

    if not isinstance(error, SqlQueryError):
        return None
    return {
        "line": error.line,
        "column": error.column,
        "position": error.position,
        "expected": error.expected,
        "offending": error.offending,
        "context": error.context,
    }


def _milliseconds(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000, 3)


def transaction_report_json(report, table_names) -> dict[str, Any]:
    """Serialize a BEGIN/END/ROLLBACK ``TransactionReport`` without paths.

    ``table_names`` maps engine resource labels to table names. Undo traffic
    is reported apart from query I/O; it is before-image copying, not crash
    recovery.
    """

    metrics = report.metrics
    locked = (*report.held_resources, *(() if metrics is None else metrics.held_resources))
    return {
        "transaction_id": report.id.value,
        "session_id": report.session_id,
        "state": report.state.value,
        "tables_touched": table_names(report.touched_tables),
        "tables_locked": table_names(locked),
        "lock_wait_ms": None if metrics is None else _milliseconds(metrics.lock_wait_seconds),
        "blocker_ids": [] if metrics is None else [item.value for item in metrics.blocker_ids],
        "failure_cause": None if metrics is None else metrics.failure_cause,
        "undo": None if metrics is None else {
            "bytes_captured": metrics.undo.bytes_captured,
            "bytes_restored": metrics.undo.bytes_restored,
            "files_captured": metrics.undo.files_captured,
            "files_restored": metrics.undo.files_restored,
        },
        "completion_ms": None if metrics is None else _milliseconds(metrics.completion_seconds),
        "warnings": list(report.warnings),
    }


def explanation_json(report) -> dict[str, Any]:
    """Serialize the facts of one EXPLAIN / EXPLAIN ANALYZE outside its plan."""

    return {
        "analyzed": report.executed,
        "complete": report.complete,
        "output_rows": report.output_rows,
        "planning_ms": _milliseconds(report.planning_seconds),
        "execution_ms": _milliseconds(report.execution_seconds),
        "lock_wait_ms": _milliseconds(report.lock_wait_seconds),
        "transaction_id": report.transaction_id,
        "transaction_state": report.transaction_state,
        "error": None if report.error_type is None else {
            "type": report.error_type,
            "message": report.error_message,
        },
    }
