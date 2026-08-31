# PLAN.md

> Context version: **1.1** — aligned with `AGENTS.md`, `PROJECT_CONTEXT.md`, `REQUIREMENTS.md`, and `ETAPA_01.md`.

## Part 1 Implementation Plan — Relational Database

**Project:** Multimodal Mini-DBMS  
**Course:** Base de Datos 2 — 2026-2  
**Scope:** Part 1 — Relational Database (Tables and SQL)

---

# 1. Purpose of this document

This document defines the implementation roadmap for **Part 1**.

It answers:

> **In what order should Part 1 be implemented?**

It must be read together with the other coordination documents:

- `REQUIREMENTS.md` — official academic requirements;
- `PROJECT_CONTEXT.md` — stable architectural and technical decisions;
- `AGENTS.md` — operating instructions for Codex;
- `ETAPA_XX.md` — detailed plan for the current implementation stage.

This file does **not** replace `REQUIREMENTS.md`.

If this plan conflicts with an official requirement, `REQUIREMENTS.md` takes precedence and the conflict must be reported before implementation continues.

---

# 2. Relationship with the other project documents

The coordination model is:

```text
REQUIREMENTS.md
    |
    |  WHAT must be implemented
    v
PROJECT_CONTEXT.md
    |
    |  HOW the system is currently designed
    v
PLAN.md
    |
    |  IN WHAT ORDER Part 1 is implemented
    v
ETAPA_XX.md
    |
    |  WHAT TO DO NOW
    v
CODE
```

`AGENTS.md` governs how Codex should work with all of these documents.

Stable architectural decisions discovered during implementation should be promoted to `PROJECT_CONTEXT.md`.

Detailed stage instructions belong in `ETAPA_XX.md`, not in this roadmap.

---

# 3. Overall objective of Part 1

At the end of Part 1, the system should support a complete flow similar to:

```text
User
 |
 v
Frontend
 |
 v
REST API
 |
 v
SQL Parser
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
 +----------------------+
 |                      |
 v                      v
Indexes              Storage Files
 |                      |
 +----------+-----------+
            |
            v
           Pages
            |
            v
           Disk
```

At minimum, the implementation must be capable of supporting the required SQL families, for example:

```sql
INSERT INTO students VALUES (...);

SELECT *
FROM students
WHERE id = 100;

SELECT *
FROM students
ORDER BY age;

SELECT career, COUNT(*)
FROM students
GROUP BY career;

DELETE FROM students
WHERE id = 100;
```

The exact supported syntax is defined by `REQUIREMENTS.md` and later Stage 7 decisions.

---

# 4. Core implementation principles

## 4.1 Build from lower layers upward

Preferred dependency direction:

```text
Disk
↑
Pages
↑
Storage Files
↑
Indexes
↑
Relational Operators
↑
Planner / Executor
↑
SQL
↑
API
↑
Frontend
```

Therefore:

- do not start by building the frontend;
- do not build the SQL engine before physical operators exist;
- do not build indexes before the storage layer is stable;
- do not let higher layers manipulate lower-level internals directly.

---

## 4.2 Preserve modularity

Later parts of the academic project build on Part 1.

Part 1 should therefore expose clear abstractions rather than a single tightly coupled program.

Important layer boundaries are defined in `PROJECT_CONTEXT.md`.

---

## 4.3 Required algorithms must remain visible

Do not replace academic algorithms with an external DBMS or high-level execution library.

Examples of forbidden substitutions are defined in `AGENTS.md`.

Auxiliary libraries are acceptable when they do not replace the algorithm being studied.

---

## 4.4 Each stage must leave reusable artifacts

A stage is useful only if the next stage can build on it.

Example:

```text
Stage 2
Page / Serialization / PageManager
        |
        v
Stage 3
HeapFile / PagedSequentialFile
        |
        +------------------+
        |                  |
        v                  v
Stage 4                  Stage 5
B+                       Extendible Hashing
        \                  /
         \                /
          v              v
             Stage 6
             Operators
```

---

## 4.5 Tests are part of implementation

For every stage, use the testing rules in `AGENTS.md`.

A stage should generally include:

1. unit tests;
2. functional tests;
3. persistence tests when persistence applies;
4. integration tests with previous stages.

A stage is not complete simply because the happy path runs once.

---

# 5. The 10-stage roadmap

| Stage | Name | Primary outcome |
|---|---|---|
| 1 | Architecture and Data Model | Stable foundational abstractions |
| 2 | Pages, Records, and Base Persistence | Reliable physical storage layer |
| 3 | Heap File and Paged Sequential File | Required file organizations |
| 4 | B+ Tree | Clustered and unclustered B+ access |
| 5 | Extendible Hashing | Dynamic hash index |
| 6 | Relational Operators and External Algorithms | Physical query execution |
| 7 | SQL Parser, Planner, and Executor | Required SQL execution |
| 8 | Transactions and Concurrency | Safe concurrent execution |
| 9 | API and Frontend | Required user interface |
| 10 | Experiments, Integration, and Delivery | Comparative evidence and final integration |

Stages should normally be completed in this order.

Stages 4 and 5 may be developed in parallel once Stage 3 is stable and the shared interfaces are mature enough.

---

# 6. Stage 1 — Architecture and Data Model

Detailed specification:

> `ETAPA_01.md`

## Objective

Define the foundational abstractions before implementing physical persistence.

## Main outputs

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
- Stage 1 unit and integration tests.

## Dependencies

None.

## Explicitly out of scope

- binary pages;
- real `PageManager`;
- Heap File;
- Paged Sequential File;
- B+ implementation;
- Extendible Hashing implementation;
- SQL parser;
- planner;
- executor;
- transactions;
- API;
- frontend;
- benchmarks.

## Completion rule

Stage 1 is complete only when the Definition of Done in `ETAPA_01.md` is satisfied.

---

# 7. Stage 2 — Pages, Records, and Base Persistence

## Objective

Build the physical layer that can serialize data, write pages, close the process, reopen the file, and recover the same information correctly.

---

## 7.1 Decisions that must become explicit

Before or during this stage, resolve and document:

- final page size;
- binary page layout;
- `PageHeader` format;
- slot-directory format where applicable;
- variable-length-record strategy;
- `FileHeader` format;
- binary encoding / endianness;
- `NULL` representation if supported;
- catalog persistence strategy if needed at this stage.

Once stable, these decisions belong in `PROJECT_CONTEXT.md`.

---

## 7.2 Expected components

Conceptual example:

```text
engine/storage/
├── page.py
├── page_header.py
├── serializer.py
├── file_header.py
└── page_manager.py
```

Exact filenames may differ if the repository already has a coherent structure.

---

## 7.3 Minimum capabilities

### Page

Conceptually:

```text
insert serialized record
read slot
mark/remove slot
report free space
serialize page
deserialize page
```

### Page manager

Conceptually:

```text
allocate_page()
read_page(page_id)
write_page(page)
flush()
close()
```

---

## 7.4 Minimum tests

- create a page;
- insert a record;
- serialize it;
- write it to disk;
- close the file;
- reopen it;
- recover the same record;
- manage multiple pages;
- reject invalid access cleanly.

---

## Definition of Done

- persistence works;
- page I/O is encapsulated;
- storage can reopen persisted data;
- tests pass;
- no Heap File logic is required to make the page layer work.

---

# 8. Stage 3 — Heap File and Paged Sequential File

This stage implements the two required file organizations.

---

## 8A. Heap File

### Objective

Store records in arrival order across disk pages while reusing available free space.

### Minimum operations

```text
insert(record) -> RID
read(rid) -> Record
delete(rid)
scan() -> iterator
```

### Required behavior

Free space must actually be reused.

Possible implementations include:

- free list;
- free-page directory;
- simplified free-space map.

The exact strategy is an architectural decision.

### Minimum tests

- one-page insertion;
- multi-page insertion;
- deletion;
- reinsertion into reusable space;
- read by RID;
- full scan;
- persistence after reopen.

---

## 8B. Paged Sequential File

### Objective

Maintain records ordered by a chosen key.

### Minimum operations

```text
insert(record)
search(key)
delete(key or rid)
scan()
reorganize()
```

### Required behavior

- ordered insertion;
- lazy deletion;
- measurable wasted space;
- reorganization strategy.

The assignment presents more than 30% wasted space as an example trigger. If the project adopts 30% as its default, that decision should be recorded in `PROJECT_CONTEXT.md`.

### Minimum tests

- insert unsorted input;
- verify final order;
- insert a key between existing keys;
- lazy deletion;
- wasted-space calculation;
- trigger reorganization;
- verify ordering after reorganization.

---

## Definition of Done

Both organizations:

- use the Stage 2 page layer;
- persist data correctly;
- have independent tests;
- expose behavior that can later be benchmarked fairly.

---

# 9. Stage 4 — B+ Tree

## Objective

Implement the required B+ structure and support both unclustered and clustered behavior.

---

## 9.1 Generic B+ core

Minimum conceptual operations:

```text
insert(key, value)
search(key)
range_search(low, high)
delete(key, value?)
```

Expected structural behavior:

- leaf split;
- internal split;
- root split;
- linked leaves for range traversal;
- redistribution and/or merge according to the chosen deletion algorithm;
- root shrink when applicable.

---

## 9.2 Unclustered B+

Conceptually:

```text
key -> RID
```

Physical row order remains independent from index order.

---

## 9.3 Clustered B+

The physical record organization must meaningfully reflect the clustered key order.

Do not implement an ordinary unclustered index and label it `clustered=True`.

The final physical design must be recorded in `PROJECT_CONTEXT.md`.

---

## 9.4 Minimum tests

- insertion without split;
- leaf split;
- internal split;
- root split;
- exact lookup;
- range lookup;
- deletion;
- redistribution;
- merge;
- leaf traversal;
- duplicate-key behavior if duplicates are supported.

---

## Definition of Done

- generic B+ behavior is stable;
- unclustered access works;
- clustered behavior is physically meaningful;
- range queries work;
- persistence behavior is defined consistently with the architecture.

---

# 10. Stage 5 — Extendible Hashing

## Objective

Implement the required dynamic hash index using Extendible Hashing.

## Core concepts

```text
Directory
Global Depth
Bucket
Local Depth
```

## Minimum operations

```text
insert(key, rid)
search(key)
delete(key, rid)
```

## Required behavior

- deterministic hash strategy suitable for persistence;
- directory lookup using relevant hash bits;
- bucket split;
- local-depth update;
- directory doubling when needed;
- correct directory-pointer updates.

Directory shrinking is optional unless later required by the adopted design.

## Minimum tests

- exact lookup;
- collisions;
- full bucket;
- split;
- directory doubling;
- shared bucket references;
- deletion;
- persistence if the index is persisted at this stage.

## Definition of Done

The implementation clearly supports equality access and does not pretend to provide ordered range behavior.

---

# 11. Stage 6 — Relational Operators and External Algorithms

## Objective

Build physical query execution before connecting the SQL parser.

---

## 11.1 Operator contract

Recommended conceptual interface:

```text
open()
next()
close()
```

or an equivalent Python iterator model.

SQL syntax must not be embedded into physical operator implementations.

---

## 11.2 Minimum operator set

```text
TableScan
IndexScan
Filter
Projection
ExternalSort
Group
Join
```

---

## 11.3 TableScan

Must iterate active records from a table.

Minimum tests:

- empty table;
- one page;
- multiple pages;
- deleted records.

---

## 11.4 IndexScan

Must retrieve records through B+ or Extendible Hashing when appropriate.

Minimum tests:

- equality lookup;
- B+ range lookup;
- invalid RID handling;
- empty index.

---

## 11.5 Filter

Must evaluate conditions supported by the future SQL subset.

Expression evaluation should remain separate from storage.

---

## 11.6 Projection

Returns selected columns from incoming rows.

---

## 11.7 External Sort

`ORDER BY` must ultimately use External Sorting with k-way merge.

Conceptual phases:

```text
Input
 |
 v
Memory-sized chunks
 |
 v
Sort each chunk
 |
 v
Sorted runs on disk
```

then:

```text
run1 --\
run2 ---\
run3 ----> k-way merge -> output
runN ---/
```

A configurable memory budget or equivalent mechanism should force multi-run behavior during tests.

---

## 11.8 GROUP BY

Must use a strategy satisfying `REQUIREMENTS.md`, based on:

- External Hashing;
- strategic index use;
- or a documented combination.

Do not delegate the required behavior to pandas.

---

## 11.9 JOIN

Recommended progression:

1. Nested Loop Join as a baseline;
2. Hash Join;
3. index-assisted join when appropriate.

At least one optimized strategy must clearly satisfy the official requirement.

---

## Definition of Done

A physical plan can be assembled and executed manually without SQL, for example:

```text
Projection(name)
  |
Filter(age > 20)
  |
TableScan(students)
```

---

# 12. Stage 7 — SQL Parser, Planner, and Executor

## Objective

Transform required SQL statements into the Stage 6 physical operators.

---

## 12.1 Grammar

Support only the SQL subset required by `REQUIREMENTS.md`.

Do not prioritize advanced SQL features over required functionality.

---

## 12.2 AST

Build semantic nodes independent from the parser library.

Conceptual example:

```text
SelectStatement
├── columns
├── table
├── where
├── order_by
└── group_by
```

---

## 12.3 Planner

The initial planner may be rule-based.

Examples:

```text
Equality predicate + useful hash index
    -> Hash IndexScan

Range predicate + useful B+
    -> B+ RangeScan

No useful index
    -> TableScan + Filter
```

A cost-based optimizer is not required unless the project later adopts one.

---

## 12.4 Executor

The executor must execute the actual physical plan.

The plan shown to the frontend must reflect the operators really used.

---

## Minimum SQL tests

Required families include:

```sql
INSERT INTO ...
VALUES (...);
```

```sql
SELECT *
FROM ...;
```

```sql
SELECT *
FROM ...
WHERE ...;
```

```sql
SELECT ...
FROM ...
ORDER BY ...;
```

```sql
SELECT ...
FROM ...
GROUP BY ...;
```

```sql
DELETE FROM ...
WHERE ...;
```

JOIN syntax/coverage must be sufficient to demonstrate the required join implementation.

---

## Definition of Done

- parser produces an AST;
- planner produces a physical plan;
- executor returns correct results;
- indexes can be chosen when appropriate;
- the reported execution plan matches actual execution.

---

# 13. Stage 8 — Transactions and Concurrency

## Objective

Provide safe concurrent access and the mandatory thread-based demonstration.

---

## 13.1 Transaction Manager

Conceptually:

```text
Transaction
├── id
├── state
└── held locks / metadata
```

Possible states:

```text
ACTIVE
COMMITTED
ABORTED
```

Exact semantics are architectural decisions.

---

## 13.2 Lock Manager

Current recommended direction in `PROJECT_CONTEXT.md`:

```text
Shared Lock (S)
Exclusive Lock (X)
```

Compatibility:

| | S | X |
|---|---:|---:|
| S | yes | no |
| X | no | no |

A simplified Strict 2PL design is acceptable if formally adopted and documented.

---

## 13.3 Required transaction syntax

```text
BEGIN TRANSACTION
END TRANSACTION
```

The exact lifecycle semantics must be documented before implementation is considered stable.

---

## 13.4 Mandatory concurrency demonstration

Show both:

### Unsafe execution

```text
T1 and T2
read/modify the same data
without protection
-> incorrect result
```

### Protected execution

```text
T1 acquires lock
T2 waits
T1 completes
T2 continues
-> correct result
```

---

## Minimum tests

- multiple readers;
- reader vs writer;
- multiple writers;
- lock release;
- complete transaction lifecycle;
- reproducible race-condition demonstration;
- protected correct execution.

---

## Definition of Done

The race condition and its correction can be demonstrated repeatedly and explained through the implemented concurrency mechanism.

---

# 14. Stage 9 — API and Frontend

## Objective

Expose the engine through the required GUI without violating architectural boundaries.

---

## 14.1 API

The API wraps the DBMS engine.

It must not reimplement storage, indexing, planning, or execution.

Conceptual endpoints may include:

```text
GET  /tables
GET  /tables/{name}
POST /query
```

A query response may include:

```json
{
  "columns": [],
  "rows": [],
  "execution_plan": {},
  "metrics": {}
}
```

The exact contract should be decided when Stage 9 is implemented.

---

## 14.2 Frontend

Current recommended stack:

```text
React
TypeScript
Vite
```

This is a project decision, not an official requirement.

---

## Required panel 1 — Files

Show:

- loaded tables;
- columns;
- types;
- useful table structure metadata.

---

## Required panel 2 — Query

Provide:

- SQL editor;
- execution action;
- useful error feedback.

---

## Required panel 3 — Results

Show query output in tabular form.

---

## Required panel 4 — Execution Plan

Show:

- operators;
- operation order;
- indexes used;
- relevant physical access information.

Do not generate a decorative plan disconnected from the executor.

---

## Definition of Done

A user can execute a query from the GUI and observe:

```text
query
result
actual execution plan
```

---

# 15. Stage 10 — Experiments, Integration, and Delivery

## Objective

Produce the required comparative evidence and prove that all Part 1 layers work together.

---

## 15.1 Reproducible datasets

Required sizes:

```text
1,000
10,000
100,000
```

Use reproducible generation whenever randomness is involved.

---

## 15.2 File-organization comparison

Compare:

```text
Heap File
vs
Paged Sequential File
```

Measure:

- insertion time;
- primary-key search time;
- disk space used;
- reorganization time.

---

## 15.3 Index comparison

Compare:

```text
Clustered B+
Unclustered B+
Extendible Hashing
```

Evaluate:

- equality;
- range;
- sorting.

Measure:

- index construction time;
- query time;
- extra disk space;
- behavior under frequent insertions/deletions.

---

## 15.4 Benchmark methodology

To reduce misleading results:

- use the same hardware;
- use the same logical datasets;
- use the same random seed when applicable;
- separate dataset generation from query timing;
- repeat measurements;
- record benchmark configuration;
- document cache/warm-up behavior when relevant.

Do not fabricate benchmark values.

---

## 15.5 Experimental outputs

Produce:

- raw CSV/JSON results;
- charts;
- comparison tables;
- conclusions.

Conclusions must follow from the measured results.

---

## 15.6 Final integration

Validate the full path:

```text
Frontend
  ↓
API
  ↓
SQL Engine
  ↓
Operators
  ↓
Indexes / Storage Files
  ↓
Pages
  ↓
Disk
```

Also validate:

- restart and persistence;
- table loading/creation mechanism adopted by the project;
- SQL error handling;
- concurrency;
- benchmark scripts;
- documentation.

---

# 16. Stage dependencies

```text
Stage 1
Architecture
    |
    v
Stage 2
Pages / Persistence
    |
    v
Stage 3
Heap / Sequential
    |
    +----------------+
    |                |
    v                v
Stage 4          Stage 5
B+               Hash
    |                |
    +-------+--------+
            |
            v
         Stage 6
         Operators
            |
            v
         Stage 7
        SQL Engine
            |
            v
         Stage 8
       Transactions
            |
            v
         Stage 9
       API / Frontend
            |
            v
         Stage 10
       Experiments
```

---

# 17. Recommended work cycle with Codex

For every stage:

## Step 1 — Inspect

Use a prompt similar to:

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
and the current ETAPA_XX.md file.

Inspect the repository.
Do not modify code yet.

Report what already exists, what is missing for the current stage,
and any conflicts with the project documentation.
```

## Step 2 — Implement one small task

```text
Implement only task X.Y from the current stage document.

Reuse existing compatible code.
Do not implement future-stage functionality.

Add or update the relevant tests.
```

## Step 3 — Validate

```text
Run the relevant tests.

Explain any failures.
Do not modify unrelated code.
```

## Step 4 — Promote stable decisions

If implementation work resolves a previously open architectural decision, update `PROJECT_CONTEXT.md`.

Do not add temporary debugging details to `PROJECT_CONTEXT.md`.

---

# 18. Global completion rule for Part 1

Part 1 is complete only when:

```text
[ ] Stage 1 complete
[ ] Stage 2 complete
[ ] Stage 3 complete
[ ] Stage 4 complete
[ ] Stage 5 complete
[ ] Stage 6 complete
[ ] Stage 7 complete
[ ] Stage 8 complete
[ ] Stage 9 complete
[ ] Stage 10 complete
```

and the completion checklist in `REQUIREMENTS.md` is fully satisfied.

---

# 19. Current status

Current planned stage:

> **Stage 1 — Architecture and Data Model**

Current detailed stage document:

> `ETAPA_01.md`

Current implementation progress: repository/package setup, the foundational
data model (`DataType`, `Column`, `Schema`, `RID`, `Record`), table/index metadata,
and the in-memory `Catalog` are implemented with passing unit tests and a
model/catalog integration test. Abstract storage, index/ordered-index, and
operator contracts (1.10) and integrated domain errors (1.11) are now implemented
with passing interface/error tests. The next work is final Stage 1 integration
and Definition-of-Done review in `ETAPA_01.md`; this update does not formally
close Stage 1 or begin Stage 2.

Codex must inspect the repository before assuming which Stage 1 components are already implemented.
