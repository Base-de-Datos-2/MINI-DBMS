# Stage 7 Tasks 7.33–7.35 — metadata, durable CREATE, and constraints

**Implemented and verified:** 2026-09-20  
**Scope:** Stage 7 extension Tasks 7.33, 7.34, and 7.35. EXPLAIN execution,
final scenario acceptance, API/editor integration, and extension closure remain
in Tasks 7.36–7.40.

> **Subsequent status (2026-09-20):** Tasks 7.36–7.40 completed explanation
> execution, exact acceptance, and extension closure. This file remains the
> incremental evidence for Tasks 7.33–7.35; final evidence is in
> `ETAPA_07_EXTENSION_AUDIT.md`.

## Outcome

The handwritten CREATE syntax from Task 7.32 now binds into durable logical
metadata and executes through an engine-owned database service. A
manifest-backed database can be created or reopened without caller-supplied
schemas, and SQL-created tables remain queryable after a fresh process restart.
CREATE uses the existing Heap and unclustered B+ implementations rather than a
parallel storage path.

SQL and the managed database write API share the same VARCHAR, type, record
capacity, and primary-key validation immediately before the existing mutation
maintenance service writes. Primary-key uniqueness is backed by a real unique
B+ index, including DELETE/reinsert and restart behavior.

## Implementation map

| Area | Implemented behavior |
|---|---|
| Logical metadata | Immutable `ColumnConstraint` entries extend `TableMetadata` with optional declared VARCHAR length and one primary key while preserving the old two-argument constructor and unrestricted legacy VARCHAR metadata |
| CREATE binding | `INT` and `INTEGER` map to `DataType.INTEGER`; ordered columns and constraints are retained; duplicate columns, multiple keys, invalid lengths, and name collisions produce located binding errors before file allocation |
| Shared validation | `engine.maintenance.validation` validates schema identity, concrete typed values, Unicode code-point limits, B+ key representability, strict codecs, and complete record size |
| DDL boundary | `engine.query.ddl.DdlService` is the narrow injected protocol; the query layer does not import the API or the concrete database owner |
| Planning/execution | CREATE preparation is side-effect free; `CreatePlanSpec` revalidates mutable state at execution; successful execution returns a completed definition result without rows or an affected-row count |
| Database owner | `engine.database.Database` owns the root, strict manifest, Catalog, QueryEnvironment, permanent Heap/B+ handles, and configured SqlEngine |
| Persistence | Canonical UTF-8 `database.catalog.json` uses magic `MINIDB_CATALOG`, version 1, exact fields, opaque UUID-backed filenames, atomic same-directory replacement, and strict duplicate/path/reference checks |
| Reopen | The owner reconstructs ordered metadata and runtime registrations from the manifest, then existing Heap/B+ open paths cross-check physical headers before exposure |
| CREATE compensation | New files are initialized, flushed, and structurally checked before publication. Ordinary publication/manifest failures unregister the new live bundle, close its handles, and remove only its files; cleanup failure makes the owner unavailable |
| Mutation integration | SQL INSERT and `Database.insert()` pass table metadata into the established `MutationService`; all registered indexes continue through the existing maintenance, repair, and RID rules |
| Compatibility | Existing definition-driven `api.database.Database` remains an explicit legacy mode, does not infer/write the manifest, and rejects SQL CREATE because no DDL service is injected |

## Persistence and failure boundaries

The manifest is the database discovery source of truth. Per-file headers remain
authoritative for physical format and schema/index identity. A missing,
malformed, incomplete, escaping, duplicate, or header-inconsistent manifest
entry prevents open. Logical SQL names never become filesystem paths.

CREATE provides deterministic compensation for ordinary Python exceptions. It
does not claim transactions, concurrent DDL, WAL, or crash-atomic commit across
the manifest, table, and index files. Those boundaries remain outside Stage 7.
Raw storage objects remain documented low-level primitives; normal SQL writes
and the managed database write API enforce the new logical constraints.

## Test coverage

The new tests cover:

- legacy metadata construction and immutable ordered constraint metadata;
- declaration bounds, duplicate/unknown constraints, multiple keys, NULL/type
  rejection, Unicode character counts, record bytes, and B+ key bytes;
- side-effect-free preparation, empty queryability, opaque paths, exact
  manifest shape, clean and fresh-process reopen;
- repeated CREATE preserving rows/files, and injected Heap, index, registry,
  and manifest failures followed by a valid CREATE;
- missing/malformed/incomplete manifests, traversal/absolute paths, and Heap/B+
  header cross-checks;
- primary-key duplicates before and after reopen, 100/101-character VARCHAR
  values, multibyte key bounds, DELETE/reinsert, and programmatic writes through
  the shared maintenance route;
- unchanged query, mutation, API, architecture, storage, index, and operator
  behavior through the complete repository regression suite.

## Verification

Commands ran from the repository root with warnings treated as errors and
without pytest cache writes.

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\database\test_managed_database.py::test_semantically_invalid_create_is_rejected_before_file_allocation `
  tests\query\test_binder.py `
  tests\query\test_executor_results.py `
  tests\query\test_executor_writes.py `
  -q -W error -p no:cacheprovider
# 84 passed in 7.41s

.venv\Scripts\python.exe -m pytest tests\test_architecture.py `
  -q -W error -p no:cacheprovider
# 19 passed in 14.17s

.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
# 2724 passed in 1323.40s (0:22:03)
```

The complete count is current evidence for the checked-out working tree. The
historical 2,556-test count remains attributed only to the original Stage 7
baseline audit.
