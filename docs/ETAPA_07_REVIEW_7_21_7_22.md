# Stage 7 review — Tasks 7.21-7.22 and initial Task 7.26

**Date:** 2026-09-18

**Scope:** Block 6 of the revised `ETAPA_07.md`

**Boundary:** reusable SELECT execution, streaming result ownership, public
Python API, and the prepared/runtime reporting foundation

## Result

Tasks 7.21-7.22 are implemented and verified for the currently executable
SELECT path. `SqlEngine.prepare()` parses, binds, and plans without executing;
each `PreparedQuery.execute()` instantiates a fresh Stage 6 operator tree and
`ExecutionContext`; and `QueryResult` streams rows while owning deterministic
cleanup and retaining its final report. The engine can be used without an HTTP
or frontend dependency.

The mutation-facing clauses of Task 7.22 remain intentionally unavailable
until Tasks 7.23-7.25 provide atomic INSERT/DELETE maintenance. Mutation plans
can be prepared and inspected without writes, but attempting to execute one
raises a controlled `UnsupportedAccessError`. This preserves the stage order
and prevents a result iterator from becoming an accidental mutation trigger.

The initial SELECT-side reporting foundation of Task 7.26 is also implemented.
Prepared descriptions are immutable planning facts; runtime reports are taken
from the actual instantiated operators and include measured Stage 6 counters.
Task 7.26 remains open until mutation reporting and the complete acceptance
matrix are available. Stage 7 remains open.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| Stage 7 had reusable plan specifications but no owner for Stage 6 `PhysicalPlan` executions | Callers had no stable way to open, stream, close, or inspect a planned SQL statement | Add `SqlEngine`, `PreparedQuery`, and `QueryResult` over the existing Stage 6 contract |
| Reusing a previously instantiated operator tree would also reuse exhausted cursors and mutable algorithm state | A second execution could be empty, corrupt, or inherit stale counters/resources | Keep only immutable specifications in prepared queries and instantiate a new tree and context for every execution |
| Result cleanup did not have a Stage 7 ownership boundary | Early stop and exceptions could leak temporary files, cursors, memory reservations, or handles; closing too much could invalidate Catalog-managed storage | Make each result own only its physical plan/context/transient resources and borrow permanent storage/index managers |
| Exhaustion, early close, partial failure, and cleanup failure were not distinguishable to API consumers | A truncated preview or failed stream could be reported as a successful empty/completed query | Define `CREATED`, `OPEN`, `COMPLETE`, `CLOSED`, and `FAILED`; preserve the original exception and record partial delivery separately |
| Cleanup could mask the original execution error or stop after the first cleanup error | Diagnostics would identify the wrong cause and later resources could remain open | Attempt stream and plan cleanup independently, retain the primary failure, and attach secondary cleanup failures as notes |
| An active result was checked only after work for the next statement could begin | A second statement could parse/bind before the single-session policy rejected it | Enforce the idle-session boundary before preparing or executing the next statement |
| Unconditional eager materialization would defeat bounded Stage 6 execution | Large query results could consume unbounded memory or be silently truncated | Keep iteration and `fetchmany()` primary; require an explicit hard limit for `fetchall()` and use a bounded compatibility `rows` property that raises rather than truncates |
| Prepared facts and runtime evidence had no explicit separation | A UI could present estimated/selected operators as if they were measured execution | Return a `PlanSpecDescriptor` before execution and a distinct `PlanReport` only after an actual run starts |
| Runtime index descriptors exposed only the adapter class | Reports could not prove which persisted index was actually opened | Add the persisted index name to index-scan and index-assisted operator details while retaining the adapter type |
| Stage 6 source accounting covered `IndexScan` but omitted index-assisted join/group operators | Runtime reports understated permanent base/index I/O for those plans | Capture inner table and index sources for `IndexNestedLoopJoin` and `IndexOrderedGroup` |
| Exposing mutation execution before the shared maintenance layer exists would risk partial table/index updates | INSERT/DELETE could violate the all-index consistency contract | Permit no-write preparation/inspection and reject execution until Tasks 7.23-7.25 implement the maintenance boundary |

## Frozen execution and result policies

- Prepared queries are reusable specifications, not live cursors.
- Every execution receives a fresh operator tree and `ExecutionContext`.
- One unconsumed SELECT result owns a `SqlEngine` session at a time. This is a
  lifecycle rule, not a Stage 8 concurrency guarantee.
- A result owns transient execution resources and never closes permanent
  Catalog-managed table/index handles.
- Normal exhaustion produces `COMPLETE`; explicit early close produces
  `CLOSED`; execution or cleanup failure produces `FAILED`.
- A consumer exception closes owned resources but remains a consumer-side
  early termination rather than being mislabeled as an engine execution error.
- Streaming is the primary interface. Bounded materialization never silently
  drops rows.
- Prepared descriptions do no I/O and never apply mutations. Runtime reports
  describe the instantiated operator tree and measured counters.
- INSERT/DELETE execution is closed until the maintenance work in Tasks
  7.23-7.25 can return one synchronous, completed command result.

## Implemented modules

| Module | Responsibility |
|---|---|
| `engine/query/executor.py` | Public prepare/execute facade, fresh execution construction, streaming result state machine, bounded fetch helpers, cleanup/error ownership, and prepared/runtime reports |
| `engine/query/__init__.py` | Stable public exports for the execution and result API |
| `engine/operators/scan.py` | Persisted runtime index identity for index scans |
| `engine/operators/index_strategies.py` | Persisted runtime index identity for index-assisted group/join routes |
| `engine/operators/pipeline.py` | Permanent table/index I/O capture for all current index-assisted operator families |
| `tests/query/test_executor_results.py` | 18 lifecycle, failure, ownership, streaming, repeated-execution, session, no-write mutation, and reporting regressions |

The stable ownership and reporting decisions are recorded in
`PROJECT_CONTEXT.md`; the public execution contract is also documented in
`docs/sql-grammar.md`. `PLAN.md`, `ETAPA_07.md`, and `AGENTS.md` keep Stage 7
open and identify the remaining work.

## Verification evidence

Focused syntax, binding, planning, execution, reporting, and architecture
coverage:

```text
.venv/Scripts/python.exe -m pytest \
  tests/query/test_ast.py tests/query/test_lexer.py \
  tests/query/test_parser.py tests/query/test_parser_contract.py \
  tests/query/test_binder.py tests/query/test_planner_block_5a.py \
  tests/query/test_planner_relational.py tests/query/test_planner_select.py \
  tests/query/test_executor_results.py tests/test_architecture.py \
  -q -W error -p no:cacheprovider

243 passed in 169.94s (0:02:49)
```

The 18 Block 6 regressions include empty and fully consumed results, bounded
batches, early close, consumer exceptions, failures during open/next/close,
fresh repeated execution, the active-result rule, bounded materialization,
read-only mutation inspection, actual persisted index identity, measured
index-assisted I/O, and partial external-sort spill reporting.

The affected Stage 6 reporting/operator subset also remains green:

```text
94 passed in 184.84s (0:03:04)
```

Cross-stage strict regression:

```text
.venv/Scripts/python.exe -m pytest tests \
  --ignore=tests/query/test_executor_writes.py \
  --ignore=tests/query/test_index_pushdown.py \
  -q -W error -p no:cacheprovider

2519 passed in 635.70s (0:10:35)
```

The two ignored files require INSERT/DELETE execution and index maintenance
from Tasks 7.23-7.25. Unlike the previous Block 5B baseline,
`test_planner_select.py` is now included in the strict suite because the public
`QueryResult` and `run_sql` API exists.

`compileall`, `pip check`, and `git diff --check` also pass.

## Handoff to the next block

Tasks 7.23-7.25 must add a shared mutation-maintenance service and synchronous
command results without weakening this result lifecycle. Once both write paths
exist, Task 7.26 can finish mutation reporting and Tasks 7.27-7.30 can run the
complete end-to-end, restart, cleanup, documentation, and closure acceptance
matrix.
