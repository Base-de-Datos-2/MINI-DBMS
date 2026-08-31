# PROJECT_CONTEXT.md

## Project identity

**Project:** Minigestor de Base de Datos Multimodal  
**Course:** Base de Datos 2  
**Academic term:** 2026-2

The project consists of building a small multimodal database-management system progressively.

The current implementation focus is:

> **Part 1 — Relational Database (Tables and SQL)**

The project must remain modular because later parts build on structures created earlier.

---

## Main architectural objective

The system should expose, as clearly as possible, how a SQL query becomes physical operations over storage.

Conceptual flow:

```text
SQL
 |
 v
Parser
 |
 v
AST
 |
 v
Planner
 |
 v
Physical Execution Plan
 |
 v
Executor
 |
 v
Relational Operators
 |
 +-------------------+
 |                   |
 v                   v
Indexes            Storage
 |                   |
 +---------+---------+
           |
           v
          Pages
           |
           v
           Disk
```

The project is not intended to be a thin wrapper around PostgreSQL, SQLite or another complete DBMS.

---

## Current development scope

The current goal is to complete Part 1 before expanding the engine with spatial, text or multimedia capabilities.

Part 1 must provide:

- storage in disk pages;
- Heap File;
- Paged Sequential File;
- clustered B+ index;
- unclustered B+ index;
- Extendible Hashing;
- external sorting;
- grouping and join strategies;
- a limited SQL parser;
- planning/execution;
- transactions and concurrency control;
- a frontend with execution-plan visualization;
- experimental comparisons.

---

## Current recommended stack

These are project decisions, not official assignment requirements.

### Engine
Python 3

### Parser
Lark

### HTTP API
FastAPI

### Frontend
React + TypeScript + Vite

### SQL editor
Monaco Editor is recommended but optional.

### Tests
pytest

### Benchmarks / plots
`time.perf_counter` + matplotlib

If the repository already contains a working alternative stack that satisfies the assignment, preserve it unless there is a clear reason to migrate.

---

## Proposed repository organization

```text
mini-dbms/
|
├── AGENTS.md
├── PROJECT_CONTEXT.md
├── REQUIREMENTS.md
├── README.md
|
├── engine/
│   ├── storage/
│   ├── indexes/
│   ├── operators/
│   ├── query/
│   ├── transactions/
│   └── catalog/
|
├── api/
├── frontend/
├── tests/
├── benchmarks/
├── data/
└── docs/
```

This is a target organization, not an instruction to rewrite an existing repository that already has a coherent structure.

---

## Layer responsibilities

### `engine/storage`

Owns physical storage concepts such as:
- pages;
- page headers;
- records;
- serialization;
- file headers;
- page I/O;
- Heap File;
- Paged Sequential File;
- free-space tracking.

### `engine/indexes`

Owns:
- generic B+ implementation;
- clustered B+ behavior;
- unclustered B+ behavior;
- Extendible Hashing.

### `engine/operators`

Owns physical relational operators such as:
- Table Scan;
- Index Scan;
- Filter;
- Projection;
- Sort;
- Group;
- Join.

### `engine/query`

Owns:
- SQL grammar;
- parser;
- AST;
- planner;
- execution-plan representation;
- executor coordination.

### `engine/transactions`

Owns:
- transaction state;
- lock management;
- concurrency control.

### `engine/catalog`

Owns metadata such as:
- tables;
- schemas;
- columns;
- indexes;
- table storage organization.

### `api`

Exposes engine functionality through HTTP.

### `frontend`

Provides the required graphical interface.

### `benchmarks`

Contains reproducible experimental scripts. Benchmark logic should not contaminate core engine logic.

---

## Fundamental data concepts

### RID

A record should have a stable location reference when required by an access structure.

Current conceptual design:

```text
RID(page_id, slot_id)
```

This is especially useful for unclustered indexes.

If the existing implementation already has an equivalent physical identifier, preserve it.

---

## Schema

A table schema should describe:
- column name;
- type;
- order;
- optional constraints needed by the supported SQL subset.

Start with a small set of types sufficient for the project.

Recommended initial types:

```text
INTEGER
FLOAT
BOOLEAN
VARCHAR
```

Do not expand the type system until required.

---

## Record

A Record represents one relational row according to a Schema.

The Record abstraction should remain independent from React, FastAPI and parser-specific objects.

---

## Page

A Page is the fundamental fixed-size storage unit.

Important note:

> The assignment requires page-based storage but does not prescribe a page size in the project statement.

Therefore the page size must be a configurable or explicitly documented project decision.

Do not hard-code a size because an earlier discussion suggested one unless the implementation has formally adopted it.

---

## Storage abstractions

A general storage manager should conceptually support operations such as:

```text
insert(record)
read(rid)
delete(rid)
scan()
```

Concrete organizations may expose additional operations.

---

## Heap File model

Required behavior:

- records are stored in arrival order;
- records are distributed across disk pages;
- free space must be reused;
- a full scan must be possible;
- records should be addressable using the project's chosen physical identifier.

A Heap File must not be implemented by inserting rows into SQLite/PostgreSQL.

---

## Paged Sequential File model

Required behavior:

- records remain ordered by a chosen key;
- insertion preserves the ordering;
- deletion is lazy;
- wasted space must be measurable;
- a reorganization mechanism must exist.

The assignment gives **more than 30% wasted space** as an example trigger for reorganization.

The implementation may use that threshold as the default unless the team explicitly documents another valid strategy.

The file organization must remain page-based.

---

## B+ index model

One reusable B+ implementation is preferred over two unrelated trees.

Core B+ behavior should support:
- equality lookup;
- range lookup;
- insertion;
- splitting;
- deletion;
- the balancing operations required by the chosen deletion algorithm;
- linked leaves where useful for range traversal.

### Unclustered B+

Conceptually:

```text
key -> RID
```

The physical row order is independent from index order.

### Clustered B+

The physical organization of records must reflect the index key ordering sufficiently to behave as a clustered organization.

Do not label an ordinary unclustered index as "clustered" only in metadata.

The exact physical design should be documented once implemented.

---

## Extendible Hashing model

The required dynamic-hashing strategy is Extendible Hashing.

Expected concepts:
- directory;
- global depth;
- buckets;
- local depth;
- equality search;
- bucket split;
- directory expansion when necessary.

This structure is intended primarily for equality access.

It is not a replacement for B+ range access.

---

## Relational operators

The engine should expose physical operators independent from SQL syntax.

Recommended operator set:

```text
TableScan
IndexScan
Filter
Projection
ExternalSort
Group
Join
```

This keeps parsing separate from execution.

---

## External sorting

`ORDER BY` must be supported using External Sorting with k-way merge.

Conceptual algorithm:

1. Read chunks that fit in the allowed in-memory working area.
2. Sort each chunk.
3. Persist sorted runs.
4. Merge the runs using a k-way merge.

The implementation should not simply call an in-memory sort on the entire required dataset and call it external sorting.

Using Python's `heapq` inside the merge is acceptable because it does not replace the external-sort algorithm.

---

## GROUP BY

The assignment requires optimized `GROUP BY` using External Hashing and/or strategic index usage.

A valid design may begin with in-memory hash aggregation and extend to partitioned/external hashing when data exceeds the configured memory budget.

The final implementation must be able to justify how the required external/index strategy is satisfied.

---

## JOIN

The assignment requires optimized joins using External Hashing and/or strategic index usage.

Recommended implementations:

- Nested Loop Join as a baseline;
- Hash Join;
- index-assisted join when an appropriate index exists.

At least one required optimization path must clearly satisfy the assignment.

---

## SQL subset

The SQL parser only needs to support the subset required by the project.

Required families:

```sql
SELECT ...
FROM ...
WHERE ...

SELECT ...
FROM ...
ORDER BY ...

SELECT ...
FROM ...
GROUP BY ...

INSERT INTO ...
VALUES (...)

DELETE FROM ...
WHERE ...
```

The project does not require a complete SQL standard implementation.

Do not add advanced SQL syntax at the cost of required features.

---

## Query planning

The planner should choose an access path based on available structures.

Examples:

```text
Equality predicate on indexed key
    -> Hash lookup or B+ lookup

Range predicate
    -> B+ range scan when available

No useful index
    -> Table scan
```

The planner can begin simple and rule-based.

A cost-based optimizer is not an explicit Part 1 requirement.

---

## Execution plans

The physical execution plan should be an actual representation of what the executor runs.

Example:

```text
Projection(name)
  |
IndexScan(table=students, index=idx_students_id, condition=id=100)
```

The frontend's execution-plan panel should visualize this real plan.

---

## Transactions and concurrency

The project requires transaction grouping and concurrency control.

Current recommended strategy:

- a Transaction Manager;
- a Lock Manager;
- shared locks for compatible reads;
- exclusive locks for writes;
- a simple locking protocol sufficient to demonstrate safe concurrent execution.

A simplified strict two-phase-locking design is acceptable as a project decision if implemented consistently.

Do not implement MVCC unless explicitly chosen later.

---

## Required thread demonstration

The project must include a simulation where multiple transactions execute concurrently.

The demonstration should show:

1. concurrent transactions;
2. a race condition / conflicting access;
3. how the concurrency-control mechanism prevents or resolves the incorrect result.

This demonstration should be reproducible.

---

## Frontend

The graphical interface requires four primary panels:

### Files panel
Shows loaded tables and their structure.

### Query panel
Allows the user to write SQL.

### Results panel
Shows result rows in tabular form.

### Execution Plan panel
Shows how the query was executed, including relevant indexes and operation order.

The frontend should consume the engine through a clean API rather than importing storage internals.

---

## API

FastAPI is the current recommended transport layer.

Potential conceptual endpoints:

```text
GET  /tables
GET  /tables/{table_name}
POST /query
```

The exact API may evolve.

The DBMS engine must be callable independently from the web layer.

---

## Metrics and instrumentation

Because the project requires experiments, core execution should expose enough information to measure behavior.

Useful metrics may include:

```text
elapsed_ms
pages_read
pages_written
records_scanned
index_name
operator_name
```

Only metrics that are actually measured should be reported.

Do not fabricate instrumentation values.

---

## Experimental datasets

Part 1 requires comparisons using:

```text
1,000 records
10,000 records
100,000 records
```

Use the same logical datasets across compared techniques whenever possible.

Dataset generation should be reproducible.

---

## Part 1 experimental comparisons

### File organization comparison

Compare:
- Heap File;
- Paged Sequential File.

Measure:
- insertion time;
- primary-key search time;
- disk space used;
- reorganization time.

### Index comparison

Compare:
- clustered B+;
- unclustered B+;
- Extendible Hashing.

Evaluate:
- exact equality search;
- range search;
- sorting.

Measure:
- index construction time;
- query time;
- extra disk space;
- behavior under frequent insertions/deletions.

The report must include comparative charts, a summary table and conclusions about when each technique is preferable.

---

## 10-stage implementation roadmap

### 1. Architecture and data model
Foundation classes/interfaces only.

### 2. Pages, records and persistence
Reliable disk/page layer.

### 3. Heap + Paged Sequential
Both required file organizations.

### 4. B+
Generic B+ plus clustered/unclustered use.

### 5. Extendible Hashing
Dynamic hash index.

### 6. Operators and external algorithms
Physical relational execution.

### 7. SQL engine
Parser, AST, planner and executor.

### 8. Transactions and concurrency
Safe concurrent execution.

### 9. API and frontend
Required user interface.

### 10. Experiments and integration
Benchmarks, graphs, conclusions and delivery cleanup.

---

## Current stage

Initial repository context version:

> **Stage 1 — Architecture and data model**

If the repository already contains code from later stages, do not delete it. First inspect and determine the actual implementation status.

---

## Important unresolved design decisions

The following should not be guessed silently:

- final page size;
- exact binary page layout;
- exact variable-length-record strategy;
- exact clustered B+ physical layout;
- supported comparison operators in `WHERE`;
- aggregation functions beyond those required by tests/use cases;
- exact transaction syntax details beyond the assignment's `BEGIN TRANSACTION` / `END TRANSACTION`;
- deadlock handling strategy;
- memory budget used by external algorithms.

When one of these decisions is made, document it here.

---

## Project philosophy

Prefer:
- simple;
- testable;
- educational;
- modular;
- observable implementations.

Avoid:
- unnecessary frameworks;
- hidden magic;
- premature optimization;
- building features from future parts before Part 1 is stable.

The engine should make database-internals concepts visible rather than obscure them.
