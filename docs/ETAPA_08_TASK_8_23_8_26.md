# Stage 8 Tasks 8.23–8.26 — controlled evidence and demonstration

**Date:** 2026-09-24  
**Checkout base:** `cddb1e45191f0186d04c354bfec2918ad23b8bb9` plus the current uncommitted Stage 8 work  
**Runtime:** Python 3.12.4, pytest 8.4.2

## Delivered scope

| Task | Evidence |
|---|---|
| 8.23 | `tests/transactions/test_controlled_evidence.py` uses barriers, events, mutation-entry probes, lock snapshots, and bounded future joins. It verifies overlapping S holders, FIFO writer fairness, S/X and X/X exclusion, repeatable range reads, phantom prevention, dirty-read prevention, joins, independent tables, and empty terminal lock state. Existing focused lock/session tests cover reacquisition, two-upgrade cycles, timeouts, cancellation, primary-key conflicts, and victim cleanup. |
| 8.24 | The new tests inject failures at snapshot capture, base write, index write, and DELETE spool discovery, then compare rows, index validity, and exact physical bytes. They also preserve an unrelated committed table and reopen with a fresh owner. Existing Stage 8 tests cover commit flush failure, post-write failure, partial DELETE, sequential/index rebuild and RID movement, failed restore quarantine, CREATE publication compensation, and clean commit/abort reopen. |
| 8.25 | `demos/transactions_demo.py` creates disposable engine databases and runs two real SQL workers. Its private demo-only adapter constructs uncoordinated `SqlEngine` facades; it does not add a production flag. Both workers read `0` behind a barrier. A harness mutex serializes each physical DELETE+INSERT pair, so the isolated logical race reproducibly ends at `1`. |
| 8.26 | The protected schedule uses separate normal sessions, explicit transactions, SELECT/DELETE/INSERT, and the same business computation. Both first attempts read `0` under S, the upgrades create a real cycle, the requesting victim aborts, and that worker retries the complete transaction from a fresh read. Two operations commit and the final value is `2`, equal to a separately executed serial oracle. Attempt evidence includes transaction ID, read/write values, outcome, failure type, blockers, and measured lock wait. |

## Controlled isolation matrix

| Schedule | Controlled evidence | Expected and observed outcome |
|---|---|---|
| S/S plus fairness | Two explicit readers reach a barrier with simultaneous S holders. An X request is observed in the lock queue before a later S request. A mutation-entry event proves the writer has not reached data access while blocked. | Both original readers complete. The writer runs before the late reader, and the late reader observes its committed row. |
| Repeatable range / phantom | A reader completes a range SELECT and retains S. An INSERT is observed queued; its mutation-entry event is unset. The reader repeats the range before END. | Both reads return the same rows. The INSERT runs only after END. |
| Dirty read | A writer inserts inside an explicit group and retains X. A second session's SELECT is observed queued. | The writer rolls back; the reader then returns no uncommitted row. |
| Join sources | An explicit join completes and retains S on both base tables. A writer against one source is observed queued. | The source writer waits until END. |
| Independent table | While the join-source writer is blocked, a third session inserts and commits on another table. | The unrelated commit completes without a database-wide execution mutex and survives. |
| Primary-key conflict | Existing `test_competing_primary_key_check_runs_after_x_lock` observes the second X waiter. | Commit exposes the duplicate and abort permits the waiting insert, according to the terminal action. |
| Upgrade deadlock | Both protected demo workers read under S, then DELETE requests X. | One requesting transaction is a reported `DeadlockVictimError`; abort cleanup releases its S before the survivor proceeds. |
| Serial outcome | The protected history contains two COMMITTED business operations and one ABORTED attempt. | Final `2` matches real serial reads `[0, 1]`; the unsafe completed writes read `[0, 0]` and end at `1`. |

The schedules do not infer blocking from elapsed time. Every blocked assertion
uses the lock manager's synchronized snapshot and, where relevant, an event at
the first storage mutation. Thread joins have finite deadlines.

## Atomicity and failure matrix

| Boundary | Evidence |
|---|---|
| Snapshot allocation/copy | New cross-table capture failure test plus `test_capture_quota_and_copy_failure_leave_no_partial_image`. |
| Base and index write | New parametrized explicit-group test; prior successful SQL and the partial failing statement restore to byte-identical files. A separate implicit index fault confirms one-statement abort, empty locks, and default-session reuse. |
| DELETE discovery spool | New injected append failure test; no target mutation survives and the prior group INSERT is removed. |
| RID movement/rebuild | `test_delete_rollback_restores_heap_sequential_bplus_and_hash`, `test_legacy_hash_and_clustered_sequential_restore_exact_files`, and the existing mutation rebuild-failure tests. |
| Commit flush | `test_commit_flush_failure_uses_undo_before_success`. |
| Restore/validation | `test_failed_second_table_restore_quarantines_owner_and_retains_images` and `test_restore_failure_cancels_waiter_before_lock_release`. |
| CREATE publication | `test_create_failures_remove_only_new_files_and_allow_a_later_create`, now reached through the coordinated default session, and the concurrent duplicate publication test. |
| Clean reopen | New peer-commit/capture-failure test, grouped rollback tests, and two-table commit reopen coverage. |

These checks demonstrate ordinary in-process rollback and clean reopen. They do
not demonstrate power-loss recovery, WAL replay, or crash-atomic multi-file
commit.

## Reproducible demo

From the repository root on Windows:

```powershell
.venv\Scripts\python.exe -W error -m demos.transactions_demo
```

On POSIX:

```bash
.venv/bin/python -W error -m demos.transactions_demo
```

The command uses a temporary directory and prints JSON. To retain the three
databases for inspection, pass an absent or empty directory:

```powershell
.venv\Scripts\python.exe -m demos.transactions_demo --directory transaction-demo-data
```

Expected invariant fields:

- `unsafe.attempts[*].read_value` is `[0, 0]` and `unsafe.final_value` is `1`;
- `protected.committed_business_operations` is `2`;
- `protected.aborted_attempts` is `1`, with one `DeadlockVictimError`;
- `protected.final_value` and `serial_oracle.final_value` are `2`;
- `protected_matches_serial_oracle` is `true`.

Transaction IDs, victim identity, blocker IDs, and timings can vary with the
thread schedule. The invariant history and result do not.

## Verification performed for this block

```text
.venv\Scripts\python.exe -m pytest tests\transactions\test_controlled_evidence.py -q -W error -p no:cacheprovider
9 passed in 4.47s

.venv\Scripts\python.exe -m pytest tests\transactions -q -W error -p no:cacheprovider
90 passed in 25.27s

.venv\Scripts\python.exe -m pytest tests\test_architecture.py tests\database\test_managed_database.py tests\query\test_mutation_maintenance.py tests\query\test_stage7_extension_acceptance.py -q -W error -p no:cacheprovider
52 passed in 15.78s

.venv\Scripts\python.exe -W error -m demos.transactions_demo
unsafe final=1; protected final=2; serial oracle final=2

.venv\Scripts\python.exe -m compileall -q engine api demos tests\transactions\test_controlled_evidence.py
passed

git diff --check
passed (only Git's existing LF-to-CRLF working-copy warnings)
```

Tasks 8.27–8.30 are complete: bounded stress is in
`tests/transactions/test_bounded_stress.py`, the request/session contract is in
`docs/ETAPA_08_STAGE_9_HANDOFF.md`, and the final regression and closure are in
`docs/ETAPA_08_AUDIT.md`.
