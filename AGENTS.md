# AGENTS.md

> Context version: **2.0** — aligned with `PLAN.md` and the formally completed `ETAPA_03.md`.

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
- Lark for grammar parsing;
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
- Lark

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

Latest completed stage:

> **Stage 3 — Heap File and Paged Sequential File**

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
**Stage 4 has not started.** Remain at the completed Stage 3 boundary until the
user explicitly requests advancing; closure alone does not authorize B+ Tree
work. No B+ nodes, clustered/unclustered indexes, buffer pool, WAL or
concurrency were added.

Latest completed detailed stage specification:

> `ETAPA_03.md`

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
