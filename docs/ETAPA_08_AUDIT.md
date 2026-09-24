# Stage 8 closure audit

**Stage:** 8 — Transactions and Concurrency  
**Closed:** 2026-09-24  
**Plan:** `ETAPA_08.md`, Tasks 8.1–8.30  
**Audited source:** Git `HEAD` `cddb1e45191f0186d04c354bfec2918ad23b8bb9` plus the current Stage 8 worktree changes  
**Environment:** Windows, Python 3.12.4, pytest 8.4.2

The Stage 8 implementation and evidence are complete at the in-process database
owner/session boundary. All 37 Definition of Done items in `ETAPA_08.md` are
satisfied. This closure does not claim crash recovery, process-shared locking,
or completed transaction integration in the Stage 9 HTTP/UI adapter.

No commit was created as part of this implementation request. The recorded hash
is the base `HEAD`; the tested source is that commit plus the complete current
worktree diff and untracked Stage 8 files reported by `git status`. The audit
does not mislabel the uncommitted worktree as an immutable commit.

## Task audit

| Task | Result and evidence |
|---|---|
| 8.1 | Inspected session/result ownership, mutation failures, replacement, persistence and the API guard; `docs/ETAPA_08_TASK_8_1_INSPECTION.md`. |
| 8.2 | Froze session, isolation, wait, abort, commit, quota and crash-recovery boundaries; `docs/transactions.md`. |
| 8.3 | Added immutable states/reports, owner-scoped IDs, transitions and structured transaction errors; `engine/transactions/model.py`, `manager.py`, `errors.py`. |
| 8.4 | Added one shared coordinator with independent `SqlSession` facades for managed and legacy owners; `engine/transactions/session.py`, both owner modules. |
| 8.5 | Added handwritten BEGIN TRANSACTION, END TRANSACTION and ROLLBACK AST/parser/dispatch while preserving one statement per call. |
| 8.6 | Mapped every control, SELECT/join, INSERT, DELETE, CREATE and EXPLAIN form to schema/table/file intents with stable identities; `engine/transactions/resources.py`. |
| 8.7 | Implemented transaction-owned S/X grants, compatibility, idempotent reacquisition and terminal release; `engine/transactions/locks.py`. |
| 8.8 | Added condition waits, FIFO queue blockers, S-to-X upgrades, finite timeout and cancellation wakeup. |
| 8.9 | Added wait-for cycle detection and requesting-participant victim handling with abort before conflicting access. |
| 8.10 | Protected complete `PageManager` transfers and mutable runtime/catalog registries with short latches; physical concurrency tests pass. |
| 8.11 | Added quota-reserved, chunked, hashed table/base/index before-images before first write; `engine/transactions/undo.py`. |
| 8.12 | Restored exact bytes/lengths, reopened canonical handles, validated indexes and advanced runtime generations; `runtime.py`. |
| 8.13 | Defined commit success after complete write-set validation and synchronization, before lock release; `completion.py`. |
| 8.14 | Restored every table touched by a failed group and quarantined failed restore/validation with retained diagnostics. |
| 8.15 | Routed owner-backed explicit and implicit execution through access planning, locks, completion and prepared-plan rebinding. |
| 8.16 | Kept implicit SELECT protection through EOF/close and explicit locks through END/ROLLBACK; external operator cleanup is tested. |
| 8.17 | Protected INSERT constraints and base/index maintenance after first-write capture; managed programmatic insertion uses the same boundary. |
| 8.18 | Protected DELETE discovery/write/rebuild and verified Heap, Sequential, clustered/unclustered B+ and Hash rollback. |
| 8.19 | Coordinated standalone CREATE under schema X with atomic publication/compensation and explicit-group rejection; metadata uses the fair gate. |
| 8.20 | Preserved planning-only EXPLAIN and made ANALYZE execute once under SELECT locks with separate timings/outcome. |
| 8.21 | Added bounded synchronized traces and metrics for locks, blockers, query I/O, undo I/O, latches, causes and completion. |
| 8.22 | Added safe-point cancellation and finite session/database shutdown without forced thread termination or premature shared-handle close. |
| 8.23 | Verified dirty-read, repeatable/range-read, fair waiter, reader overlap and independent-table schedules; `test_controlled_evidence.py`. |
| 8.24 | Injected snapshot/base/index/spool/rebuild/restore/publication failures and verified whole-group state, quarantine and clean reopen. |
| 8.25 | Built an unsafe disposable real-engine schedule whose two reads of zero produce the lost-update result one; `demos/transactions_demo.py`. |
| 8.26 | Built protected whole-business retry after an upgrade deadlock and a real serial oracle; both finish at two with honest attempt evidence. |
| 8.27 | Added seed `8272026` bounded stress, focused transaction/API gates and the complete strict regression below. |
| 8.28 | Specified request-owned sessions, result/error variants, cancellation/status and safe admission migration; `docs/ETAPA_08_STAGE_9_HANDOFF.md`. |
| 8.29 | Synchronized current coordination, SQL, transaction, demo and Stage 9 documents while retaining historical Stage 7 audits. |
| 8.30 | Audited all tasks and 37 criteria, reran the clean demo and gates, and recorded this closure with declared limits. |

## Definition of Done audit

The 37 individual checkboxes remain visible in `ETAPA_08.md`; none is waived.
Their evidence resolves as follows:

| Definition of Done group | Result | Primary verification |
|---|---:|---|
| Transactions and sessions | 8/8 | `test_controls.py`, `test_model.py`, `test_sessions.py`, `test_sql_integration.py`: exact controls, one statement, ownership, busy/protocol behavior, implicit use and provisional commands. |
| Concurrency and physical safety | 9/9 | `test_locks.py`, `test_physical_concurrency.py`, `test_controlled_evidence.py`: S/X lifetime, complete access coverage, compatible overlap, physical safety, waits, deadlock/timeout/cancel, victim cleanup and isolation schedules. |
| Undo and commit | 9/9 | `test_undo_completion.py`, `test_sql_integration.py`, `test_controlled_evidence.py`: image bounds, exact multi-table/structure restore, generation refresh, commit point, quarantine, clean reopen and explicit crash boundary. |
| Integration and evidence | 11/11 | `test_lifecycle_integration.py`, `test_controlled_evidence.py`, `test_bounded_stress.py`, 97 API compatibility tests, the clean demo and the 2,831-test full regression. |

This produces 37/37 satisfied criteria. The final four closure checkboxes were
set only after the stress, handoff, contradiction scan, audit and complete
regression evidence existed.

## Task 8.27 bounded workload

The workload uses seed `8272026`, four worker sessions, six inserted keys and
two deleted keys per worker, two concurrently used tables, a third table for a
forced lock wait, a 15-second future bound, a 64 KiB operator budget, four open
handles, a 16-row materialization limit, 4 MiB per-transaction undo, 16 MiB
owner undo, 4 KiB copy chunks and two capture slots.

Each worker executes a grouped insert/read/commit, an explicit rollback, a
group that fails on a duplicate primary key after a prior write, and implicit
deletes. The test compares exact row multisets with a precomputed serial oracle,
checks primary-key uniqueness, validates each B+ structure and every key/RID/base
association, proves deleted/rolled-back/failed keys absent, verifies a real
waiter and blocker, and requires an empty lock table, zero active transactions,
one remaining default session, no unclean marker, no owned undo artifact, and
the same result after a fresh owner reopen.

## Recorded commands and results

Run from the repository root with the worktree described above:

```text
.venv\Scripts\python.exe -m pytest tests/transactions/test_bounded_stress.py -q -W error -p no:cacheprovider
1 passed in 1.79s

.venv\Scripts\python.exe -m pytest tests/transactions -q -W error -p no:cacheprovider
91 passed in 14.35s

.venv\Scripts\python.exe -m pytest tests/api -q -W error -p no:cacheprovider
97 passed in 28.21s

.venv\Scripts\python.exe -m demos.transactions_demo
unsafe final=1; protected final=2; serial oracle final=2; protected_matches_serial_oracle=true

.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
2831 passed in 950.74s (0:15:50)

.venv\Scripts\python.exe -W error -m compileall -q engine api demos tests\transactions
passed

git diff --check
passed (Git emitted only LF-to-CRLF working-copy notices)
```

The complete regression contains all prior Stage 1–7 suites plus the Stage 8
tests. No frontend file changed in this block, so the conditional frontend
build gate was not run. `REQUIREMENTS.md` was reviewed and not changed because
there was no new academic clarification.

## Demonstration result

`python -m demos.transactions_demo` creates three clean disposable databases:

- two unprotected workers both read `0` and write `1`, producing the real lost
  update `final_value=1`;
- protected sessions expose one S-to-X deadlock victim, retry that worker's
  whole read/compute/delete/insert business operation, commit two operations,
  and produce `final_value=2`;
- the serial oracle reads `0`, then `1`, and also produces `final_value=2`.

Attempt transaction IDs, victim identity and wait durations may vary. The
controlled history, one aborted attempt, two committed business operations and
final values are the asserted evidence.

## Definition of Done conclusion

- Session ownership and one-statement transaction controls are implemented for
  managed and legacy in-process owners.
- Rigorous table-level 2PL prevents dirty reads, covered phantoms and protected
  lost updates; compatible readers and independent tables overlap.
- Whole-group ordinary abort restores every captured table/index set before
  locks release. Failed restoration quarantines the owner.
- Commit validates and synchronizes the write set before `COMMITTED` becomes
  the success point.
- Real storage/index integrations, CREATE, EXPLAIN/ANALYZE, metrics,
  cancellation and shutdown pass their focused and complete regressions.
- Bounded stress, resource cleanup, clean reopen and the required threaded
  comparison are reproducible from the commands above.
- The Stage 9 adapter boundary and guard-removal prerequisites are explicit.

## Declared limits and remaining work

- Before-images copy the complete first-written table and every associated
  index. Capture space and handles are bounded, but time and I/O scale with that
  physical set.
- Guarantees cover ordinary in-process failures and orderly close/reopen. There
  is no WAL, redo, automatic crash recovery, power-loss atomicity, distributed
  transaction or cross-process lock manager.
- Locking is table scoped, so writers to different rows of one table serialize.
- CREATE is standalone under schema X and is rejected inside explicit groups.
- The HTTP/UI still uses the emergency admission guard and default session; it
  does not yet expose stable cross-request sessions, transaction controls,
  exhaustive result variants, cancellation or status. Follow
  `docs/ETAPA_08_STAGE_9_HANDOFF.md` before claiming concurrent API support.
- Stage 9 integration and Stage 10 experiments/delivery remain open.

## Closure decision

Stage 8 is closed against the recorded evidence on 2026-09-24. `PLAN.md`,
`PROJECT_CONTEXT.md`, `AGENTS.md`, `README.md`, `ETAPA_08.md`, `ETAPA_09.md`,
`docs/sql-grammar.md`, `docs/sql.md`, `docs/transactions.md`, and `docs/demo.md`
carry the current boundary. Stage 7 audit descriptions remain historical and
continue to describe their deliberately lower-level execution contract.
