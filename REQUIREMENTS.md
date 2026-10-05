# REQUIREMENTS.md

> Context version: **1.1** — aligned with the implementation-document structure without changing the official requirements.

## Status

This file summarizes the **official project requirements** relevant to the current implementation.

Primary source:

> `Proyecto_Final.pdf` — "Minigestor de Base de Datos Multimodal", Base de Datos 2, 2026-2.

This file should contain requirements from the assignment, not personal implementation preferences.

When the instructor clarifies or changes a requirement, update this file.

---

## Relationship with implementation documents

This file is the source of truth for **official academic requirements**.

The following files have different purposes:

- `PROJECT_CONTEXT.md` records architectural and technical decisions;
- `PART_01/PLAN_PARTE_01.md` defines the implementation roadmap for Part 1;
- `PART_01/ETAPA_XX.md` defines the detailed tasks for the current stage;
- `AGENTS.md` defines how Codex should work in the repository.

`PART_01/PLAN_PARTE_01.md` and `PART_01/ETAPA_XX.md` may explain how the team intends to satisfy a requirement, but they must not add, remove, weaken or override an official requirement in this file.

If an implementation document conflicts with `REQUIREMENTS.md`, the requirement in this file takes precedence and the conflict must be reported before implementation continues.

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

All five parts remain delivery obligations. The user authorized the complete
backend correction/implementation phase on 2026-10-04; frontend implementation
is deferred, without removing its academic requirements. Spatial requirements
are in section 15; text, multimedia and application requirements follow below.
The official source is the current `Proyecto_Final.pdf`.

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
- final presentation (15 minutes plus 5 minutes of questions).

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

---

# 15. Part 2 — Spatial Database (Coordinates and Maps)

Source: `Proyecto_Final.pdf`, physical page 3, section 2.2. The earlier DOCX
comparison is historical; the current PDF is present and was decomposed into
verifiable requirements in `docs/auditoria/MATRIZ_REQUISITOS.csv`.
Implementation choices and preparation status belong in the Part 2 plan/context.

## 15.1 Implementation

- Own R-Tree for geographic 2D points (latitude, longitude).
- Range/radius queries, k nearest neighbors and intersection with polygons.
- Both Euclidean and geodesic/Haversine distance metrics.

## 15.2 Visualization and SQL

An interactive map panel displays stored points and highlights spatial results.
The SQL parser must support the assignment's examples:

```sql
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

```sql
SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
```

## 15.3 Experiments

Compare sequential search, the own R-Tree and PostgreSQL GiST for radius
1/5/10 km and k=10/50/100 on 1,000/10,000/100,000 points. Measure construction
time, mean time over 100 queries, memory and disk space. Present comparison
graphs and a table explaining when each technique is appropriate.

The assignment does not prescribe an R-Tree page layout, persistent POINT DDL,
two database-owner integrations or a second complete metric matrix. These are
implementation decisions, not additional academic requirements.

# 16. Part 3 — Full-text search

Source: `Proyecto_Final.pdf`, physical pages 3–4, section 2.3.

- Implement an inverted index using SPIMI.
- Implement TF-IDF with cosine similarity and BM25 ranking.
- Extend SQL with MATCH, selection of TF_IDF/BM25, SCORE, ordering and LIMIT
  as illustrated by the assignment.
- Compare TF-IDF/cosine, BM25 and PostgreSQL GIN with identical queries and
  1,000/10,000/100,000 documents; query lengths are 1, 3 and 5+ words.
- Measure construction/query time, Precision@10, Recall@10, memory and disk;
  present comparative graphs and a advantages/disadvantages table.

# 17. Part 4 — Multimedia search

Source: `Proyecto_Final.pdf`, physical page 4, section 2.4.

- ExtractFeatures uses SIFT for images and MFCC for audio.
- Quantize descriptors with K-Means or Tree Quantization, count visual/audio
  words and apply TF-IDF to obtain a K-dimensional histogram.
- Implement IVF and HNSW and Euclidean, dot-product and cosine metrics.
- Extend SQL with SIMILAR_TO, index/metric selection and SIMILARITY_SCORE as
  illustrated by the assignment.
- Compare both indexes and Euclidean/cosine with k=10 at
  1,000/10,000/100,000 images/audio objects.
- Measure construction/query time, Recall@10 and memory; provide time-versus-
  dataset-size graphs, a gallery of actual success/error cases and a table.

# 18. Part 5 — Application

Source: `Proyecto_Final.pdf`, physical pages 4–5, section 2.5; Anexo A,
physical pages 6–7.

- Build one real application consuming the own engine's REST or GraphQL API.
- Integrate at least two of relational, spatial, text or multimedia data.
- Provide a user interface demonstrating the system (deferred in this phase).
- Select one Anexo A option: academic-document RAG, hybrid e-commerce,
  audio copyright detection, or face recognition. Only the selected option's
  specific components apply; optional features remain optional.

The application's selection and implementation details belong in
PROJECT_CONTEXT.md and its implementation documentation. PostgreSQL is solely
an experimental comparator; it does not implement this project's algorithms.
