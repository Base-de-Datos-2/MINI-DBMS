# Stage 8 to Stage 9 integration handoff

**Recorded:** 2026-09-24  
**Stage 8 status:** closed at the engine boundary  
**Stage 9 status:** transaction-aware HTTP/UI integration implemented and verified
on 2026-09-25 (checklist at the end); formal closure pending

## Adapter inventory at handoff time (historical, 2026-09-24)

The Stage 9 demo already has one long-lived `api.database.Database` owner. That
legacy owner now constructs a `SessionCoordinator`, exposes `open_session()` and
`shutdown()`, and shares the same Catalog, storage and index handles among its
sessions. The HTTP adapter does not use those independent sessions yet:

- `EngineService` executes every request through `database.engine`, the
  compatibility default session.
- `_admission` is one process-wide nonblocking mutex. A competing request gets
  `ENGINE_BUSY`; an admitted request holds the mutex through prepare, execution,
  preview conversion, metrics and cleanup.
- The default parsed-statement allowlist contains only `SELECT`. Optional demo
  write mode adds `INSERT` and `DELETE`, still under global serialization.
- The result dispatcher serializes only row results and mutation command
  results. It has no branches for `DefinitionResult`, `ExplanationResult`, or
  transaction-control `TransactionReport` values.
- HTTP request identity is not a database session identity. There is no stable
  server-side session registry, transaction status response, or cancellation
  route connected to `SqlSession.cancel()`.
- The frontend has no transaction identity/state display and cannot submit a
  multi-request `BEGIN`/DML/`END` group as one owned session.

This inventory describes the adapter, not the engine. Stage 8 concurrency and
rollback are verified through `Database.open_session()` and real threads.

## Required session ownership

1. Keep exactly one database owner per server process and data directory.
2. Add a bounded server-side registry of opaque client session tokens to live
   `SqlSession` objects returned by `database.open_session()`. Never expose or
   trust the engine's numeric session ID as authorization.
3. A client keeps the same opaque token across separate calls. For example,
   these are three individual HTTP submissions owned by one `SqlSession`:

   ```text
   BEGIN TRANSACTION
   INSERT INTO t VALUES (1)
   END TRANSACTION
   ```

4. Serialize calls per session and return a structured session-busy response
   for a simultaneous call on the same token. Independent tokens may execute
   concurrently and wait in the Stage 8 lock manager.
5. Closing a client session must close its cursor, abort any open group, release
   locks, and then remove the registry entry. Server shutdown must stop new
   sessions, call the bounded database shutdown path, and close the owner only
   after safe-point cleanup.
6. A missing, expired, or closed token must fail without creating a replacement
   transaction implicitly. Registry bounds and any idle-expiry policy must be
   visible configuration with deterministic tests.

## Admission-lock migration rule

Preserve the current global admission guard until the complete adapter below is
implemented and its concurrent HTTP tests pass. When transaction requests are
enabled, do not hold that mutex while a statement waits for a logical lock. A
blocked statement may depend on `END TRANSACTION` or `ROLLBACK` arriving through
another HTTP request; keeping global admission during the wait would prevent
the blocker from completing.

The replacement should use a short registry/lifecycle mutex only while looking
up or changing session ownership. SQL execution then occurs outside that mutex
through the selected `SqlSession`. Remove or narrow `_admission` only in the
same reviewed change that proves all result cleanup, owner lifecycle and
concurrent request behavior.

## Result and error contract to add

The adapter needs exhaustive dispatch over the current engine result families:

| Engine value | HTTP result kind | Required facts |
|---|---|---|
| `QueryResult` | `rows` | Ordered columns, bounded rows/bytes, complete/partial state, plan and metrics; always close the cursor. |
| `CommandResult` | `command` | Affected rows, transaction ID and whether the result is provisional or committed. |
| `DefinitionResult` | `definition` | Created table definition and durable publication outcome. |
| `ExplanationResult` | `explanation` | Prepared plan, ANALYZE execution report when present, partial failure and transaction context. |
| `TransactionReport` | `transaction` | Transaction/session ID, state, final outcome, held/requested resources, blocker IDs, waits, undo counts, cause and warnings. |

At minimum, freeze and test stable responses for:

| Engine condition | Suggested HTTP status/code | Client behavior |
|---|---|---|
| Concurrent call on one session | `409 SESSION_BUSY` | Finish or cancel the in-flight call; do not replay a mutation automatically. |
| Statement waiting for another transaction | Request remains pending with bounded server timeout; optional status shows blockers | Allow the blocker to submit END/ROLLBACK through its own session. |
| Deadlock victim or ordinary group abort | `409 TRANSACTION_ABORTED` with cause and final state | Retry the complete business transaction only when the application chooses. |
| Lock timeout | `409 LOCK_TIMEOUT` | Report the aborted attempt; never claim commit. |
| Invalid BEGIN/END/ROLLBACK lifecycle | `409 TRANSACTION_PROTOCOL` | Keep the documented engine state and show the actionable protocol message. |
| Cooperative cancellation | `409 TRANSACTION_CANCELLED` after safe-point acknowledgement | Display the terminal abort outcome and release owned resources. |
| Owner quarantine or shutdown | `503 ENGINE_UNAVAILABLE` | Disable execution until controlled reopen/repair. |

Do not serialize Python tracebacks, local paths, undo filenames, or raw exception
objects. Preserve request IDs and the existing SQL location envelope.

## Cancellation and disconnects

- A cancellation endpoint or disconnect handler resolves the client token and
  calls `SqlSession.cancel()`; it does not close shared database handles.
- Cancellation is complete only after the executing request acknowledges its
  abort/close result. A dropped network connection alone is not evidence that
  engine work stopped.
- SELECT preview code must close `QueryResult` in every success, truncation,
  error and disconnect path. For an explicit group, cursor close keeps logical
  locks until a later END/ROLLBACK; for an implicit SELECT it ends the group.
- Server shutdown uses `Database.shutdown(timeout_seconds=...)` and reports an
  unavailable state if bounded cleanup cannot finish safely.

## Transaction status in the UI

Show the opaque client session, current transaction ID, `IDLE`/`ACTIVE`/terminal
state, whether the last command is provisional, wait duration and blocker IDs,
and the final commit/abort cause. Keep query I/O, undo I/O and lock-wait metrics
separate. The UI must never turn an aborted provisional mutation into a
successful row count or describe ordinary in-process undo as crash recovery.

## Verification checklist

Implemented and verified on 2026-09-25 (`api/sessions.py`,
`api/engine_service.py`, `tests/api/test_sessions.py`, frontend session bar).
Evidence and limits: `docs/ETAPA_09_REVISION_2026_09_25.md`.

- [x] Stable token reuses one `SqlSession` across separate BEGIN/DML/END calls
  (`test_begin_insert_end_across_separate_requests_form_one_group`).
- [x] Two tokens can read concurrently and independent-table writers overlap
  (`test_readers_share_and_independent_table_writers_overlap`, and the
  unrelated read served while another request waits).
- [x] A blocked request does not prevent its blocker from committing or rolling
  back (`test_a_blocked_request_does_not_prevent_its_blocker_from_committing`;
  two real browser tabs).
- [x] Same-session reentrancy returns `SESSION_BUSY` without changing the group
  (same test).
- [x] Row, command, definition, explanation and transaction results serialize
  exhaustively (`EngineService._dispatch`; EXPLAIN/ANALYZE and definition tests).
- [x] Provisional command results change to committed only after END succeeds
  (INSERT inside a group reports `provisional: true`; END reports `COMMITTED`).
- [x] Deadlock, timeout, automatic abort, cancellation and quarantine map to
  truthful responses (deadlock, lock-timeout, execute-error, cancel, shutdown
  and quarantine tests).
- [x] Early preview close, execution error, disconnect, session close and
  server shutdown leak no cursor, lock, worker or undo artifact (session close,
  expiry and shutdown tests reopen cleanly; a real `Ctrl+C` with a waiting
  request left no undo/unclean artifact). A dropped connection lets the
  request finish and close its cursor; an explicit group then keeps its locks
  until END/ROLLBACK, session close (tab close sends it) or idle expiry. A real
  network drop was not simulated.
- [x] Default SELECT-only mode and optional-write policy remain server
  enforced (policy from the AST; a refused statement never reaches the group).
- [x] The existing API suite, new concurrent HTTP schedules and frontend build
  all pass before `_admission` is narrowed. It now serializes only sessionless
  calls on the shared default session.
