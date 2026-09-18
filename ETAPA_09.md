# ETAPA_09.md

## Stage 9 — API and Frontend: Emergency Presentation Plan

**Revision:** 2026-09-18  
**Part:** Relational Database  
**Starting point:** Stage 7 reported complete; Stage 8 not implemented  
**Immediate objective:** A working local GUI over the real SQL engine for today's progress presentation  
**Status:** Emergency demo ready (2026-09-18); evidence in `docs/ETAPA_09_AVANCE.md`, runbook in `docs/demo.md`. Stage 9 is not closed: transaction integration waits for Stage 8\
**Execution mode:** Single backend process, serialized engine access, read-only SQL by default  
**Follow-up:** Stage 8, remaining Stage 9 integration, then Stage 10

## 1. Authorized sequencing exception

The team has explicitly chosen to implement an initial Stage 9 before Stage 8. This is an authorized change in implementation order, not permission to remove transaction/concurrency requirements or mark them complete. Do not stop solely because an older stage-order pointer says Stage 8 must come first.

The temporary order is:

1. Verify the Stage 7 interfaces needed by the presentation.
2. Implement the required emergency Stage 9 tasks below.
3. Present the working GUI and identify pending transaction/concurrency work.
4. Implement Stage 8 and its required demonstration.
5. Complete Stage 9 transaction/session integration and rerun integration tests.
6. Complete Stage 10 experiments and final delivery.

The emergency milestone is **Stage 9 demo ready**, not **Part 1 complete**. REQUIREMENTS.md still requires transactions, concurrency, and experiments; its Part 1 milestone is not waived by this plan. If today's evaluation expects all of Part 1, this presentation remains a partial delivery.

The team also explicitly chose a handwritten SQL lexer and parser. Preserve the completed Stage 7 parser; do not introduce Lark, another parser generator, or a separate frontend/API SQL parser.

## 2. Sources, authority, and assumptions

This plan uses the current REQUIREMENTS.md (GUI requirements in Section 8), PLAN.md (Stage 9 in Section 14), PROJECT_CONTEXT.md, AGENTS.md, and the revised ETAPA_07.md. The academic scope remains unchanged. This document is an implementation plan, not a new assignment specification.

The user reports Stage 7 complete. No repository is inspected or modified merely by creating this document. Task 9.1 must identify actual entry points, supported syntax, fixtures, and test commands before code is written.

Some coordination documents still recommend Lark or carry older stage pointers. The user's manual-parser decision and authorized emergency sequence supersede those stale recommendations. Reconcile them during implementation without changing REQUIREMENTS.md to describe team choices as academic obligations.

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

| Panel | Required emergency behavior | Optional later enhancement |
|---|---|---|
| Files | Loaded tables and selected table structure from Catalog | Upload/import wizard and rich storage visualization |
| Query | SQL textarea, Execute action, error feedback, verified presets | Syntax highlighting, completion, history persistence |
| Results | Ordered columns, bounded rows, null/empty/loading/error states | Export and server-side continuation |
| Execution Plan | Real operators, child relationships, indexes, relevant details | Animated graph and advanced profiling |

A schema panel is the Files panel, not a fifth substitute. Preset queries must fill the editor and execute through the same API as manually entered SQL. Production UI data must never come from hard-coded expected results or a mock database.

## 4. Priorities and time control

| Priority | Meaning | Tasks |
|---|---|---|
| P0 | Required for an honest working presentation | 9.1–9.15 and 9.18 |
| P1 | Add only after all P0 checks pass | 9.16–9.17 |
| Deferred | Resume after the presentation | Stage 8, transaction-aware Stage 9 work, Stage 10 |

Work in vertical increments:

1. **Foundation:** inspect contracts, prepare fixtures, define limits, own engine lifecycle and admission.
2. **First visible success:** API query response plus editor/results, using one real SELECT.
3. **Complete required panels:** Files, actual plan, clear errors, and verified presets.
4. **Freeze and rehearse:** integration tests, clean restart, actual browser run, and documented launch steps.

Set a feature-freeze time before the presentation and reserve the final portion of available time for rehearsal. Do not estimate implementation duration before Task 9.1 reveals existing work. Drop P1 features first when time is short. A broken P0 path is repaired or reported as incomplete; it is never replaced by fabricated data.

Do not spend the deadline on authentication, public deployment, editor plugins, visual graph layout, theme systems, uploads, or benchmark dashboards. Local presentation is the baseline; publication and multi-user service are outside this milestone.

## 5. Boundaries before Stage 8

### Required temporary execution policy

- One backend process owns the demonstration engine and its data directory.
- One admitted engine operation runs at a time across all routes that access engine state.
- A second request requiring the engine is rejected promptly with a structured `ENGINE_BUSY` response; do not build an unbounded queue.
- The guard covers preparation, execution, cursor consumption, metrics snapshot, serialization of engine-owned values, and cleanup.
- Shared counters, Catalog reads, plan inspection, and optional writes use the same policy. HTTP health checks may read immutable/cached status without touching the engine.
- No CLI, second server, background importer, or external process accesses that data directory during the demo. A process-local guard cannot protect those accesses.
- Run one worker; disable automatic reload for the presentation. One worker alone does not prevent concurrent request handlers, so the admission guard is still required.
- Keep the synchronous engine work and guard ownership in one coherent execution context. Do not let an async request cancellation release a guard while a worker thread continues using the engine.
- On a browser disconnect, finish or cooperatively stop the admitted operation and close its resources before releasing admission. A network timeout does not prove engine execution stopped.
- If cleanup cannot establish a usable engine state, mark the service unavailable for engine requests until a controlled restart/repair. Do not silently continue with a leaked cursor or corrupt state.

This guard is temporary server admission control. It does not implement transaction grouping, rollback, isolation levels, a database lock manager, cross-process locking, or the required simultaneous-transaction demonstration.

### Statement policy

Default to **SELECT-only** for today's GUI. Enforce this on the server by inspecting the parsed statement kind using the existing parser/prepare API, before execution. Do not decide safety using `startswith('SELECT')`, substring matching, regex stripping, or frontend buttons.

Parse the complete submission under Stage 7's one-statement rule. Reject multiple statements and unsupported syntax. BEGIN TRANSACTION, END TRANSACTION, COMMIT, and ROLLBACK cannot succeed as no-ops. If Stage 7 already rejects them during parsing, preserve that rejection; new transaction grammar is not required today.

INSERT/DELETE may be enabled only through Task 9.16's tested, explicit configuration. The API restriction does not remove those already implemented engine features or their academic requirements.

## 6. Adapter architecture and resource contract

Keep the API thin. It validates transport input, applies the presentation policy, calls the existing engine, converts results to JSON, and releases resources. It must not implement SQL semantics, storage, indexes, joins, sorting, or aggregate algorithms.

The frontend depends on HTTP contracts, not Python internals. The engine remains callable independently of FastAPI and React.

### Bounded preview, not a persistent server cursor

The simplest emergency contract is one response containing a bounded preview. Keep Stage 7 streaming inside the adapter and close the cursor before returning the response. Do not retain cursors across HTTP requests or add pagination sessions today.

Proposed defaults, to freeze or adapt in Task 9.2:

| Limit | Suggested value | Meaning |
|---|---:|---|
| Displayed rows | 100 | Default preview count |
| Maximum requested preview | 500 | Hard server-side cap, independent of client validation |
| SQL text | 32 KiB UTF-8 | Transport limit, aligned with Stage 7's own limit |
| Encoded response | 1 MiB | Explicit JSON byte budget, including metadata |
| Plan nodes/depth | Configured bounded values | Prevent oversized or recursive descriptors |

These are project defaults, not instructor requirements. Adapt them to verified schema/record limits. A row limit is not a execution-time or total engine-memory limit: sorting/grouping/joining can perform substantial work before returning the first row. Preserve Stage 6 memory/temp budgets and use rehearsed fixtures.

For a row cap N, consume at most N+1 output rows. If the extra row exists, report truncation and retain only N. If EOF occurs, report complete consumption. This also distinguishes exactly N rows from more than N. Count the extra row as consumed in measurements, not as displayed.

Apply the byte cap incrementally as well. Reserve space for response metadata and delimiters; never build an unbounded response before checking its size. If metadata or a single row cannot fit, return a structured result-size error after cleanup. Do not silently truncate strings or alter values to fit. If accumulated rows hit the byte cap, return the accepted prefix with explicit truncation and the corresponding reason.

Do not call unconditional `fetchall`, count every remaining row, rerun the query to infer totals, append an unsupported SQL LIMIT, or sort/group results in the frontend. Browser pagination of the already returned preview is optional and must not imply access to the entire result.

## 7. Proposed HTTP contracts

Names are suggestions; adapt compatible existing routes. Keep a small documented API rather than adding every possible endpoint.

| Method and route | Responsibility | Engine admission needed? |
|---|---|---|
| GET /api/health | Cached startup/readiness and execution mode | No engine access |
| GET /api/tables | Loaded table summaries from Catalog | Yes |
| GET /api/tables/{table_id} | Columns, types, organization, indexes when available | Yes |
| POST /api/query | Parse, enforce policy, execute once, return bounded results and actual plan | Yes |

IDs are Catalog identifiers, never arbitrary filesystem paths. Do not expose file-opening or command-running endpoints. An upload/import route and a reset HTTP route are unnecessary for the demo.

Illustrative request:

```json
{"sql":"SELECT name FROM students WHERE age > 20 ORDER BY name;","max_rows":100}
```

The response should specify the following fields. Exact names may follow an existing convention:

| Field | Meaning |
|---|---|
| request_id | Correlates this operation's result, error, plan, and logs; not an idempotency guarantee |
| kind | `rows` or, if enabled, `command` |
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
| mode | Read-only demo or explicitly enabled serialized-write demo |

A successful response with an early-closed preview has `result_complete=false`. EOF-complete empty results have zero rows, the actual column schema, and `result_complete=true`. An execution exception produces an error, not a success response with the rows accumulated so far.

Preserve Stage 7 value semantics. Use arrays so joined columns with equal names do not overwrite one another. Encode null as JSON null and booleans as booleans. Define lossless encoding for integers outside JavaScript's safe integer range and exact decimals if supported, for example string values with column encoding metadata. Do not silently round them. Handle non-finite floats explicitly under the existing engine type policy; emit valid JSON or a structured conversion error.

### Error mapping

| Condition | Suggested HTTP status | User-facing meaning |
|---|---:|---|
| Malformed transport input | 400 or framework-standard 422 | Request fields are invalid |
| SQL lexical/syntax/semantic error | 422 | Query is invalid; include existing source location where available |
| Statement disabled in demo mode | 403 | Query type is not enabled in this presentation mode |
| Missing table metadata resource | 404 | Selected Catalog object does not exist |
| Another engine operation active | 409 | Engine busy; try after the current operation finishes |
| Oversized request | 413 | SQL body exceeds the limit |
| Response cannot fit bounded encoding | 422 | Result exceeds the presentation response limit |
| Engine not ready or unusable | 503 | Controlled restart/repair needed |
| Unexpected engine/server failure | 500 | Operation failed; include a diagnostic request ID |

Use a consistent error envelope with code, message, request ID, and optional SQL location. Record technical details in server logs; show no Python tracebacks or local paths in the normal UI. If optional writes fail, preserve the engine's confirmed partial-effect information and never claim rollback.

## 8. Task sequence

| Task | Work | Priority | Dependencies |
|---|---|---|---|
| 9.1 | Inspect Stage 7 and document the sequencing exception | P0 | User-reported Stage 7 completion |
| 9.2 | Freeze demo contracts and limits | P0 | 9.1 |
| 9.3 | Prepare persistent demonstration fixtures | P0 | 9.1–9.2 |
| 9.4 | Implement API startup/shutdown and engine adapter | P0 | 9.1–9.2 |
| 9.5 | Implement exclusive engine admission and read-only policy | P0 | 9.4 |
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
| 9.16 | Optionally enable verified INSERT/DELETE | P1 | All P0 functional checks; existing Stage 7 write guarantees |
| 9.17 | Optional readability and usability polish | P1 | All P0 functional checks |
| 9.18 | Document milestone and Stage 8 return plan | P0 | Verified outcomes; update after any P1 work |

Add relevant tests with each task. Task 9.14 is a focused integration gate, not permission to defer testing until the end.

## 9. Detailed tasks

### Task 9.1 — Verify the completed engine and authorized exception

**Actions:**

- Read current repository AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, and ETAPA_07.md.
- Record Stage 7 as user-reported complete and Stage 8 as not implemented. Verify the relevant Stage 7 tests rather than assuming the public interface matches illustrative names.
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
- Record single-process ownership, reject-when-busy policy, read-only default, and cursor lifetime.
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
- On shutdown, stop admission, finish/clean admitted work, then close engine-owned resources in the correct order.
- Refuse invalid/unavailable demo configuration with an actionable startup error.
- Document one-process, one-worker startup with reload disabled for presentation.

**Tests:** Startup, wrong directory, health before/after readiness, repeated requests, and shutdown cleanup.

**Acceptance:** No route accidentally creates a second engine owner or closes the application engine when closing one result.

### Task 9.5 — Enforce serialized admission and statement policy

**Actions:**

- Put a shared admission guard around every operation accessing mutable engine/Catalog/counter state.
- Use immediate busy rejection for a competing request; do not wait indefinitely or serialize only in JavaScript.
- Hold ownership through prepare, read-only AST classification, execution, preview conversion, measurements, and result cleanup.
- Use the existing handwritten parser or prepared statement metadata to allow SELECT only. Ensure no execution happens during classification.
- Reject all unsupported/disabled statement kinds, including complete multi-statement submissions.
- Keep the guard owned by the code actually doing synchronous engine work. If offloaded to a worker thread, that worker retains admission until its own cleanup finishes.
- Do not implement a cancel button unless actual cooperative engine cancellation is already available and verified.
- Ensure metadata routes also reject as busy or use an explicitly immutable snapshot. Frontend loading should avoid unnecessary simultaneous engine requests.

**Tests:** Overlap requests deterministically with test synchronization; the second engine operation must not start. Test query-versus-metadata overlap, lexical error, execution error, disconnect handling, and successful admission after cleanup. Use test events/barriers rather than timing-only sleeps.

**Acceptance:** Actual engine operations never overlap within the supported server process. No test or documentation describes this as the completed Stage 8 concurrency mechanism.

### Task 9.6 — Expose Files-panel metadata

**Actions:**

- List real loaded tables and return selected table columns/types/nullability when supported.
- Include organization/index names and indexed columns only when Catalog exposes them accurately.
- Use stable Catalog IDs and preserve column order. Avoid reading full tables for counts or previews during schema loading.
- Keep paths and storage object instances out of JSON.
- Handle no tables, missing table, unavailable metadata, and busy admission clearly.

**Tests:** Fixtures match metadata responses; unknown IDs fail; listing does not mutate data.

**Acceptance:** Files panel can explain the schema used in the demonstration without hard-coded table structures.

### Task 9.7 — Execute one SQL statement with bounded output

**Actions:**

- Validate request shape and SQL byte length, then enter the shared admission path.
- Prepare/classify and execute exactly once through existing engine APIs. If prepare and execute are distinct, prefer execution of that prepared object where supported; do not execute once for data and again for the plan.
- Preserve the existing schema for zero-row results.
- Apply incremental row and byte limits from Section 6, using at most one row of lookahead beyond the row cap.
- Convert values under the explicit JSON encoding policy without collapsing duplicate columns or duplicate rows.
- Obtain the real plan and available runtime details from that execution, including fallback operators when reported.
- Close the cursor and copy final available statistics while still owning admission. Return only detached JSON-safe values; never a generator that continues reading the engine after the guard is released.
- On exceptions, close all owned resources and return a failure envelope, not partial-success rows.

**Tests:** Empty result, one row, fewer than N, exactly N, N+1, byte cap, large single value, duplicate column names, Unicode, null, large integer, early-close temp cleanup, and error during iteration/conversion.

**Acceptance:** The HTTP adapter preserves engine results and memory/resource guarantees while providing an honest bounded preview.

### Task 9.8 — Report errors and truthful measurements

**Actions:**

- Map domain errors using Section 7; preserve lexical/syntax source spans from the handwritten parser.
- Include request IDs in responses/logs. Do not treat request IDs as duplicate-write prevention.
- Use an existing monotonic timer for backend elapsed time and label its scope, such as prepare-through-cleanup including preview conversion.
- Keep browser round-trip duration separate from engine/backend time.
- Copy execution-local counters or validated before/after deltas under the guard. Do not reset global counters from another route or sum inclusive child timings.
- For early-closed previews, mark metrics partial and total rows unknown; a sort may still have consumed all input before output was truncated.
- Report unavailable measurements as unavailable. Do not invent a cost, I/O count, transaction ID, or speedup.

**Tests:** SQL location mapping, busy error, unexpected error, partial metrics, counters isolated between sequential queries, and no leaked internal paths/tracebacks.

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
- Show a brief mode label such as `Read-only demo · Transactions pending`. Put detailed development limits in the runbook, not in the main interaction.
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
- Associate displayed metrics with this result and separate partial from complete consumption.
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
- Test malformed SQL, semantic errors, disabled writes/transactions, and second statements with unchanged persistent data.
- Test overlapping requests, including metadata during a query, with deterministic synchronization.
- Test early preview close, conversion/iteration errors, and busy-state release after cleanup.
- Run relevant API tests, existing Stage 7 regressions, frontend type/build checks, and repository-mandated checks. Record failures; do not claim the whole suite passed if only a subset ran.
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
- Record precisely which functionality is demonstrated and which work remains for Stage 8/10.

**Acceptance:** Another teammate can start the application from the runbook and repeat the demonstration.

### Task 9.16 — Optional verified mutation demonstration

**Priority:** P1; skip entirely if presentation time is short.

**Prerequisite:** Existing Stage 7 write consistency, index maintenance, ordinary-failure, and clean-reopen tests pass. No new transaction implementation belongs here.

**Actions:**

- Enable INSERT/DELETE only through explicit server configuration, default off, against the disposable demo directory.
- Extend the parsed-statement allowlist; retain the same admission guard and execute each accepted command synchronously once.
- Return actual affected rows separately from SELECT previews. Fetching/rendering the response must not execute the command again.
- Do not automatically retry mutations on timeout, refresh, or network failure. A lost response means outcome unknown until inspected; a request ID is not deduplication.
- Keep transaction controls unsupported. Do not call these operations committed transactions or claim rollback/crash atomicity.
- Surface confirmed partial effects from the existing failure contract. Stop writes if base/index consistency is uncertain.
- Demonstrate an insertion followed by a read-back and an exact-target deletion only after rehearsal; reset offline while the backend is stopped.

**Tests:** Disabled write has no effects, enabled write runs once, affected count, scan/index agreement, simulated response loss without retry, and persistence after clean restart.

**Acceptance:** Optional writes remain truthful about their Stage 7 guarantees. Failure to pass this gate leaves the read-only demo intact.

### Task 9.17 — Optional presentation polish

**Priority:** P1; no feature below compensates for a failing P0 task.

**Actions:** Improve font sizes, panel spacing, table readability, keyboard access, status badges, and useful plan detail expansion. Add lightweight syntax highlighting only if it is already easy to integrate. Match existing project style instead of rebuilding a design system.

**Acceptance:** Polish does not introduce new dependencies or behavior that destabilizes the rehearsed execution path. Repeat the browser smoke check after changes.

### Task 9.18 — Record progress and return to Stage 8

**Actions:**

- Record `Stage 9 emergency demo ready` only after its checklist passes; leave Stage 8 and Stage 10 pending.
- Update project progress pointers to show the temporary order and the manual-parser decision.
- Record real endpoint/types, resource limits, local launch commands, allowed statements, and known limitations.
- Identify the adapter boundaries where Stage 8 will add session/transaction ownership, transaction syntax, and concurrency behavior.
- Retain the admission guard until Stage 8 protection is integrated and tested across HTTP requests and result lifetimes. Removing it simply because a lock-manager class exists is insufficient.
- List the remaining Stage 9 work after Stage 8: transaction-aware API errors/results, session lifetime, cursor/transaction interaction, disconnect behavior, concurrent tests, and optional write controls.
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
| 8 | Explain pending work | Transactions/concurrency and full experiments remain pending |

Check the actual plan instead of promising a particular index if the planner chooses another valid path. A small fixture proves correctness and connectivity, not scalability. If showing external spills, use the separately rehearsed larger fixture and real counters; do not describe the four-row example as proof of disk spilling.

Suggested explanation:

> This interface executes SQL through our own storage, indexes, and query operators. The current presentation mode admits one engine operation at a time. Transaction grouping and database concurrency control are the next milestone; the present interface does not claim those guarantees.

## 11. Completion checklists

### Emergency Stage 9 demo ready

- [ ] Actual Stage 7 entry points and relevant baseline tests were inspected.
- [ ] The authorized sequencing exception is recorded; Stage 8 is still pending.
- [ ] Existing handwritten parsing is reused with no second parser.
- [ ] Demo data is persistent, deterministic, and separate from normal working data.
- [ ] One backend process owns the data and uses one shared engine admission guard.
- [ ] Competing engine requests are rejected; exceptions/disconnects cannot release admission prematurely.
- [ ] HTTP writes and transaction commands are rejected by default before execution.
- [ ] Query execution reaches the actual project engine once per accepted request.
- [ ] Row and byte caps preserve bounded output, complete/partial status, and truthful totals.
- [ ] Cursors/temp resources close before engine admission is released.
- [ ] Files, Query, Results, and Execution Plan panels all function.
- [ ] Plans/index labels come from real engine descriptors.
- [ ] Empty, error, busy, truncated, and backend-unavailable states are clear.
- [ ] Values and schemas retain correct ordering, types, duplicates, and null behavior.
- [ ] Relevant API/engine tests and frontend build checks pass, with actual scope recorded.
- [ ] The browser demonstration works after clean startup/reopen.
- [ ] A teammate can follow the launch/runbook and repeat the presets.
- [ ] Known limits and Stage 8/10 follow-up are documented.

### Optional writes ready, only if enabled

- [ ] Explicit configuration enables writes only on disposable demo data.
- [ ] Existing Stage 7 consistency/failure tests pass.
- [ ] INSERT/DELETE execute once and report actual outcomes.
- [ ] No automatic mutation retry or false rollback claim exists.
- [ ] Scan/index agreement and clean-reopen persistence are verified.

### After Stage 8, before claiming complete integration

- [ ] Transaction/session semantics are connected through the API and reflected in the UI where needed.
- [ ] Cursor lifetime, failure, and disconnect policies agree with implemented transaction semantics.
- [ ] Simultaneous requests are tested under the real database concurrency mechanism.
- [ ] Mandatory thread-based race/protected-execution demonstration exists.
- [ ] The temporary admission policy is retained or revised only after real protection is verified.
- [ ] Stage 9 regressions still pass; Stage 10 experiments and final requirements are completed separately.

## 12. Suggested modules and deliverables

Adapt names to the actual repository. These are implementation suggestions, not files to create regardless of need.

| Location | Responsibility |
|---|---|
| api/app.py | Application lifecycle, routes, and transport configuration |
| api/engine_service.py | Engine ownership, admission, policy, bounded result conversion |
| api/schemas.py | Request/response/error contracts |
| frontend/src/api/ | Typed HTTP client and response types |
| frontend/src/components/ | Four required panels and small shared UI components |
| scripts/setup_demo.py | Explicit offline preparation/reset of dedicated demo fixtures |
| tests/api/ | Real-engine HTTP integration, bounds, errors, and admission tests |
| Existing frontend test location | UI state and response association tests |
| docs/demo.md | Launch commands, exact presets, expected results, limitations, and rehearsal evidence |

The artifact for this planning task is ETAPA_09.md. Creating it does not itself implement these modules or modify other coordination documents. Their updates are tasks for the implementation work.

## 13. Working prompts for Codex

### Inspection and immediate execution plan

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_07.md, and ETAPA_09.md. Stage 7 is reported complete; Stage 8
is not implemented. The user explicitly authorized the emergency Stage 9
sequence. Preserve the handwritten parser.

Complete Task 9.1, identify actual interfaces/scripts and relevant test
results, and freeze Task 9.2's smallest demo contract. Reuse existing code.
Do not implement transactions or reimplement engine algorithms.
```

### First vertical increment

```text
Implement Tasks 9.3-9.8 and the minimum portions of 9.9-9.11 needed for
one real SELECT from the browser. Use the existing engine, dedicated
persisted fixtures, one backend worker, exclusive engine admission,
server-enforced read-only policy, and bounded rows/JSON bytes.

Close the result and capture detached plan/metrics before releasing
admission. Add focused tests. Do not introduce Lark, fetchall, fake rows,
mock production plans, transaction controls, or public deployment.
```

### Complete the required interface

```text
Finish the four real panels, errors, and verified presets in Tasks
9.9-9.13. Use the same request's actual plan, result, and statistics.
Keep preview truncation explicit and protect against stale responses.
Prioritize a readable nested plan over graphical decoration.
```

### Presentation gate

```text
Execute Tasks 9.14-9.15 and 9.18. Verify real HTTP/browser behavior,
full-input rejection, preview/resource limits, overlapping-request
rejection, error recovery, clean restart, and all four panels.
Record actual commands and evidence. Mark only the emergency milestone
ready; Stage 8 and Stage 10 remain pending. Skip P1 until P0 passes.
```

### Return after the presentation

```text
Inspect the demo integration and prepare the Stage 8 plan from actual
engine/API boundaries. Keep transactions, session ownership, cursor
lifetimes, failure guarantees, and concurrency testing explicit. Do not
remove the temporary admission guard before real protection is verified.
After Stage 8, finish Stage 9 integration and proceed to Stage 10.
```
