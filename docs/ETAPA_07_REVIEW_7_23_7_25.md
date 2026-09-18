# Stage 7 review — Tasks 7.23-7.25

**Date:** 2026-09-18

> **Subsequent status:** Tasks 7.26-7.30 and Stage 7 were closed later on
> 2026-09-18. See `docs/ETAPA_07_REVIEW_7_26_7_30.md` and
> `docs/ETAPA_07_AUDIT.md`. Open-status statements below describe this earlier
> review checkpoint.

**Scope:** Block 7 of the revised `ETAPA_07.md`

**Boundary:** shared mutation maintenance, consistent INSERT, stable bounded
DELETE targets, and ordinary-failure compensation

## Result

Tasks 7.23-7.25 are implemented and verified. INSERT and DELETE now execute
synchronously through the public SQL engine and return one completed, rowless
`CommandResult`. Reading that result or its affected-row count cannot execute
the command again.

The query layer owns DELETE target discovery because discovery uses Stage 6
physical operators. It writes each exact RID and complete old record to a
framed disk spool, closes the discovery plan, and only then calls the lower
`engine.maintenance` service. The maintenance layer therefore has no upward
dependency on query planning or operators.

Successful Heap mutations keep every declared B+ and hash association aligned
with the single base write. A sequential INSERT that can move RIDs marks every
index incomplete before movement and rebuilds all of them from the resulting
base file. Ordinary failures use the base storage as authority: INSERT attempts
to remove its new row, DELETE retains its confirmed earlier deletions, and all
indexes are rebuilt. An index whose repair fails remains persistently marked
incomplete so neither the live environment nor a later reopen can silently use
it.

Stage 7 remains open. Task 7.26 still needs its final reporting acceptance, and
Tasks 7.27-7.30 still cover end-to-end acceptance, restart/resource validation,
documentation completion, and formal closure.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| The repository exposed per-adapter write helpers but no table-wide coordinator | A base row could be committed while only some declared indexes were updated | Add `MutationService` as the single base/index maintenance boundary and require every bound index to participate |
| A prepared INSERT could become stale before execution | A uniqueness probe performed only during binding could permit a later duplicate | Repeat mutable uniqueness checks immediately before the first write |
| Updating sequential indexes one association at a time reused RIDs that insertion may move | Existing index entries could point to different records | Persistently mark every index incomplete before movement and atomically rebuild all indexes from storage |
| DELETE could otherwise mutate the scan or index cursor that was enumerating targets | Leaf traversal, hash results, or slot reuse could skip rows or delete the wrong occurrence | Complete physical discovery and close the plan before the mutation pass |
| Collecting every DELETE RID in a Python list violated the bounded-execution contract | Large deletes could consume unbounded memory | Use a framed temporary disk spool with one writer/read handle and measured target/byte counts |
| A RID alone cannot prove row identity after slot reuse | A replacement row could be deleted from a stale target | Spool the complete old record and verify `storage.read(rid)` still equals it before maintenance |
| Statement rollback does not exist before Stage 8 | A later DELETE failure could be falsely reported as all-or-nothing | Preserve the confirmed completed prefix and expose it on `MaintenanceError` |
| A partial index failure could leave earlier index updates visible | Subsequent indexed reads could silently disagree with the base table | Mark and atomically rebuild every index from current storage after an ordinary mutation failure |
| A failed repair could be forgotten on close/reopen | An incomplete persistent index could return incorrect rows | Expose persistent `mark_incomplete()` adapter operations and block live/reopened access until rebuild succeeds |
| The first maintenance draft imported physical operators | The lower maintenance layer depended upward on query execution | Move DELETE discovery orchestration to `SqlEngine`; keep `engine.maintenance` dependent only on storage/index contracts |
| Mutation results reused the streaming-result shape | Fetching rows or inspecting a result could suggest deferred or repeated execution | Add a synchronous `CommandResult` with no row API and one stable affected-row count |

## Frozen mutation policies

- Parse, bind, and prepared-plan validation do not write data.
- A prepared mutation is revalidated against the current Catalog, storage, and
  index identities before execution.
- INSERT writes the base record exactly once. Heap indexes receive one
  key/RID association; RID-moving storage rebuilds every index.
- All registered table indexes are part of the command. A missing, closed, or
  incomplete required index rejects the mutation before its first write.
- DELETE target discovery is disk-backed and completes before any row changes.
  Each target contains its RID and full old record, preserving occurrences and
  old index keys.
- A row counts as deleted only after the base storage deletion succeeds.
- Earlier successful DELETE rows remain deleted after a later ordinary failure;
  the error reports that confirmed count.
- The base file is authoritative during repair. The service never reinserts a
  deleted row at a different RID and calls that a rollback.
- Successful commands flush storage and indexes before returning. A failed
  repair leaves a persistent incomplete marker and identifies unavailable
  indexes in the error.
- These guarantees cover ordinary exceptions and clean reopen. They do not
  provide concurrent-write safety, transaction isolation, WAL recovery, or
  crash-atomic commits across multiple files.

## Implemented modules

| Module | Responsibility |
|---|---|
| `engine/maintenance/service.py` | Disk-backed target spool, shared INSERT/DELETE coordination, mutable constraint recheck, flush boundary, compensation, repair, and measured mutation reports |
| `engine/maintenance/__init__.py` | Stable maintenance-layer exports |
| `engine/query/executor.py` | Operator-driven DELETE discovery, synchronous mutation dispatch, command results, and mutation/discovery reporting |
| `engine/query/__init__.py` | Public command result/report exports |
| `engine/indexes/unclustered_bplus.py` | Persistent incomplete marker and live access rejection for unclustered B+ adapters |
| `engine/indexes/clustered_bplus.py` | Persistent incomplete marker for clustered/RID-remapped B+ adapters |
| `engine/indexes/unclustered_hash.py` | Persistent incomplete marker for hash adapters |
| `tests/query/test_mutation_maintenance.py` | Ten table-wide consistency, bounded-target, RID-reuse, failure, rebuild, result, and restart regressions |
| `tests/query/test_executor_writes.py` | Public INSERT/DELETE, validation, uniqueness, index, and reopen coverage |
| `tests/query/test_index_pushdown.py` | Indexed SQL access after maintained writes |
| `tests/query/test_executor_results.py` | Command execution after SELECT lifecycle ownership and no duplicate mutation |

The stable contract is also recorded in `PROJECT_CONTEXT.md` and
`docs/sql-grammar.md`. `PLAN.md`, `ETAPA_07.md`, and `AGENTS.md` continue to
identify Stage 7 as active.

## Verification evidence

Focused mutation, public execution, index-pushdown, result-lifecycle, and
architecture coverage:

```text
63 passed in 25.86s
```

The final mutation-maintenance file, including no-index reopen and stale
RID/slot-reuse protection, passes independently:

```text
.venv/Scripts/python.exe -m pytest \
  tests/query/test_mutation_maintenance.py \
  -q -W error -p no:cacheprovider

10 passed in 1.11s
```

All persistent index adapters and the affected sequential-storage contracts
remain green:

```text
.venv/Scripts/python.exe -m pytest \
  tests/indexes \
  tests/storage/test_paged_sequential_file.py \
  tests/storage/test_paged_sequential_maintenance.py \
  tests/storage/test_sequential_ordering.py \
  -q -W error -p no:cacheprovider

558 passed in 105.19s (0:01:45)
```

The complete unfiltered cross-stage suite, including the two mutation files
previously excluded by the Block 6 review, passes with warnings treated as
errors:

```text
.venv/Scripts/python.exe -m pytest tests \
  -q -W error -p no:cacheprovider

2545 passed in 1036.23s (0:17:16)
```

`compileall` and `pip check` also pass. No dependency was added.

## Handoff to the next block

Task 7.26 can now close the combined SELECT/command reporting contract using
the real `MutationReport` and DELETE discovery `PlanReport`. Tasks 7.27-7.30
must then exercise the complete supported SQL matrix, restart and resource
cleanup, update the remaining public documentation, and run the formal Stage 7
Definition of Done audit before the stage can be marked complete.
