# Stage 7 review — Tasks 7.1-7.4

**Date:** 2026-09-17  
**Scope:** Blocks 1-2 of the revised `ETAPA_07.md`  
**Decision:** handwritten lexer and recursive-descent parser; no Lark

## Result

Tasks 7.1-7.4 are implemented and verified against their revised acceptance
criteria. Stage 7 remains open: parser-hardening Tasks 7.5-7.7 and all semantic,
planning, execution, and mutation Tasks 7.8-7.30 are outside this review and
are not implemented by this result.

## Critical findings and corrections

| Finding | Risk | Correction |
|---|---|---|
| `PLAN.md`, `PROJECT_CONTEXT.md`, and the former Stage 7 audit claimed a binder/planner/executor, maintenance package, and 2,350 passing tests that are absent from the current tree | A later stage could start from a false closure | Restored Stage 6 as the latest completed stage, reopened Stage 7, and prominently invalidated the non-reproducible audit |
| `AGENTS.md` and `PROJECT_CONTEXT.md` still named Lark as the parser stack | Direct conflict with the team decision and revised Stage 7 plan | Recorded the handwritten lexer/recursive-descent stack and removed the stale implementation restriction |
| There was no frozen grammar or optional-feature policy | Parser behavior could drift and accepted syntax had no execution plan | Added `docs/sql-grammar.md`, including grammar, ownership, limits, feature matrix, access selection, result lifetime, and mutation boundaries |
| AST nodes had no source locations | Binder/parser diagnostics could not identify the originating syntax | Added immutable shared `SourceSpan` metadata to every syntax node; locations do not affect structural equality |
| Tokens retained only normalized values and a starting offset | Original spelling, decoded types, end positions, and line/column diagnostics were lost | Added a parser-independent token model with original lexeme, normalized value, typed decoded value, exact span, and EOF |
| Comparison operators were mixed with punctuation | Downstream parser checks depended on token text rather than lexical kind | Added a dedicated `COMPARISON_OPERATOR` token kind and kept plus/minus distinct |
| `+` and `-` were rejected except for `--` comments | The adopted signed-number grammar could not be implemented cleanly | Lex the signs separately; Task 7.5.2 will attach one optional sign to numeric literals |
| SQL and numeric input were unbounded | Pathological input could consume excessive memory/CPU or expose Python integer conversion limits | Added a 65,536-character SQL bound, a 1,024-digit numeric bound, finite-float validation, and controlled lexical errors |
| The architecture suite rejected the lexer export list during review | Fresh isolated imports failed | Kept constants directly importable but limited `__all__` to API symbols, restoring all architecture checks |

## Frozen SQL choices

The optional behavior already present in the handwritten parser is now
explicitly adopted instead of remaining accidental:

- aliases with `AS` or an unambiguous implicit alias;
- `--` line comments, but no block comments;
- qualified stars (`relation.*`);
- one optional INSERT column list;
- multiple ORDER BY and GROUP BY keys;
- `COUNT(*)`, `COUNT(column)`, `SUM`, `AVG`, `MIN`, and `MAX` subject to Stage 6 type rules;
- whole-table DELETE when WHERE is absent;
- exact-case Catalog identifiers and case-insensitive keywords;
- one complete statement with an optional final semicolon.

Whole-table DELETE is only a syntax decision at this point. Tasks 7.12 and
7.24 must give it the same prevalidation, stable-target collection, index
maintenance, and ordinary-failure compensation as filtered DELETE.

## Stage 6 interface baseline

| Concern | Reusable implementation | Stage 7 obligation |
|---|---|---|
| Operator lifecycle | `engine/operators/base.py`: open/next/close state contract | Executor must close on exhaustion, early stop, and failure |
| Resource budgets | `engine/operators/context.py`: `ExecutionContext` | Reuse the existing budget; do not create a SQL-only memory model |
| Plans/results | `engine/operators/pipeline.py`: `PhysicalPlan`, `run_plan` | Build fresh operator trees and report the path actually run |
| Expressions and binding targets | `engine/operators/expressions.py`, `rows.py` | Binder must produce typed Stage 6 expressions and preserve provenance |
| Scans/index routes | `scan.py`, `index_strategies.py`; Catalog index factories | Hash for eligible equality, B+ for equality/range, scan fallback, residual Filter |
| ORDER BY | `ExternalSort` | Planner must reach the existing external implementation |
| GROUP BY | `ExternalHashGroup`; Stage 6 aggregate classes | Binder validates aggregate signatures; planner reuses the operator |
| JOIN | `NestedLoopJoin`, `GraceHashJoin`, index-assisted strategies | One adopted inner join must map to a compatible existing route |
| Writes | No `engine/maintenance/` service exists | Tasks 7.23-7.25 must build and verify coordinated storage/index mutation |
| RID movement | Sequential/clustered storage can move RIDs | DELETE/INSERT maintenance must use existing rebuild/recovery contracts |

No parser-generator dependency exists in `pyproject.toml`; its runtime
dependencies remain empty. The current `engine/query` production surface is
limited to AST/source contracts, tokens/lexer, and the pre-existing parser.

## Verification evidence

Commands were run from the repository root with the project virtual
environment and warnings treated as errors.

```text
.venv/Scripts/python.exe -m pytest --ignore=tests/query -q -W error -p no:cacheprovider
2295 passed in 557.99s

.venv/Scripts/python.exe -m pytest tests/query/test_ast.py tests/query/test_lexer.py tests/query/test_parser.py -q -W error -p no:cacheprovider
47 passed in 0.14s

.venv/Scripts/python.exe -m pytest tests/test_architecture.py -q -W error -p no:cacheprovider
19 passed in 7.48s

.venv/Scripts/python.exe -m compileall -q engine tests/query
completed successfully
```

The full `tests/query` collection is intentionally not green yet. It stops at
three import errors because future-task tests reference modules that do not
exist:

- `engine.maintenance` from `test_executor_writes.py`;
- `engine.query.environment` from `test_index_pushdown.py`;
- `engine.query.environment` from `test_planner_select.py`.

This is evidence that Tasks 7.8-7.25 are pending. Placeholder modules were not
added to conceal the boundary.

## Remaining work for Block 3

> **Completed on 2026-09-17.** The items below were the handoff into Tasks
> 7.5-7.7 and are now resolved. See `ETAPA_07_REVIEW_7_5_7_7.md`.

At the Block 2 handoff, Tasks 7.5-7.7 had these known gaps, all resolved by the
review linked above:

1. Attach PLUS/MINUS to numeric AST literals and reject signs elsewhere.
2. Enforce the frozen nesting limit of 128 as a controlled query error instead
   of allowing a raw `RecursionError`.
3. Restrict INSERT values to literals; the current parser also accepts column
   references even though no row scope exists for VALUES.
4. Give parser-originated errors full spans/line-column metadata and test valid
   parsing immediately after failures.
5. Expand negative coverage for malformed lists, duplicate/wrong-order clauses,
   multiple statements, unsupported transaction syntax, and boundary nesting.

These items did not invalidate Tasks 7.1-7.4; they were the explicit acceptance
work of Block 3.
