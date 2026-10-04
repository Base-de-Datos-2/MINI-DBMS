"""Task 10.9: the plans the SQL planner really chooses for the measured queries.

The structure experiments call storage and index classes directly. This module
asks the full SQL path the same questions: it creates one table per structure
through ``api.database.Database`` (the owner the HTTP API uses), then runs
``EXPLAIN ANALYZE`` for exact equality, ranges of the three selectivities and
``ORDER BY id``, with indexes enabled and disabled. Each row records the real
plan descriptor (operator chain and access-path details), the rows produced
and the execution time, so the report can show which access path the planner
picks and whether that pick is the fastest one.

The planner chooses access paths by rule (exact index first, then B+ range),
not by an estimated cost, so the plan does not depend on table size; 10,000
rows are used by default.
"""

from __future__ import annotations

from pathlib import Path
import random
from statistics import median
from typing import Any

from api.database import (
    HEAP,
    SEQUENTIAL,
    Database,
    DatabaseDefinition,
    IndexDefinition,
    TableDefinition,
)
from engine.catalog import IndexType
from engine.operators.context import DEFAULT_BUDGET_BYTES

from .datasets import KEY_COLUMN, SCHEMA, generate
from .harness import ResultWriter, workspace


EXPERIMENT = "sql_plans"
SELECTIVITIES = (0.001, 0.01, 0.10)

#: (table, structure label of the other experiments, organization, index type, clustered)
TABLES = (
    ("t_unclustered", "unclustered_bplus", HEAP, IndexType.BPLUS, False),
    ("t_hash", "extendible_hash", HEAP, IndexType.EXTENDIBLE_HASH, False),
    ("t_clustered", "clustered_bplus", SEQUENTIAL, IndexType.BPLUS, True),
)


def definition(size: int) -> DatabaseDefinition:
    rows = generate(size)
    ordered = sorted(rows)
    tables = []
    for table, _, organization, index_type, clustered in TABLES:
        source = ordered if organization == SEQUENTIAL else rows
        tables.append(TableDefinition(
            name=table,
            schema=SCHEMA,
            organization=organization,
            key_column=KEY_COLUMN if organization == SEQUENTIAL else None,
            indexes=(IndexDefinition(
                name=f"{table}_id", column=KEY_COLUMN, index_type=index_type,
                unique=True, clustered=clustered,
            ),),
            rows=lambda source=source: iter(source),
        ))
    return DatabaseDefinition(name=f"plans_{size}", tables=tuple(tables))


def queries(size: int) -> list[tuple[str, float | None, str]]:
    """(operation, selectivity, WHERE/ORDER clause) shared by every table."""

    rng = random.Random(size * 7_919 + 1)
    key = rng.randint(1, size)
    result = [("equality_present", None, f"WHERE id = {key}"),
              ("equality_absent", None, f"WHERE id = {size + 1}")]
    for selectivity in SELECTIVITIES:
        width = max(1, int(size * selectivity))
        low = rng.randint(1, size - width + 1)
        result.append(("range", selectivity, f"WHERE id >= {low} AND id <= {low + width - 1}"))
    result.append(("ordered_retrieval", None, "ORDER BY id"))
    return result


def _chain(plan) -> str:
    """Operator chain from the root; an index scan names the index it reads."""

    names = []
    for node in plan.walk():
        index = dict(node.details).get("index") if node.name == "IndexScan" else None
        names.append(f"{node.name}({index})" if index else node.name)
    return " <- ".join(names)


def _access(plan) -> tuple[str, dict[str, str]]:
    for node in plan.walk():
        if node.name in ("IndexScan", "TableScan"):
            return node.name, dict(node.details)
    return "?", {}


def run(size: int, repetitions: int, writer: ResultWriter, workdir: Path) -> list[dict[str, Any]]:
    """Create the tables once and record one row per (table, query, option)."""

    summary = []
    with workspace(workdir, f"sql-plans-{size}") as directory:
        database = Database.create(definition(size), directory / "db",
                                   memory_budget_bytes=DEFAULT_BUDGET_BYTES)
        try:
            session = database.open_session()
            try:
                for table, structure, organization, _, _ in TABLES:
                    for operation, selectivity, clause in queries(size):
                        sql = f"EXPLAIN ANALYZE SELECT * FROM {table} {clause}"
                        for use_indexes in (True, False):
                            seconds, chain, access, details, rows = [], None, None, None, None
                            for _ in range(repetitions):
                                result = session.execute(sql, use_indexes=use_indexes)
                                seconds.append(result.execution_seconds)
                                chain = _chain(result.plan)
                                access, details = _access(result.plan)
                                rows = result.output_rows
                            row = writer.record(
                                experiment=EXPERIMENT, structure=structure,
                                operation=operation, size=size, repetition=1,
                                elapsed_seconds=median(seconds), count=1,
                                selectivity=selectivity, table=table,
                                organization=organization, sql=sql[len("EXPLAIN ANALYZE "):],
                                use_indexes=use_indexes, plan=chain, access=access,
                                access_details=details, rows_returned=rows,
                                execution_seconds_all=seconds,
                            )
                            summary.append(row)
            finally:
                session.close()
        finally:
            database.close()
    return summary


def render(rows: list[dict[str, Any]], output: Path) -> Path:
    """Markdown table: chosen plan versus forced table scan, per query."""

    lines = [
        "# Planes elegidos por el planner SQL (Tarea 10.9)", "",
        "Generado por `python -m benchmarks plans`. Cada consulta se ejecutó con "
        "`EXPLAIN ANALYZE` sobre la ruta SQL completa (`api.database.Database`), "
        "con índices habilitados y deshabilitados; el tiempo es la mediana de las "
        "ejecuciones. Tamaño: " + ", ".join(sorted({f"{row['size']:,}" for row in rows})) + " registros.",
        "",
        "| Tabla (estructura) | Consulta | Plan con índices | ms | Plan sin índices | ms | Filas | ¿El planner eligió la opción más rápida? |",
        "|---|---|---|---:|---|---:|---:|---|",
    ]
    paired: dict[tuple, dict[bool, dict[str, Any]]] = {}
    for row in rows:
        paired.setdefault((row["table"], row["structure"], row["operation"], row["selectivity"]), {})[row["use_indexes"]] = row
    for (table, structure, operation, selectivity), pair in paired.items():
        with_index, without = pair[True], pair[False]
        label = operation if selectivity is None else f"{operation} {selectivity:.1%}"
        index_ms = with_index["elapsed_seconds"] * 1000
        scan_ms = without["elapsed_seconds"] * 1000
        if with_index["plan"] == without["plan"]:
            verdict = "mismo plan"
        elif index_ms <= scan_ms:
            verdict = "sí"
        else:
            verdict = f"no: el recorrido es {index_ms / scan_ms:.1f}× más rápido"
        lines.append(
            f"| `{table}` ({structure}) | {label} | {with_index['plan']} | {index_ms:,.2f} "
            f"| {without['plan']} | {scan_ms:,.2f} | {with_index['rows_returned']:,} | {verdict} |"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
