# Stage 8 Task 8.1 — baseline inspection

**Inspected checkout:** `main` at `bf381e3d98673509f928b4a95fe410658e5312c6` on 2026-09-21. The plan's `25fb7916d15e7dd4f43911b415ede00c09257a48` and the Stage 7 audit's `49b575470f612191cd1b8e7fe5fb8d6e89cbca02` are historical references, not the current checkout. The working tree was clean before this documentation work. **Environment:** Windows; the repository `.venv` runs Python 3.12.4 and pytest 8.4.2. The system `python` resolves to Python 2.7 and cannot run this project.

## Existing ownership and entry points

| Entry point | Current ownership and behavior | Stage 8 boundary |
|---|---|---|
| `engine.database.Database.create/open`, `_assemble`, `_open_table`, `close` | The manifest owner holds Catalog, QueryEnvironment, one SqlEngine, and all permanent Heap/B+ handles. Open reconstructs them from manifest metadata. Close closes the engine, indexes, then storages. | Make this the canonical coordinator for a physical directory; session close must not close shared handles. Reject a competing in-process owner. |
| `Database.engine`, `Database.insert`, `storage_for`, `index_for`, `create_table`, `validate_create` | The default engine, managed programmatic insert, borrowed handle access, and multi-file CREATE are currently separate entry points. `create_table` registers files/runtime objects before atomic manifest publication and compensates ordinary failures; failed cleanup marks the owner unavailable. | Route public writes and DDL through one coordinator; classify raw borrowed handles as exclusive/internal access. Schema gate must cover CREATE and metadata publication. |
| `SqlEngine.prepare/describe/execute/close`, `PreparedQuery.execute`, `prepare_sql/run_sql` | One facade has one `_active_result`. Preparation binds live runtime objects without an execution lock; execution is one SQL statement and has no transaction state. `PreparedQuery` points back to its owning engine. | One facade per session; pure preparation never starts/ends a group. Revalidate plans after execution locks. Audit convenience functions so they do not bypass coordination. |
| `QueryResult.open/next/close`, `ExplanationResult` | SELECT lazily opens a fresh Stage 6 plan, owns temporary/operator resources, and releases the facade on EOF, early close, or failure. Plain EXPLAIN describes only; ANALYZE consumes one SELECT execution. | A cursor's lifetime determines implicit read completion. Explicit read locks survive cursor close until END/ROLLBACK. ANALYZE needs SELECT locks; EXPLAIN needs protected metadata. |
| `QueryEnvironment` and `Catalog` | Catalog holds metadata; environment registers and lends mutable storage/index objects without owning their handles. Binders and plans retain object identities. Registrations are ordinary dict mutations without a concurrency protocol. | Registry publication, replacement, and close need short protection and per-table generations. No session may use stale borrowed objects after restore. |
| `MutationService.insert/delete`, `DeleteTargetSpool` | INSERT checks uniqueness, changes storage and indexes, then flushes. DELETE discovers exact RID/old-row targets in a disk spool before mutation and may keep a confirmed deleted prefix after a later failure. Index repair/rebuild may persist incomplete markers. | Take X before checks or DELETE discovery; snapshot the full table/index write set before any persistent change. The service's local repair is not group rollback. |
| `PageManager` and storage/index adapters | PageManager shares one unbuffered seek/read/write handle and mutable header/counters. Sequential reorganization, B+ rebuild, and Hash rebuild replace files and refresh internal state; RID movement can force index rebuilds. | Add short physical latches or equivalent positional I/O; logical S/S compatibility alone is unsafe. Undo must restore bytes, lengths, allocation/header/cache state, and canonical references. |
| `api.database.Database`, `api.engine_service.EngineService`, HTTP routes | Stage 9 uses a separate definition-driven owner and one SqlEngine. EngineService's nonblocking process admission lock serializes preparation through cursor cleanup; SELECT is the default allowlist, optional writes add INSERT/DELETE. It does not expose CREATE or explanation results. | Preserve this guard. Engine concurrency must be proved through new sessions before a later HTTP adapter migrates ownership, result serialization, and session persistence. |

Direct `HeapFile`, `PagedSequentialFile`, B+ and Hash construction/mutation/rebuild/close in lower-level tests and registered `QueryEnvironment` fixtures are valid internal test paths. Their current APIs do not claim safe concurrent access. The legacy API owner and the registered-environment fixtures need an explicit adapter to the same coordinator; merely constructing two `SqlEngine` objects over one environment would not provide protection.

## Permanent write and replacement inventory

- Heap, Sequential, B+ and Hash writes go through `PageManager.allocate_page/write_page`, whose header and counters are mutable. `read_page` uses a shared `seek` followed by a full read, so even compatible S readers can interfere without physical protection.
- `PagedSequentialFile.reorganize` writes and validates a sibling file, then uses `PageManager.commit_replacement`. Clustered B+ reorganization first marks the tree incomplete and rebuilds it after the sequential replacement.
- `BPlusTree.rebuild_from_storage` and `ExtendibleHashIndex.rebuild_from_storage` replace their index files. Their headers, free lists, directories, nodes/caches, and adapter consistency flags must be considered during restoration.
- `MutationService` can write persistent incomplete markers before RID-moving maintenance, perform base/index changes, rebuild indexes, and flush. Managed `Database.insert` invokes it directly. SQL DELETE also writes a temporary target spool before the mutation pass.
- Managed CREATE creates a Heap and optional B+ file, mutates Catalog and environment registrations, then replaces the manifest. Its compensation is local to standalone DDL, not a transaction undo log.
- `Database.close`, individual storage/index `close`, and replacement helpers can invalidate handles still borrowed by a prepared plan or open cursor. The coordinator must cover every normal read, write, rebuild, replacement, and close path. Direct raw-object access remains an explicitly exclusive/internal boundary.

## Existing tests and baseline

| Behavior | Existing coverage to preserve |
|---|---|
| SQL lifecycle, one active result, cleanup, prepared plans | `tests/query/test_executor_results.py`, `test_stage7_resources.py`, `test_planner_select.py`, `test_explain.py` |
| INSERT/DELETE, partial failures, index maintenance | `tests/query/test_executor_writes.py`, `test_mutation_maintenance.py`, `test_stage7_acceptance.py` |
| CREATE, manifest, constraints, restart | `tests/database/test_managed_database.py`, `test_manifest_validation.py`, `tests/query/test_stage7_extension_acceptance.py` |
| Page persistence/replacement and index rebuilds | `tests/storage/test_page_manager_io.py`, `test_paged_sequential_maintenance.py`, `tests/indexes/test_bplus_build.py`, `test_hash_integration.py` |
| Emergency API admission/allowlists | `tests/api/test_engine_service.py`, `test_http.py`, `test_database.py` |

The historical Stage 7 extension audit reports 2,742 strict tests on an earlier revision. No transaction tests or implementation exist yet: `engine/transactions/__init__.py` is a placeholder. The current-checkout SQL/database/API baseline result is below; the complete cross-stage regression is the Task 8.27 gate.

## Confirmed gaps and follow-up tasks

1. No owner-scoped sessions, transaction state machine, lock manager, or undo store exist (8.3–8.9, 8.11–8.14).
2. No physical latch, registry generation, or safe shared read protocol exists (8.10). Existing plan identity checks in `engine/query/planner.py` are useful but must run after locks and account for restored generations (8.6, 8.12, 8.15).
3. No public path currently turns Stage 7's retained DELETE prefix into whole-group rollback. Managed programmatic insert also bypasses any future SQL-only wrapper (8.15, 8.17–8.18).
4. CREATE and the legacy API owner need explicit coordination without widening the manifest or removing the emergency HTTP admission guard (8.19, 8.28).
5. Existing tests are single-session or use direct internal fixtures. Controlled thread schedules, physical S/S tests, undo fault injection, and a deterministic engine-backed demo must be added incrementally (8.7–8.27).

## Baseline result

From the repository root, with the checkout at `bf381e3d98673509f928b4a95fe410658e5312c6` and the documentation changes in progress:

```powershell
.venv\Scripts\python.exe -m pytest tests/query tests/database tests/api -q -W error -p no:cacheprovider
```

**Result:** 436 passed in 233.25 seconds (0:03:53), exit code 0. This rechecks the current SQL, managed database, and emergency API boundaries without treating the historical 2,742 count as a new run. A complete `pytest -q -W error -p no:cacheprovider` was started and reached 34% with no reported failure, then intentionally interrupted in favor of this focused Task 8.1 baseline. It has no complete-suite result; Task 8.27 still requires the full regression.
