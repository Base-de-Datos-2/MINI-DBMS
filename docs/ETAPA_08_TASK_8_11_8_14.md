# Stage 8 Tasks 8.11–8.14 — physical undo and completion

**Date:** 2026-09-22. **Scope:** transaction-owned before-images, exact restore,
terminal commit/abort, and fail-closed restoration. SQL data statement routing
remains Task 8.15.

## Implementation

| Task | Result |
|---|---|
| 8.11 | `UndoStore` captures one base plus every declared index file after table X and pre-write flush. It reserves exact bytes against per-transaction/owner quotas and a free-space margin, limits concurrent captures to two, copies in at most 1 MiB chunks using one source and one target handle, hashes each image, fsyncs it, then publishes a complete descriptor. Failed copies remove unpublished images. |
| 8.12 | Abort closes only affected canonical storage/index handles, restores exact files and lengths, removes replacement candidates first observed during that transaction, then reopens existing factories. It checks base scan counts and every index's structural/base coverage, and bumps table resource generations. Other tables remain untouched. |
| 8.13 | END rejects an open result, validates and flushes every modified structure, transitions to COMMITTED while X is retained, then releases locks and discards images. A pre-success failure invokes full abort. Post-success cleanup errors are report warnings with retained artifact debt, never a rollback. Terminal cleanup can be retried. |
| 8.14 | Write/lock failures abort the whole group, including prior successful actions. Abort retains X until restoration and validation complete. A failed restore marks the owner unavailable and quarantines its lock domain before waiters can access data; the state is ABORT_FAILED and undo artifacts remain. Duplicate abort returns the same terminal report. |

The owner marker `.minidb_unclean` and a nonempty `.minidb_undo` reject a fresh
managed or legacy open. This detects interrupted operations without claiming
automatic crash recovery. Managed and legacy owner constructors accept an
`UndoLimits` value for controlled quota tests and deployments.

The internal `SqlSession.run_write(table_name, action)` entry point enforces
the lock/capture/abort sequence used by this block's tests. Its action is
table-scoped and uses canonical owner handles. SQL data statements through
`session.execute` still fail before effects; raw `Database.engine` retains its
Stage 7 compatibility behavior. Task 8.15 must route normal SQL statements
through these protections before public transactional data mode is claimed.

## Focused evidence

`tests/transactions/test_undo_completion.py` verifies whole-group rollback,
byte-for-byte Heap/B+ restore, multi-table commit and clean reopen, failure in
the second action, partial DELETE, B+ growth/page truncation, Hash growth,
Sequential reorganization and clustered RID changes, stale resource plans,
independent-table committed data, pre-success flush failure, post-success
cleanup debt, repeated abort/cleanup, quota/copy failures, bounded large-file
copy, owner quarantine, waiter cancellation, deadlock victim restoration, and
owned replacement artifact cleanup. ABORT_FAILED artifacts cannot be removed
through terminal cleanup and remain for external inspection. Tests use both
managed and legacy owners.

The focused command
`.venv\Scripts\python.exe -m pytest tests/transactions/test_undo_completion.py -q -W error -p no:cacheprovider`
passed **16 tests**. The transaction plus architecture gate passed **82 tests**
in 32.81 seconds. The final command
`.venv\Scripts\python.exe -m pytest tests -q -W error -p no:cacheprovider`
passed **2,803 tests in 1,246.29 seconds**. `compileall` and `git diff --check`
also passed; Git reported only the repository's expected LF-to-CRLF notices.

## Remaining boundary

This block proves in-process physical completion through controlled internal
actions. It does not yet make `Database.engine`, `SqlSession.execute` data
statements, the HTTP API, or direct storage helpers transactional. Explicit
and implicit SQL routing, cursor lifetime, programmatic write migration,
observability, and the full threaded demonstration remain Tasks 8.15 onward.
There is no WAL, redo, crash-atomic multi-file commit, or automatic recovery.
