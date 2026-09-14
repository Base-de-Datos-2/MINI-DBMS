# ETAPA_07.md

> Documentation baseline: context v1.1 and ETAPA_06.md. This file is an implementation plan; it does not add or override academic requirements.

## Stage 7 - SQL Parser, Planner, and Executor

**Part:** Relational Database  
**Prerequisite:** Stage 6 complete  
**Previous stage:** Stage 6 - Relational Operators and External Algorithms  
**Next stage:** Stage 8 - Transactions and Concurrency  
**Roadmap:** PLAN.md, Section 12  
**Status:** Planned. No implementation task is marked complete.

The user reports Stage 6 as completed. This document uses that report as its starting point; it does not certify the actual repository or its test results. Task 7.1 verifies the implementation and its adopted decisions.

## 1. Purpose and expected outcome

Stage 7 connects the SQL language to the physical execution layer already built. A user should be able to submit a supported SQL statement through a Python engine interface and obtain either a result stream or a completed mutation result.

The responsibilities are distinct:

| Component | Input | Output | Responsibility |
|---|---|---|---|
| Parser | SQL text | Parser-independent AST | Recognize the supported syntax |
| Binder / semantic analyzer | AST and Catalog | Typed, resolved statement | Resolve tables, columns, aliases, and operation validity |
| Planner | Resolved statement and physical capabilities | Physical plan specification | Select compatible access paths and operators |
| Executor | Physical plan and execution context | Rows or affected-row count | Run the actual plan and own its resources |
| Result interface | Executor output and statistics | Structured engine response | Expose columns, rows/counts, plan details, and completion state |

The binder is a proposed internal component within the SQL engine, not an additional academic requirement.

At completion, the same storage and operator implementations used by manually assembled Stage 6 plans must be reachable through SQL. Stage 7 must not reimplement external sorting, grouping, joins, B+ trees, or Extendible Hashing.

## 2. Authority, sources, and continuity

| Source | Relevant responsibility |
|---|---|
| REQUIREMENTS.md, Sections 5-6 | External algorithms and required SQL query families |
| Proyecto_Final.pdf, Sections 2.1.2-2.1.3 | Original algorithm and limited-SQL requirements |
| PROJECT_CONTEXT.md | Stable architecture, data types, index capabilities, and selected algorithms |
| PLAN.md, Section 12 | Stage 7 parser, AST, planner, and executor scope |
| ETAPA_06.md | Operator lifecycle, bound expressions, schemas, resource budgets, and truthful statistics |
| AGENTS.md | Implementation constraints and testing rules |
| ETAPA_07.md | Detailed tasks for the current stage |

The existing coordination documents and the original assignment were used to establish scope. The supplied file-organization material supports the distinction between B+ range access and hash equality access; it is not a SQL grammar specification.

Some available coordination copies still contain historical Stage 1 status fields. During implementation, read the current repository versions and reconcile stale pointers with verified progress. Do not discard completed work because an older document names an earlier stage.

This file does not claim that Stage 6 selected every proposed aggregate, join variant, or optional feature. Preserve the implementation choices actually accepted there.

Creating this document does not modify the other project documents or the source repository.

## 3. Requirements and implementation choices

### Required outcomes

- SELECT with all columns and the supported explicit projections.
- WHERE conditions sufficient to use the implemented access techniques.
- ORDER BY using the required external-sort implementation.
- GROUP BY exposing the optimized grouping route accepted in Stage 6.
- JOIN syntax sufficient to demonstrate the accepted optimized join route.
- INSERT INTO ... VALUES (...).
- DELETE FROM ... WHERE ....
- Parser output separated from physical execution.
- A physical plan that can select useful indexes.
- An executor whose results and reported plan reflect actual execution.

A complete SQL standard, a cost-based optimizer, and a particular parser library are not required by the assignment.

### Recommended route

- Keep Python and the existing project stack.
- Use Lark if the project has not already adopted another suitable grammar parser.
- Build a small parser-independent AST.
- Bind names and types before any mutation.
- Use a deterministic rule-based planner.
- Reuse Stage 6 expression and operator APIs through narrow adapters.
- Use existing table/index maintenance services for writes.
- Provide a Python result cursor and a small bounded demonstration adapter.
- Expose plan inspection through a Python API before adding optional EXPLAIN syntax.

Lark, AST class names, the binding layer, and exact lexical choices are project decisions. Do not replace an already approved parser or compatible execution contract merely to match these suggestions.

## 4. Scope and stage boundaries

### Included

- an explicit supported SQL subset;
- tokenization, grammar, AST construction, and useful syntax errors;
- Catalog-backed semantic validation;
- relation aliases and unambiguous column binding;
- binding of approved predicates, sort keys, grouping keys, and aggregates;
- deterministic physical access-path selection;
- filter, projection, sort, group, and join plan construction;
- SELECT execution and resource-safe result consumption;
- INSERT and DELETE through existing storage/index maintenance;
- explicit ordinary-failure behavior for mutations;
- real plan descriptions, result schemas, row counts, and statistics;
- end-to-end SQL, persistence, negative, and regression tests;
- documentation and a reproducible engine-level demonstration.

### Excluded unless already explicitly adopted

- transaction grouping, locking, concurrency, WAL, MVCC, or crash recovery;
- BEGIN TRANSACTION and END TRANSACTION execution, which belongs to Stage 8;
- HTTP endpoints, GUI, SQL editor, and plan rendering;
- DDL such as CREATE TABLE / CREATE INDEX / DROP;
- UPDATE, RETURNING, INSERT SELECT, and multi-statement scripts;
- outer joins, correlated subqueries, CTEs, windows, UNION, and recursive SQL;
- DISTINCT, HAVING, and expression features not adopted in the supported subset;
- automatic join-order search and a cost-based optimizer;
- prepared-plan caching across schema changes;
- final experimental campaigns and reports.

Tests and demos create tables/indexes through the existing Catalog/storage setup API. They do not require new DDL.

Unsupported transaction statements must fail clearly; do not accept them as no-ops and imply protection exists.

## 5. Supported SQL contract

Task 7.2 freezes the contract below against Stage 6 capabilities. These are proposed implementation choices, not claims about what the instructor explicitly mandated.

### Baseline coverage

| Area | Baseline contract |
|---|---|
| Submission | Exactly one complete statement; optional final semicolon |
| Keywords | Case-insensitive keywords; identifiers follow the adopted Catalog case policy |
| Identifiers | Simple unquoted names; optional relation qualification |
| Strings | Single-quoted strings; doubled quote represents a literal quote |
| Numbers | Integer and decimal literals, including approved signed values |
| SELECT | SELECT * and explicit named-column lists |
| Aliases | Relation aliases and output aliases with AS |
| FROM | One table; support one explicit INNER JOIN or JOIN for the minimum join demonstration |
| WHERE | Approved comparisons; AND/OR/NOT with explicit precedence and parentheses |
| ORDER BY | At least one bound key with ASC/DESC; default ASC |
| GROUP BY | At least one grouping key and the aggregate functions actually adopted in Stage 6 |
| Aggregate minimum | COUNT(*) for an executable grouping demonstration |
| JOIN ON | A supported equality key pair; additional residual conditions only if deliberately supported |
| INSERT | One VALUES row; schema-order values required, optional column list recommended |
| DELETE | DELETE FROM one table WHERE predicate |
| NULL | Only the semantics already supported and tested by the type/operator layer |
| Errors | Unsupported or invalid input produces a structured error, never partial interpretation |

For the baseline, SELECT without WHERE is supported. DELETE without WHERE is deliberately rejected unless Task 7.2 adopts whole-table deletion and adds its tests. This restriction does not weaken the required DELETE ... WHERE query family.

Additional ORDER BY/GROUP BY keys, several joins, qualified stars, comments, quoted identifiers, NULLS FIRST/LAST, IS NULL, and extra aggregates may be enabled only when the binder and operators support them consistently. Document their actual status instead of accepting syntax that silently does something else.

### Semantic rules

- SELECT preserves duplicate row occurrences unless an explicitly supported operator changes cardinality.
- AND binds more tightly than OR; comparison binds inside NOT; parentheses override precedence.
- Aliases from the SELECT list are not visible in WHERE.
- An unqualified column must resolve to exactly one relation.
- For grouped output, every non-aggregate selected column must be a grouping key.
- SELECT * with GROUP BY is invalid when expansion includes ungrouped columns.
- ORDER BY may reference a supported output alias or a bound source/grouped column; hidden sort keys must not disappear too early.
- Ordinary equality joins preserve all matching row pairs.
- WHERE retains only TRUE if nullable three-valued logic is supported.
- GROUP BY NULL equivalence and NULL equality-join behavior follow Stage 6.
- Do not silently invent numeric coercions incompatible with index keys or comparison semantics.
- A malformed suffix or second statement cannot be ignored.

### Clause order

The accepted text follows SELECT, FROM/JOIN, WHERE, GROUP BY, ORDER BY, omitting optional clauses. Its logical meaning follows relation construction and joining, filtering, grouping/aggregation, ordering, and final output projection. Physical operators may be rearranged only when equivalence is preserved.

Projection may retain internal fields for downstream sorting/grouping, then remove them at final output. Do not equate the textual SELECT position with physical projection order.

## 6. Design checkpoint

| Decision | What must be recorded |
|---|---|
| Parser | Existing parser or Lark; grammar ownership and dependency version |
| SQL subset | Exact accepted statements, predicates, aliases, aggregates, and optional features |
| Name policy | Identifier normalization, relation aliases, and Catalog lookup semantics |
| AST | Parser-independent statement/expression shapes and source spans |
| Binder | Typed references and compatibility with Stage 6 expressions |
| Plan model | Immutable specification or equivalent, separate from mutable execution state |
| Access selection | Deterministic eligibility rules and tie-breaking among compatible indexes |
| Ordering | ExternalSort baseline; index-order optimization only when explicitly adopted |
| Group/join route | The actually completed Stage 6 optimization paths |
| Results | Streaming ownership, schema availability, affected rows, and partial/final status |
| Writes | Maintenance service, validation boundary, ordinary-failure policy, and flush boundary |
| DELETE targets | Stable target enumeration and policy for RID movement/reorganization |
| Resources | Reuse of Stage 6 memory budgets, temp ownership, and cleanup |
| Diagnostics | Error categories, source locations, and measured-versus-planned statistics |
| Reuse | Whether a plan can run again with fresh context; no shared live operator state |

## 7. Execution invariants

1. Parsing never mutates storage or constructs live cursors.
2. Binding resolves every required name/type and validates the statement before writes.
3. The planner uses capabilities actually available in Catalog and Stage 6.
4. Every index restriction is a sound candidate filter: it cannot exclude a true match.
5. Residual predicates remain when an access path does not enforce the full condition.
6. Hash equality access is never used as ordered or range access.
7. Physical planning preserves duplicate multiplicity, typed comparisons, grouping, and null behavior.
8. Preparing or inspecting a plan does not execute its mutations.
9. Each execution owns fresh operator state and an explicit result lifetime.
10. SELECT stays read-only over permanent tables/indexes.
11. INSERT and DELETE maintain every affected index and return actual completed counts.
12. Failed writes never return a success result or leave an invalid index advertised as usable.
13. DELETE does not traverse and mutate a moving target set without a correctness policy.
14. Whole-query memory and temporary-resource guarantees from Stage 6 remain in force.
15. Descriptors identify the executed plan and its runtime fallbacks.
16. No API in this stage claims transaction isolation or crash atomicity.

## 8. Task sequence

| Task | Work | Main dependency |
|---|---|---|
| 7.1 | Inspect Stage 6 and establish baseline | Reported Stage 6 completion |
| 7.2 | Freeze SQL and execution contracts | 7.1 |
| 7.3 | Define AST and source locations | 7.2 |
| 7.4 | Implement lexical rules | 7.2-7.3 |
| 7.5 | Parse SELECT, predicates, grouping, sorting, and joins | 7.3-7.4 |
| 7.6 | Parse INSERT and DELETE | 7.3-7.4 |
| 7.7 | Add strict parsing diagnostics | 7.5-7.6 |
| 7.8 | Bind relations and column names | 7.3, Catalog |
| 7.9 | Bind typed predicates | 7.8 |
| 7.10 | Bind projections, aliases, and ordering | 7.8-7.9 |
| 7.11 | Bind grouping and aggregates | 7.10 |
| 7.12 | Bind and validate mutations | 7.6, 7.8-7.9 |
| 7.13 | Define physical specifications and operator factories | 7.8-7.12 |
| 7.14 | Plan baseline table scans | 7.13 |
| 7.15 | Select equality indexes | 7.14 |
| 7.16 | Plan B+ ranges and residual predicates | 7.15 |
| 7.17 | Plan filters and projections | 7.14-7.16 |
| 7.18 | Plan ORDER BY | 7.10, 7.17 |
| 7.19 | Plan GROUP BY | 7.11, 7.18 |
| 7.20 | Plan joins | 7.9, 7.13, 7.17 |
| 7.21 | Implement execution lifecycle | 7.13-7.20 |
| 7.22 | Expose engine and result APIs | 7.21 |
| 7.23 | Execute INSERT with index maintenance | 7.12, 7.21 |
| 7.24 | Execute DELETE over stable targets | 7.12, 7.21 |
| 7.25 | Verify mutation failure consistency | 7.23-7.24 |
| 7.26 | Expose actual plans and measurements | 7.21-7.25 |
| 7.27 | Add end-to-end SQL acceptance tests | Required execution paths |
| 7.28 | Test restart, spilling, and resource cleanup | 7.27 |
| 7.29 | Add negative, differential, and regression tests | 7.27-7.28 |
| 7.30 | Document the supported engine and Stage 8 handoff | Required tasks complete |

## 9. Detailed tasks

### Task 7.1 - Inspect the completed Stage 6 implementation

**Objective:** Establish the exact contracts that SQL will call.

**Actions:**

- Read current repository coordination documents and ETAPA_06.md.
- Verify the completed Stage 6 tests, especially external-sort passes, grouping/join optimization, duplicates, resource bounds, and cleanup.
- Locate operator constructors, expression types, schema binding helpers, provenance, and the manual runner.
- Record the supported aggregate signatures, comparison rules, and join variants.
- Inspect Catalog table/index discovery and whether indexes can be unavailable or incomplete.
- Inspect table mutation services and their actual index-maintenance guarantees.
- Determine whether clustered/sequential insert/delete can move existing RIDs.
- Preserve compatible parser/query code already present.
- Run the configured Stage 1-6 suite and record real baseline results.

**Tests/evidence:** Commands, actual pass/fail/skip results, and an interface compatibility table.

**Acceptance:** The plan is reconciled with real code; earlier stage proposals are not mistaken for implemented capabilities.

### Task 7.2 - Freeze the supported SQL contract

**Objective:** Turn Sections 5-6 into a documented implementation contract.

**Actions:**

- Record accepted syntax, rejected features, and optional features already supported.
- Confirm COUNT(*) and any additional adopted aggregates.
- Decide exact alias/case behavior, null rules, literal ranges, and statement terminators.
- Decide one-statement submission and whether comments are supported.
- Select access-path eligibility and deterministic tie-breaks.
- Define result lifetime, re-execution, and partial/final statistics.
- Specify mutation validation, index consistency, ordinary-failure behavior, and durability limits.
- Preserve approved Stage 6 semantics rather than creating a second expression engine.
- Build a coverage matrix mapping each accepted SQL feature to grammar, binder, planner, executor, and tests.

**Tests/evidence:** Review representative valid and invalid statements for every matrix row.

**Acceptance:** No grammar feature is accepted without a planned semantic and physical implementation.

### Task 7.3 - Define parser-independent AST nodes

**Objective:** Represent syntax without parser-library objects leaking into execution.

**Actions:**

- Define SelectStatement, InsertStatement, and DeleteStatement or existing equivalents.
- Define table references, aliases, join specifications, select items, sort items, and group keys.
- Define literals, unresolved column references, comparisons, Boolean expressions, and aggregate calls.
- Distinguish star selection from COUNT(*) and ordinary function arguments.
- Retain useful source spans for errors.
- Keep unresolved names distinct from Catalog-resolved references.
- Avoid Page, RID mutation logic, or live operators in AST constructors.

**Tests:** AST construction, structural equality/snapshots, source spans, optional clauses, and malformed constructor input where validation belongs there.

**Acceptance:** AST consumers do not depend on Lark parse-tree details or perform side effects.

### Task 7.4 - Implement lexical rules

**Objective:** Tokenize the selected subset consistently.

**Actions:**

- Handle case-insensitive keywords without altering string contents.
- Normalize identifiers according to the adopted Catalog policy.
- Parse punctuation and comparison operators with correct longest-token behavior.
- Support escaped single quotes inside strings and permitted signed numeric literals.
- Implement comments only if selected, keeping comment-like text inside strings literal.
- Preserve error positions and enforce full input consumption.
- Treat statement length/nesting limits as documented implementation limits if needed.
- Do not split input naively on semicolons, spaces, or commas.

**Tests:** Mixed keyword case, keyword-like identifier prefixes, embedded semicolons/commas, escaped quotes, negative literals, malformed literals, and comments if adopted.

**Acceptance:** The lexical layer cannot accidentally execute or reinterpret a second statement hidden after a valid prefix.

### Task 7.5 - Parse SELECT and relational clauses

**Objective:** Produce the AST for the approved SELECT subset.

**Actions:**

- Parse star/column/aggregate selections and AS aliases.
- Parse FROM and the supported explicit inner join syntax.
- Parse WHERE with comparison, NOT, AND, OR, and parentheses under the adopted precedence.
- Parse GROUP BY and ORDER BY in their allowed positions.
- Treat table/column existence as semantic work; syntax parsing does not query table contents.
- Do not accept arbitrary function calls as if aggregate support were unlimited.
- Reject unsupported clause combinations or leave a precise semantic error for the binder.
- Convert grammar output into the AST using one explicit transformation layer.

**Tests:** Minimal SELECT, each clause individually, combined clauses, join aliases, precedence, unmatched parentheses, wrong clause order, and trailing garbage.

**Acceptance:** Each supported SELECT has an unambiguous AST; precedence is tested independently from execution.

### Task 7.6 - Parse INSERT and DELETE

**Objective:** Recognize the required write statements without mutating anything.

**Actions:**

- Parse INSERT INTO table VALUES (one row).
- Parse optional INSERT column lists if adopted.
- Retain typed literal syntax without validating table constraints in the parser.
- Parse DELETE FROM table WHERE predicate.
- Enforce the selected no-WHERE deletion policy.
- Reject multi-row VALUES, UPDATE, RETURNING, and INSERT SELECT unless explicitly adopted.
- Keep write AST construction side-effect free.

**Tests:** Valid writes, quoted string values, wrong punctuation, unsupported multiple VALUES rows, missing required WHERE, and two statements in one submission.

**Acceptance:** Parsing a write never changes table or index bytes.

### Task 7.7 - Provide strict syntax diagnostics

**Objective:** Make errors actionable without returning partial success.

**Actions:**

- Translate parser exceptions into a project-level syntax error with location and a concise explanation.
- Distinguish unsupported syntax from malformed accepted syntax where practical.
- Ensure every parser entry point consumes the complete statement.
- Prevent recovery mechanisms from returning an executable prefix after a suffix error.
- Do not expose raw parser stack traces as the normal engine error interface.
- Keep diagnostic construction independent from execution.

**Tests:** Invalid token, incomplete statement, duplicate clauses, second statement, reserved transaction syntax, and string/comment edge cases.

**Acceptance:** Invalid SQL produces no executable plan and no storage mutation.

### Task 7.8 - Bind table references, aliases, and columns

**Objective:** Resolve names using Catalog and build relation scopes.

**Actions:**

- Resolve each table to its real schema and storage identity.
- Assign distinct relation-instance identities, including for two aliases of the same table if self-join is supported.
- Reject duplicate relation aliases.
- Bind qualified columns within the specified relation instance.
- Reject unqualified columns that match zero or multiple input relations.
- Expand SELECT * in deterministic FROM/output-schema order.
- Preserve original display names separately from bound positions/identifiers.
- Reuse Stage 6 qualified column identity rather than passing unresolved strings downstream.

**Tests:** Unknown table/column, ambiguous id after a join, explicit qualification, aliases, duplicate aliases, star order, and alias case policy.

**Acceptance:** Every executable reference names exactly one input field.

### Task 7.9 - Bind typed predicates and join keys

**Objective:** Translate parsed expressions into Stage 6's tested expression model.

**Actions:**

- Bind references and literal values with explicit types.
- Validate comparison compatibility and only adopt supported coercions.
- Translate Boolean structure without losing parentheses/precedence.
- Reuse TRUE/FALSE/UNKNOWN behavior when NULL is supported.
- Reject aggregate calls in WHERE or JOIN ON.
- Validate join keys against supported inner-equality semantics.
- Define safe comparison normalization for index eligibility, including signed zero and accepted numeric conversions.
- Keep non-indexable expressions executable as residual filters if otherwise supported.

**Tests:** Valid comparisons, type errors, null predicates, literal range/length errors, nested Boolean logic, and join-key type mismatch.

**Acceptance:** Scan predicates, index restrictions, and join equality have compatible semantics.

### Task 7.10 - Bind projection, aliases, and ORDER BY

**Objective:** Construct the exact output schema and preserve needed internal fields.

**Actions:**

- Bind every selected field and output alias.
- Define repeated output names and ambiguous ORDER BY aliases explicitly.
- Resolve ORDER BY against approved output aliases or source fields.
- Keep SELECT aliases out of WHERE scope.
- Carry a hidden source sort key if it is not selected; remove it after sorting.
- Bind direction and the adopted null-ordering policy.
- Preserve bag semantics; projection does not deduplicate.
- Reject unsupported positional ORDER BY or expressions rather than guessing.

**Tests:** Reordered fields, output aliases, ORDER BY an unselected source column, missing sort fields, duplicate aliases, and incompatible directions/features.

**Acceptance:** Output columns match SELECT exactly while downstream operators retain all required keys.

### Task 7.11 - Bind GROUP BY and aggregates

**Objective:** Validate aggregation semantics before physical planning.

**Actions:**

- Bind group keys to source fields.
- Resolve aggregate names, arity, accepted input types, and output types through Stage 6's registry.
- Distinguish COUNT(*) and COUNT(column).
- Reject non-grouped selected columns and nested aggregates.
- Validate ORDER BY in grouped queries against group keys, aggregate outputs, and adopted alias rules.
- Do not retain arbitrary source columns through aggregation to make invalid SQL appear to work.
- Support global aggregation without GROUP BY only if adopted and tested.
- Preserve Stage 6 empty-input and nullable-aggregate rules.

**Tests:** Valid grouping, invalid SELECT *, ungrouped columns, nested/unknown aggregates, COUNT(*), empty groups, and ordering by an aggregate alias.

**Acceptance:** A bound grouped statement can be mapped directly to the adopted Group operator without inventing aggregate behavior.

### Task 7.12 - Bind and validate INSERT/DELETE targets

**Objective:** Reject predictable invalid mutations before the first write.

**Actions:**

- Resolve the target table and its writable storage adapter.
- Validate INSERT arity, column order/list, duplicate columns, type ranges, string lengths, nullability, and existing schema constraints.
- Fill omitted fields only when approved defaults/nullability allow it; otherwise reject.
- Validate every affected index's key compatibility and known uniqueness constraints through the maintenance layer.
- Bind DELETE predicates in the target table's scope.
- Require a real stable target identity for deletion; projected values are not enough.
- Identify indexes/reorganization policies that affect write correctness.
- Do not add new PK/FK semantics merely because SQL is introduced.

**Tests:** Unknown target, incorrect value count, invalid type/length, duplicate column, null/default rules, unique violation, and invalid DELETE predicate.

**Acceptance:** Syntax, binding, and predictable validation failures leave the entire table/index state unchanged.

### Task 7.13 - Define resolved statements and physical plan construction

**Objective:** Separate the semantic result from mutable execution instances.

**Actions:**

- Define a small BoundStatement model or equivalent using typed Stage 6 expressions.
- Define physical specifications containing operator type, children, arguments, schema, and capability metadata.
- Use an operator factory to instantiate actual Stage 6 operators with fresh context.
- Avoid building a large separate relational-algebra framework unless already present.
- Provide a mutation-plan variant for INSERT and DELETE.
- Keep permanent Catalog identities separate from transient cursor handles.
- Disable stale prepared-plan reuse across schema changes unless a version-check policy exists.
- Make plan construction and inspection non-mutating.

**Tests:** Bound-to-physical mapping, fresh instances on repeated execution, invalid capabilities, no live cursor after prepare, and schema-change rejection if reuse is allowed.

**Acceptance:** The executor receives a complete plan and does not need to reinterpret raw SQL.

### Task 7.14 - Plan a correct TableScan baseline

**Objective:** Establish a correctness fallback before optimization.

**Actions:**

- Plan SELECT from each supported storage organization through TableScan.
- Add the complete WHERE predicate as Filter when present.
- Add bound output projection in a semantically correct position.
- Plan empty and unsupported-index cases through the same baseline.
- Expose a test-only planning mode that disables index selection.
- Do not change source storage to make scanning easier.

**Tests:** SELECT *, explicit columns, filtered scans, deleted records, sequential storage, and equivalence to manually assembled Stage 6 plans.

**Acceptance:** Every baseline-supported SELECT is executable before index-selection rules are introduced.

### Task 7.15 - Select compatible equality indexes

**Objective:** Use B+ or Extendible Hashing for eligible equality predicates.

**Actions:**

- Discover usable indexes through Catalog and verified capability metadata.
- Recognize simple bound column-equals-literal conditions, including a safely reversed literal-equals-column form.
- Check key schema, type normalization, index completeness, and nullable-key coverage.
- Use a documented deterministic tie-break when multiple indexes qualify; do not call it a measured cheapest plan.
- Instantiate the correct clustered/unclustered/hash adapter.
- Retain residual predicates not enforced by the chosen lookup.
- Treat unavailable or incomplete indexes according to Catalog policy; do not select them.
- Preserve duplicate matching RIDs.

**Tests:** Hash/B+ equality, multiple eligible indexes, missing/unavailable index, duplicate keys, extra AND predicates, and equality against scan baseline.

**Acceptance:** Index selection is deterministic and cannot introduce false negatives.

### Task 7.16 - Plan B+ ranges and preserve Boolean meaning

**Objective:** Select range candidates without changing the full predicate.

**Actions:**

- Recognize supported lower/upper bounds on one indexed key.
- Normalize inclusive/exclusive endpoints carefully.
- Combine compatible conjunctive bounds and detect contradictory intervals only when proven safe.
- Keep the full condition as a residual filter whenever exact enforcement is uncertain.
- For OR/NOT expressions that the chosen access path cannot cover, use TableScan plus Filter.
- Do not push only one OR branch into an index and silently discard the other.
- Do not select a hash range scan.
- Validate coercions and ordering against the index's comparison policy.

**Tests:** Open/closed intervals, equal bounds, contradictions, AND with unrelated predicates, OR, NOT, nulls if supported, and range-baseline equivalence.

**Acceptance:** Every true matching row remains in the chosen candidate set.

### Task 7.17 - Construct filter/projection pipelines and safe pushdown

**Objective:** Compose the bound statement without losing fields or row occurrences.

**Actions:**

- Preserve fields needed by residual predicates, joins, grouping, and sorting.
- Apply final output projection only after its dependencies are satisfied.
- Reuse bound positions/identities after schema-changing operators.
- Initially preserve a simple correct order; push predicates down only when their referenced relations and semantics make it valid.
- For inner joins, push a single-relation conjunct only with a tested equivalence rule.
- Do not move an OR expression piecemeal or filter aggregate results as if they were base fields.
- Track ordering properties conservatively.

**Tests:** Hidden fields, nested filters, joined columns, duplicate rows, and pushdown enabled/disabled equivalence.

**Acceptance:** Optimization cannot alter the requested output schema or row multiset.

### Task 7.18 - Plan ORDER BY through ExternalSort

**Objective:** Reach the required external sorting algorithm from SQL.

**Actions:**

- Instantiate Stage 6 ExternalSort with bound keys, direction, tie/null policy, and the execution budget.
- Carry hidden sort fields until final projection.
- Keep the baseline SQL ORDER BY route explicitly backed by ExternalSort.
- An index-order optimization may be added only if formally adopted, proven compatible with every requested sort property, and reported honestly.
- Never remove the demonstrated external-sort SQL path from acceptance tests.
- Do not implement a second whole-result Python sort in the SQL layer.

**Tests:** ASC/DESC, selected/unselected keys, equal keys, invalid ORDER BY references, and a tiny-budget query that forces multiple merge passes.

**Acceptance:** SQL ORDER BY can visibly execute real disk-backed k-way merging within Stage 6 limits.

### Task 7.19 - Plan GROUP BY with the accepted optimized strategy

**Objective:** Connect validated grouping and aggregates to the completed Group implementation.

**Actions:**

- Apply source WHERE filtering before grouping.
- Instantiate ExternalHashGroup or the strategic-index grouping route actually adopted in Stage 6.
- Supply complete bound group keys and aggregate-state specifications.
- Bind aggregate result positions and aliases in the derived output schema.
- Add ExternalSort after grouping when ORDER BY requests grouped output order.
- Reject incompatible indexed-grouping preconditions rather than assuming an index covers every group.
- Preserve empty/global aggregate behavior from Stage 6.
- Do not aggregate with a new SQL-layer dictionary or pandas.

**Tests:** COUNT(*), adopted additional aggregates, filtered groups, empty input, repeated keys, grouped ORDER BY aliases, and more groups than fit in the granted state budget for the external route.

**Acceptance:** At least one SQL GROUP BY query demonstrates the actual required optimization, including its measured execution evidence.

### Task 7.20 - Plan supported joins

**Objective:** Connect SQL relations and ON conditions to the completed Join implementations.

**Actions:**

- Bind logical left/right relation identities and output schemas.
- Choose the Stage 6 optimized join route using explicit availability and precondition rules.
- Use GraceHashJoin by default if it is the completed route; use an adopted IndexNestedLoopJoin when its inner index is eligible.
- Retain NestedLoopJoin as a test baseline and a supported fallback where appropriate.
- Preserve logical output column order when build/probe sides are swapped.
- Apply residual ON and WHERE predicates in their correct scopes.
- Avoid join-order search and unsupported outer-join rewrites.
- Restrict the initial implementation to the join count and predicate form accepted in Task 7.2.

**Tests:** Qualified equal-name columns, no matches, one-to-many, many-to-many, duplicate projection values, null keys if supported, and equivalence with the baseline join.

**Acceptance:** SQL joins preserve m*n duplicate-key multiplicity and demonstrate an optimized strategy.

### Task 7.21 - Implement executor lifecycle and ownership

**Objective:** Run the prepared physical plan through Stage 6's existing execution contract.

**Actions:**

- Instantiate fresh operator state and ExecutionContext per execution.
- Open the root, yield rows on demand, and close reliably on exhaustion, early stop, or exception.
- Preserve the established shared memory reservations and temporary ownership.
- Keep final statistics available after resources close.
- Do not close permanent storage handles owned by a higher-level engine unless that ownership is explicitly transferred.
- Never execute the same mutation again when fetching its result or reading its affected-row count.
- Define single-session behavior for an open SELECT cursor followed by a mutation. Recommended baseline: require closing the active result first.
- Do not promise concurrent safety before Stage 8.
- Distinguish execution failure after partial row delivery from a successfully completed result.

**Tests:** Empty query, full/partial consumption, failure during open/next/close, fresh repeated execution, active-result policy, and no duplicate mutation.

**Acceptance:** All outcomes have a defined resource and completion state.

### Task 7.22 - Expose a stable Python engine/result API

**Objective:** Provide one entry point that later API/frontend layers can call.

Illustrative contract, to adapt to existing naming:

~~~python
prepared = engine.prepare(sql)       # parse, bind, plan; no mutations
description = prepared.describe()    # inspect without executing

with engine.execute(sql) as result:
    schema = result.schema
    for row in result:
        consume(row)
~~~

INSERT/DELETE should execute synchronously once and return a completed command result, rather than relying on row iteration to trigger writes.

**Actions:**

- Expose result kind, output schema, completion state, errors, and statistics.
- For SELECT, keep streaming consumption primary.
- Offer fetchmany with a documented bound if useful; do not make unconditional fetchall the engine default.
- If a demo collects a preview, report truncation/partial consumption honestly.
- For mutations, return actual completed affected rows and no fabricated row table.
- Keep AST and bound internal fields out of the final visible schema.
- Decide whether prepare plans are single-use or reusable with fresh instances.
- Keep the API independent from FastAPI/React.

**Tests:** Schema before/after consumption under the selected contract, bounded fetch, empty results, command results, error propagation, and repeated prepares with no side effects.

**Acceptance:** The SQL engine can be used independently and does not defeat Stage 6's bounded execution.

### Task 7.23 - Execute INSERT through the maintenance layer

**Objective:** Insert one validated row and keep every applicable index consistent.

**Actions:**

- Validate the entire single-row command before mutation.
- Delegate the physical insertion to the existing table/storage adapter.
- Add the resulting key/RID association to every applicable index through the shared maintenance service.
- Preserve the adopted uniqueness and repeated-association policies.
- Handle clustered/sequential storage movement through its existing remap/rebuild protocol for all affected indexes.
- Return an affected-row count of one only after the defined successful mutation boundary.
- Apply the established flush policy before reporting the corresponding persistence guarantee.
- Do not implement page writes, B+ maintenance, or hash maintenance inside parser/planner code.
- Connect mid-operation errors to Task 7.25's tested consistency policy.

**Tests:** Heap and sequential/clustered targets supported by the project, no indexes, several indexes, duplicate non-unique key, uniqueness violation, invalid row, reopen after success, and injected maintenance failure.

**Acceptance:** A successful INSERT is visible through a full scan and every affected index after reopen.

### Task 7.24 - Execute DELETE over a stable target set

**Objective:** Delete exactly the original matching rows despite access-path or RID changes.

**Recommended strategy:**

1. Execute a target-discovery plan using the original predicate.
2. Store the required target identities and old indexed keys in a bounded disk-backed spool when necessary.
3. Close the discovery cursor before changing its table or index.
4. Delete each target through the shared table/index maintenance service.
5. Release the spool and return the number of completed deletions.

**Critical rules:**

- Do not mutate the same B+ leaf chain/hash result cursor while enumerating it.
- Do not collect every target RID in an unbounded Python list.
- Preserve each target row occurrence; duplicate values do not identify one row.
- A spool of RIDs alone is safe only if remaining RIDs stay stable during the deletion pass.
- Defer reorganization/compaction that moves rows when the storage contract permits it, then perform the existing remap/rebuild before reporting success.
- If movement cannot be deferred, use a tested stable logical identity or translate remaining targets through the maintenance remap. Never delete a newly moved row solely because it occupies a stale slot.
- Capture old index keys before the record disappears.
- Remove all affected index associations and define affected rows as completed record deletions.
- Keep concurrent writes outside this stage's supported execution model.

**Tests:** No matches, one/many matches, duplicate-valued rows, indexed predicates, deleted/reused slots, more targets than memory, and sequential/clustered reorganization.

**Acceptance:** Every original match is deleted once, no nonmatch is deleted, and all indexes remain usable and correct.

### Task 7.25 - Define and test ordinary mutation failure behavior

**Objective:** Preserve an honest, consistent boundary for writes before full transactions exist.

**Actions:**

- Separate parse/bind/constraint failures, which must write nothing, from failures during physical mutation.
- Reuse the existing maintenance service's compensation/repair contract where available.
- Ensure one completed row mutation leaves its base record and affected indexes in agreement.
- If an index update fails after a base change, complete an existing safe compensation/repair path, or mark affected indexes unavailable before another query can select them.
- For multi-target DELETE, define whether completed earlier deletions remain after a later failure. If the service does not provide statement rollback, report failure and the confirmed completed count; do not claim all-or-nothing behavior.
- Persist any required invalid/unavailable state before reopening could silently treat an incomplete index as valid. Use an existing validated rebuild/check path before reenabling it.
- If cleanup or repair also fails, preserve the original error and identify the affected table/index state accurately.
- Do not invent undo by reinserting a deleted record at a different RID and pretending the original index pointers are restored.
- Do not add WAL, a transaction manager, or a full rollback engine to solve this stage.
- Document which guarantees apply to ordinary exceptions and clean reopen, and which crash guarantees remain out of scope.

**Tests:** Failure before first write, index failure after base insertion, failure between index updates, failure partway through DELETE, failure during remap/rebuild, and reopening after the declared failure state.

**Acceptance:** Failed mutations cannot be reported as successful, and incomplete indexes cannot silently return incorrect results. The documented contract is supported by tests.

### Task 7.26 - Expose plans and measured execution details

**Objective:** Make the reported plan match the one the executor actually uses.

**Actions:**

- Derive plan descriptions from physical specifications and actual instantiated operators.
- Record selected storage/index names, residual predicates, sort/group/join keys, output schema, and child relationships.
- Distinguish prepared plan descriptions from completed runtime measurements.
- Reuse Stage 6 counters for rows, permanent/temporary I/O, run/partition counts, memory, and fallbacks.
- Do not double-count inclusive child statistics or add inclusive timings as independent costs.
- Report whether a result was fully consumed; a preview does not establish total output cardinality.
- Inspecting an INSERT/DELETE plan must never apply it.
- Expose a Python describe/inspect API. SQL EXPLAIN is optional; EXPLAIN ANALYZE mutation behavior is outside the baseline.

**Tests:** Selected index versus actual cursor, table-scan fallback, real ExternalSort spills, group/join fallback metadata, no-write plan inspection, and partial-result counters.

**Acceptance:** Stage 9 can display an accurate plan without inventing information disconnected from execution.

### Task 7.27 - Add end-to-end SQL acceptance tests

**Objective:** Test the full language-to-storage path.

**Actions:**

- Execute every supported required statement family through the public SQL entry point.
- Set up schemas, records, and indexes using existing fixture APIs.
- Assert output schemas as well as values.
- Exercise useful hash equality, both B+ access variants, B+ range, and table-scan fallback.
- Execute combined WHERE/GROUP BY/ORDER BY and JOIN/projection plans.
- Execute INSERT and DELETE, then verify their results through both scans and indexes.
- Assert actual operator descriptions and evidence of the adopted optimization routes.
- Use Section 12's examples as a minimal reproducible acceptance dataset.

**Tests:** Valid SQL matrix, expected output/counts, plan identity, and mutation persistence.

**Acceptance:** Passing parser tests alone is insufficient; every required family reaches real storage and returns the correct result.

### Task 7.28 - Verify restart, external execution, and resource cleanup

**Objective:** Ensure the SQL entry point preserves Stage 6 guarantees.

**Actions:**

- Close all storage/index managers, reopen through Catalog, then run fresh SQL executions.
- Force ORDER BY input to create more runs than merge fan-in and at least two merge passes.
- Force the adopted external grouping/join paths beyond their memory grant, or verify strategic index use for approved alternatives.
- Verify hidden sort fields and join output do not cause unbounded result collection.
- Force DELETE discovery to spill its target spool.
- Close a SELECT result early and verify all owned temporary files/handles are released.
- Inject operator/temporary-file failures through the SQL interface.
- Reexecute equivalent queries with different valid budgets and compare logical results.
- Confirm read-only queries leave base data unchanged.

**Tests:** Fresh process objects, tiny budgets, skew, partial consumption, exception cleanup, and post-mutation reopen.

**Acceptance:** SQL execution does not bypass external algorithms, memory accounting, cleanup, or persisted input reconstruction.

### Task 7.29 - Add negative, differential, and regression tests

**Objective:** Detect semantic and optimization errors outside the happy path.

**Negative cases:**

- malformed SQL, unsupported clauses, trailing statements, and unterminated strings;
- missing/ambiguous identifiers and alias-scope errors;
- incompatible types and unsupported aggregates;
- invalid grouped projections;
- hash range requests through inappropriate planner rules;
- insufficient budgets and unavailable/corrupt indexes;
- invalid INSERT and failed DELETE states;
- unsupported transaction commands.

**Differential cases:**

- compare SQL results with manually assembled Stage 6 plans;
- compare optimized plans with index-disabled table-scan plans;
- compare optimized joins with NestedLoopJoin;
- compare unordered outputs as multisets, not plain sets;
- compare ordered outputs by the selected tie policy;
- verify valid budget changes do not alter results;
- test AND/OR/NOT combinations and duplicate/null data under the adopted subset.

**Regression:** Run the configured Stage 1-6 and Stage 7 suites. Keep test-only oracles bounded; production execution must not delegate to another DBMS, pandas, or eval.

**Acceptance:** Every supported feature has positive and relevant negative coverage, and every optimization has an equivalence test.

### Task 7.30 - Document the supported SQL engine and Stage 8 handoff

**Objective:** Make actual capabilities explicit for users and the next implementation stage.

**Actions:**

- Publish the accepted SQL subset, examples, unsupported syntax, and error categories.
- Update PROJECT_CONTEXT.md with AST/binding/plan boundaries, result ownership, access rules, and mutation failure semantics.
- Record actual aggregate/join/null/case support instead of copying proposed features as implemented.
- Document manual engine setup without requiring new DDL or a frontend.
- Record real commands and verification results.
- While implementing, set current-stage pointers to Stage 7 and ETAPA_07.md.
- After closure, record Stage 7 completion and Stage 8 as next; generate ETAPA_08.md before claiming its plan exists.
- Identify transaction-integration points: execution context/session ownership, write services, active cursors, and error states.
- Preserve the explicit distinction between current ordinary-failure handling and future transaction/concurrency guarantees.

**Tests/evidence:** Run the documented demo from persisted fixtures and verify the examples match supported grammar.

**Acceptance:** Stage 8 can add transaction/concurrency behavior around a tested SQL engine without reconstructing missing contracts.

## 10. Planner decision tables

### Access paths

| Bound condition | Eligible path | Required additional behavior |
|---|---|---|
| No predicate | TableScan | Preserve active-row multiplicity |
| Exact equality on compatible indexed column | Hash or B+ IndexScan | Apply residual conditions |
| Supported interval on B+ key | B+ range IndexScan | Honor endpoint policy and residuals |
| Equality/range without usable index | TableScan + Filter | Evaluate the complete predicate |
| Conjunction containing one useful indexed condition | Sound index candidate path | Filter remaining/full condition as needed |
| OR/NOT not covered by a proved index rule | TableScan + Filter | Preserve the complete Boolean expression |
| Unavailable/incomplete index | Do not select it | Use valid fallback or report the established storage error |
| ORDER BY | ExternalSort baseline | Preserve hidden keys until output projection |

Rule-based selection is not a claim of optimal cost. Do not add cost estimates without a defined source and model.

### Group/join strategies

| Operation | Default reuse | Required checks |
|---|---|---|
| GROUP BY | Stage 6 ExternalHashGroup | Keys, aggregate state, memory, skew fallback |
| Index-driven grouping if adopted | Stage 6 ordered group path | Full row coverage and compatible leading-key order |
| Inner equality join | Stage 6 GraceHashJoin if implemented | Compatible keys, paired partitioning, duplicates |
| Indexed inner join if adopted | Stage 6 IndexNestedLoopJoin | Eligible inner index, RID validity, full match stream |
| Baseline/fallback join | Stage 6 NestedLoopJoin | Rescan/spool contract and bounded output |

Do not select a merely proposed Stage 6 operator that was never implemented.

## 11. Suggested modules and implementation increments

### Modules

| Location | Responsibility |
|---|---|
| engine/query/grammar.lark | Grammar if Lark is selected |
| engine/query/ast.py | Parser-independent syntax model |
| engine/query/parser.py | Parsing and AST conversion |
| engine/query/binder.py | Catalog and type resolution |
| engine/query/bound.py | Resolved statement specifications, if a separate module helps |
| engine/query/planner.py | Rule-based physical planning |
| engine/query/physical_plan.py | Specifications and instance construction |
| engine/query/executor.py | Lifecycle and command execution coordination |
| engine/query/results.py | Cursor/command result contracts |
| engine/query/engine.py | Public prepare/execute interface |
| Existing maintenance module | Shared table/index mutations |
| tests/unit/query/ | Lexer/parser/binder/planner isolation |
| tests/integration/query/ | SQL through real storage/indexes/operators |
| docs/sql.md | Actual supported SQL and examples |

Use current repository organization where compatible. Do not create parallel implementations just to match these names.

### Increments

| Increment | Tasks | Exit condition |
|---|---|---|
| A. Syntax | 7.1-7.7 | Complete accepted SQL parses; invalid input fails without side effects |
| B. Semantics | 7.8-7.12 | Every name/type/aggregate/write target is validated |
| C. Physical planning | 7.13-7.20 | Bound statements map to real compatible operators |
| D. Execution and results | 7.21-7.22 | Streaming SELECT executes and closes correctly |
| E. Mutations | 7.23-7.25 | INSERT/DELETE preserve the documented consistency contract |
| F. Evidence and handoff | 7.26-7.30 | Actual plans, SQL tests, restart/resource checks, and documentation pass |

Add tests alongside each task. The final testing tasks provide integration coverage, not permission to defer earlier tests.

## 12. Reproducible SQL acceptance dataset

Use existing setup APIs to create these illustrative tables. Names and data are examples, not mandatory project-domain choices.

### Initial students

| id | name | career | age |
|---:|---|---|---:|
| 1 | Ana | CS | 22 |
| 2 | Luis | EE | 19 |
| 3 | Sol | CS | 24 |
| 4 | Omar | EE | 23 |

### Initial enrollments

| student_id | course |
|---:|---|
| 1 | DB2 |
| 1 | OS |
| 3 | DB2 |
| 4 | OS |

Create an equality-capable index on students.id and a B+ index on students.age through existing APIs. Use separate equivalent fixtures to exercise clustered versus unclustered organization.

### A. Basic selection and output schema

~~~sql
SELECT name, career
FROM students
WHERE age > 20
ORDER BY name;
~~~

Expected columns: name, career. Expected ordered rows: (Ana, CS), (Omar, EE), (Sol, CS).

### B. Equality index lookup

~~~sql
SELECT *
FROM students
WHERE id = 3;
~~~

Expected: exactly Sol's row. Assert a compatible usable index is selected under the configured rule. Compare against the index-disabled baseline.

### C. B+ range with residual filtering

~~~sql
SELECT name
FROM students
WHERE age >= 22 AND age < 24 AND career = 'EE';
~~~

Expected: Omar only. The range on age does not replace the career predicate.

### D. Boolean fallback correctness

~~~sql
SELECT id
FROM students
WHERE id = 1 OR career = 'EE'
ORDER BY id;
~~~

Expected ids: 1, 2, 4. An id=1 lookup alone is incorrect.

### E. Ordering by a hidden source field

~~~sql
SELECT name
FROM students
ORDER BY age;
~~~

Expected names: Luis, Ana, Omar, Sol. The result exposes only name even though age remains available internally until sorting.

### F. Grouping and aggregate alias

~~~sql
SELECT career, COUNT(*) AS total
FROM students
GROUP BY career
ORDER BY career;
~~~

Expected rows: (CS, 2), (EE, 2). Test ORDER BY total separately with the adopted tie policy.

### G. Join with qualified columns

~~~sql
SELECT s.name, e.course
FROM students AS s
JOIN enrollments AS e ON s.id = e.student_id
WHERE s.age > 20
ORDER BY s.name;
~~~

Expected row multiset: (Ana, DB2), (Ana, OS), (Sol, DB2), (Omar, OS). Ascending name order is required; relative order of Ana's tied rows follows the selected tie contract.

### H. One INSERT and a read-back

Run on a fresh fixture:

~~~sql
INSERT INTO students VALUES (5, 'Eva', 'CS', 21);
~~~

Expected affected rows: 1. Then:

~~~sql
SELECT name FROM students WHERE id = 5;
~~~

Expected: Eva. Close/reopen storage and confirm scans plus all affected indexes agree.

### I. DELETE and index consistency

Run on a fresh fixture:

~~~sql
DELETE FROM students WHERE age < 21;
~~~

Expected affected rows: 1. Luis disappears from students and its indexes; Ana, Sol, and Omar remain. No foreign-key cascade is implied by this example.

### J. Semantic rejection without writes

~~~sql
SELECT name, COUNT(*) FROM students GROUP BY career;
~~~

Reject the ungrouped name reference.

~~~sql
INSERT INTO students VALUES (8, 'Mia', 'CS', 'not_an_integer');
~~~

Reject the age type mismatch with unchanged table/index state.

### K. Multiple statements are not silently accepted

~~~sql
SELECT * FROM students; DELETE FROM students WHERE id = 1;
~~~

Reject the submission under the single-statement contract. Do not execute either an accepted prefix or the second statement.

### L. Scaled external-path evidence

Repeat equivalent ORDER BY/GROUP BY/JOIN queries using deterministic larger fixtures and small valid budgets:

- sort creates more runs than its merge fan-in and at least two merge passes;
- external grouping exceeds the group-state memory allowance;
- external join spills real partitions;
- accepted strategic-index alternatives demonstrate actual index traversal/probes;
- outputs agree with bounded test oracles and manual Stage 6 plans;
- early close removes execution-owned temporary files.

## 13. Validation commands and evidence

Use the actual configured repository commands. Illustrative commands after these paths exist:

~~~bash
pytest -q tests/unit/query
pytest -q tests/integration/query
pytest -q
~~~

Run existing lint/type/format gates required by AGENTS.md; do not introduce new tooling just to match an example.

Record:

| Evidence | Required details |
|---|---|
| Syntax | Accepted/rejected coverage and full-input checks |
| Semantics | Name/type/aggregate validation and unchanged-state errors |
| Planning | Actual chosen indexes/operators and residual conditions |
| Execution | Correct schema, row multiset/order, and affected count |
| External paths | Budget, real spills, runs/passes, partitions, or indexed strategy evidence |
| Mutation consistency | Scan/index agreement, RID movement, and injected-failure behavior |
| Restart | Fresh managers and post-write query results |
| Resources | Early close, peak accounted memory, handles, and temporary cleanup |
| Regressions | Real Stage 1-7 test command results |

Do not assert a speedup because an index was selected. Controlled performance comparisons remain in Stage 10.

## 14. Definition of Done

Stage 7 is complete only when the required functionality is implemented and verified.

### Contracts and parsing

- [ ] Actual Stage 6 prerequisites and baseline tests were inspected.
- [ ] Supported SQL syntax and optional features are explicitly documented.
- [ ] The parser produces parser-independent AST nodes.
- [ ] Source locations support useful diagnostics.
- [ ] Keywords, identifiers, strings, numeric literals, and punctuation follow the adopted policy.
- [ ] Boolean precedence and parentheses are tested.
- [ ] Every required statement family parses.
- [ ] Trailing garbage, extra statements, and unsupported syntax are rejected.
- [ ] Parsing and plan inspection do not mutate storage.

### Semantic analysis

- [ ] Tables and columns resolve through Catalog.
- [ ] Ambiguous/unknown names and duplicate relation aliases fail clearly.
- [ ] Types and literals follow Stage 6 semantics.
- [ ] SELECT output schema and aliases are correct.
- [ ] Hidden ORDER BY keys survive until sorting and disappear from final output.
- [ ] Grouped projections and aggregate signatures are validated.
- [ ] Join references and key types are correct.
- [ ] INSERT/DELETE validation happens before predictable invalid writes.
- [ ] NULL behavior, if supported, is consistent across predicates, indexes, grouping, and joins.

### Physical planning

- [ ] A table-scan baseline can execute the supported SELECT subset.
- [ ] Eligible equality queries use compatible hash or B+ indexes.
- [ ] Eligible ranges use B+ with correct endpoints.
- [ ] OR/NOT and residual predicates preserve the complete Boolean meaning.
- [ ] Index availability, key types, and coverage are checked.
- [ ] ORDER BY demonstrably reaches ExternalSort.
- [ ] GROUP BY reaches the Stage 6 required optimized route.
- [ ] JOIN reaches the Stage 6 required optimized route.
- [ ] Plans reference real implemented operators and use fresh execution state.
- [ ] Predicate/projection rewrites have equivalence tests.

### Execution and results

- [ ] Public Python prepare/execute interfaces work independently of HTTP/UI.
- [ ] SELECT results are streamed under the Stage 6 resource contract.
- [ ] Output rows preserve required duplicate multiplicity.
- [ ] Empty and combined-clause queries are correct.
- [ ] Full consumption, early stop, and exceptions close owned resources.
- [ ] Partial result delivery and final completion are distinguished.
- [ ] Repeated execution cannot reuse corrupt live state or repeat a mutation accidentally.
- [ ] Planned descriptions and measured execution details are distinguished.

### Mutations

- [ ] INSERT updates the base storage and every affected index.
- [ ] DELETE discovers and applies a stable target set.
- [ ] Large DELETE target sets remain within the memory contract.
- [ ] RID movement/reorganization cannot delete the wrong row or stale remaining targets.
- [ ] Ordinary validation failures leave permanent state unchanged.
- [ ] Mid-operation failures follow a tested compensation/repair/unavailable-state policy.
- [ ] Failed statements do not return success or invented affected counts.
- [ ] Incomplete indexes cannot be selected silently after a failure/reopen.
- [ ] Successful writes persist according to the adopted flush boundary.
- [ ] Transaction isolation and crash atomicity are not falsely claimed.

### Verification and handoff

- [ ] End-to-end SQL tests cover every required family.
- [ ] SQL output agrees with manual and unoptimized physical baselines.
- [ ] Tiny-budget SQL tests demonstrate required external behavior.
- [ ] Restart tests create fresh storage/index managers and operator objects.
- [ ] Read-only SQL preserves permanent data.
- [ ] Invalid syntax, semantic errors, corruption, and resource failures are tested.
- [ ] The configured Stage 1-7 regression suite passes.
- [ ] Descriptors and metrics report the operators actually executed.
- [ ] Documentation reflects implemented capabilities and known limits.
- [ ] Stage 8 integration points are documented without implementing its features.

## 15. Main risks and controls

| Risk | Control |
|---|---|
| Parser executes while building the AST | Side-effect-free parsing and unchanged-state tests |
| Valid prefix is executed despite invalid suffix | Full-input parsing and single-statement tests |
| Column aliases bind to the wrong relation | Qualified scope resolution and ambiguity errors |
| Python coercion disagrees with index semantics | Shared typed expressions and index eligibility checks |
| One OR branch becomes the entire candidate set | Full-scan fallback unless a complete rule is proven |
| Projection drops a sort/group/join key | Bound dependency tracking and final output projection |
| Invalid GROUP BY returns arbitrary row values | Semantic rejection before execution |
| Join loses duplicate matches | Multiset tests including m*n cases |
| SQL wrapper collects every row | Streaming result ownership and bounded previews |
| DELETE mutates its own scan/index cursor | Complete stable target discovery before mutation |
| Reorganization invalidates spooled RIDs | Deferred movement or verified remapping/stable identities |
| A write updates only one of several indexes | Shared maintenance path and failure-injection tests |
| Failed index is still advertised as usable | Persisted unavailable state and validated repair/rebuild policy |
| Plan inspection triggers writes | Separate prepare/describe from execute |
| Static plan hides runtime fallback | Actual operator descriptors and measured fallback metadata |
| Incomplete transactions are exposed as working | Explicit rejection until Stage 8 |

## 16. Suggested commits and working prompts

### Commit organization

1. Record Stage 7 contracts and verification baseline.
2. Add AST, lexical rules, grammar, and syntax diagnostics.
3. Add Catalog scope binding and typed expressions.
4. Add projection/order/group/mutation semantic validation.
5. Add physical specifications and baseline plans.
6. Add equality/range index selection with residual tests.
7. Add sort/group/join planning.
8. Add executor lifecycle and result interface.
9. Connect INSERT to shared maintenance.
10. Connect stable-target DELETE and failure handling.
11. Add truthful plans/metrics and end-to-end SQL tests.
12. Complete restart/resource/regression checks and documentation.

This is a suggested organization for the user's repository workflow, not an instruction to push changes.

### Inspection prompt

~~~text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, ETAPA_06.md,
and ETAPA_07.md. Stage 6 is reported complete.

Complete Task 7.1 only. Inspect actual operators, bound expressions,
schemas, aggregate/join capabilities, index cursors, Catalog, memory
contracts, and mutation-maintenance services. Run the configured baseline
tests and report evidence, gaps, and conflicts. Do not modify code yet.
~~~

### Design checkpoint prompt

~~~text
Complete Task 7.2. Freeze the supported SQL subset and the parser/AST/
binder/planner/executor boundaries. Preserve actual Stage 6 semantics.

Define alias/type/null rules, index eligibility, result ownership,
INSERT/DELETE validation, stable DELETE targets, index-maintenance failure
behavior, and persistence limits. Distinguish project decisions from
official requirements. Do not implement transactions or the frontend.
~~~

### First implementation prompt

~~~text
Implement Tasks 7.3-7.4 using the approved design: parser-independent AST
nodes, source spans, and lexical rules. Add tests for case handling,
quoted strings, signed numbers, punctuation, and statement boundaries.

Do not implement binding, planning, live operators, or mutations yet.
Reuse existing compatible modules and run the relevant tests.
~~~

### Incremental implementation prompt

~~~text
Implement only the next incomplete required task in ETAPA_07.md.
Verify its dependencies, preserve completed-stage contracts, and add the
specified positive and negative tests. Report actual validation results.
Do not implement optional SQL features or Stage 8 work automatically.
~~~

### Closure prompt

~~~text
Audit ETAPA_07.md against the actual repository. Verify the required SQL
families end to end, parser/binder rejection, optimized-versus-baseline
equivalence, real external execution, streaming cleanup, persistent
INSERT/DELETE index consistency, and failure behavior.

Run the configured regression suite. Distinguish planned, implemented,
verified, optional, and missing items. Do not mark Stage 7 complete without
evidence for its required Definition of Done. Do not implement Stage 8.
~~~

## 17. Condition for starting Stage 8

Stage 8 can begin when the supported SQL engine can reliably:

- parse complete statements into a reusable syntax model;
- resolve names/types and reject invalid statements before mutation;
- plan actual storage/index/operator access;
- execute bounded SELECT pipelines and consistent supported writes;
- report real output, affected counts, plans, and errors;
- preserve prior-stage behavior across restart and failures;
- pass the required Stage 7 Definition of Done.

Generate ETAPA_08.md from the then-current implementation and PROJECT_CONTEXT.md before starting its work.

Stage 8 adds BEGIN TRANSACTION / END TRANSACTION, concurrency control, and the required thread-based race-condition/protected-execution demonstration. Its design must establish the transactional guarantees that Stage 7 explicitly leaves unimplemented.

