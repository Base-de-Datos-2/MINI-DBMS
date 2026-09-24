# SQL engine guide

> **Current status (2026-09-20):** this guide documents the verified Stage 7
> Tasks 7.1–7.40 implementation. Limited CREATE is executable in an engine-owned
> manifest database; EXPLAIN and EXPLAIN ANALYZE execute through the public
> engine result contract. See the
> [Task 7.31 decisions](ETAPA_07_TASK_7_31_DECISIONS.md) and
> [extension closure audit](ETAPA_07_EXTENSION_AUDIT.md).

> **Stage 8 closure (2026-09-24):** owner-created sessions and the
> compatibility `Database.engine` execute every existing SQL family through
> coordinated schema/table protection. Tasks 8.1–8.30 close with bounded
> rollback, controlled concurrency evidence, seeded stress and 2,831 strict
> passing tests; see [the audit](ETAPA_08_AUDIT.md).

This guide describes the SQL engine implemented by Stage 7 and coordinated by
the Stage 8 owner/session lifecycle. The normative
grammar, token/span conventions, parser limits, and production-to-function map
are in [sql-grammar.md](sql-grammar.md).

## Public setup and execution

Manifest-backed applications create or open one engine-owned database. It owns
the persistent manifest, Catalog, runtime registry, permanent Heap/B+ handles,
and configured `SqlEngine`:

```python
from engine.database import Database

with Database.create("university-db", name="university") as database:
    definition = database.engine.execute("""
        CREATE TABLE students (
            id INT PRIMARY KEY,
            name VARCHAR(100),
            age INT
        )
    """)
    assert definition.table_name == "students"
    database.engine.execute("INSERT INTO students VALUES (1, 'Eva', 21)")

with Database.open("university-db") as database:
    with database.engine.execute("SELECT * FROM students") as rows:
        print([row.values for row in rows])
```

`Database.open()` discovers the schema and primary index from
`database.catalog.json`; callers do not supply a Python schema. CREATE is
available only through this manifest-backed owner. It allocates opaque managed
filenames and publishes success after the new Heap, optional unique B+ primary
index, live registrations, and manifest are ready.

### Transactions in an owner-backed database

`Database.engine` is the default session. `Database.open_session()` creates an
independent session with its own active transaction and cursor slot, backed by
the same Catalog, storage/index runtime, lock manager, and completion service.

```python
with Database.open("university-db") as database:
    session = database.open_session()
    try:
        session.execute("BEGIN TRANSACTION")
        inserted = session.execute(
            "INSERT INTO students VALUES (2, 'Ada', 22)"
        )
        assert inserted.provisional and not inserted.committed

        with session.execute("SELECT name FROM students WHERE id = 2") as rows:
            assert [row.values for row in rows] == [("Ada",)]

        session.execute("END TRANSACTION")
        assert inserted.committed
    finally:
        session.close()
```

Standalone SELECT, INSERT, and DELETE use one implicit transaction. An
implicit mutation commits before its result is returned. An implicit SELECT
holds its S locks until EOF or explicit close. Inside an explicit group,
cursor EOF/close releases operator and temporary resources while logical locks
remain until END or ROLLBACK. An ordinary execution failure aborts the complete
group; protocol errors such as nested BEGIN or END with an open cursor leave
the group available for correction or explicit rollback.

`prepare()` and `describe()` remain side-effect free. At execution, a prepared
statement is rebound under its granted resources so rollback-driven runtime
handle replacement cannot reuse a stale storage or index object.

The explicit legacy setup remains supported for existing definition-driven
databases. Applications create schemas and physical managers through the
existing Python APIs and register borrowed handles in `QueryEnvironment`:

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

The extension additionally accepts these forms:

```text
CREATE TABLE <table> (
    <column> <INT|INTEGER|VARCHAR(positive-integer)> [PRIMARY KEY]
    [, ...]
)

EXPLAIN [ANALYZE] <supported-select-statement>
```

`parse_sql` returns located ASTs for both forms. Manifest-backed engines bind,
prepare, and execute CREATE. Engines without an injected DDL service reject it
without side effects. Every engine with a valid query environment can prepare
and execute the SELECT-only explanation forms.

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

SQL-created `VARCHAR(n)` columns accept 1–4,075 Unicode code points. Each value
is checked by character count without normalization or truncation, then by
strict UTF-8 encoding and the complete 4,079-byte record capacity. A VARCHAR
primary-key value also has the existing 255-byte B+ key limit. All columns
require concrete values because this dialect has no SQL NULL representation.

## Exact one-statement alumnos scenario

Each block below is one independent `engine.execute(...)` call against the
same manifest-backed database. They are not a script and must not be joined or
split automatically.

```sql
-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);
```

```sql
-- 1
SELECT * FROM alumnos
WHERE nombre = 'Pérez, Juan';
```

```sql
-- 2
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
```

```sql
-- 3
SELECT * FROM alumnos
WHERE id = 999;
```

```sql
-- 4
EXPLAIN
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
```

```sql
-- 5
EXPLAIN ANALYZE
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
```

Immediately after CREATE, the three SELECT statements succeed with the
four-column schema and no rows. Plain EXPLAIN returns the prepared
Projection/ExternalSort/Filter/TableScan tree with no runtime evidence;
ANALYZE runs that SELECT once and reports zero output rows.

After submitting these three INSERT statements individually:

```sql
INSERT INTO alumnos VALUES (3, 'Pérez, Juan', 1, 17);
```

```sql
INSERT INTO alumnos VALUES (1, 'Ana', 2, 14);
```

```sql
INSERT INTO alumnos VALUES (2, 'Luis', 1, 10);
```

query 1 returns `(3, 'Pérez, Juan', 1, 17)`, query 2 returns id 1 followed by
id 3, query 3 remains a successful empty result, and ANALYZE reports two
output rows. Closing the owner and calling `Database.open(database_path)`
reconstructs the schema and primary index from `database.catalog.json`; the
same submissions then produce the same results without caller-supplied
metadata.

A request such as `CREATE TABLE ...; SELECT ...` or `INSERT ...; SELECT ...`
raises `SqlSyntaxError` before the first statement has an effect. One optional
final semicolon followed by whitespace or `--` comments is accepted, and
semicolon/comment text inside a quoted string remains data.

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
mutation again. Owner-coordinated results expose `transaction_id`, `committed`,
and `provisional`. An explicit command is provisional at statement return and
becomes committed only after successful END; an implicit command is committed
before it is returned.

CREATE returns a completed `DefinitionResult` with the exact table name and
optional reserved primary-index name. It has no row stream and no
`affected_rows`. CREATE preparation is side-effect free; the prepared
definition is deliberately non-reusable because successful execution changes
the catalog generation it was prepared against.

Both explanation forms return a completed `ExplanationResult`, whose
`statement_kind` distinguishes `EXPLAIN` from `EXPLAIN_ANALYZE`. Its structured
`plan` is a `PlanSpecDescriptor`, separate from a SELECT row schema. Plain
EXPLAIN validates the prepared table/index identities but never constructs or
opens a row operator: `executed` is false, `complete` is true, and
`statistics`, `output_rows`, and `execution_seconds` are `None`.

EXPLAIN ANALYZE creates one fresh physical tree, drains it once to EOF without
retaining result rows, and returns only after operator/context cleanup. Its
`executed` and `complete` flags are true, `output_rows` is the final root
cardinality, and `statistics` is the actual `PlanReport`. `planning_seconds`
and `execution_seconds` have separate wall-time scopes. A failed analysis
raises `AnalysisExecutionError`; its report is `FAILED`, `complete` is false,
and any available partial runtime evidence remains accessible through the
exception. The ordinary SELECT materialization limit does not apply to
analysis.

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

### Adapter-facing result contract

One editor submission contains one complete SQL statement and produces either
one result object or one exception. Adapters inspect both enums explicitly;
they do not infer behavior from SQL text and must reject unknown future kinds.

| `ResultKind` | `StatementKind` | Payload and ownership |
|---|---|---|
| `ROWS` | `SELECT` | Lazy row stream with a SELECT schema; caller drains or closes it |
| `COMMAND` | `INSERT`, `DELETE` | Synchronous mutation report with `affected_rows`; no row stream |
| `DEFINITION` | `CREATE` | Synchronous created table/index identity; no row stream or affected-row count |
| `EXPLANATION` | `EXPLAIN` | Synchronous prepared plan; no runtime measurements or row schema |
| `EXPLANATION` | `EXPLAIN_ANALYZE` | Synchronous prepared plan plus one completed run's measurements; no retained rows |

All synchronous variants release operation-owned resources before return. An
unconsumed `ROWS` result continues to block every new statement on the same
engine. The existing Stage 9 HTTP adapter intentionally keeps its earlier
allowlists until the separate integration task adds exhaustive serialization
for definitions and explanations.

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

Inside an owner-coordinated session, table X is granted before mutable
constraint checks or DELETE discovery, and the complete base/index file set is
captured before the first write. Ordinary failure restores all tables changed
by the group and reopens their canonical runtime objects before releasing
conflicting waiters. Successful implicit commands and END validate and flush
the complete write set before reporting commit.

A deliberately standalone `SqlEngine(QueryEnvironment)` keeps the Stage 7
maintenance behavior: INSERT attempts to remove its newly written row; DELETE
may retain confirmed earlier deletions; indexes are repaired from base storage.
That lower-level route has no transaction isolation. Neither route provides
WAL recovery or crash-atomic commit across multiple files.

## Unsupported syntax

The list below describes the currently executable boundary. Limited
`CREATE TABLE`, `EXPLAIN SELECT`, and `EXPLAIN ANALYZE SELECT` are implemented.
Multiple statements remain unsupported.

The following remain outside the Stage 7 subset:

- UPDATE, UPSERT, MERGE, DDL other than the limited parsed CREATE TABLE form,
  subqueries, set operations, and more than one JOIN;
- outer, cross, natural, and non-equality-only joins;
- NULL, defaults, constraints other than the parsed inline PRIMARY KEY,
  arithmetic expressions, positional ORDER BY, DISTINCT, HAVING, LIMIT/OFFSET,
  and window functions;
- COMMIT, savepoints and other transaction or concurrency commands. Owner
  sessions execute `BEGIN TRANSACTION`, `END TRANSACTION`, and `ROLLBACK`;
  a deliberately standalone `SqlEngine` rejects transaction controls;
- EXPLAIN around INSERT, DELETE, CREATE, or another EXPLAIN statement;
- multiple statements or trailing tokens after the optional final semicolon.

Recognized out-of-scope syntax raises `SqlUnsupportedError`. Malformed accepted
syntax raises `SqlSyntaxError`; invalid characters/literals raise
`SqlLexicalError`; bounded-input failures raise `SqlLimitError`; resolved-name
or semantic failures raise `SqlBindingError` or its located table/column
variants. These all derive from the project `ValidationError` hierarchy.
Invalid definitions, duplicate tables/keys, invalid values, and storage
failures retain their existing domain exceptions. An execution-time ANALYZE
failure uses `AnalysisExecutionError` to keep its original cause and an
explicit incomplete partial report.

## Reproducible verification

The original Section 12 dataset is executed through the public API in
`tests/query/test_stage7_acceptance.py`. The exact CREATE/EXPLAIN extension
scenario, its empty/populated/reopened phases, constraints, and one-statement
boundary are in `tests/query/test_stage7_extension_acceptance.py`. External
and restart behavior is in `tests/query/test_stage7_resources.py`. EXPLAIN
non-execution, measured analysis, spill cleanup, failure, and public result
contracts are in `tests/query/test_explain.py`.

```powershell
.venv\Scripts\python.exe -m pytest tests/query tests/test_architecture.py `
  -q -W error -p no:cacheprovider
```

The original Stage 7 audit records the baseline closure. The extension closure
audit records the exact CREATE/EXPLAIN scenario, restart/failure matrix, and
the final complete result of **2,742 passing tests** under warnings-as-errors.

## Stage 8 integration points

Stage 8 Tasks 8.3–8.30 add owner sessions, resource access plans, S/X locks,
short physical latches, physical undo, terminal completion, and coordinated
SQL execution plus controlled concurrency evidence around these boundaries:

- each session owns one `SqlEngine` facade and its active SELECT cursor policy;
  independent facades share the owner's runtime and transaction coordinator.
- `QueryResult` owns operator/context lifetime and exposes completion,
  early-close, and failure states.
- `MutationService` is the table-wide base/index write boundary.
- `MaintenanceError.completed_rows` and persistent incomplete-index markers
  expose the current ordinary-failure state.
- storage/index managers remain borrowed durable resources registered in
  `QueryEnvironment`.

The transaction contract defines identity, sessions, lock policy, commit and
abort boundaries, deadlock behavior, and recovery limits. Standalone CREATE
holds schema X across publication/compensation, pure planning uses the short
metadata gate, and ANALYZE reports separate lock/planning/execution evidence
plus its transaction outcome. The owner exposes bounded ordered traces,
cooperative cancellation, and finite `shutdown()`; compatibility `close()`
still refuses active calls. The Tasks 8.23–8.26 runbook and unsafe/protected
threaded comparison are in `docs/ETAPA_08_TASK_8_23_8_26.md`. Bounded stress,
the Stage 9 handoff and closure evidence are in `tests/transactions/test_bounded_stress.py`,
`docs/ETAPA_08_STAGE_9_HANDOFF.md`, and `docs/ETAPA_08_AUDIT.md`. Physical
before-image rollback is bounded and in-process; it is not WAL-backed crash
recovery. The emergency HTTP adapter still serializes requests and does not yet
expose stable cross-request sessions.
