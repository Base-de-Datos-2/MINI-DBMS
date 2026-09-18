# Stage 7 review — Tasks 7.26-7.30

**Date:** 2026-09-18

**Scope:** Block 8 of the revised `ETAPA_07.md`

**Boundary:** reporting closure, public acceptance, restart/external/resource
evidence, differential regression, documentation, and formal closure

## Result

Tasks 7.26-7.30 are implemented and verified. The exact acceptance dataset is
executed through the public SQL API, real Stage 6 external paths are forced
under small budgets, durable files are reopened through fresh managers, and
normal, early-close, and injected-failure paths release all owned resources.
Optimized SQL results agree with forced scan and alternative join baselines.

The full warnings-as-errors suite passes 2,556 tests. All 63 Stage 7 Definition
of Done criteria are now checked, and the formal evidence is in
`docs/ETAPA_07_AUDIT.md`.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| Executing an existing `PreparedQuery` accepted new `use_indexes` or planning options but ignored them | A caller could believe a different route was executed than the prepared/reportable plan | Reject every execution-time planning override for a prepared query and require explicit re-preparation |
| Prepared TableScan/IndexScan and mutation descriptions omitted concrete storage or exact mutation indexes | The public report could not fully identify the durable route affected | Add concrete storage adapter names, table identity, chosen access index, and exact mutation index names |
| Equivalent query tests did not execute the exact Section 12 dataset | Stage acceptance could not be reproduced literally from the specification | Add one public acceptance module using the stated students/enrollments rows and statements |
| External algorithms were tested below SQL but not as a complete public-API resource matrix | SQL wiring could bypass spilling, restart, or cleanup behavior without detection | Force multi-pass sort, group repartition, Grace-join overflow/fallback, fresh reopen, early close, and writer failure through `SqlEngine` |
| The existing closure audit described an unreproducible older tree | Documentation falsely implied Stage 7 had already closed | Replace it with the successful current-tree audit and exact commands/counts |
| There was no consolidated public SQL usage guide | Supported syntax, lifecycle, reports, failure guarantees, and limits were scattered | Add `docs/sql.md` and link it to the normative grammar and Stage 8 handoff |
| A Stage 6 integration test asserted the old exact TableScan descriptor | Truthful storage reporting broke a stale presentation assertion | Update the expected string and rerun the entire suite from zero |

## Acceptance and differential evidence

`tests/query/test_stage7_acceptance.py` verifies:

- exact output schemas and values for the Section 12 dataset;
- actual hash equality and unclustered B+ equality/range routes;
- residual predicates and OR fallback to TableScan;
- hidden ORDER BY fields and final projection;
- measured `ExternalHashGroup` and `GraceHashJoin` execution;
- INSERT/DELETE reports, scan/index agreement, and fresh-manager read-back;
- clustered B+ access over `PagedSequentialFile`;
- optimized/index-disabled equivalence and Grace/NestedLoop join equivalence;
- unchanged storage/index state after syntax, semantic, and predictable
  mutation failures;
- rejection of planning overrides on an existing prepared query.

`tests/query/test_stage7_resources.py` verifies:

- sort initial runs beyond fan-in and at least two merge passes;
- real temporary page I/O, spill bytes, peak memory, and peak handles;
- group repartition and budget-invariant grouped results;
- Grace join overflow plus actual nested-loop fallback and baseline equivalence;
- cleanup after full consumption, early close, and injected temporary-write
  failure;
- fresh storage/index manager reopen followed by index, group, sort, and join
  SQL in a new environment.

Focused results:

```text
tests/query/test_stage7_acceptance.py                 6 passed in 1.89s
tests/query/test_stage7_resources.py                  5 passed in 51.29s
tests/query + tests/test_architecture.py            281 passed in 128.14s
tests (warnings as errors, no pytest cache)         2556 passed in 936.76s
```

## Reporting outcome

Prepared descriptions remain immutable and read-only. Runtime reports come
from the actual fresh Stage 6 tree and distinguish complete, early-closed, and
failed executions. They expose real operator hierarchy and measured counters;
mutation reports add affected rows, storage/index maintenance, and DELETE
discovery/spool evidence. No report claims transaction isolation, rollback,
WAL recovery, concurrency safety, or a measured index speedup.

## Closure and handoff

The supported behavior and limits are consolidated in `docs/sql.md`; the
formal grammar remains in `docs/sql-grammar.md`. `ETAPA_07.md`, `PLAN.md`,
`PROJECT_CONTEXT.md`, and `AGENTS.md` identify Stage 7 as closed and Stage 8 as
the next roadmap stage. No `ETAPA_08.md` or Stage 8 implementation is claimed.
