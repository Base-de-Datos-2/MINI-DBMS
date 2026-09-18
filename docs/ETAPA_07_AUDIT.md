# Stage 7 closure audit — SQL parser, planner, and executor

**Closure date:** 2026-09-18

**Stage specification:** `ETAPA_07.md`

**Result:** Tasks 7.1-7.30 and all 63 Definition of Done criteria are satisfied.

## Reproducible evidence

The formal cross-stage command was run from the repository root with the
project virtual environment:

```powershell
.venv\Scripts\python.exe -m pytest tests -q -W error -p no:cacheprovider
```

Result:

```text
2556 passed in 936.76s (0:15:36)
```

No Stage 7 mutation, acceptance, restart, spilling, cleanup, or differential
test is skipped or marked expected-failure. Focused evidence also passed:

| Scope | Result |
|---|---:|
| `tests/query/test_stage7_acceptance.py` | 6 passed |
| `tests/query/test_stage7_resources.py` | 5 passed |
| `tests/query` plus `tests/test_architecture.py` | 281 passed |

The first complete run exposed one stale Stage 6 exact-string assertion after
TableScan descriptors began naming the concrete storage adapter. The assertion
was updated to the truthful descriptor and the complete suite was rerun from
zero; only the successful 2,556-test rerun is closure evidence.

## Task closure

| Tasks | Evidence and implemented behavior |
|---|---|
| 7.1-7.2 | Stage 6 prerequisites were inspected; the handwritten-parser contract, exact supported syntax, aliases, comments, signed-number rules, whole-table DELETE policy, and real baseline are documented. |
| 7.3-7.4 | Parser-independent immutable AST nodes and complete token metadata retain source spans, exact lexemes, decoded values, EOF, limits, and controlled lexical failures. |
| 7.5-7.7 | The bounded recursive-descent parser covers SELECT, INSERT, DELETE, precedence, optional syntax, full-input consumption, fresh state, and located diagnostics. |
| 7.8-7.12 | Catalog-backed binding resolves names, exact types, projections, hidden order dependencies, aggregates, joins, and mutation targets without writes. |
| 7.13-7.17 | Immutable plan specifications create fresh TableScan, hash/B+ IndexScan, Filter, and Projection trees with safe candidates, residual predicates, range endpoints, and stale-plan checks. |
| 7.18-7.20 | SQL reaches the real Stage 6 `ExternalSort`, `ExternalHashGroup`, `GraceHashJoin`, eligible `IndexNestedLoopJoin`, and selectable `NestedLoopJoin` baseline. |
| 7.21-7.22 | `SqlEngine`, reusable `PreparedQuery`, streaming `QueryResult`, synchronous `CommandResult`, and explicit completion states own fresh transient execution resources. |
| 7.23-7.25 | The shared maintenance service keeps base storage and all declared indexes aligned, uses bounded stable DELETE targets, repairs ordinary failures, and persists incomplete-index state when repair fails. |
| 7.26 | Prepared facts and measured runtime reports are separate. Descriptors name real operators, concrete storage adapters, chosen indexes, predicates, keys, and exact mutation indexes; runtime data comes from actual Stage 6 reports. Prepared planning options cannot be silently overridden at execution. |
| 7.27 | The exact Section 12 students/enrollments dataset passes through the public API across selection, hash/B+ access, Boolean fallback, hidden ordering, grouping, joins, INSERT, DELETE, and semantic rejection. |
| 7.28 | Fresh-manager restart, forced sort runs and merge passes, group repartition, Grace-join overflow/fallback, early close, injected failure, memory/handle accounting, and temporary cleanup are verified. |
| 7.29 | Optimized results agree with forced TableScan and manual algorithm baselines; malformed, semantic, and failed-execution paths preserve the specified permanent state; the full Stage 1-7 regression suite passes. |
| 7.30 | The grammar contract, public SQL guide, architecture, roadmap, stage status, limitations, and Stage 8 integration points are documented without implementing Stage 8. |

## Definition of Done mapping

The 63 checked criteria in `ETAPA_07.md` are supported as follows:

| Criterion group | Count | Primary evidence |
|---|---:|---|
| Contracts and parsing | 16 | `docs/sql-grammar.md`; lexer/parser/AST tests; malformed-input, span, limit, precedence, fresh-state, and no-write tests |
| Semantic analysis | 9 | binder tests and public acceptance tests for resolution, ambiguity, exact types, output schemas, hidden order fields, aggregates, joins, and pre-write validation |
| Physical planning | 10 | plan-structure, index-pushdown, external planning, join strategy, fresh-instance, and optimized-versus-baseline tests |
| Execution and results | 8 | executor lifecycle tests plus acceptance/resource tests for streaming, duplicate multiplicity, empty/combined queries, cleanup, completion states, repeat safety, and reporting |
| Mutations | 10 | mutation-maintenance and executor-write tests for every-index consistency, bounded stable targets, RID movement, validation atomicity, compensation, incomplete markers, flushes, and honest affected counts |
| Verification and handoff | 10 | exact acceptance dataset, differential baselines, forced external paths, fresh restart, read-only preservation, injected failures, complete strict suite, reports, and closure documentation |

The NULL criterion is satisfied by a documented absence of NULL: the Stage 6
row model and Stage 7 grammar do not admit a SQL NULL literal or three-valued
logic. This policy is consistent across predicates, indexes, grouping, joins,
and mutations and is tested as unsupported syntax.

## Verified reporting contract

`PreparedQuery.describe()` is read-only and reports planned facts. SELECT
execution reports are produced from the actual operator instances and retain
measured page I/O, temporary I/O, spills, memory, handles, runs, passes,
partitions, recursion, fallback details, elapsed time, and row counts where the
operator exposes them. INSERT/DELETE reports identify the concrete storage
adapter and exact maintained indexes. DELETE additionally reports its executed
discovery plan and bounded spool statistics.

An early-closed result reports partial delivery and `fully_consumed=False`; a
failed result is never converted to success. A caller cannot pass new planning
options while executing an existing `PreparedQuery`, so the reported prepared
plan cannot diverge from a silently replanned execution.

## Declared limitations

Stage 7 deliberately remains a limited educational SQL engine:

- exactly one inner JOIN is supported; outer joins, subqueries, set operations,
  HAVING, DISTINCT, UPDATE, DDL, expressions, and multi-row VALUES are absent;
- NULL/defaults and implicit numeric coercion are absent;
- the planner is deterministic and rule-based, not cost-based;
- DELETE discovery currently uses the safe TableScan/Filter route;
- there is no SQL `EXPLAIN`; the Python API exposes real descriptions/reports;
- Catalog registration remains in memory although storage/index formats persist;
- ordinary mutation compensation is not transaction rollback, isolation, WAL,
  concurrent-write safety, or crash-atomic multi-file commit.

These limits agree with the frozen Stage 7 contract and are documented in
`docs/sql.md` and `docs/sql-grammar.md`.

## Closure decision and handoff

Stage 7 is formally closed. Stage 8 is the next roadmap stage, but no detailed
`ETAPA_08.md` plan is claimed to exist. The existing handoff points are
`SqlEngine` session ownership, `QueryResult` lifetime and states,
`MutationService` as the table-wide write boundary, persistent incomplete-index
markers, and borrowed durable managers in `QueryEnvironment`. Transaction
identity, locking, competing sessions, commit/abort, deadlocks, and recovery
must be designed in Stage 8 rather than inferred from Stage 7 compensation.

Part 1 remains incomplete because Stages 8-10 are still open.
