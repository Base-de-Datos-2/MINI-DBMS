# Stage 7 review — Tasks 7.18-7.20

**Date:** 2026-09-17

**Scope:** Block 5B of the revised `ETAPA_07.md`

**Boundary:** relational physical planning through completed Stage 6 operators

## Result

Tasks 7.18-7.20 are implemented and verified. SQL ORDER BY constructs the real
Stage 6 `ExternalSort`; GROUP BY and global aggregates construct
`ExternalHashGroup`; one supported inner join defaults to `GraceHashJoin` and
may select an eligible exact `IndexNestedLoopJoin`. `NestedLoopJoin` remains an
explicit correctness baseline. These routes extend the immutable Block 5A
physical specifications, so preparing or describing a plan performs no I/O and
each instantiation creates fresh operator state.

Stage 7 remains open. Executor/result lifecycle and its reporting foundation
were subsequently implemented in Tasks 7.21-7.22 and the initial part of 7.26.
Mutation maintenance, end-to-end acceptance, persistence/restart acceptance,
and closure work remain pending.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| Final projection could remove an unselected ORDER BY field | A valid hidden sort dependency would be unavailable to the sort operator | Place `ExternalSort` before final Projection and map output aliases back to physical input references |
| Sorting an output alias directly against the source layout is ambiguous when it shadows a source name | `SELECT id AS age ... ORDER BY age` could order by the original `age` | Use the binder's `output_position` first and resolve it to that projection item's physical selector |
| An SQL-layer Python sort/group/join would bypass the educational algorithms | Plans and metrics could claim external execution without performing it | Specifications instantiate only the completed Stage 6 `ExternalSort`, `ExternalHashGroup`, and join operators |
| Default resource grants may not prove external behavior on small fixtures | Acceptance could pass without a merge pass or hash repartition | Add immutable `PhysicalPlanningOptions` for valid exact budgets, fan-in, partition count, recursion limit, and join strategy; forced-spill SQL tests assert measured temporary I/O |
| A group key and aggregate output alias can have the same published name | The intermediate `RowLayout` would collide before final projection | Assign collision-free internal aggregate aliases and restore the SQL alias only in final Projection |
| Applying WHERE after grouping changes aggregate membership | Counts and aggregate values would include rejected rows | Build source/index candidates and the complete Filter before `ExternalHashGroup` |
| Treating equality keys as the entire ON expression drops residual ON terms | Rows failing an additional ON comparison could be emitted | Pass the complete bound ON expression as the join residual while using only extracted equality keys for partitioning/probing |
| Pushing the complete joined WHERE into one input is invalid | Cross-relation or other-side references would be evaluated in the wrong layout | Use only binder-approved relation-local index candidates at leaves and retain the complete WHERE Filter above the joined relation |
| Choosing any available inner index can misprobe a multi-key or differently keyed join | The index route could miss matches or bind the wrong column | AUTO selects an inner index only for one equality key exactly covered by a live right-side equality index; otherwise it uses Grace hash join |
| Physical build-side choice can reorder SQL output columns | A Grace optimization could expose build/probe order | Keep logical left/right schemas in the Stage 6 join specification and verify left-then-right projection after execution |

## Frozen relational-planning policies

- ORDER BY always retains the Stage 6 external-sort baseline. No index-order
  shortcut removes the demonstrated disk-backed route.
- Sorting occurs before final Projection. Hidden source/group fields remain
  available, while only the requested output schema is published.
- The first occurrence of a repeated physical ORDER BY key determines its
  direction because later repetitions cannot refine the ordering.
- GROUP BY and global aggregation use `ExternalHashGroup`. No SQL-layer
  dictionary or library aggregation exists.
- The complete WHERE predicate is evaluated before grouping. Grouped ORDER BY
  adds `ExternalSort` above `ExternalHashGroup` and before final Projection.
- Aggregate intermediate names are implementation details and cannot collide
  with group-key names; final aliases come from the bound output schema.
- AUTO join planning uses an eligible right-side exact index only for one
  equality key. Otherwise the optimized route is `GraceHashJoin`.
- `GRACE_HASH` and `NESTED_LOOP` controls support deterministic acceptance and
  differential tests. They are not a cost model or join-order search.
- Full ON and WHERE expressions remain in their respective scopes. Duplicate
  input occurrences and m*n duplicate-key multiplicity are preserved.
- NULL remains outside the current row model, as frozen in Tasks 7.1-7.2 and
  Stage 6; no planner-specific NULL semantics were invented.

## Implemented modules

| Module | Responsibility |
|---|---|
| `engine/query/planner.py` | Resource/strategy options; immutable sort/group/join specs; alias and hidden-field mapping; external group layout; Grace/nested/index join selection and residual scope |
| `engine/query/__init__.py` | Public exports for the reviewed planning options, strategy, and specifications |
| `tests/query/test_planner_relational.py` | 13 regressions covering sort/group/join correctness, structure, spill metrics, strategies, eligible index use, residual scope, aliases, empty input, stability, and multiplicity |
| `tests/query/test_planner_block_5a.py` | Replaces the former expected-failure boundary with preparation coverage for the newly supported relational plans |

## Verification evidence

Focused syntax, binding, planning, execution-through-Stage-6, and architecture
coverage:

```text
.venv/Scripts/python.exe -m pytest \
  tests/query/test_ast.py tests/query/test_lexer.py \
  tests/query/test_parser.py tests/query/test_parser_contract.py \
  tests/query/test_binder.py tests/query/test_planner_block_5a.py \
  tests/query/test_planner_relational.py tests/query/test_planner_select.py \
  tests/test_architecture.py \
  -q -W error -p no:cacheprovider -k "not public_package_api"

224 passed, 1 deselected in 50.05s
```

At the time of this Block 5B review, the deselected public API case belonged to
Tasks 7.21-7.22 because it imported the then-future `QueryResult` and `run_sql`.
That case is now covered by the subsequent Block 6 implementation. The other
ten cases in that mixed test file passed during this review, including SELECT,
WHERE, ORDER BY, GROUP BY, and JOIN behavior.

Cross-stage strict regression:

```text
.venv/Scripts/python.exe -m pytest \
  --ignore=tests/query/test_executor_writes.py \
  --ignore=tests/query/test_index_pushdown.py \
  --ignore=tests/query/test_planner_select.py \
  -q -W error -p no:cacheprovider

2490 passed in 531.97s (0:08:51)
```

At the time of this review, the ignored files required the future
executor/result API or mutation maintenance from Tasks 7.21-7.25. The
executor/result API is now present; mutation maintenance remains pending.
Applicable cases in
`test_planner_select.py` are included in the focused command above. The strict
count is the previous 2477-test Block 5A baseline plus the 13 new Block 5B
regressions.

The ORDER BY acceptance fixture creates more initial runs than the fan-in and
records at least two merge passes plus temporary page reads/writes. The GROUP
BY fixture records kernel overflow, recursive repartitioning, and temporary
page reads/writes. The default SQL join records Grace hash pairs and temporary
partition I/O. Thus every required optimized route is demonstrated by actual
execution metrics rather than plan names alone.

`compileall`, `pip check`, and `git diff --check` also pass.

## Handoff to the next block

Completed by the subsequent Block 6 review: Tasks 7.21-7.22 execute these
reusable specifications under fresh owned `ExecutionContext` objects and expose
the lifecycle through the stable Python result API. Mutation work
must continue to use the no-write plans and index obligations already bound in
Tasks 7.12-7.13 rather than reinterpreting raw SQL.
