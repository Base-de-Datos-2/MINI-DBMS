# AGENTS.md

> Context version: **4.9** — preserves the formal Stage 7 closure, records the
> verified Stage 8 closure through Task 8.30, and identifies the remaining
> transaction-aware Stage 9 integration.

## Purpose

This repository implements the academic project **"Minigestor de Base de Datos Multimodal"** for the course **Base de Datos 2 (2026-2)**.

Codex must treat this repository as an educational database-management-system implementation. The goal is to implement the required database structures and algorithms, not to hide them behind an existing DBMS or high-level library.

The current implementation priority is:

> **Part 1: Relational Database (Tables and SQL)**

Do not implement future parts unless the user explicitly asks for them.

---

## Required reading before changing code

Before modifying any source file:

1. Read `REQUIREMENTS.md`.
2. Read `PROJECT_CONTEXT.md`.
3. Read `PLAN.md`.
4. Identify the current development stage.
5. Read the corresponding stage document, for example:
   - `ETAPA_01.md` for Stage 1;
   - `ETAPA_02.md` for Stage 2;
   - and so on when those files exist.
6. Inspect the existing repository structure and current implementation.
7. Identify which existing tests cover the affected behavior.
8. Explain briefly what will be changed before making a broad or architectural modification.

If repository behavior conflicts with the official requirements, preserve the requirements and report the conflict.

Do not assume that the repository is empty. A later-stage component may already exist and must not be deleted merely because the current plan is focused on an earlier stage.

---

## Documentation roles

The repository uses five primary coordination documents.

### `REQUIREMENTS.md`

Contains the official academic requirements.

It defines **WHAT must be implemented**.

### `PROJECT_CONTEXT.md`

Contains stable architectural decisions and the current technical model.

It defines **HOW the system has been designed**.

### `PLAN.md`

Contains the Part 1 implementation roadmap.

It defines **IN WHAT ORDER the system will be implemented**.

### `ETAPA_XX.md`

Contains the detailed plan for the current implementation stage.

It defines **WHAT TO DO NOW**.

### `AGENTS.md`

Contains the operating rules for Codex.

It defines **HOW CODEX SHOULD WORK** in the repository.

---

## Source-of-truth rules

### For official academic requirements

1. `REQUIREMENTS.md`
2. Original assignment document (`Proyecto_Final.pdf`)
3. `PROJECT_CONTEXT.md`
4. `PLAN.md` / current `ETAPA_XX.md`
5. Existing code
6. Assumptions

### For stable architectural decisions

1. `PROJECT_CONTEXT.md`
2. Existing tests
3. Existing code
4. `PLAN.md` / current `ETAPA_XX.md`
5. New assumptions

### For implementation order

1. `PLAN.md`
2. Current `ETAPA_XX.md`

### For tasks inside the current stage

1. Current `ETAPA_XX.md`
2. `PLAN.md`

### For how Codex should work

1. `AGENTS.md`

Never silently invent a missing academic requirement.

If a requirement is ambiguous:
- preserve the simplest implementation compatible with the assignment;
- state the ambiguity;
- avoid adding unrelated functionality.

---

## Stage-document rule

Stage documents such as `ETAPA_01.md` are implementation plans.

They must never override:

- official requirements in `REQUIREMENTS.md`;
- stable architectural decisions in `PROJECT_CONTEXT.md`;
- operating rules in `AGENTS.md`.

If the current stage document conflicts with one of those sources, stop and report the conflict before implementing the conflicting behavior.

When a design decision made during a stage becomes stable, promote that decision to `PROJECT_CONTEXT.md`.

---

## Current scope

Work only on **Part 1: Relational Database** unless explicitly requested otherwise.

Part 1 includes:

- disk/page storage;
- Heap File;
- Paged Sequential File;
- clustered B+ index;
- unclustered B+ index;
- Extendible Hashing;
- external algorithms for sorting / grouping / joins;
- a limited SQL parser;
- query planning and execution;
- transactions;
- concurrency control;
- thread-based concurrency demonstration;
- REST API / frontend integration;
- experimental comparison and benchmarks.

Future spatial, text-retrieval, multimedia and AI features must not be mixed into the Part 1 implementation prematurely.

---

## Educational implementation constraints

The required algorithms must be implemented by this project.

Do **not** replace required functionality with:

- SQLite as the storage engine;
- PostgreSQL as the storage engine;
- MySQL or another DBMS as the storage engine;
- SQLAlchemy as the query-execution engine;
- pandas for implementing `GROUP BY`, `JOIN` or `ORDER BY`;
- a third-party B+ Tree implementation;
- a third-party Extendible Hashing implementation;
- a third-party external-sort implementation;
- an ORM that bypasses the project's own parser, planner or executor.

Auxiliary libraries are allowed when they do not replace the academic algorithm.

Examples of acceptable auxiliary uses:
- small regular expressions inside the handwritten SQL lexer;
- FastAPI for HTTP transport;
- React for the UI;
- pytest for testing;
- matplotlib for charts;
- Python standard-library modules such as `struct`, `heapq`, `threading`, `pathlib`, `time`, `json`, `csv`, `enum`, and `dataclasses`.

---

## Current technology plan

Unless the repository already contains a different approved implementation:

### DBMS / backend
- Python 3

### SQL grammar
- handwritten lexer and recursive-descent parser (team decision)

### API
- FastAPI

### Frontend
- React
- TypeScript
- Vite

### Tests
- pytest

### Benchmarks
- `time.perf_counter`
- matplotlib

These are implementation decisions, not official assignment requirements. If the repository already uses another valid stack, do not rewrite it solely to match this list.

---

## Architectural boundaries

Keep the implementation modular.

Expected conceptual layers:

```text
Frontend
   |
REST API
   |
SQL Parser
   |
AST
   |
Planner
   |
Physical Plan
   |
Executor
   |
Relational Operators
   |
Indexes / Storage Managers
   |
Pages / Records
   |
Disk
```

Important rules:

- The frontend must not manipulate pages, records, B+ nodes or hash buckets directly.
- The API must delegate query execution to the DBMS engine.
- The parser must parse SQL, not execute it.
- The planner must select physical operators / access paths.
- The executor must execute the generated plan.
- Operators should depend on storage/index interfaces rather than UI code.
- Indexes should use stable record identifiers where appropriate.
- Storage structures must persist their state to disk when persistence is part of the implemented stage.
- Avoid circular dependencies between storage, indexes, parser and frontend.

---

## Fundamental abstractions

Prefer clear abstractions such as:

### RID
A stable physical record identifier.

Conceptually:

```text
RID(page_id, slot_id)
```

### Schema
Describes columns and their types.

### Record
Represents a row conforming to a schema.

### Page
Fixed-size unit used by storage files.

### Storage interface
Expected conceptual operations:

```text
insert(record)
read(rid)
delete(rid)
scan()
```

Concrete structures may extend this contract.

### Index interface
Expected conceptual operations:

```text
insert(key, rid)
search(key)
delete(key, rid)
```

B+ indexes should additionally support range access.

Do not force an abstraction if the repository already has an equivalent, tested design with different names.

---

## Development plan

Part 1 is implemented through the 10-stage roadmap defined in:

> `PLAN.md`

Latest formally completed stage:

> **Stage 8 Tasks 8.1–8.30 — Transactions and Concurrency**

Current implementation block:

> **Stage 9 — transaction-aware HTTP/UI integration implemented 2026-09-25; formal closure pending**

Stage 1 was formally closed on 2026-08-31 after its Definition of Done and full
test suite passed. Evidence is recorded in `docs/ETAPA_01_AUDIT.md`.
**Stage 2 was formally closed on 2026-08-31**, following the user's explicit
request for tasks 2.17–2.20 and the closure audit. All 47 Definition of Done
criteria are satisfied, with 1155 passing tests. Evidence and verification
limits are recorded in `docs/ETAPA_02_AUDIT.md`.
**Stage 3 was formally closed on 2026-09-02.** All 50 Definition of Done
criteria are satisfied, with 1284 passing tests. HeapFile and
PagedSequentialFile are persistent, independently tested, integration-tested
with the same logical dataset, and ready for later measurement. Evidence and
verification limits are recorded in `docs/ETAPA_03_AUDIT.md`.
**Stage 4 was formally closed on 2026-09-03.** Tasks 4.1–4.31 and all 59
Definition of Done criteria are satisfied, with 1544 tests passing under
warnings-as-errors. The shared persistent B+ core supports complete mutation,
validation, restart, page reuse, storage-driven rebuilds and both clustered and
unclustered adapters. Catalog integration, RID-change recovery and structural
instrumentation are included. Evidence and limits are recorded in
`docs/ETAPA_04_AUDIT.md`.
**Stage 5 was formally closed on 2026-09-06 and reviewed on 2026-09-10.**
Tasks 5.1–5.27 and all 47 Definition of Done criteria are accounted for under
the documented architectural policies, with 1772 tests passing under
warnings-as-errors after the four review blocks. The original closure ran 1621
tests. The persistent Extendible Hash implementation supports
deterministic routing, dynamic growth, exact deletion, independent validation,
restart, Heap construction/rebuild and maintenance, Catalog dispatch/drop and
real metrics. Optional buddy merge and directory shrink are explicitly deferred
as permitted by the stage guide. Evidence and limitations are recorded in
`docs/ETAPA_05_AUDIT.md`.
**Stage 6 was formally closed on 2026-09-11.** Tasks 6.1–6.31 and all 59
Definition of Done criteria are satisfied, with 2252 tests passing under
warnings-as-errors after integrating the reviewed Stage 5. `engine/operators/` provides the physical execution layer:
scans, filter, projection, `ExternalSort`, `ExternalHashGroup`,
`NestedLoopJoin`, `GraceHashJoin`, the optional index-assisted routes, and the
`PhysicalPlan` runner with truthful descriptors and measured reports. Evidence
and three declared caveats are recorded in `docs/ETAPA_06_AUDIT.md`. A [2026-09-13 transversal review](docs/ETAPA_06_REVALIDACION_2026_09_13.md)
revalidated all tasks and criteria after corrections; 2295 strict tests pass.
**The original Stage 7 baseline was formally closed on 2026-09-18.** Tasks
7.1-7.30 and all 63
Definition of Done criteria are satisfied. They establish the inspected
baseline, frozen SQL contract,
parser-independent AST/source spans, bounded handwritten lexer/parser,
controlled diagnostics, Catalog-backed semantic binding without writes, and
reusable SELECT plans with safe TableScan/B+/hash access paths and real Stage 6
`ExternalSort`, `ExternalHashGroup`, `GraceHashJoin`, `NestedLoopJoin`, and
eligible `IndexNestedLoopJoin` routes.
`SqlEngine`, reusable `PreparedQuery`, and streaming `QueryResult` own fresh
operator/context instances and distinguish complete, early-closed, and failed
executions. Task 7.26 reporting separates prepared descriptions from measured
Stage 6 evidence and identifies concrete storage and indexes. A shared
maintenance service executes INSERT
once, maintains or rebuilds every declared index, discovers DELETE targets into
a bounded disk spool before writing, and exposes synchronous command results.
Ordinary failures preserve confirmed DELETE prefixes, repair indexes from base
storage, and persist an incomplete marker when repair cannot finish. Public
acceptance, differential baselines, fresh restart, forced external paths,
cleanup, and injected failures are verified. The complete warnings-as-errors
suite passes 2,556 tests; evidence and limits are recorded in
`docs/ETAPA_07_AUDIT.md`. Tasks 7.31–7.40 closed the approved CREATE/EXPLAIN
extension on 2026-09-20. They implement its handwritten syntax, durable
manifest-backed CREATE, shared VARCHAR/primary-key enforcement, EXPLAIN,
EXPLAIN ANALYZE, public result contracts, and exact empty/populated/reopened
acceptance and failure coverage. Decisions and implementation evidence are recorded in
`docs/ETAPA_07_TASK_7_31_DECISIONS.md` and
`docs/ETAPA_07_TASK_7_32.md`, `docs/ETAPA_07_TASK_7_33_7_35.md`, and
`docs/ETAPA_07_TASK_7_36_7_38.md`; final closure evidence is in
`docs/ETAPA_07_EXTENSION_AUDIT.md`. The complete warnings-as-errors suite
passes 2,742 tests. **Stage 8 was formally closed on 2026-09-24.** Its detailed
plan is `ETAPA_08.md`; the Task 8.1 inspection, Task 8.2 adopted contract,
Tasks 8.3–8.6 and 8.7–8.10 foundations are recorded in
`docs/ETAPA_08_TASK_8_1_INSPECTION.md`, `docs/transactions.md`,
`docs/ETAPA_08_TASK_8_3_8_6.md`, `docs/ETAPA_08_TASK_8_7_8_10.md`,
`docs/ETAPA_08_TASK_8_11_8_14.md`,
`docs/ETAPA_08_TASK_8_15_8_18.md`,
`docs/ETAPA_08_TASK_8_19_8_22.md`, and `PROJECT_CONTEXT.md`. Control statements,
shared sessions, access intents, S/X locks, physical latches, bounded physical
undo, commit publication, all existing SQL families, telemetry, cancellation,
and finite shutdown use the owner lifecycle. Controlled schedules, failure
injection, and the real unsafe/protected/serial comparison are recorded in
`docs/ETAPA_08_TASK_8_23_8_26.md`. Seeded bounded stress, 91 transaction tests,
97 API compatibility tests, the clean demo, and the complete strict regression
pass; the closure result is **2,831 tests in 950.74 seconds**. Evidence, limits,
and all 37 satisfied criteria are in `docs/ETAPA_08_AUDIT.md`. The concrete
Stage 9 request/session handoff is `docs/ETAPA_08_STAGE_9_HANDOFF.md`. A buffer
pool, WAL, automatic crash recovery, cross-process locking, and crash-atomic
multi-file commit remain outside Stage 8.

**Stage 9 emergency demo ready (2026-09-18)** under the authorized sequencing
exception in `ETAPA_09.md`: `api/` (FastAPI) wraps `SqlEngine` behind one
exclusive admission guard, a server-enforced SELECT-only default, and bounded
row/byte previews; `frontend/` (React, TypeScript, Vite) shows the four
required panels from real engine descriptors. Run it with
`python scripts/setup_demo.py` and then `python -m api`, as documented in
`docs/demo.md`. On 2026-09-25 the Stage 9 handoff was implemented and
verified across real concurrent HTTP requests: each client session maps an
opaque token to a Stage 8 `SqlSession`, BEGIN/END/ROLLBACK group separate
requests, and session requests wait only in the engine lock manager. The old
admission guard now serializes only sessionless calls on the shared default
session; do not widen it again. Evidence is in
`docs/ETAPA_09_REVISION_2026_09_25.md`. The SQL parser is handwritten by team decision; do not introduce
Lark or another parser generator.

Latest completed stage specification:

> `ETAPA_08.md`

Stage 1 includes, at the planning level:

- repository/module structure;
- `DataType`;
- `Column`;
- `Schema`;
- `Record`;
- `RID`;
- `TableMetadata`;
- minimal `IndexMetadata`;
- `Catalog`;
- storage contract;
- index contract;
- operator contract;
- base domain errors;
- Stage 1 unit/integration tests.

Do not implement later-stage work merely to make the project appear more complete.

Do not skip stages unless explicitly instructed.

Before moving to the next stage:

- the current-stage functionality must exist;
- relevant tests must pass;
- integration with previous stages must work;
- the current `ETAPA_XX.md` Definition of Done must be satisfied;
- stable decisions discovered during the stage must be reflected in `PROJECT_CONTEXT.md`.

For the complete descriptions of Stages 2–10, use `PLAN.md`.

---

## Change policy

When implementing a requested feature:

1. Inspect the existing code first.
2. Reuse existing abstractions when they are compatible.
3. Prefer a small coherent change over a repository-wide rewrite.
4. Preserve backward compatibility with already passing project tests.
5. Add or update tests for new behavior.
6. Run relevant tests after changes.
7. Report any failing tests that are unrelated to the requested change.
8. Do not delete working code unless replacement is necessary and justified.

For architectural refactors:
- state the reason;
- identify affected modules;
- preserve observable behavior;
- update tests and documentation.

---

## Testing policy

Every stage must include functional tests.

At minimum, cover:

### Storage
- insert;
- read;
- delete;
- scan;
- multi-page behavior;
- persistence after close/reopen where applicable;
- free-space reuse.

### Paged Sequential File
- insertion from unsorted input;
- physical/logical ordering by configured key;
- lazy deletion;
- wasted-space threshold;
- reorganization.

### B+
- equality lookup;
- range lookup;
- leaf split;
- internal split;
- root split;
- deletion;
- merge/redistribution cases implemented by the tree.

### Extendible Hashing
- equality lookup;
- collisions;
- bucket split;
- local depth;
- global depth;
- directory doubling.

### SQL
- `SELECT`;
- `WHERE`;
- `INSERT`;
- `DELETE`;
- `ORDER BY`;
- `GROUP BY`;
- supported joins.

### Concurrency
- multiple readers;
- competing writers;
- race-condition reproduction without protection when used as demonstration;
- correct result with concurrency control.

Do not consider a stage complete if its core tests fail.

---

## Benchmark policy

Benchmarks are part of the assignment, not decorative extras.

Keep benchmark code separate from core engine code.

Use reproducible datasets and record:
- dataset size;
- operation;
- structure/algorithm;
- elapsed time;
- disk space where required;
- relevant run configuration.

Do not fabricate benchmark values.

The required Part 1 dataset sizes are:
- 1,000 records;
- 10,000 records;
- 100,000 records.

---

## Execution-plan policy

The Execution Plan shown to the frontend should reflect the actual operators/access paths used.

Do not display a fake plan that is disconnected from the executor.

Examples of meaningful plan nodes:

```text
TableScan
IndexScan
Filter
Projection
ExternalSort
HashGroup
HashJoin
IndexNestedLoopJoin
```

The exact names can differ, but the plan should describe real execution decisions.

---

## Documentation policy

When an architectural decision becomes stable, update `PROJECT_CONTEXT.md`.

When an official assignment requirement is clarified by the instructor, update `REQUIREMENTS.md`.

Do not put temporary debugging notes into either source-of-truth file.

---

## Definition of "safe to continue"

Before moving to a later stage:

- required functionality from the current stage exists;
- relevant tests pass;
- the code is integrated with prior stages;
- no official requirement has been removed;
- persistence assumptions are explicit when persistence applies;
- documentation reflects important architectural decisions;
- the current `ETAPA_XX.md` Definition of Done is satisfied.

If any item is not satisfied, remain in the current stage unless the user explicitly changes the implementation plan.
