# Stage 8 Tasks 8.15–8.18 — core SQL integration

**Date:** 2026-09-23. **Scope:** explicit and implicit execution for SELECT,
INSERT, DELETE, streaming cursors, and the existing Heap, Sequential, B+, and
Hash maintenance paths.

## Implementation

| Task | Result |
|---|---|
| 8.15 | Managed and definition-driven owner engines route `execute` through their default `SqlSession`; independent sessions use the same coordinator with separate result slots. Parsing precedes transaction effects. Resource intents are granted and revalidated before binding or runtime access. A stable plan whose runtime generation changed while waiting is refreshed, and a prepared query is rebound under its locks. Standalone statements use implicit groups; statements after BEGIN use the existing explicit group. |
| 8.16 | SELECT acquires schema S plus S for every distinct source before returning its lazy cursor. An implicit cursor commits its read-only transaction only at EOF or close. An explicit cursor releases operators and temporary files at EOF/close but retains logical grants through END/ROLLBACK. Every cursor call uses the session's non-reentrant guard; iterator/open/cleanup failure aborts its group. Existing external operators keep their per-execution contexts and budgets. |
| 8.17 | INSERT acquires table X before binding constraints and publishes the table's complete physical image before `MutationService` writes. Competing primary-key inserts therefore validate after the winner's terminal outcome. `CommandResult` exposes the protecting transaction ID and committed/provisional status. Managed `Database.insert` joins the default explicit group or runs as an implicit protected write. |
| 8.18 | DELETE holds table X from bounded target discovery through base/index maintenance and terminal completion. Failure aborts the complete explicit group. Rollback restores Heap and Sequential base files plus clustered B+, unclustered B+, and Extendible Hash adapters, then refreshes live registrations and prepared generations. |

`SqlEngine(QueryEnvironment)` remains available as an intentionally
uncoordinated lower-level Stage 7 facade for isolated fixtures. Engines owned
by either database owner install a session execution router. The internal
`SqlSession.run_write` hook remains only for earlier fault-injection tests and
uses a narrow dynamically scoped bypass so it cannot create a second
transaction inside an already protected callback.

## Failure and result semantics

- A successful implicit INSERT/DELETE commits before its `CommandResult` is
  returned. A command inside an explicit group remains provisional until END.
- An ordinary parse, bind, constraint, lock, iterator, mutation, or cleanup
  failure aborts the complete group and preserves the original exception with
  the terminal outcome attached as a note.
- Nested BEGIN, terminal control without an explicit group, a simultaneous
  session/cursor call, or END with an open result is a protocol error and does
  not silently complete the group.
- A cursor does not release an implicit read at `execute()` return. A writer
  remains queued after partial iteration and proceeds only after EOF/close.
- A prepared statement may survive physical rollback: execution rebuilds its
  bound plan under current handles after the waiter obtains the stable table
  resource.

## Focused evidence

`tests/transactions/test_sql_integration.py` covers the default engine route,
explicit own-write visibility, provisional/committed results, group rollback,
implicit and explicit cursor lock lifetime, same-session cursor serialization,
both competing-primary-key terminal outcomes, cursor failure rollback,
Heap/Sequential/B+/Hash DELETE restoration, external-sort cleanup, and managed
programmatic insertion.

The focused command
`.venv\Scripts\python.exe -m pytest tests/transactions/test_sql_integration.py -q -W error -p no:cacheprovider`
passed **11 tests**. The transaction/database/API regression gate passed
**191 tests in 66.25 seconds**. The query regression gate passed **316 tests in
128.87 seconds**. The complete warnings-as-errors suite passed **2,814 tests
in 1,029.55 seconds**. `compileall` and `git diff --check` also passed; Git
reported only the repository's expected LF-to-CRLF notices.

## Remaining boundary

Tasks 8.19–8.22 still provide the dedicated CREATE, EXPLAIN/ANALYZE,
observability, cancellation, and shutdown completion. The Stage 9 HTTP layer
keeps its exclusive admission guard until request-scoped session integration is
implemented and verified. Multi-process coordination, WAL, automatic crash
recovery, and crash-atomic multi-file commit remain outside Stage 8.
