# Stage 8 Tasks 8.3–8.6 — transaction foundation

**Checkout:** `main` at `bf381e3d98673509f928b4a95fe410658e5312c6`, with uncommitted Stage 8 Blocks 1–2 changes. **Status:** foundation implemented; S/X grants, undo and coordinated data execution remain Tasks 8.7 onward.

## Implemented boundary

| Task | Concrete implementation | Focused evidence |
|---|---|---|
| 8.3 | `engine/transactions/model.py`, `manager.py`, `errors.py`: immutable transaction IDs/state snapshots and reports, guarded monotonic owner-scoped allocation, terminal transitions, structured protocol/busy/timeout/deadlock/abort/unavailable errors. The manager can commit/abort only empty groups. | `tests/transactions/test_model.py` exercises valid/invalid transitions, terminal immutability, cross-thread IDs, capacity and error metadata. |
| 8.4 | `engine/transactions/session.py`, `ownership.py`: one coordinator per managed or legacy owner, independent SqlEngine/result slots and transaction identity per session, non-reentrant calls, session close without closing shared files, and duplicate-directory rejection in one process. Existing `Database.engine` remains the Stage 7 default facade. A shared fail-closed lock-manager boundary is reserved for Task 8.7. | `tests/transactions/test_sessions.py` covers independent sessions, busy calls, default compatibility, duplicate owners, legacy fixtures, close and empty-group cleanup. Existing API tests that opened additional owners now use separate disposable directories. |
| 8.5 | Handwritten parser/AST now accepts exactly `BEGIN TRANSACTION`, `END TRANSACTION` and `ROLLBACK`, with spans, comments, case folding, one optional final semicolon, and full-input rejection. Owner sessions dispatch controls; a raw Stage 7 SqlEngine rejects them before planning. | `tests/transactions/test_controls.py` covers accepted forms, malformed/unsupported variants, extra statements and raw-engine refusal. |
| 8.6 | `engine/transactions/resources.py`: schema/data access intents keyed by database and stable table identity, deduplicated aliases, deterministic table order, base plus every associated index file, and runtime generation invalidation. Managed CREATE registers its new file set; legacy definition-driven owners supply explicit paths. Planning reads metadata only and performs no uniqueness check or DELETE discovery. | `tests/transactions/test_resources.py` covers self/multi-table joins, equality/ranges/missing keys, INSERT/DELETE X, EXPLAIN versus ANALYZE, CREATE schema X, controls, complete index files, legacy organizations and stale plans. |

Control-only calls through `Database.open_session()` can begin and end/rollback an **empty** group. Data statements through this session are rejected before binding or mutation; in an active empty group, the refusal aborts the group. Direct `Database.engine` SQL data calls keep their existing Stage 7 behavior and are not presented as concurrent transactions. This gate is intentional: accepting grouped writes before S/X locks and undo would make false atomicity claims.

## Verification

- `.venv\Scripts\python.exe -m pytest tests/transactions -q -W error -p no:cacheprovider`: **31 passed** after the new resource/ownership checks.
- `.venv\Scripts\python.exe -m pytest tests/query/test_parser_contract.py tests/api/test_engine_service.py tests/api/test_http.py tests/transactions -q -W error -p no:cacheprovider`: **144 passed** after updating tests for the new syntax and one-owner contract.
- `.venv\Scripts\python.exe -m pytest tests/query tests/database tests/api tests/transactions -q -W error -p no:cacheprovider`: **465 passed in 220.55 seconds (0:03:40)**. This is the current-checkout compatibility gate for the changed parser and both database owners.
- `.venv\Scripts\python.exe -m compileall -q engine api tests/transactions` and `git diff --check`: passed. Git emitted only existing LF-to-CRLF checkout and inaccessible global-ignore warnings.

The original Stage 7 audits remain historical. Task 8.27 still owns the complete cross-stage regression gate. The Stage 9 HTTP guard remains active and no HTTP transaction support is claimed.
