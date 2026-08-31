# REQUIREMENTS.md

## Status

This file summarizes the **official project requirements** relevant to the current implementation.

Primary source:

> `Proyecto_Final.pdf` — "Minigestor de Base de Datos Multimodal", Base de Datos 2, 2026-2.

This file should contain requirements from the assignment, not personal implementation preferences.

When the instructor clarifies or changes a requirement, update this file.

---

# 1. Project goal

Build a database manager from scratch that progressively supports multiple data types:

- relational tables;
- spatial/geographic data;
- text;
- multimedia such as images/audio.

The objective is to understand the internal operation of modern database systems by progressively implementing the modules that compose a multimodal database engine.

The project is incremental: later parts build on structures created in earlier parts.

Therefore the implementation should remain modular from the beginning.

---

# 2. Current required scope

## Part 1 — Relational Database (Tables and SQL)

Part 1 is the current implementation target.

---

# 3. Part 1 — File management and storage

The system must implement different ways to store data on disk.

## 3.1 Heap File

Required behavior:

- store records in disk pages;
- store records in arrival order;
- include a strategy to reuse free space.

---

## 3.2 Paged Sequential File

Records must remain ordered by a key.

Required behavior:

- insertion that preserves order;
- lazy deletion;
- a reorganization strategy.

The assignment gives the following example trigger:

> reorganize when more than 30% of the space is wasted.

The 30% value is presented as an example strategy in the project statement.

---

# 4. Part 1 — Indexing and optimization

The system must implement the following indexes:

## 4.1 Clustered B+ Index

Required.

---

## 4.2 Unclustered B+ Index

Required.

---

## 4.3 Dynamic Hash Index

Required technique:

> Extendible Hashing

---

# 5. Part 1 — External algorithms

## 5.1 ORDER BY

`ORDER BY` must be implemented using:

> External Sorting with k-way merge.

---

## 5.2 GROUP BY

`GROUP BY` must be optimized using:

- External Hashing; and/or
- strategic use of indexes.

The implementation must clearly demonstrate the selected required technique.

---

## 5.3 JOIN

`JOIN` must be optimized using:

- External Hashing; and/or
- strategic use of indexes.

The implementation must clearly demonstrate the selected required technique.

---

# 6. Part 1 — SQL query processing

The system must implement a SQL parser that allows basic database interaction.

Required query families include:

```sql
SELECT [*]
FROM table
WHERE condition;
```

```sql
SELECT [*]
FROM table
ORDER BY ...;
```

```sql
SELECT [*]
FROM table
GROUP BY ...;
```

```sql
INSERT INTO table
VALUES (...);
```

```sql
DELETE FROM table
WHERE condition;
```

The project explicitly states that a complete SQL-standard implementation is **not required**.

Only the SQL functionality needed to support the implemented techniques is necessary.

---

# 7. Part 1 — Transactions and concurrency

The system must allow multiple users/transactions to access the database safely.

## 7.1 Transactions

The system must support transaction grouping with:

```text
BEGIN TRANSACTION
END TRANSACTION
```

---

## 7.2 Concurrency control

The system must implement:

- a locking mechanism; or
- another concurrency-control mechanism.

---

## 7.3 Mandatory concurrency demonstration

A simulation using threads is required.

The demonstration must show:

1. multiple transactions executing simultaneously;
2. race-condition / resource-competition situations;
3. how the system handles those situations correctly.

---

# 8. Part 1 — Graphical user interface

The application must include a friendly GUI with four main panels.

## 8.1 Files panel

Must show:
- loaded tables;
- table structure.

---

## 8.2 Query panel

Must provide:
- an editor where the user writes SQL queries.

---

## 8.3 Results panel

Must show:
- query results in a table.

---

## 8.4 Execution Plan panel

Must visualize how the query was executed.

The panel should show information such as:
- indexes used;
- order of operations;
- other relevant plan information.

---

# 9. Part 1 — Experimental comparison

The project requires an experimental analysis of the implemented techniques.

---

## 9.1 File-organization comparison

Compare:

- Heap File;
- Paged Sequential File.

Required dataset sizes:

```text
1,000 records
10,000 records
100,000 records
```

Required measurements:

- insertion time;
- primary-key search time;
- disk space used;
- reorganization time.

Required conclusion:

- identify when each technique is preferable.

---

## 9.2 Index comparison

Compare:

- clustered B+;
- unclustered B+;
- Dynamic Hash / Extendible Hashing.

Evaluate:

- exact-equality searches;
- range searches;
- sorting.

Measure:

- index-construction time;
- query time;
- additional disk space required;
- performance under frequent insertions/deletions.

---

## 9.3 Experimental presentation

The analysis must include:

- comparative graphs;
- a summary table with advantages/disadvantages;
- conclusions about when each structure should be used.

---

# 10. Project-wide delivery requirements

The project deliverables include:

- source code in a Git repository (GitHub or GitLab);
- technical documentation / README;
- system architecture;
- source-code organization/archetype;
- installation manual;
- a 5–10 minute demo video;
- an incremental report;
- architectural design;
- data domain;
- explanation of algorithms;
- experimental section;
- final presentation.

---

# 11. Project milestones

According to the assignment:

| Milestone | Week | Required delivery |
|---|---:|---|
| Avance 1 | 6 | Part 1 complete |
| Entrega Parcial | 8 | Parts 1 and 2 complete |
| Avance 3 | 12 | Parts 3 and 4 complete |
| Entrega Final | 15 | Everything complete + documentation |
| Presentations | 16 | Project presentation |

---

# 12. Forward-compatibility requirements

Although Part 1 is the current scope, its architecture must not make later parts impossible.

The full project later adds:

- spatial data;
- R-Tree;
- map visualization;
- spatial SQL;
- full-text search;
- SPIMI;
- TF-IDF + cosine similarity;
- BM25;
- multimedia feature extraction;
- IVF;
- HNSW;
- multimodal/AI application integration.

These features are **not Part 1 deliverables**, but the assignment explicitly states that later parts build on earlier structures.

Therefore Part 1 should be modular enough to be extended later.

---

# 13. Non-requirements / things the assignment does not explicitly mandate for Part 1

The project statement does **not** explicitly require:

- a particular programming language;
- a particular frontend framework;
- a particular API framework;
- a specific page size;
- a complete SQL standard;
- MVCC;
- a cost-based optimizer;
- PostgreSQL as the underlying storage engine;
- SQLite as the underlying storage engine.

Such choices belong in `PROJECT_CONTEXT.md`, not in this file, unless later clarified by the instructor.

---

# 14. Part 1 completion checklist

Part 1 should not be considered complete unless all of the following are demonstrated.

## Storage
- [ ] Heap File
- [ ] page-based storage
- [ ] free-space reuse
- [ ] Paged Sequential File
- [ ] ordered insertion
- [ ] lazy deletion
- [ ] reorganization strategy

## Indexes
- [ ] clustered B+
- [ ] unclustered B+
- [ ] Extendible Hashing

## External algorithms
- [ ] External Sort with k-way merge
- [ ] GROUP BY using required optimization strategy
- [ ] JOIN using required optimization strategy

## SQL
- [ ] SELECT
- [ ] WHERE
- [ ] ORDER BY
- [ ] GROUP BY
- [ ] INSERT
- [ ] DELETE

## Transactions/concurrency
- [ ] BEGIN TRANSACTION
- [ ] END TRANSACTION
- [ ] concurrency-control mechanism
- [ ] thread-based concurrent-transactions demo
- [ ] race-condition demo
- [ ] correct protected execution

## Frontend
- [ ] Files panel
- [ ] Query panel
- [ ] Results panel
- [ ] Execution Plan panel

## Experiments
- [ ] 1,000-record dataset
- [ ] 10,000-record dataset
- [ ] 100,000-record dataset
- [ ] Heap vs Sequential comparison
- [ ] clustered vs unclustered B+ comparison
- [ ] Extendible Hashing comparison
- [ ] graphs
- [ ] summary comparison table
- [ ] conclusions
