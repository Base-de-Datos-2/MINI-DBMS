# Stage 7 review — Tasks 7.13-7.17

**Date:** 2026-09-17  
**Scope:** Block 5A of the revised `ETAPA_07.md`  
**Boundary:** reusable basic physical planning for one relation

## Result

Tasks 7.13-7.17 are implemented and verified within Block 5A's basic
single-relation boundary. `engine/query/planner.py` turns the reviewed bound
statements into immutable physical specifications, creates a fresh closed Stage
6 operator tree for each SELECT run, and provides no-write INSERT/DELETE plan
variants for later executors. Basic SELECT supports the correct TableScan
baseline, compatible B+/hash equality lookup, B+ range lookup, complete
residual filters, and final projection.

Stage 7 remains open. Block 5B subsequently implemented ORDER BY, GROUP BY, and
JOIN planning in Tasks 7.18-7.20. Execution/result APIs, write maintenance,
end-to-end acceptance, and closure work in Tasks 7.21-7.30 are still pending.

Task 7.17's constraints concerning hidden sort/group fields and join-side
predicate movement are frozen in the spec model and now have executable
integration acceptance in the Block 5B report.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| Stage 6 operators are mutable cursor-owning instances | Reusing one prepared operator could retain lifecycle/statistics state or collide across executions | Added immutable physical specs and factories; each `instantiate()` returns a distinct closed operator tree |
| A physical plan could outlive the metadata/runtime objects used to bind it | Reusing a removed, replaced, closed, or incomplete index could return invalid candidates | Capture exact Catalog/runtime identities and revalidate them before every instantiation; stale selected paths raise `StalePlanError` |
| Registration validated an index only once | A coordinated rebuild could later mark that borrowed index incomplete | `QueryEnvironment.index_for()` now rechecks table availability and index header/type/capability identity on every retrieval |
| Choosing one convenient predicate from arbitrary Boolean syntax can lose true rows | Partial OR/NOT pushdown can create false negatives | Consume only binder-approved top-level conjuncts; OR, NOT, `<>`, and proven contradictory intervals retain TableScan |
| Treating index enforcement as the full WHERE condition can miss residual terms or stale associations | Rows could be emitted despite an unrelated conjunct or an association/key mismatch | Keep the complete bound WHERE expression as a `Filter` above every TableScan or IndexScan candidate |
| Hash and B+ capabilities differ | A hash range route would be a mislabeled full scan or a runtime failure | Restrict hash to equality; require both B+ metadata and an `OrderedIndex` runtime for ranges |
| Range endpoints require more than selecting the first comparison | Open/closed and two-sided conditions could admit or omit boundary rows | Combine the strongest lower/upper endpoints with exact inclusive flags and validate values through the shared B+ codec/comparison policy |
| Multiple compatible indexes had no stable choice | Plans could depend on registration order while claiming optimization | Exact lookup precedes range lookup and exact index name breaks ties; documentation states this is deterministic, not cost-based |
| Projection could run before WHERE dependencies were consumed | An unselected predicate field could disappear before filtering | Assemble source → full Filter → final Projection, preserving hidden fields and every duplicate occurrence |
| Missing runtime indexes could abort a read that has a correct scan route | Catalog declarations without an open usable adapter would make SELECT unavailable | Read planning skips unavailable/incomplete candidates and uses TableScan; mutation binding remains strict because writes must update every declared index |
| INSERT/DELETE had semantic objects but no plan-level handoff | A later executor might reinterpret raw SQL or rebuild mutation policy | Added immutable `InsertPlanSpec` and `DeletePlanSpec`; DELETE provides a fresh RID-preserving TableScan/Filter candidate tree and neither variant writes data |

## Frozen physical-planning policies

- Physical specifications contain the operator shape, children, arguments,
  output schema, and conservative capability metadata. They hold no scan/search
  generator and inspection performs no table mutation.
- Basic SELECT always has an executable TableScan route for Heap and Paged
  Sequential storage. `use_indexes=False` forces it for differential tests.
- Only a live, compatible, complete runtime index registered beside the exact
  table storage is eligible.
- Exact equality candidates sort before range candidates; exact index name is
  the stable tie-break within one class. This is not a cardinality/cost claim.
- B+ and hash can answer equality. Only B+ can answer lower/upper ranges.
- The planner validates index key representation without opening a cursor.
- The full WHERE predicate always remains as a residual Filter. Projection is
  last in this block.
- Duplicate RIDs/rows are never collapsed by planning, filtering, or
  projection.
- A prepared plan is tied to exact immutable Catalog definitions and borrowed
  runtime identities. This substitutes a conservative freshness check for a
  schema-version facility that the current Catalog does not have.
- ORDER BY, GROUP BY, and JOIN extension points preserve the same immutable,
  full-residual and freshness policies used by the basic routes.

## Implemented modules

| Module | Responsibility |
|---|---|
| `engine/query/planner.py` | Immutable scan/filter/projection specs, SELECT factory, deterministic compatible access selection, range normalization, stale-plan checks, and mutation variants |
| `engine/query/environment.py` | Revalidate borrowed storage/index compatibility at lookup time |
| `engine/query/__init__.py` | Export the reviewed planning API |
| `tests/query/test_planner_block_5a.py` | Heap/sequential baseline, real B+/hash equality/range, residual, Boolean fallback, duplicates, freshness, immutability, and mutation no-write regressions |

## Verification evidence

```text
.venv/Scripts/python.exe -m pytest \
  tests/query/test_ast.py tests/query/test_lexer.py \
  tests/query/test_parser.py tests/query/test_parser_contract.py \
  tests/query/test_binder.py tests/query/test_planner_block_5a.py \
  tests/test_architecture.py -q -W error -p no:cacheprovider

201 passed in 10.00s
```

The focused set includes 26 new planning tests, the 156 reviewed syntax and
binding tests, and 19 architecture/import checks. Real persistent B+ and hash
adapters are used; index-enabled results are compared with the forced TableScan
baseline.

The cross-stage strict regression also passes:

```text
.venv/Scripts/python.exe -m pytest \
  --ignore=tests/query/test_executor_writes.py \
  --ignore=tests/query/test_index_pushdown.py \
  --ignore=tests/query/test_planner_select.py \
  -q -W error -p no:cacheprovider

2477 passed in 509.14s (0:08:29)
```

The three ignored files mix later Tasks 7.18-7.25 with imports that do not yet
exist. Seven already-applicable baseline/error cases from
`test_planner_select.py` pass separately. No implemented test is skipped.
`compileall`, `pip check`, architecture/import checks, and `git diff --check`
also pass.

## Handoff to the next block

Completed by the subsequent Block 5B review: Tasks 7.18-7.20 add the real Stage
6 sort, group and join operators while retaining the immutable factory,
identity validation, full-residual, duplicate-preservation, and conservative
capability rules. Continue with Task 7.21's executor lifecycle.
