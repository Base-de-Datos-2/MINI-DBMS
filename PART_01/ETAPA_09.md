# ETAPA_09.md

## Stage 9 — API and Frontend: Current Contract and Implementation Plan

**Revision:** 2026-09-30; synchronized with the implemented Stage 8 session integration
**Part:** Relational Database  
**Historical starting point:** Stage 7 reported complete; Stage 8 was not implemented
**Current objective:** Maintain the real four-panel GUI and verified transaction-aware HTTP/session contract
**Status:** Emergency demo ready (2026-09-18); Stage 8 engine work closed (2026-09-24); transaction-aware HTTP/UI integration implemented and verified (2026-09-25); **formally closed on 2026-10-01** (`docs/ETAPA_09_AUDIT.md`). Historical emergency evidence is in `docs/ETAPA_09_AVANCE.md`; current usage is in `docs/demo.md`, and the completed integration checklist is in `docs/ETAPA_08_STAGE_9_HANDOFF.md`. Integration evidence is in `docs/ETAPA_09_REVISION_2026_09_25.md`; the 2026-09-30 corrections are recorded in `docs/ETAPA_09_REVISION_2026_09_30.md`.
**Execution mode:** One backend process/worker; independent client sessions execute concurrently through Stage 8 locks; only sessionless calls use exclusive admission; writes disabled by default
**Follow-up:** Stage 10 experiments and delivery (`PART_01/ETAPA_10.md`)

The emergency sequence below records why the GUI preceded Stage 8. Sections
5–9 and 11–13 describe the current implementation contract and maintenance
checks. They must not be used to restore the former global admission policy.

## 1. Authorized sequencing exception

The team has explicitly chosen to implement an initial Stage 9 before Stage 8. This is an authorized change in implementation order, not permission to remove transaction/concurrency requirements or mark them complete. Do not stop solely because an older stage-order pointer says Stage 8 must come first.

The authorized order was:

1. Verify the Stage 7 interfaces needed by the presentation.
2. Implement the required emergency Stage 9 tasks below.
3. Present the working GUI and identify pending transaction/concurrency work.
4. Implement Stage 8 and its required demonstration. **Completed 2026-09-24.**
5. Complete Stage 9 transaction/session integration and rerun integration tests. **Implemented and verified 2026-09-25.**
6. Complete Stage 10 experiments and final delivery.

The emergency milestone is **Stage 9 demo ready**, not **Part 1 complete**. REQUIREMENTS.md still requires transactions, concurrency, and experiments; its Part 1 milestone is not waived by this plan. If today's evaluation expects all of Part 1, this presentation remains a partial delivery.

The team also explicitly chose a handwritten SQL lexer and parser. Preserve the completed Stage 7 parser; do not introduce Lark, another parser generator, or a separate frontend/API SQL parser.

## 2. Sources, authority, and assumptions

This plan uses the current REQUIREMENTS.md (GUI requirements in Section 8), PLAN.md (Stage 9 in Section 14), PROJECT_CONTEXT.md, AGENTS.md, and the revised ETAPA_07.md. The academic scope remains unchanged. This document is an implementation plan, not a new assignment specification.

Stages 7 and 8 are formally closed. Task 9.1's original inspection is historical; follow-up work must inspect the current owner/session entry points and existing tests before changing the adapter.

The handwritten-parser decision and emergency sequencing exception are recorded in the coordination documents. Keep current status pointers synchronized without changing REQUIREMENTS.md to describe team choices as academic obligations.

The existing recommended stack is Python/FastAPI and React/TypeScript/Vite. Reuse it if already adopted. Preserve a working equivalent stack; do not migrate frameworks during the emergency. Use installed/configured versions and existing scripts rather than upgrading dependencies for this milestone. A plain textarea is sufficient; Monaco and a graph library are optional.

The attached storage, index, recovery, spatial, and distributed-database materials do not add frontend features to this emergency scope. Do not introduce later-course functionality because those files are available.

## 3. What the instructor should be able to see

The live interaction must use real disk-backed project data and the real engine:

- inspect loaded tables, columns, types, and available index metadata;
- type or select one supported SQL statement;
- execute it through the API and handwritten SQL engine;
- view a bounded table of returned rows;
- inspect the actual plan, selected access paths, and available measurements;
- submit an invalid query and receive a useful error;
- repeat a valid query after the error without restarting the application.

All four required panels belong in the minimum demonstration:

| Panel | Implemented behavior | Optional later enhancement |
|---|---|---|
| Files | Loaded tables/structure from Catalog and bounded GUI creation/CSV import in write mode | Rich storage visualization |
| Query | SQL textarea, Execute action, error feedback, verified presets | Syntax highlighting, completion, history persistence |
| Results | Ordered columns, bounded rows, empty/loading/error states, provisional commands and transaction outcomes | Export and server-side continuation |
| Execution Plan | Real operators, child relationships, indexes, relevant details | Animated graph and advanced profiling |

A schema panel is the Files panel, not a fifth substitute. Preset queries must fill the editor and execute through the same API as manually entered SQL. Production UI data must never come from hard-coded expected results or a mock database.

## 4. Priorities and time control

| Priority | Meaning | Tasks |
|---|---|---|
| P0 | Required for an honest working presentation | 9.1–9.15 and 9.18 |
| P1 | Add only after all P0 checks pass | 9.16–9.17 |
| Follow-up | After the implemented integration | Formal Stage 9 closure and Stage 10; Stage 8 closed 2026-09-24 and HTTP/session integration was verified 2026-09-25 |

Work in vertical increments:

1. **Foundation:** inspect contracts, prepare fixtures, define limits, own engine lifecycle and admission.
2. **First visible success:** API query response plus editor/results, using one real SELECT.
3. **Complete required panels:** Files, actual plan, clear errors, and verified presets.
4. **Freeze and rehearse:** integration tests, clean restart, actual browser run, and documented launch steps.

Set a feature-freeze time before the presentation and reserve the final portion of available time for rehearsal. Do not estimate implementation duration before Task 9.1 reveals existing work. Drop P1 features first when time is short. A broken P0 path is repaired or reported as incomplete; it is never replaced by fabricated data.

Local presentation remains the supported deployment. Authentication, public deployment, editor plugins, visual graph layout, and benchmark dashboards are outside this stage's current scope. Bounded CSV import and GUI table creation are implemented; preserve them and their engine boundaries.

## 5. Current ownership, admission, and statement policy

### Engine/session ownership

- One backend process owns the demonstration engine and its data directory.
- A bounded registry maps opaque `X-Session-Token` credentials to independent Stage 8 `SqlSession` objects. Defaults: 16 sessions, 300-second idle expiry, and a 15-second sweep interval.
- One call per token owns that session through parsing, execution, preview conversion, measurements, and cursor cleanup. A concurrent call on the same token fails with `SESSION_BUSY`; independent tokens may execute concurrently.
- Requests without a token use the shared default session under `_admission`. A competing sessionless call fails promptly with `ENGINE_BUSY`; BEGIN/END/ROLLBACK without a token fail with `TRANSACTION_PROTOCOL`.
- SQL runs outside the registry mutex. A waiting request must allow its blocker to submit END/ROLLBACK through another session; do not widen `_admission` to client-session requests.
- Catalog routes use the engine's short metadata gate without execution admission or table data locks. Physical counts may include provisional changes and are labeled accordingly. Health uses cached state and registry configuration.
- No CLI, second server, background importer, or external process accesses that data directory during the demo. A process-local guard cannot protect those accesses.
- Run one worker with automatic reload disabled. Worker count does not prevent simultaneous handlers; per-session call ownership and sessionless admission are still required.
- Keep the synchronous engine work and guard ownership in one coherent execution context. Do not let an async request cancellation release a guard while a worker thread continues using the engine.
- On a browser disconnect, the server finishes the statement and closes its cursor. An explicit group retains logical locks until END/ROLLBACK, session close, or idle expiry. Tab close sends a best-effort keepalive DELETE; a real network-drop schedule remains unverified.
- If cleanup cannot establish a usable engine state, mark the service unavailable for engine requests until a controlled restart/repair. Do not silently continue with a leaked cursor or corrupt state.

The sessionless guard prevents reentrancy on the compatibility default session.
Stage 8 supplies grouping, rigorous table S/X locking, deadlock handling,
in-process undo, cancellation, and terminal outcomes. The mandatory engine
thread demonstration is `demos/transactions_demo.py`; cross-process sharing,
WAL, and crash recovery remain unsupported.

### Statement policy

Default to **read-only** SQL: SELECT, EXPLAIN SELECT, and EXPLAIN ANALYZE SELECT. With `--allow-writes`, INSERT/DELETE and the GUI table-creation route are enabled. BEGIN/END/ROLLBACK are allowed in both modes with a client session. Enforce policy using the existing handwritten parser's AST before execution; do not use text prefixes, regexes, or frontend buttons.

Parse the complete submission under the one-statement rule. Pass allowed SQL to `SqlSession.execute` as text so execute errors, including malformed SQL inside a group, follow the engine's abort semantics. Policy refusals never reach the engine and preserve the group. `COMMIT` remains unsupported. SQL CREATE is disabled in the legacy demo owner; standalone GUI creation uses the selected session's schema-change path and is refused before execution while that session has an open group.

INSERT/DELETE require Task 9.16's explicit write configuration. Their row counts are provisional inside an explicit group and committed only after successful END. An implicit mutation commits before returning. The API restriction does not remove engine features or academic requirements.

## 6. Adapter architecture and resource contract

Keep the API thin. It validates transport input, applies the presentation policy, calls the existing engine, converts results to JSON, and releases resources. It must not implement SQL semantics, storage, indexes, joins, sorting, or aggregate algorithms.

The frontend depends on HTTP contracts, not Python internals. The engine remains callable independently of FastAPI and React.

### Bounded preview, not a persistent server cursor

One response contains a bounded preview. Keep engine streaming inside the adapter and close the cursor before returning. Client sessions persist across requests; row cursors do not. Early close ends an implicit SELECT but preserves an explicit group's logical locks until END/ROLLBACK.

Implemented defaults (`api/schemas.py`):

| Limit | Value | Meaning |
|---|---:|---|
| Displayed rows | 100 | Default preview count |
| Maximum requested preview | 500 | Hard server-side cap, independent of client validation |
| SQL text | 32 KiB UTF-8 | Transport cap; distinct from the engine's 65,536-character lexer limit |
| Encoded response | 1 MiB | Explicit JSON byte budget, including metadata |
| Plan nodes/depth | 128 / 32 | Prevent oversized or recursive descriptors |
| HTTP body | 64 KiB; 17 MiB for the two import routes | CSV content has its separate cap |
| CSV | 8 MiB / 10,000 data rows | Bounded GUI import |

These are project defaults, not instructor requirements. Adapt them to verified schema/record limits. A row limit is not a execution-time or total engine-memory limit: sorting/grouping/joining can perform substantial work before returning the first row. Preserve Stage 6 memory/temp budgets and use rehearsed fixtures.

For a row cap N, consume at most N+1 output rows. If the extra row exists, report truncation and retain only N. If EOF occurs, report complete consumption. This also distinguishes exactly N rows from more than N. Count the extra row as consumed in measurements, not as displayed.

Apply the byte cap incrementally as well. Reserve space for response metadata and delimiters; never build an unbounded response before checking its size. If metadata or a single row cannot fit, return a structured result-size error after cleanup. Do not silently truncate strings or alter values to fit. If accumulated rows hit the byte cap, return the accepted prefix with explicit truncation and the corresponding reason.

Do not call unconditional `fetchall`, count every remaining row, rerun the query to infer totals, append an unsupported SQL LIMIT, or sort/group results in the frontend. Browser pagination of the already returned preview is optional and must not imply access to the entire result.

## 7. Implemented HTTP contracts

The following routes are implemented in `api/app.py`. Preserve compatible transport contracts when making follow-up changes.

| Method and route | Responsibility | Engine admission needed? |
|---|---|---|
| GET /api/health | Cached startup/readiness and execution mode | No engine access |
| GET /api/tables | Loaded table summaries from Catalog | Metadata gate only |
| GET /api/tables/{table_id} | Columns, types, organization, indexes when available | Metadata gate only |
| POST /api/sessions | Open a client session and return its opaque token | Short registry ownership |
| GET /api/session | Transaction/lock/wait state for the token | No execution admission |
| POST /api/session/cancel | Request cooperative cancellation | No execution admission |
| DELETE /api/session | Close session and abort its open group | Session cleanup |
| POST /api/query | Execute once, return bounded results and actual plan | Per-session call guard; exclusive admission only without a token |
| POST /api/import/preview | Parse CSV and infer types without loading it | No engine access |
| POST /api/tables | Standalone GUI table creation/import in write mode | Selected session and schema X; exclusive admission only without a token |

IDs are Catalog identifiers, never arbitrary filesystem paths. Do not expose file-opening, command-running, or reset endpoints. CSV import is bounded and uses the project's own storage/index builders.

Illustrative request:

```json
{"sql":"SELECT name FROM students WHERE age > 20 ORDER BY name;","max_rows":100}
```

The response should specify the following fields. Exact names may follow an existing convention:

| Field | Meaning |
|---|---|
| request_id | Correlates this operation's result, error, plan, and logs; not an idempotency guarantee |
| kind | `rows`, `command`, `explanation`, `transaction`, or `definition` (exhaustive serialization; SQL CREATE remains disabled) |
| columns | Ordered descriptors: position/id, display name, logical type, encoding |
| rows | Arrays aligned with columns, preserving duplicate names and row multiplicity |
| returned_rows | Number actually included in the response |
| truncated / truncation_reason | Whether preview stopped early; `row_limit`, `byte_limit`, or null |
| result_complete | Whether output was exhausted successfully, not whether every possible query phase ran |
| total_rows | Exact only when exhausted and known; otherwise null |
| affected_rows | Actual successful command count only; null for SELECT |
| execution_plan | Descriptor from the prepared/executed engine plan, including actual runtime fallbacks when available |
| plan_status | Whether plan is prepared, execution-observed, or unavailable |
| metrics | Measured values with scope and completion flags; unavailable counters are null/omitted |
| mode | `read-only` or legacy wire value `serialized-writes`; the latter enables writes and does not imply global serialization of client sessions |
| session | Final client-session state when a token was supplied |
| transaction / transaction_report | Command provisional/committed outcome, or control-report state, resources, waits, undo, and cause |

A successful response with an early-closed preview has `result_complete=false`. EOF-complete empty results have zero rows, the actual column schema, and `result_complete=true`. An execution exception produces an error, not a success response with the rows accumulated so far.

Preserve engine value semantics. Rows are arrays so duplicate joined column
names cannot overwrite one another. Booleans remain booleans; integers outside
JavaScript's safe range are decimal strings, and non-finite floats use
`Infinity`/`-Infinity`/`NaN` strings with column encoding metadata. The engine
does not support NULL or an exact-decimal SQL type; do not imply those types
are implemented.

### Error mapping

| Condition | HTTP status/code | User-facing meaning |
|---|---:|---|
| Malformed transport input | 422 INVALID_REQUEST | Request fields are invalid |
| SQL lexical/syntax/semantic error | 422 | Query is invalid; include existing source location where available |
| Statement disabled in demo mode | 403 | Query type is not enabled in this presentation mode |
| Missing table metadata resource | 404 | Selected Catalog object does not exist |
| Another sessionless operation active | 409 ENGINE_BUSY | Default session busy; use a client session or wait |
| Concurrent call on one token | 409 SESSION_BUSY | Finish or cancel its current call; no automatic replay |
| Missing/expired/closed token | 404 SESSION_NOT_FOUND | Open a new session explicitly; do not replay the statement |
| Registry capacity | 429 SESSION_LIMIT | Close a session or wait for expiry |
| Invalid transaction lifecycle or control without token | 409 TRANSACTION_PROTOCOL | Preserve the documented group state |
| Deadlock/abort, cancellation, lock timeout | 409 TRANSACTION_ABORTED / TRANSACTION_CANCELLED / LOCK_TIMEOUT | Inspect terminal transaction outcome and cause |
| Oversized request | 413 | SQL body exceeds the limit |
| Response cannot fit bounded encoding | 422 | Result exceeds the presentation response limit |
| Engine not ready or unusable | 503 | Controlled restart/repair needed |
| Unexpected engine/server failure | 500 | Operation failed; include a diagnostic request ID |

Use a consistent error envelope with code, message, request ID, optional SQL location, and transaction details. Record technical details in server logs; show no Python tracebacks or local paths. `details.group_aborted` means the session lost its group, not proof of restoration. Claim successful undo only for confirmed `ABORTED`. For `ABORT_FAILED`, show failed restoration and quarantine requiring inspection/repair; never claim all changes were undone or locks released. Missing/other outcomes must remain explicitly unconfirmed. Query I/O, undo I/O, and lock waits retain separate scopes.

## 8. Task sequence and maintenance checks

Tasks 9.1–9.18 originated in the emergency plan. The actions below are
synchronized with the implemented adapter; they remain verification guides
for follow-up changes. Dated evidence preserves the original milestone.

| Task | Work | Priority | Dependencies |
|---|---|---|---|
| 9.1 | Inspect Stage 7 and document the sequencing exception | P0 | User-reported Stage 7 completion |
| 9.2 | Freeze demo contracts and limits | P0 | 9.1 |
| 9.3 | Prepare persistent demonstration fixtures | P0 | 9.1–9.2 |
| 9.4 | Implement API startup/shutdown and engine adapter | P0 | 9.1–9.2 |
| 9.5 | Enforce per-session ownership, sessionless admission, and statement policy | P0 | 9.4, closed Stage 8 |
| 9.6 | Expose Catalog metadata | P0 | 9.3–9.5 |
| 9.7 | Expose bounded query execution and actual plan | P0 | 9.3–9.5 |
| 9.8 | Map errors and expose measured statistics | P0 | 9.7 |
| 9.9 | Build frontend shell and typed API client | P0 | 9.2 |
| 9.10 | Connect Files and Query panels | P0 | 9.6–9.9 |
| 9.11 | Implement Results panel and preview states | P0 | 9.7–9.10 |
| 9.12 | Implement actual Execution Plan panel | P0 | 9.7–9.11 |
| 9.13 | Add verified presentation queries | P0 | 9.3, 9.10–9.12 |
| 9.14 | Run focused integration and browser checks | P0 | 9.5–9.13 |
| 9.15 | Rehearse clean startup and freeze demo | P0 | 9.14 |
| 9.16 | Enable verified INSERT/DELETE only by configuration | P1 | P0 checks and Stage 8 transaction guarantees |
| 9.17 | Optional readability and usability polish | P1 | All P0 functional checks |
| 9.18 | Document milestones, completed Stage 8 integration, and remaining closure | P0 | Verified outcomes; update after follow-up changes |

Add relevant tests with each task. Task 9.14 is a focused integration gate, not permission to defer testing until the end.

## 9. Detailed tasks

### Task 9.1 — Verify the completed engine and authorized exception

**Actions:**

- Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, ETAPA_08.md, and this stage document.
- Record Stage 7 and Stage 8 as formally closed and the Stage 9 session integration as implemented. Verify affected engine/API tests rather than assuming interfaces match illustrative names.
- Locate parsing/preparation, statement kind, execution, schema, plan descriptors, counters, cursor close/context management, Catalog lookup, and fixture setup.
- Map actual APIs to the adapter responsibilities. Determine whether metrics are global, execution-local, or inclusive of child operators.
- Identify existing API/frontend modules, package versions, scripts, and tests. Reuse them.
- Check ordinary mutation failure semantics, but keep HTTP writes disabled initially.
- Record the approved sequence in repository progress documents and the manual-parser decision where stale. Preserve historical completed stages and academic requirements.

**Evidence:** A short compatibility table and actual commands/results for the relevant baseline tests.

**Acceptance:** The implementer knows which engine methods to call and does not need to reconstruct engine logic in HTTP handlers. A missing interface is addressed with a narrow adapter or reported as a prerequisite gap.

### Task 9.2 — Freeze the smallest presentation contract

**Actions:**

- Adopt endpoint names, JSON schema, preview row/byte limits, supported encodings, error mapping, and result-completion semantics.
- Record single-process ownership, per-token busy rejection, sessionless admission, read-only policy, and cursor/group lifetimes.
- Decide existing frontend stack and local origin arrangement. Prefer the existing dev proxy/same-origin setup; if needed, restrict CORS to the explicit local frontend origin(s).
- Choose a simple plan rendering: nested cards or a table with node/parent IDs and child order. A real tree does not require a graph-layout dependency.
- Decide fixture size and preset queries from demonstrated Stage 7 capabilities.
- Freeze optional work and define the feature-freeze/rehearsal window.

**Evidence:** Transport types or a concise contract document and examples covering complete, empty, truncated, busy, and invalid-query responses.

**Acceptance:** Backend/frontend can integrate against one contract with no fabricated metrics or implicit full-result collection.

### Task 9.3 — Prepare persistent, repeatable demo data

**Actions:**

- Use the existing setup API to create a dedicated demo directory, tables, and appropriate indexes. Do not require CREATE TABLE SQL if the parser does not support DDL.
- Use deterministic small fixtures with known answers; include duplicate values, a no-match condition, a join, and grouped output.
- Add a modest larger fixture only if needed to show an existing external algorithm. Verify it runs comfortably on the presentation machine before adding its preset.
- Close/flush setup objects and reopen from disk through the real Catalog/engine path. Preserve the project's established metadata persistence contract; no redesign is required.
- Keep a clearly named reset/setup script for this demo directory only. Run it while the server is stopped. Never erase the normal project data directory.
- Do not reseed or reset data on page refresh or every query.

**Tests:** Known expected rows and clean reopen using fresh engine objects.

**Acceptance:** The same launch produces predictable live results from persisted project storage.

### Task 9.4 — Own engine startup and shutdown in the API

**Actions:**

- Create one application-owned adapter/service and open the configured demo engine once.
- Use the framework's existing lifecycle convention; avoid opening an engine per request or sharing mutable prepared-query state.
- Expose cached readiness/mode through health without touching storage.
- Preserve fresh execution contexts per statement and Stage 6 resource budgets.
- On shutdown, refuse new work, cancel running session statements, and call bounded `Database.shutdown` before closing shared handles. If cleanup cannot finish, keep the service unavailable.
- Refuse invalid/unavailable demo configuration with an actionable startup error.
- Document one-process, one-worker startup with reload disabled for presentation.

**Tests:** Startup, wrong directory, health before/after readiness, repeated requests, and shutdown cleanup.

**Acceptance:** No route accidentally creates a second engine owner or closes the application engine when closing one result.

### Task 9.5 — Enforce session ownership, admission, and statement policy

**Actions:**

- Select the token's `SqlSession` under the short registry mutex, then execute outside that mutex. Keep exclusive admission only for sessionless calls on the default session.
- Return `SESSION_BUSY` for simultaneous calls on one token and `ENGINE_BUSY` for competing sessionless calls. Independent sessions use the engine's lock manager and finite waits.
- Hold the selected session's call ownership through AST classification, execution, preview conversion, measurements, and cursor cleanup.
- Use the handwritten AST to apply Section 5's read-only/write/control policy without execution during classification. Allowed SQL goes to `SqlSession.execute`, preserving group-level error semantics.
- Reject all unsupported/disabled statement kinds, including complete multi-statement submissions.
- Keep the guard owned by the code actually doing synchronous engine work. If offloaded to a worker thread, that worker retains admission until its own cleanup finishes.
- Connect the implemented cancel endpoint/button to `SqlSession.cancel()` and display cancellation as pending until the executing request acknowledges its terminal outcome.
- Read Catalog metadata through the engine's metadata gate without execution admission. Describe counts as physical and potentially provisional.

**Tests:** Synchronize real requests using engine lock state or events: compatible readers and independent-table writers overlap; a blocked request allows its blocker to END/ROLLBACK; same-token reentrancy and competing sessionless calls fail predictably. Check cleanup, cancellation, expiry, and shutdown. A real network drop remains outside recorded verification.

**Acceptance:** Independent client sessions execute concurrently under Stage 8 protection. The registry/admission guards never prevent a blocker from completing its group.

### Task 9.6 — Expose Files-panel metadata

**Actions:**

- List real loaded tables and return selected table columns/types/nullability when supported.
- Include organization/index names and indexed columns only when Catalog exposes them accurately.
- Use stable Catalog IDs and preserve column order. Avoid reading full tables for counts or previews during schema loading.
- Keep paths and storage object instances out of JSON.
- Handle no tables, missing table, and unavailable metadata clearly; metadata routes do not acquire execution admission.

**Tests:** Fixtures match metadata responses; unknown IDs fail; listing does not mutate data.

**Acceptance:** Files panel can explain the schema used in the demonstration without hard-coded table structures.

### Task 9.7 — Execute one SQL statement with bounded output

**Actions:**

- Validate request shape and SQL byte length, then select the session or sessionless path.
- Classify the handwritten AST for policy and execute SQL exactly once through the selected session. Do not pre-bind allowed SQL in the adapter, which would bypass the engine's group-abort behavior on execute errors.
- Preserve the existing schema for zero-row results.
- Apply incremental row and byte limits from Section 6, using at most one row of lookahead beyond the row cap.
- Convert values under the explicit JSON encoding policy without collapsing duplicate columns or duplicate rows.
- Obtain the real plan and available runtime details from that execution, including fallback operators when reported.
- Close the cursor and copy final available statistics while still owning the session call. Return detached JSON-safe values; explicit-group locks remain until END/ROLLBACK.
- On exceptions, close all owned resources and return a failure envelope, not partial-success rows.

**Tests:** Empty result, one row, fewer than N, exactly N, N+1, byte cap, large single value, duplicate column names, Unicode, null, large integer, early-close temp cleanup, and error during iteration/conversion.

**Acceptance:** The HTTP adapter preserves engine results and memory/resource guarantees while providing an honest bounded preview.

### Task 9.8 — Report errors and truthful measurements

**Actions:**

- Map domain errors using Section 7; preserve lexical/syntax source spans from the handwritten parser.
- Include request IDs in responses/logs. Do not treat request IDs as duplicate-write prevention.
- Use an existing monotonic timer for backend elapsed time and label its scope, such as prepare-through-cleanup including preview conversion.
- Keep browser round-trip duration separate from engine/backend time.
- Use execution-local plan counters and transaction reports. Do not subtract shared counters across concurrent sessions, reset global counters, or sum inclusive child timings. Keep query I/O, undo I/O, and lock waits distinct.
- For early-closed previews, mark metrics partial and total rows unknown; a sort may still have consumed all input before output was truncated.
- Report unavailable measurements as unavailable. Do not invent a cost, I/O count, transaction ID, or speedup.

**Tests:** SQL location mapping, busy/protocol/abort/timeout/cancel errors, injected rollback restoration failure with `ABORT_FAILED`/quarantine, partial metrics, isolated concurrent counters, and no leaked internal paths/tracebacks.

**Acceptance:** Results, plan, error, and metrics are associated with the same request and reflect what actually happened.

### Task 9.9 — Build a simple frontend shell and API client

**Actions:**

- Reuse existing frontend scaffolding. Build a readable four-panel workspace with minimal dependencies.
- Define request/response types matching the API, including nullable/unavailable fields and errors.
- Add a single transport client using the configured base URL; do not hard-code a teammate's absolute path or machine address.
- Represent idle, loading, success, empty, truncated, busy, failure, and backend-unavailable states.
- Keep previous and current executions identifiable so stale responses cannot overwrite newer ones.
- Render SQL, values, and error text as text; do not inject them as raw HTML.

**Tests:** Type/build checks and API-client handling of success, structured failure, and unavailable server. UI test doubles are allowed in tests, not as runtime demonstration data.

**Acceptance:** The shell starts reliably and has clear locations for all required panels.

### Task 9.10 — Connect Files and Query panels

**Actions:**

- Load tables, then selected metadata, using controlled sequential requests or the documented metadata snapshot policy.
- Display selected table columns/types and actual index metadata.
- Add a SQL textarea and an Execute button. Disable duplicate submission while this frontend request is active.
- Keep the submitted SQL snapshot associated with its result even if the user edits the text during execution.
- Show the real mode and this tab's session state. BEGIN/END/ROLLBACK use the same query route as the editor; display held locks and live waits/blockers, with a cancel action for an active request.
- Offer an execution shortcut if inexpensive; keep keyboard labels/accessibility clear.
- Display SQL diagnostics near the editor and preserve user input after errors.

**Tests:** Execute typed SQL, missing query, error editing/retry, busy from another client, and backend unavailable.

**Acceptance:** A user can discover a table, write a real supported SELECT, and execute it without a command-line intervention.

### Task 9.11 — Show correct tabular results

**Actions:**

- Render ordered column descriptors and aligned row arrays; distinguish null, empty string, zero, and false.
- Show zero-row results as a successful empty result rather than an error.
- Label truncation as `Showing first N rows; more results exist` when known, or the precise byte-limit message. Do not display N as the total when total is unknown.
- Use horizontal scrolling and controlled text wrapping so wide rows do not break the workspace.
- Label frontend-only page navigation as navigation within the preview, if added.
- Associate displayed metrics with this result and separate partial from complete consumption. Display command counts as provisional until END succeeds; distinguish confirmed abort from failed/unconfirmed restoration.
- Clear or explicitly mark the previous result as previous when a new request fails; never display old rows as the new query's success.

**Tests:** Empty, duplicate names, null, Unicode, long values, truncation, and error after earlier success.

**Acceptance:** The instructor can read the true output and understand whether it is complete.

### Task 9.12 — Show the actual execution plan

**Actions:**

- Render engine-provided operator nodes and child relationships in a nested view or explicit node/parent table.
- Include actual table/index names, access type, residual filter, join/group/sort keys, and output schema when available.
- Explain that child data feeds parent operators; avoid presenting one misleading numbered sequence for branching joins.
- Distinguish a prepared descriptor from execution-observed behavior. Display runtime fallback metadata when available.
- If the engine has no plan descriptor, implement a narrow descriptor adapter over its real plan/operator objects; do not guess a plan from SQL keywords.
- Show a clearly unavailable/error state if descriptor retrieval fails. A missing actual plan blocks the P0 plan-panel criterion.
- Keep optional per-node metrics unavailable where the engine does not measure them.

**Tests:** Full scan, an actual eligible index path, filter/projection, sorting, and a branching join. Verify displayed index names agree with actual descriptors.

**Acceptance:** The plan explains the real execution path for the displayed request. No decorative/mock plan is substituted.

### Task 9.13 — Assemble verified demo queries

**Actions:**

- Add a small preset selector or buttons that insert SQL into the editor; execution always uses POST /api/query.
- Use the repository's actual fixture names and grammar. Verify expected rows through engine tests before showing a preset.
- Include basic filtering, index equality/range, ORDER BY, GROUP BY, JOIN, and one deliberate syntax/semantic error where these are supported as reported by Stage 7.
- Keep queries short enough to explain. If a required engine family fails, record the defect and repair the relevant integration or exclude the failing preset honestly; do not claim that coverage is verified.
- Use an actual planner-selected index, not a UI toggle that changes a label while keeping execution unchanged.

**Evidence:** A small table of preset SQL, purpose, expected output, and actual operator/index descriptor.

**Acceptance:** Presets demonstrate real existing capabilities and are reproducible from clean startup.

### Task 9.14 — Verify API, browser, and overlap behavior

**Actions:**

- Test the exact public HTTP path against real temporary project storage and compare rows/schema with direct engine execution.
- Test malformed SQL, semantic errors, disabled writes, controls without a session, and second statements. Policy refusals preserve a group; engine execute errors follow its full-group abort contract.
- Test overlapping requests, including metadata during a query, with deterministic synchronization.
- Test early preview close, conversion/iteration errors, and busy-state release after cleanup.
- Run affected API/transaction and engine regression tests, frontend type/build checks, and repository-mandated checks. Record actual scope; do not claim the whole suite passed if only a subset ran.
- Open the actual browser and execute the preset sequence. Check all four panels, result/plan association, no stale response, and recovery from invalid SQL.
- Check startup/reopen from disk and confirm read-only queries leave permanent data unchanged.

**Acceptance:** The critical demo path is verified in the browser, not only through mocked unit tests or HTTP documentation.

### Task 9.15 — Rehearse and freeze the presentation build

**Actions:**

- Document actual setup/start commands from the repository and required ports/environment values. Do not invent entry-module names in the final runbook.
- Rehearse starting from stopped services and persisted fixtures, opening the GUI, running each preset, and stopping cleanly.
- Keep a tested version/commit and lockfiles for the presentation. Do not upgrade dependencies after the final rehearsal.
- Close other engine processes. Disable reload and use the documented single-worker backend command.
- Prepare a clearly labeled screenshot/short recording of the real successful run as a presentation fallback if useful. A recording is evidence of an earlier run, never live execution.
- Record the implemented Stage 8/9 integration, formal Stage 9 closure status, known verification limits, and pending Stage 10 work.

**Acceptance:** Another teammate can start the application from the runbook and repeat the demonstration.

### Task 9.16 — Optional verified mutation demonstration

**Priority:** P1; skip entirely if presentation time is short.

**Prerequisite:** Existing write consistency, index maintenance, Stage 8 implicit-transaction, and clean-reopen tests pass. No second transaction implementation belongs in the API.

**Actions:**

- Enable INSERT/DELETE only through explicit server configuration, default off, against the disposable demo directory.
- Preserve the parsed-statement allowlist and session/sessionless paths; execute each accepted command synchronously once.
- Return actual affected rows separately from SELECT previews. Fetching/rendering the response must not execute the command again.
- Do not automatically retry mutations on timeout, refresh, or network failure. A lost response means outcome unknown until inspected; a request ID is not deduplication.
- With a client token, BEGIN/END/ROLLBACK group requests; without one, commands use individual implicit transactions. Explicit command counts remain provisional until END. Do not claim crash atomicity.
- Surface confirmed commit/abort outcomes. Failed restoration is `ABORT_FAILED` and owner quarantine, not successful rollback. Stop writes if the owner is quarantined or consistency is uncertain.
- Demonstrate an insertion followed by a read-back and an exact-target deletion only after rehearsal; reset offline while the backend is stopped.

**Tests:** Disabled write has no effects, enabled write runs once, affected count, scan/index agreement, simulated response loss without retry, and persistence after clean restart.

**Acceptance:** Configured writes preserve Stage 8 group/undo guarantees and truthful provisional/terminal outcomes. Failed gates leave writes disabled.

### Task 9.17 — Optional presentation polish

**Priority:** P1; no feature below compensates for a failing P0 task.

**Actions:** Improve font sizes, panel spacing, table readability, keyboard access, status badges, and useful plan detail expansion. Add lightweight syntax highlighting only if it is already easy to integrate. Match existing project style instead of rebuilding a design system.

**Acceptance:** Polish does not introduce new dependencies or behavior that destabilizes the rehearsed execution path. Repeat the browser smoke check after changes.

### Task 9.18 — Record milestone history and current integration status

**Actions:**

- Record `Stage 9 emergency demo ready` only after its checklist passes. Stage 8 was pending at that checkpoint and closed later on 2026-09-24; Stage 10 remains pending.
- Update project progress pointers to show the temporary order and the manual-parser decision.
- Record real endpoint/types, resource limits, local launch commands, allowed statements, and known limitations.
- Record the implemented session/transaction ownership, controls, errors/results, cancellation, lifecycle, and concurrent HTTP verification from 2026-09-25.
- Preserve sessionless admission and the per-token call guard; the former global guard was narrowed only after integration tests passed.
- List formal Stage 9 closure and verification limits separately from already implemented session features. Real network-drop behavior remains unverified; SQL CREATE stays disabled under the legacy demo owner.
- Keep Stage 10 benchmarks and full delivery requirements explicitly pending.

**Acceptance:** Teammates can distinguish demonstrated capability from deferred requirements and have a concrete next step after the presentation.

## 10. Presentation script and example fixture

Prefer existing verified fixtures. If none are suitable, reuse the Stage 7 illustrative fixture through existing setup APIs:

- students(id, name, career, age): (1, Ana, CS, 22), (2, Luis, EE, 19), (3, Sol, CS, 24), (4, Omar, EE, 23).
- enrollments(student_id, course): (1, DB2), (1, OS), (3, DB2), (4, OS).
- Equality-capable index on students.id and B+ index on students.age, created through the project's existing index setup APIs.

These are examples, not new domain requirements. Adapt only to confirmed engine syntax and names.

| Step | SQL/action | Expected demonstration |
|---|---|---|
| 1 | Open Files and inspect students | Real Catalog schema and indexes |
| 2 | `SELECT name FROM students WHERE age > 20 ORDER BY name;` | Ana, Omar, Sol; filtering and actual sorting plan |
| 3 | `SELECT * FROM students WHERE id = 3;` | Sol's row; eligible equality access under actual planner rules |
| 4 | `SELECT name FROM students WHERE age >= 22 AND age < 24;` | Ana and Omar as a multiset; B+ range when selected |
| 5 | `SELECT career, COUNT(*) AS total FROM students GROUP BY career ORDER BY career;` | (CS, 2), (EE, 2); real grouped execution |
| 6 | `SELECT s.name, e.course FROM students AS s JOIN enrollments AS e ON s.id = e.student_id WHERE s.age > 20 ORDER BY s.name;` | Ana/DB2, Ana/OS, Omar/OS, Sol/DB2; ties follow existing contract |
| 7 | `SELECT unknown_column FROM students;` then rerun Step 2 | Useful semantic error and normal recovery |
| 8 | In two tabs: BEGIN/INSERT in A, SELECT in B, then END or ROLLBACK in A | Distinct sessions, provisional changes, real lock wait, and terminal outcome |
| 9 | Explain pending work | Formal Stage 9 closure and Stage 10 experiments/delivery; network-drop verification remains limited |

Check the actual plan instead of promising a particular index if the planner chooses another valid path. A small fixture proves correctness and connectivity, not scalability. If showing external spills, use the separately rehearsed larger fixture and real counters; do not describe the four-row example as proof of disk spilling.

Suggested explanation:

> This interface executes SQL through our own storage, indexes, and query operators. Each browser tab owns an engine session. BEGIN/END/ROLLBACK group separate requests, and independent sessions use the real table locks, deadlock handling, and in-process undo from Stage 8. Command counts remain provisional until END succeeds.

## 11. Completion checklists

### Historical emergency demo checkpoint (2026-09-18)

The original milestone was verified in
`docs/ETAPA_09_AVANCE.md`. Its global admission and SELECT-only policy were
replaced by the current session contract on 2026-09-25; do not apply these
historical policies to current code. Current status is recorded below.

### Current GUI and transport

- [x] Existing handwritten parsing and engine algorithms are reused.
- [x] Dedicated deterministic demo data persists across clean reopen.
- [x] Files, Query, Results, and Execution Plan panels use real engine data/descriptors.
- [x] Each accepted statement executes once; errors preserve request/SQL association.
- [x] Row/byte previews are bounded, cursor cleanup is enforced, and completion/totals are truthful.
- [x] Values, column order, and duplicate names/rows preserve engine semantics; the engine does not support NULL.
- [x] The runbook documents actual routes, launch commands, limits, and verification scope.

### Optional writes ready, only if enabled

- [x] Explicit configuration enables writes on the dedicated demo directory; default mode refuses them.
- [x] Stage 8 sessions preserve storage/index consistency and failure semantics.
- [x] INSERT/DELETE execute once and distinguish provisional/committed outcomes.
- [x] No automatic mutation replay occurs; rollback success requires confirmed ABORTED.
- [x] Scan/index agreement and clean-reopen persistence have real-engine tests.

### Current transaction-aware integration

- [x] Transaction/session semantics are connected through the API and reflected in the UI where needed. (2026-09-25)
- [x] Cursor lifetime and disconnect policy follow the implemented transaction contract. (2026-09-25; a real network drop was not simulated)
- [x] Simultaneous requests are tested under the real database concurrency mechanism. (`tests/api/test_sessions.py`, two browser tabs)
- [x] Mandatory engine-level thread-based race/protected-execution demonstration exists (`demos/transactions_demo.py`).
- [x] The temporary admission policy is retained or revised only after real protection is verified. (now sessionless-only)
- [x] Stage 9 regressions still pass; Stage 10 experiments and final requirements are completed separately.
- [x] Failed restoration is shown as `ABORT_FAILED`/quarantine; rollback success requires `ABORTED`. (2026-09-30; frontend and injected HTTP regression)
- [x] Formal Stage 9 closure decision and audit recorded (2026-10-01, `docs/ETAPA_09_AUDIT.md`).

## 12. Suggested modules and deliverables

These are the implemented module locations; preserve their responsibilities.

| Location | Responsibility |
|---|---|
| api/app.py | Application lifecycle, routes, and transport configuration |
| api/engine_service.py | Engine ownership, admission, policy, bounded result conversion |
| api/schemas.py | Request/response/error contracts |
| frontend/src/api.ts, frontend/src/types.ts | Typed HTTP client and response types |
| frontend/src/components/ | Four required panels and small shared UI components |
| scripts/setup_demo.py | Explicit offline preparation/reset of dedicated demo fixtures |
| tests/api/ | Real-engine HTTP integration, bounds, errors, and admission tests |
| Existing frontend test location | UI state and response association tests |
| docs/demo.md | Launch commands, exact presets, expected results, limitations, and rehearsal evidence |

These modules exist in the repository. Verify their current contracts before changes and synchronize current coordination documents alongside code; preserve dated audits as historical evidence.

## 13. Working prompts for Codex

### Inspection and immediate execution plan

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_08.md, ETAPA_09.md, and the completed Stage 8-to-9 handoff.
Stages 7 and 8 are closed; the Stage 9 HTTP/session integration is implemented.
Preserve the handwritten parser and current session ownership.

Review Tasks 9.1-9.2 against actual interfaces/scripts and relevant tests.
Preserve the existing transport contract and reuse existing code.
Reuse the implemented transaction layer and engine algorithms.
```

### First vertical increment

```text
Verify Tasks 9.3-9.11 with one real SELECT from the browser. Use the existing engine, dedicated
persisted fixtures, one backend worker, per-session calls and sessionless
admission, server-enforced statement policy, and bounded rows/JSON bytes.

Close the result and capture detached plan/metrics before releasing the
session call guard. Add focused tests. Do not introduce Lark, fetchall, fake rows,
mock production plans, a second transaction layer, or public deployment.
```

### Complete the required interface

```text
Maintain the four real panels, errors, and verified presets in Tasks
9.9-9.13. Use the same request's actual plan, result, and statistics.
Keep preview truncation explicit and protect against stale responses.
Prioritize a readable nested plan over graphical decoration.
```

### Presentation gate

```text
Execute Tasks 9.14-9.15 and 9.18. Verify real HTTP/browser behavior,
full-input rejection, preview/resource limits, compatible session overlap,
same-session busy rejection, error recovery, clean restart, and all four panels.
Record actual commands and evidence. Keep the completed engine/session
integration distinct from formal Stage 9 closure and pending Stage 10 work.
```

### Return after the presentation

```text
Use the completed `docs/ETAPA_08_STAGE_9_HANDOFF.md` checklist to maintain
request-owned sessions, all result variants, errors, cancellation and status.
Keep cursor/group lifetimes, ABORTED versus ABORT_FAILED, and concurrent HTTP
tests explicit. Preserve admission only for sessionless calls. Record formal
Stage 9 closure separately, then proceed to Stage 10 when authorized.
```
