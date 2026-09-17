# Stage 7 review — Tasks 7.8-7.12

**Date:** 2026-09-17  
**Scope:** Block 4 of the revised `ETAPA_07.md`  
**Boundary:** semantic binding and read-only mutation validation

## Result

Tasks 7.8-7.12 are implemented and verified. `engine/query/binder.py` resolves
the parser-independent AST against Catalog metadata and explicitly registered
runtime objects. It produces immutable semantic results built from Stage 6
`ColumnReference`, expression, layout, and aggregate contracts. Binding does
not construct physical operators or write table/index state.

Stage 7 remains open. The later review completed basic physical planning in
Tasks 7.13-7.17. Advanced planning, execution, mutation maintenance,
end-to-end acceptance, and closure work in Tasks 7.18-7.30 remain pending.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| Catalog intentionally stores metadata but no open storage/index objects | A binder could resolve a table name while still planning against no real physical target | Added `QueryEnvironment`, an explicit borrowed-object registry that verifies exact Catalog identity, storage schema, index header/type/capability, and adapter/storage association where exposed |
| Unresolved AST names could have leaked into Stage 6 operators | Ambiguous join columns or stale table aliases could resolve differently downstream | Bound every executable reference to Stage 6 `ColumnReference` identities through `RowLayout`; aliases replace the original qualifier and relation instances receive distinct IDs |
| Reimplementing predicate typing in the SQL layer risked disagreement with scans and indexes | A query could compare values that an index cannot represent consistently | Lowered predicates to Stage 6 `Expression` objects and binds them immediately; exact types and the no-coercion policy remain authoritative |
| A planner needs safe index candidates without weakening full Boolean meaning | Extracting an OR branch or lossy conversion could create false negatives | Expose only exact-type equality/range column-literal terms from top-level conjunctions; keep `<>`/OR/NOT residual-only, reverse operators safely, canonicalize FLOAT signed zero like the hash codec, and retain the complete expression as the residual predicate |
| JOIN ON previously had syntax but no executable semantic contract | A non-equality join could reach a hash-join planner that cannot execute it correctly | Require at least one equal-typed column equality crossing the two inputs; preserve additional supported ON terms as residuals |
| SELECT aliases, source fields, and hidden ORDER BY dependencies had no resolved scope | WHERE could incorrectly see SELECT aliases, or projection could discard a required sort key | Bind WHERE before projection, give exact output names, reject duplicates/positional ordering, resolve bare ORDER BY names to output aliases first, and mark unselected source keys as hidden dependencies |
| Aggregate calls had syntax but no signature/grouping validation | Invalid SUM/AVG inputs or ungrouped selected columns could fail during execution | Instantiate and bind the Stage 6 aggregate classes, distinguish COUNT forms, adopt tested global aggregation, reject GROUP BY without an aggregate, and enforce grouped SELECT/ORDER BY rules |
| INSERT values were syntactically literals but not guaranteed storable | Type/range/page-size/index-key failures could happen after the first write | Reorder optional column lists into schema order; require every field because NULL/defaults do not exist; validate exact types, int64/UTF-8 encoding, page capacity, and every registered index key before returning a bound mutation |
| Declared indexes could be unavailable during a mutation | A table write could leave an index stale | Mutation binding requires a live adapter for every Catalog index and records every association the future maintenance layer must update |
| Known uniqueness violations were deferred too late | A predictable duplicate could reach a mutation path before rejection | Perform read-only probes of unique indexes and unique Paged Sequential keys. Bound results retain recheck flags because Task 7.23 must validate again immediately before writing |
| DELETE requires physical identity and may interact with RID-moving storage | Value-only deletion or scan-and-mutate over a moving organization can target the wrong row | Bound DELETE retains the real storage, target layout, required RID flag, all affected indexes, and whether the storage may move RIDs; no rows are deleted in this block |

## Frozen semantic policies

- Catalog and SQL identifier lookup is exact and case-sensitive.
- A relation alias replaces the table name inside that query scope.
- One supported self-join uses two distinct aliases/instance IDs over the same
  table metadata and storage.
- Duplicate relation aliases and duplicate published output names are errors.
- `*` expands in FROM-then-JOIN and schema-column order. Qualified star uses
  the exposed relation name.
- INTEGER/FLOAT are not implicitly converted. NULL/defaults are absent.
- Safe index conditions come only from a direct comparison or top-level AND;
  OR and NOT remain complete residual expressions.
- Bare ORDER BY names prefer an exact output alias, then resolve as source
  fields. Qualified names always resolve in source scope. Positional ORDER BY
  and general expressions are rejected.
- The adopted grouped-query subset requires at least one aggregate. Global
  aggregation without GROUP BY is supported when every selected item is an
  aggregate.
- Stage 6 owns aggregate input/output types and empty-input behavior.
- Binding may read a uniqueness structure but cannot mutate it. Execution must
  repeat mutable-state checks; binding does not claim isolation.

## Implemented modules

| Module | Responsibility |
|---|---|
| `engine/query/environment.py` | Pair immutable Catalog definitions with borrowed live storage/index adapters and verify compatibility |
| `engine/query/binder.py` | Resolve relations, expressions, joins, projection/order dependencies, grouping/aggregates, and mutation targets |
| `engine/query/errors.py` | Add located semantic errors while preserving `UnknownTableError`/`UnknownColumnError` compatibility |
| `engine/query/__init__.py` | Export the reviewed semantic API |
| `tests/query/test_binder.py` | Positive, negative, no-write, real-index, grouping, join, alias, range, size, and uniqueness regressions |

The bound classes are semantic data only. Task 7.13 still owns physical plan
specifications, operator factories, schema-version/reuse policy, and mutation
plan construction.

## Verification evidence

```text
.venv/Scripts/python.exe -m pytest \
  tests/query/test_binder.py \
  tests/query/test_ast.py tests/query/test_lexer.py \
  tests/query/test_parser.py tests/query/test_parser_contract.py \
  tests/test_architecture.py -q -W error

175 passed in 7.86s
```

The focused set includes 52 new binding tests, the 104 reviewed AST/lexer/parser
tests, and 19 architecture/import checks. It verifies that failed or successful
mutation binding leaves spy and real storage/index state unchanged.

The cross-stage strict regression also passes:

```text
.venv/Scripts/python.exe -m pytest \
  --ignore=tests/query/test_executor_writes.py \
  --ignore=tests/query/test_index_pushdown.py \
  --ignore=tests/query/test_planner_select.py \
  -q -W error -p no:cacheprovider

2451 passed in 549.91s (0:09:09)
```

This is the 2,295-test Stage 1-6 baseline plus 104 reviewed syntax tests and 52
new binding tests. No test was skipped. At this review point, a complete
`tests/query` collection found 154 implemented cases and stopped on the three
then-future imports: `engine.query.planner`, `engine.query.executor`, and
`engine.maintenance`. Tasks 7.13-7.17 subsequently added the real planner;
executor and maintenance remain pending rather than receiving placeholders.

## Handoff status

Tasks 7.13-7.17 now consume `BoundSelect`, `BoundInsert`, and `BoundDelete`
without reinterpreting raw SQL. The reviewed basic planner keeps the full
residual predicate, instantiates fresh Stage 6 operators, and exposes no-write
mutation variants. Tasks 7.18-7.20 must extend those specifications while
preserving hidden ORDER BY/group dependencies and safe join scope. Tasks
7.23-7.25 still own the single maintenance service and the immediate
pre-write uniqueness recheck.
