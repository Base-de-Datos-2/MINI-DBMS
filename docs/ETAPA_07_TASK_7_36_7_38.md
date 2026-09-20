# Stage 7 Tasks 7.36–7.38 evidence

**Date:** 2026-09-20  
**Scope:** engine-level `EXPLAIN SELECT`, `EXPLAIN ANALYZE SELECT`, and the
compatible public result contract.  
**Excluded:** Stage 9 HTTP/frontend serialization, Stage 8 transactions and
concurrency, cost estimation, and PostgreSQL-compatible formatting.

## Implemented behavior

`ExplainPlanSpec` wraps the same immutable `SelectPlanSpec` produced for an
ordinary SELECT. It preserves the caller's physical planning options and index
policy and exposes the child's structured `PlanSpecDescriptor` directly.

Plain EXPLAIN performs a side-effect-free identity recheck for every selected
table and index. It does not instantiate a Stage 6 operator, open a cursor,
read rows, or allocate a temporary workspace. The completed explanation has:

- `StatementKind.EXPLAIN` and `ResultKind.EXPLANATION`;
- `executed == False` and `complete == True`;
- the prepared physical tree, including children, columns, predicates, sort
  keys, table/storage names, and selected index identity;
- `statistics`, `output_rows`, and `execution_seconds` set to `None`.

EXPLAIN ANALYZE instantiates one fresh SELECT tree and drains it once to EOF.
Rows are discarded as they are counted; the SELECT materialization limit is
not consulted. The physical plan is closed before the synchronous result is
returned. The completed explanation has:

- `StatementKind.EXPLAIN_ANALYZE` and `ResultKind.EXPLANATION`;
- `executed == True` and `complete == True`;
- final root output cardinality and the actual post-cleanup Stage 6
  `PlanReport`;
- separate parse/bind/plan and execution-through-cleanup wall times;
- the actual runtime descriptor, counters, spill evidence, and fallback facts
  already reported by Stage 6 operators.

An execution or cleanup failure raises `AnalysisExecutionError`. Its
`ExplanationExecutionReport` is `FAILED`, has `complete == False`, retains the
original cause, names the error type/message, and includes any partial runtime
report available after cleanup. No failed analysis is returned as successful.

## Public ownership and compatibility

Every public result now exposes a statement identity. The result dispatch
surface is exhaustive:

| Result | Statements | Ownership |
|---|---|---|
| `QueryResult` / `ROWS` | SELECT | Caller drains or closes the active stream |
| `CommandResult` / `COMMAND` | INSERT, DELETE | Synchronous and complete |
| `DefinitionResult` / `DEFINITION` | CREATE | Synchronous; no affected-row count |
| `ExplanationResult` / `EXPLANATION` | EXPLAIN, EXPLAIN_ANALYZE | Synchronous; no row schema or retained rows |

An unconsumed SELECT still blocks every later statement on the same engine.
All explanation resources are released before return, so a later call can run
immediately. Parsing still consumes the complete submission before binding or
execution; invalid second statements cannot partially create or insert data.

Located syntax, unsupported-feature, and binding errors retain the established
SQL hierarchy. Invalid definitions, duplicate table/key failures, invalid
values, and storage failures retain their existing domain errors. Incomplete
analysis is the one new execution-specific public error described above.

The Stage 9 service keeps its earlier explicit allowlists and result dispatch
until Tasks 7.39–7.40 or a separately requested integration updates its HTTP
contract. Adding enum members did not grant access automatically.

## Verification

Focused contract and compatibility gate:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/query/test_explain.py `
  tests/query/test_parser_extension.py `
  tests/query/test_executor_results.py `
  tests/database/test_managed_database.py `
  -q -W error
```

Result: **83 passed**.

SQL and unchanged Stage 9 API regression gate:

```powershell
.venv\Scripts\python.exe -m pytest tests/query tests/api -q -W error
```

Result: **407 passed**.

The tests cover non-instantiation and absence of temporary work for plain
EXPLAIN, index/scan descriptions, unknown names, unsupported children,
exact-once execution, empty and populated cardinality, repeated-run isolation,
a zero preview cap, real external sort spilling and cleanup, injected partial
failure and recovery, active-stream ownership, and pre-effect complete-input
validation.

Complete repository gate:

```powershell
.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
```

Result: **2,734 passed in 1,320.15 seconds (22:00)**. Tasks 7.39–7.40 remain
pending and this document does not close the extension.
