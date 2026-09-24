# Stage 8 Tasks 8.19–8.22 — remaining lifecycle integration

**Date:** 2026-09-24. **Scope:** standalone CREATE, EXPLAIN/ANALYZE,
transaction telemetry, cooperative cancellation, and orderly owner shutdown.

## Implementation

| Task | Result |
|---|---|
| 8.19 | Standalone CREATE obtains logical schema X before binding/publication and retains it through success or compensated cleanup. `MetadataGate` adds a fair, short reader/writer boundary: managed engine `prepare`/`describe` and metadata lists use read; CREATE uses write across Catalog, runtime, resource-map, and manifest publication. Existing data sessions retain schema S, so CREATE cannot replace or close a borrowed permanent handle. CREATE inside an explicit group still aborts the complete group without implicit commit. |
| 8.20 | Plain EXPLAIN keeps the real planner and never instantiates its SELECT operators. ANALYZE acquires every SELECT source, executes exactly one fresh `PhysicalPlan`, closes it before implicit completion, and retains explicit locks through END/ROLLBACK. `ExplanationExecutionReport` now carries lock-wait, planning, and execution time plus transaction ID/state. `AnalysisExecutionError.report` preserves measured partial runtime evidence and is updated with the final abort outcome. |
| 8.21 | `TransactionObservability` records owner-sequenced transaction, logical-lock, physical-latch, query-I/O, and undo-I/O events. Metrics expose session/transaction identity, live/final state, held/requested resources, accumulated real wait, blockers, deadlock/timeout/cancel cause, captured/restored bytes, completion duration, planning/execution time, context-attributed query I/O, and outcome. The event deque is capped at 4,096 and reports its capacity and eviction count. `PhysicalPlan` now receives completed permanent page transfers through a context-local callback keyed to its actual source managers, so overlapping plans cannot charge each other's shared `PageManager` counters. Snapshot/restore traffic stays in `undo_io`. |
| 8.22 | `SqlSession.cancel()` can run without the non-reentrant call guard. It cancels a queued lock request immediately and sets a cooperative flag checked before/after synchronous execution and at each physical-plan row boundary. Cursor cancellation flows through normal result failure cleanup and whole-group abort. Compatibility `close()` remains fail-fast. `SqlSession.shutdown()` and both database owners' `shutdown()` request cancellation, wait to a finite caller-provided deadline, close results, abort groups, and only then allow permanent handles to close. No forced worker termination is used; the coordinator owns no background workers. |

## Public diagnostics

- `SessionCoordinator.transaction_metrics(TransactionId)` returns a live or
  terminal immutable `TransactionMetrics` snapshot.
- `SessionCoordinator.trace(transaction_id=..., session_id=...)` returns an
  immutable `TraceSnapshot`; `truncated` and `truncated_events` disclose bounded
  retention.
- Terminal `TransactionReport.metrics` contains the final snapshot.
- `ExplanationExecutionReport` adds `lock_wait_seconds`, `transaction_id`, and
  `transaction_state`. Existing Stage 7 fields and SELECT-only plan children are
  unchanged.
- `SqlSession.shutdown(timeout_seconds=...)` and
  `Database.shutdown(timeout_seconds=...)` are the bounded cancellation paths.
  `close()` preserves its established immediate refusal for a busy call.

## Failure and safety boundaries

- A CREATE duplicate or validation failure after a schema wait observes the
  newly published metadata, aborts its own implicit transaction, and leaves no
  second file/resource registration.
- Cancellation is cooperative. The controller never closes a shared handle
  while the executor still owns the call guard. If the deadline expires,
  shutdown raises `SessionBusyError` and leaves owner handles open.
- Failed physical restoration remains `ABORT_FAILED`; shutdown preserves its
  terminal report, quarantine, and undo artifacts instead of claiming cleanup.
- The trace is diagnostic evidence, not WAL. It is neither persisted nor used
  for crash recovery.
- Multi-process locking, WAL/redo, crash-atomic multi-file commit, transactional
  DDL, and Stage 9 request-session identity remain outside this block.

## Focused evidence

`tests/transactions/test_lifecycle_integration.py` covers:

- CREATE waiting for a live schema reader while the reader remains valid;
- two concurrent same-name CREATE attempts with exactly one publication;
- explicit-group CREATE rejection restoring its earlier INSERT;
- pure prepare blocked from observing an in-progress CREATE publication;
- ANALYZE waiting for a writer and reporting separate timings;
- ANALYZE read-your-writes and explicit lock retention;
- failed analysis partial evidence and final ABORTED state;
- real lock/query/undo trace categories and bounded trace eviction;
- waiter and streaming-cursor cancellation with peer reuse; and
- orderly database shutdown restoring an open group before fresh reopen.

The focused file passes **7 tests**. The complete `tests/transactions` directory
passes **81 tests**. The query/transaction/database/API gate passes **515 tests
in 218.20 seconds**. Architecture plus focused lifecycle/plan coverage passes
**47 tests in 18.60 seconds**. The final complete command
`.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider` passes
**2,821 tests in 1,121.74 seconds**. `compileall` and `git diff --check` also
pass; Git reports only the repository's expected LF-to-CRLF notices.

## Follow-on completion

Tasks 8.23–8.26 provide the controlled isolation/atomicity matrices and the
unsafe/protected threaded demonstration. Tasks 8.27–8.30 add bounded stress,
the complete regression, the Stage 9 handoff, documentation synchronization,
and the closure audit. See `docs/ETAPA_08_TASK_8_23_8_26.md`,
`docs/ETAPA_08_STAGE_9_HANDOFF.md`, and `docs/ETAPA_08_AUDIT.md`. The Stage 9
HTTP exclusive admission guard remains until that request/session adapter is
explicitly implemented and verified.
