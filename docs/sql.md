# Stage 7 SQL engine guide

This guide describes the SQL engine implemented by Stage 7. The normative
grammar, token/span conventions, parser limits, and production-to-function map
are in [sql-grammar.md](sql-grammar.md).

## Public setup and execution

Stage 7 does not add SQL DDL. Applications create schemas, table metadata,
storage managers, and indexes through the existing Python APIs, then register
their live handles in `QueryEnvironment`.

```python
from engine.catalog import Catalog, Column, DataType, Schema, TableMetadata
from engine.query import QueryEnvironment, SqlEngine
from engine.storage import HeapFile

students_schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])

catalog = Catalog()
catalog.register_table(TableMetadata("students", students_schema))

storage = HeapFile.create("students.heap", students_schema)
try:
    environment = QueryEnvironment(catalog)
    environment.register_storage("students", storage)
    engine = SqlEngine(environment)

    prepared = engine.prepare(
        "SELECT name FROM students WHERE age >= 18 ORDER BY name"
    )
    print(prepared.describe().render())   # planning facts; no execution

    result = prepared.execute()           # lazy SELECT result
    for record in result:
        print(record.values)

    command = engine.execute(
        "INSERT INTO students VALUES (5, 'Eva', 21)"
    )
    print(command.affected_rows)          # 1; mutation already completed
finally:
    storage.close()
```

Index metadata and its live adapter must also be registered before preparing a
statement that reads or mutates that indexed table. The Catalog remains an
in-memory registry in the current architecture; storage and index files carry
their own persistent formats and are reopened explicitly after restart.

## Accepted SQL

The engine accepts exactly one statement per submission.

```text
SELECT <projection>
FROM <table> [AS] <alias>
[[INNER] JOIN <table> [AS] <alias> ON <predicate>]
[WHERE <predicate>]
[GROUP BY <column> [, ...]]
[ORDER BY <column-or-output-alias> [ASC|DESC] [, ...]]

INSERT INTO <table> [(<column> [, ...])] VALUES (<literal> [, ...])

DELETE FROM <table> [WHERE <predicate>]
```

Supported projection items are `*`, columns, and the aggregates `COUNT(*)`,
`COUNT(column)`, `SUM`, `AVG`, `MIN`, and `MAX`. One inner join is supported.
Join conditions must contain at least one compatible cross-relation equality
key. Additional `ON` terms remain residual predicates.

Predicates support `=`, `<>`, `!=`, `<`, `<=`, `>`, and `>=`, combined with
`NOT`, `AND`, `OR`, and parentheses. Precedence is `NOT`, then `AND`, then
`OR`. Literals are strings, signed integers, signed floats, and the Boolean
keywords `TRUE` and `FALSE`. A sign belongs to one numeric literal only.

Keywords are case-insensitive. Catalog identifiers, aliases, and column names
are case-sensitive. A relation alias replaces the original table qualifier in
that scope. Types are exact: INTEGER is not implicitly coerced to FLOAT or
VARCHAR.

`INSERT` requires a value for every schema column because defaults and NULL do
not exist in the Stage 6/7 row model. An optional column list may reorder fields
but may not omit or repeat them. `DELETE FROM table` without `WHERE` is the
adopted whole-table form.

## Planning and execution routes

- Every single-relation SELECT has a `TableScan` baseline.
- A compatible hash or B+ index may serve exact equality.
- B+ indexes may serve bounded or one-sided ranges; hash indexes never serve a
  range.
- OR, NOT, unsupported index combinations, and unavailable indexes retain a
  complete scan/filter route.
- The complete WHERE expression remains a residual `Filter`, even when an
  index narrows candidate rows.
- ORDER BY uses the Stage 6 `ExternalSort` implementation. Hidden order fields
  remain available until the final projection.
- GROUP BY uses `ExternalHashGroup` and its bounded repartition/sorted-fallback
  behavior.
- A supported join defaults to `GraceHashJoin`. AUTO may choose
  `IndexNestedLoopJoin` only when the logical right input has one compatible
  exact index for the single equality key. `NestedLoopJoin` remains an explicit
  correctness baseline.

This is a deterministic rule-based planner, not a cost optimizer. Selecting an
index does not claim a measured speedup.

`PhysicalPlanningOptions` provides exact sort/group/join grants, partition and
fan-in controls, and deterministic join strategy selection for tests. The
enclosing `SqlEngine.memory_budget_bytes` must be at least as large as the
explicit grants requested by its simultaneously live blocking operators.
Planning options are fixed by `prepare()`. Executing an existing
`PreparedQuery` with new options is rejected; prepare a new query instead.

## Results and reports

`SELECT` returns a lazy `QueryResult`. Iteration and `fetchmany(size)` are the
primary bounded interfaces. `fetchall(limit=...)` and the compatibility `rows`
property use hard limits and raise instead of silently truncating output.

One unconsumed SELECT owns its `SqlEngine` session. Exhaustion produces
`COMPLETE`; explicit early close produces `CLOSED`; execution or cleanup errors
produce `FAILED`. Partial delivery is never reported as successful completion.
Closing a result releases its operator tree, context, temporary files, memory
reservations, and handles without closing Catalog-owned storage/index managers.

INSERT and DELETE return a completed `CommandResult` with `affected_rows` and
no row stream. Fetching or inspecting a command result cannot execute the
mutation again.

`PreparedQuery.describe()` returns immutable planning facts, including output
columns, physical children, storage/index identities, predicates, and
sort/group/join keys. `QueryResult.report.runtime` returns the measured Stage 6
`PlanReport` from the actual operator instances. Runtime evidence includes
local row counts, root elapsed time, permanent and temporary page I/O, spill
bytes, peak reserved memory, peak handle use, runs, partitions, recursion, and
fallback metadata. Inclusive parent/child counters and timings are not added
together.

DELETE command statistics additionally contain the real discovery
`PlanReport`, target count, and spool bytes. INSERT reports association updates
or complete index rebuilds.

## Mutation consistency

Preparing, describing, parsing, or binding a statement never changes records
or index associations. Mutable uniqueness and runtime identities are checked
again immediately before a write.

INSERT writes its base record once. Heap-backed indexes receive the resulting
RID association. A sequential insertion that can move RIDs first marks every
index incomplete and then rebuilds them all from base storage.

DELETE executes and closes its discovery plan before writing. Exact RID and old
record pairs are stored in a framed disk spool rather than an unbounded Python
list. Each target is re-read and compared with its original record before its
index associations and base row are removed, preventing a reused RID from
deleting a replacement row.

Ordinary failures use base storage as the repair authority. INSERT attempts to
remove its newly written row. DELETE retains and reports its confirmed earlier
deletions. Every index is rebuilt; one that cannot be repaired remains
persistently incomplete and is rejected by live and reopened access. Successful
commands flush storage and indexes before returning.

These guarantees do not provide transaction isolation, concurrent-write
safety, WAL recovery, statement rollback, or crash-atomic commits across
multiple files.

## Unsupported syntax

The following remain outside the Stage 7 subset:

- UPDATE, UPSERT, MERGE, DDL, subqueries, set operations, and more than one
  JOIN;
- outer, cross, natural, and non-equality-only joins;
- NULL, defaults, constraints declared through SQL, arithmetic expressions,
  positional ORDER BY, DISTINCT, HAVING, LIMIT/OFFSET, and window functions;
- BEGIN/COMMIT/ROLLBACK and every transaction or concurrency command;
- SQL EXPLAIN and EXPLAIN ANALYZE;
- multiple statements or trailing tokens after the optional final semicolon.

Recognized out-of-scope syntax raises `SqlUnsupportedError`. Malformed accepted
syntax raises `SqlSyntaxError`; invalid characters/literals raise
`SqlLexicalError`; bounded-input failures raise `SqlLimitError`; resolved-name
or semantic failures raise `SqlBindingError` or its located table/column
variants. These all derive from the project `ValidationError` hierarchy.

## Reproducible verification

The Section 12 dataset from `ETAPA_07.md` is executed through the public API in
`tests/query/test_stage7_acceptance.py`. External and restart behavior is in
`tests/query/test_stage7_resources.py`.

```powershell
.venv\Scripts\python.exe -m pytest tests/query tests/test_architecture.py `
  -q -W error -p no:cacheprovider
```

The Stage 7 closure audit records the complete cross-stage command and exact
test counts.

## Stage 8 integration points

Stage 8 can add transaction and concurrency behavior around these existing
boundaries:

- `SqlEngine` owns one session and the active SELECT cursor policy.
- `QueryResult` owns operator/context lifetime and exposes completion,
  early-close, and failure states.
- `MutationService` is the table-wide base/index write boundary.
- `MaintenanceError.completed_rows` and persistent incomplete-index markers
  expose the current ordinary-failure state.
- storage/index managers remain borrowed durable resources registered in
  `QueryEnvironment`.

Stage 8 must define transaction identity, locks, competing sessions, commit and
abort boundaries, deadlock behavior, and recovery separately. It must not
reinterpret the current compensation path as WAL-backed rollback.
