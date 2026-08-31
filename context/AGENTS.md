# AGENTS.md

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
3. Inspect the existing repository structure and current implementation.
4. Identify the current development stage.
5. Identify which existing tests cover the affected behavior.
6. Explain briefly what will be changed before making a broad or architectural modification.

If repository behavior conflicts with the official requirements, preserve the requirements and report the conflict.

---

## Source-of-truth rules

Use the following precedence:

### For what the project must implement

1. `REQUIREMENTS.md`
2. Original assignment document (`Proyecto_Final.pdf`)
3. `PROJECT_CONTEXT.md`
4. Existing code
5. Assumptions

### For architectural decisions already made by the team

1. `PROJECT_CONTEXT.md`
2. Existing tests
3. Existing code
4. New assumptions

### For how Codex should work in the repository

1. `AGENTS.md`

Never silently invent a missing academic requirement.

If a requirement is ambiguous:
- preserve the simplest implementation compatible with the assignment;
- state the ambiguity;
- avoid adding unrelated functionality.

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

Part 1 is organized into 10 implementation stages.

### Stage 1 — Architecture and data model
- repository/module structure;
- schema representation;
- supported basic data types;
- records;
- RID;
- catalog/table metadata;
- abstract storage/index/operator contracts.

### Stage 2 — Pages, records and base persistence
- page structure;
- page header;
- slot metadata where required;
- serialization/deserialization;
- page read/write;
- file metadata;
- persistence tests.

### Stage 3 — File organizations
- Heap File;
- free-space reuse;
- Paged Sequential File;
- ordered insertion;
- lazy deletion;
- wasted-space accounting;
- reorganization strategy.

### Stage 4 — B+ Tree
- generic B+ structure;
- equality search;
- range search;
- insertion;
- splits;
- deletion;
- redistribution/merge when required;
- clustered behavior;
- unclustered behavior.

### Stage 5 — Extendible Hashing
- directory;
- global depth;
- local depth;
- buckets;
- equality lookup;
- bucket split;
- directory doubling;
- insert/delete behavior.

### Stage 6 — Relational operators and external algorithms
- table scan;
- index scan;
- filter;
- projection;
- external sort using k-way merge;
- `GROUP BY`;
- `JOIN`;
- external hashing and/or index-based optimization as appropriate.

### Stage 7 — SQL engine
- SQL grammar;
- AST;
- planner;
- executor;
- supported SQL subset from `REQUIREMENTS.md`;
- execution-plan representation.

### Stage 8 — Transactions and concurrency
- transaction lifecycle;
- `BEGIN TRANSACTION`;
- `END TRANSACTION`;
- lock/concurrency mechanism;
- safe concurrent access;
- thread-based race-condition demonstration.

### Stage 9 — API and frontend
- API wrapper around the engine;
- Files panel;
- SQL editor;
- Results panel;
- Execution Plan panel.

### Stage 10 — Experiments, integration and delivery
- required dataset sizes;
- storage comparisons;
- index comparisons;
- plots/tables;
- conclusions;
- integration tests;
- technical documentation.

Do not skip stages merely to make a demo appear complete.

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
- persistence assumptions are explicit;
- documentation reflects important architectural decisions.
