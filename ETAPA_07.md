# ETAPA_07.md

> Documentation baseline: REQUIREMENTS.md v1.1, PROJECT_CONTEXT.md v4.0,
> PLAN.md v3.5, the verified Tasks 7.1–7.30 audit, and ETAPA_06.md. This file
> is an implementation plan; it does not add or override academic requirements.

## Stage 7 - SQL Parser, Planner, and Executor

**Part:** Relational Database  
**Prerequisite:** Stage 6 complete  
**Previous stage:** Stage 6 - Relational Operators and External Algorithms  
**Next stage:** Stage 8 - Transactions and Concurrency  
**Roadmap:** PLAN.md, Section 12  
**Revision:** 2026-09-20 — Tasks 7.36–7.38 EXPLAIN execution and result contracts complete
**Status:** Original Stage 7 baseline and Tasks 7.31–7.38 complete; extension Tasks 7.39–7.40 remain pending. CREATE, EXPLAIN, and EXPLAIN ANALYZE are implemented at the engine boundary; completed baseline work remains preserved.

Tasks 7.1–7.30 were closed on 2026-09-18 and Stage 8 remains unimplemented.
Task 7.31 inspected commit `87f442a` and froze the extension decisions in
`docs/ETAPA_07_TASK_7_31_DECISIONS.md`. Task 7.32 implements the syntax boundary,
Tasks 7.33–7.35 implement durable CREATE and shared constraints, and Tasks
7.36–7.38 implement the explanation/result boundary. Preserve the completed
baseline and describe Tasks 7.39–7.40 as planned until verified.

### Adopted team decision and revision scope

The team has decided to implement the SQL lexer and parser manually. This decision supersedes the earlier recommendation to use Lark. Do not introduce Lark or another parser generator as an implementation shortcut.

This revision preserves Tasks 7.1–7.30 as the baseline and adds Tasks 7.31–7.40 for limited CREATE TABLE, durable schema registration, constraints, EXPLAIN SELECT, and EXPLAIN ANALYZE SELECT. Existing tasks are clarified where the new scope changes their contracts. Every editor submission contains exactly one statement; complete scripts, batch execution, and automatic statement splitting remain excluded. Existing completed work must be inspected and reused.

The recommended manual technique is recursive descent with explicit precedence levels. The team decision is manual construction; recursive descent is a proposed technique to record in Task 7.2, not an academic requirement. Preserve a compatible handwritten technique already adopted by the team.

## 1. Purpose and expected outcome

Stage 7 connects the SQL language to the physical execution layer already built. A user should be able to submit a supported SQL statement through a Python engine interface and obtain a result stream, a completed command result, or an explanation result with explicitly identified execution status.

The responsibilities are distinct:

| Component | Input | Output | Responsibility |
|---|---|---|---|
| Handwritten lexer | SQL text | Tokens with source spans | Recognize lexical units and invalid characters |
| Handwritten parser | Tokens | Parser-independent AST | Recognize complete statements and construct syntax nodes |
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

The previous version established scope from the coordination documents and the original assignment. This revision applies the team's explicit manual-parser and single-statement SQL-extension decisions to that plan; it does not claim a fresh source-code or assignment audit. The supplied file-organization material supports the distinction between B+ range access and hash equality access; it is not a SQL grammar specification.

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

### Additional outcomes required by this team revision

- Execute the exact CREATE TABLE declaration in Section 12.M as one statement.
- Persist the table identity, ordered schema, declared VARCHAR limit, primary-key definition, and required index registration.
- Preserve `--` comments and strings such as `'Pérez, Juan'` correctly.
- Execute SQL EXPLAIN SELECT without running its SELECT.
- Execute SQL EXPLAIN ANALYZE SELECT once to completion and report real measurements.
- Reject any second statement before executing the first statement.
- Complete Task 7.40's documentation synchronization before declaring this extension complete.

These are explicit project-scope additions requested by the team. Do not relabel them as requirements taken from the academic assignment.

### Recommended route

- Keep Python and the existing project stack.
- Implement the lexer and parser manually; use recursive descent unless a compatible handwritten approach is already adopted.
- Document the grammar and build AST nodes directly from tokens. Keep parsing independent of Catalog and execution.
- Build a small parser-independent AST.
- Bind names and types before any mutation.
- Use a deterministic rule-based planner.
- Reuse Stage 6 expression and operator APIs through narrow adapters.
- Use existing table/index maintenance services for writes.
- Provide a Python result cursor and a small bounded demonstration adapter.
- Reuse Python plan inspection to implement required SQL EXPLAIN SELECT and EXPLAIN ANALYZE SELECT; see Tasks 7.36–7.37.

Manual parsing is the adopted team decision. The specific parsing technique, AST class names, binding layer, and lexical details remain project-level choices. Reconcile stale parser recommendations in repository documentation with this decision. Do not change academic requirements or compatible downstream contracts.

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
- documentation and a reproducible engine-level demonstration;
- limited CREATE TABLE with INT/INTEGER, VARCHAR(n), and one optional inline single-column PRIMARY KEY;
- persistent database discovery metadata and shared constraint enforcement;
- EXPLAIN SELECT and EXPLAIN ANALYZE SELECT as individual statements.

### Excluded unless already explicitly adopted

- transaction grouping, locking, concurrency, WAL, MVCC, or crash recovery;
- BEGIN TRANSACTION and END TRANSACTION execution, which belongs to Stage 8;
- HTTP endpoints, GUI, SQL editor, and plan rendering;
- other SQL DDL: CREATE INDEX, ALTER TABLE, DROP, schemas, and IF NOT EXISTS;
- composite/table-level primary keys, foreign keys, defaults, and CHECK constraints;
- EXPLAIN or EXPLAIN ANALYZE for CREATE/INSERT/DELETE and nested EXPLAIN;
- UPDATE, RETURNING, INSERT SELECT, and multi-statement scripts;
- outer joins, correlated subqueries, CTEs, windows, UNION, and recursive SQL;
- DISTINCT, HAVING, and expression features not adopted in the supported subset;
- automatic join-order search and a cost-based optimizer;
- prepared-plan caching across schema changes;
- final experimental campaigns and reports.

Existing fixtures may still use Catalog/storage setup APIs. The new acceptance
scenario must use a manifest-backed engine database and create `alumnos`
through SQL, without a predeclared Python schema. Physical storage creation
remains delegated to existing implementations. Engine-level acceptance is
required; API/editor acceptance follows the separately reviewed Stage 9
integration. Stage 7 owns this extension even when it changes components first
created in Stages 1–6.

Unsupported transaction statements must fail clearly; do not accept them as no-ops and imply protection exists.

## 5. Supported SQL contract

Task 7.2 freezes the contract below against Stage 6 capabilities. These are proposed implementation choices, not claims about what the instructor explicitly mandated.

### Baseline coverage

| Area | Baseline contract |
|---|---|
| Submission | Exactly one complete statement; optional final semicolon followed by whitespace/comments and EOF; reject multiple statements before any execution |
| Comments | `--` through LF, CRLF, CR, or EOF outside strings; preserve source positions |
| CREATE TABLE | Unquoted table and column names; INT/INTEGER and VARCHAR(n); optional inline PRIMARY KEY on at most one column |
| EXPLAIN | EXPLAIN followed by a supported SELECT; describe only |
| EXPLAIN ANALYZE | EXPLAIN ANALYZE followed by a supported SELECT; run once to EOF and report actual metrics |
| Keywords | Case-insensitive keywords; identifiers follow the adopted Catalog case policy |
| Identifiers | Simple unquoted names; optional relation qualification |
| Strings | Single-quoted strings; doubled quote represents a literal quote |
| Numbers | Integer and decimal literals, including approved signed values |
| SELECT | SELECT * and explicit named-column lists |
| Aliases | Preserve adopted explicit and unambiguous implicit aliases |
| FROM | One table; support one explicit INNER JOIN or JOIN for the minimum join demonstration |
| WHERE | Approved comparisons; AND/OR/NOT with explicit precedence and parentheses |
| ORDER BY | At least one bound key with ASC/DESC; default ASC |
| GROUP BY | At least one grouping key and the aggregate functions actually adopted in Stage 6 |
| Aggregate minimum | COUNT(*) for an executable grouping demonstration |
| JOIN ON | A supported equality key pair; additional residual conditions only if deliberately supported |
| INSERT | One VALUES row; schema-order values required, optional column list recommended |
| DELETE | Preserve adopted DELETE FROM one table with optional WHERE |
| NULL | Current no-NULL dialect retained; require values for all inserted columns, reject NULL/None and omitted values; document this deviation from standard nullable SQL columns |
| Errors | Unsupported or invalid input produces a structured error, never partial interpretation |

SELECT without WHERE and whole-table DELETE without WHERE were adopted in the reviewed implementation. Preserve those tested behaviors; this extension must not narrow existing SQL capabilities.

Preserve adopted multiple ORDER BY/GROUP BY keys, qualified stars, implicit aliases, optional INSERT column lists, and implemented aggregates. `--` comments are required, not optional. Block comments (`/* ... */`), quoted identifiers, NULLS FIRST/LAST, IS NULL, and other unimplemented syntax remain explicitly unsupported. Comment markers inside a quoted string are ordinary data.

### DDL and explanation contract

The minimum new grammar, integrated into the existing handwritten grammar, is:

~~~ebnf
submission        = statement, [ ";" ], EOF ;
statement         = select | insert | delete | create_table | explain ;
create_table      = "CREATE", "TABLE", identifier, "(",
                    column_definition, { ",", column_definition }, ")" ;
column_definition = identifier, data_type, [ "PRIMARY", "KEY" ] ;
data_type         = "INT" | "INTEGER" | "VARCHAR", "(", positive_integer, ")" ;
explain           = "EXPLAIN", [ "ANALYZE" ], select ;
~~~

Keywords are case-insensitive. Existing SELECT/INSERT/DELETE productions remain
in effect. This EBNF is documentation, not a parser-generator input. CREATE
accepts exactly the three spellings above; legacy programmatic schemas may
continue using existing FLOAT, BOOLEAN, and unrestricted VARCHAR metadata.

- Map INT and INTEGER to the same integer type and retain its existing range checks.
- VARCHAR(n) requires `1 <= n <= 4075`, where 4075 is the current
  `MAX_RECORD_SIZE` minus the four-byte VARCHAR prefix. It counts Unicode code
  points in the decoded string; do not use UTF-8 byte length for the declared
  character limit. Independently enforce strict UTF-8 and the complete
  record/page byte capacity. Never normalize or silently truncate.
- Preserve the original string value and current equality semantics; do not strip accents or normalize case implicitly.
- At most one inline PRIMARY KEY is accepted on INTEGER or VARCHAR. Enforce
  uniqueness and non-nullness, persist its definition, and reuse a unique
  unclustered B+ index. A VARCHAR primary-key value also obeys the existing
  255-byte UTF-8 B+ key limit. A primary key does not imply physical clustering
  or ordered SELECT output.
- Repeated CREATE of an exact case-sensitive table name is an error and cannot
  truncate existing files. Reject duplicate exact column names, the reserved
  `__pk__<table>` index-name collision, empty definitions, unsupported
  types/constraints, and lengths outside 1–4075 before creating files.
- The current engine has no SQL NULL representation. This extension keeps that restricted dialect: all inserted fields need concrete values, including non-key columns. Document that non-key columns do not yet acquire standard SQL nullable behavior. Do not add a NULL bitmap or three-valued logic merely to execute this scenario. A later nullable-SQL extension requires a separate end-to-end design.
- EXPLAIN and EXPLAIN ANALYZE wrap SELECT only. No ANALYZE command, EXPLAIN options, JSON SQL syntax, or PostgreSQL output compatibility is required.
- An empty result is a successful SELECT with its output schema. Missing `id = 999` is not an exception.
- A fresh table contains no rows. The six user statements contain no INSERT; empty query results are therefore the correct initial outcome.

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
| Parser | Handwritten implementation; recursive descent or adopted manual technique; grammar owner; no parser generator |
| Tokens | Kinds, original lexemes, decoded values, spans, EOF, and identifier/keyword rules |
| Parser mechanics | Lookahead, progress, expression precedence, delimiter ownership, and nesting/input limits |
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

1. Lexing and parsing never mutate storage, resolve Catalog names, or construct live cursors.
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
17. Lexer/parser loops consume input or terminate with a result/error; malformed input cannot cause an infinite loop.
18. Public SQL parsing succeeds only after a complete statement, an optional final semicolon, and EOF.
19. AST nodes carry syntax and spans, not token-stream state or parser instances.

## 8. Task sequence

| Task | Work | Main dependency |
|---|---|---|
| 7.1 | Inspect Stage 6 and establish baseline | Reported Stage 6 completion |
| 7.2 | Freeze SQL and execution contracts | 7.1 |
| 7.3 | Define AST and source locations | 7.2 |
| 7.4 | Implement token model and handwritten lexer | 7.2-7.3 |
| 7.5 | Implement parser utilities, expressions, and SELECT clauses | 7.3-7.4 |
| 7.6 | Parse INSERT and DELETE manually | 7.3-7.4, 7.5.1-7.5.2 |
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
| 7.30 | Document the supported baseline and Stage 8 handoff | Baseline tasks complete |
| 7.31 | Verify baseline and freeze extension decisions | Completed baseline |
| 7.32 | Extend manual lexer, AST, and parser | 7.31 |
| 7.33 | Extend schema metadata and definition validation | 7.31–7.32 |
| 7.34 | Execute CREATE and persist database registration | 7.33 |
| 7.35 | Enforce constraints through shared mutations | 7.33–7.34 |
| 7.36 | Implement non-executing EXPLAIN SELECT | 7.32, existing plan description |
| 7.37 | Implement measured EXPLAIN ANALYZE SELECT | 7.36 |
| 7.38 | Extend one-statement engine/result contract | 7.34, 7.36–7.37 |
| 7.39 | Validate exact SQL scenario and regressions | 7.35–7.38 |
| 7.40 | Synchronize documentation and close extension | Start at 7.31; finish after 7.39 |


The current implementation starts with Task 7.31. Revisit Tasks 7.1–7.30 only to address an actual integration change or regression. Tasks 7.31–7.40 own all new work; earlier numbered tasks below remain useful baseline specifications.

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
- Record the team's manual-parser decision and inspect existing lexer/parser/query code for reuse.
- Locate any existing parser-generator dependencies or adapters; plan their removal only where unused after migration. Preserve unrelated dependencies and existing SQL tests.
- Reconcile documentation that still recommends a parser generator with the current team decision.
- Run the configured Stage 1-6 suite and record real baseline results.

**Tests/evidence:** Commands, actual pass/fail/skip results, and an interface compatibility table.

**Acceptance:** The plan is reconciled with real code; earlier stage proposals are not mistaken for implemented capabilities.

### Task 7.2 - Freeze the supported SQL contract

**Objective:** Turn Sections 5-6 into a documented implementation contract.

**Actions:**

- Record accepted syntax, rejected features, and optional features already supported.
- Adopt the handwritten lexer/parser boundary and select recursive descent or the compatible manual technique already present.
- Write the supported grammar in docs/sql-grammar.md or an existing equivalent; a handwritten parser still needs a grammar.
- Define token kinds, keyword recognition, original lexemes, decoded literals, source spans, and EOF.
- Define lookahead, delimiter ownership, precedence, parser progress, and input/nesting limits.
- For ordinary recursive descent, express repeated clauses with loops and avoid left-recursive productions.
- Map grammar productions to parsing functions and AST nodes, then link them to the feature coverage matrix.
- Confirm COUNT(*) and any additional adopted aggregates.
- Decide exact alias/case behavior, null rules, literal ranges, and statement terminators.
- Preserve exactly one statement per submission; require `--` comments outside strings. Complete the extension contract in Task 7.31.
- Select access-path eligibility and deterministic tie-breaks.
- Define result lifetime, re-execution, and partial/final statistics.
- Specify mutation validation, index consistency, ordinary-failure behavior, and durability limits.
- Preserve approved Stage 6 semantics rather than creating a second expression engine.
- Build a coverage matrix mapping each accepted SQL feature to grammar, binder, planner, executor, and tests.

**Tests/evidence:** Review representative valid and invalid statements for every matrix row.

**Acceptance:** No grammar feature is accepted without a planned semantic and physical implementation.

### Task 7.3 - Define parser-independent AST nodes

**Objective:** Represent syntax independently of handwritten lexer/parser implementation details.

**Actions:**

- Define SelectStatement, InsertStatement, and DeleteStatement or existing equivalents. Task 7.32 adds CreateTableStatement, column/type definitions, and ExplainStatement(select, analyze).
- Define table references, aliases, join specifications, select items, sort items, and group keys.
- Define literals, unresolved column references, comparisons, Boolean expressions, and aggregate calls.
- Distinguish star selection from COUNT(*) and ordinary function arguments.
- Retain useful source spans for errors.
- Keep unresolved names distinct from Catalog-resolved references.
- Avoid Page, RID mutation logic, or live operators in AST constructors.

**Tests:** AST construction, structural equality/snapshots, source spans, optional clauses, and malformed constructor input where validation belongs there.

**Acceptance:** AST consumers depend on syntax node contracts and source spans, not token kinds, token cursors, parser instances, or side effects. The handwritten parser creates this same AST directly.

### Task 7.4 - Implement tokens and the handwritten lexer

**Objective:** Convert SQL text into a complete token sequence with useful locations and predictable failure behavior.

#### Task 7.4.1 - Define the token contract

**Actions:**

- Define token kinds for adopted keywords, identifiers, numbers, strings, punctuation, comparison operators, and EOF.
- Store original lexeme, source span, and decoded value when meaningful. Reuse Task 7.3's span convention.
- Choose character offsets and line/column conventions explicitly; a recommended span is zero-based start offset with exclusive end, plus one-based line/column diagnostics.
- Preserve original spelling for errors. Apply keyword recognition and identifier normalization separately; never lowercase the entire SQL input.
- Define reserved-word policy. Recognize keywords only after scanning a complete identifier, so `ordering` is not split into `ORDER` and a suffix.
- Recommended baseline: tokenize PLUS/MINUS separately and let literal parsing attach an optional sign to a number. Supporting a signed literal does not add general arithmetic expressions.

**Tests:** Token values and spans, keyword-like identifiers, case policy, punctuation, signed-number token sequences, and EOF location.

**Acceptance:** Tokens have an explicit shared contract and cannot contain Catalog objects or execution state.

#### Task 7.4.2 - Implement character scanning

**Actions:**

- Maintain a character cursor and location tracking; implement small scanning helpers for whitespace, identifiers, numbers, and strings.
- Use longest-match recognition for supported multi-character operators such as `<=`, `>=`, and the adopted inequality spelling(s), before single-character operators.
- Scan quoted strings as a unit. Decode doubled single quotes, and retain spaces, commas, semicolons, and keyword text inside the string.
- Specify decimal syntax, and reject malformed numeric forms. Exponent notation, special floating values, and additional literal forms require explicit adoption.
- Ignore required `--` line comments only outside strings, through line end or EOF; retain accurate source locations. Reject unsupported block comments explicitly. Preserve existing limits and progress guarantees.
- Reject unsupported characters at their actual position; do not silently skip them.
- Append exactly one EOF token after scanning the entire input.
- Small regular expressions for individual token classes are compatible with a handwritten lexer. Do not use regular expressions or string splitting as a substitute for the statement parser.

**Tests:** Empty/whitespace input, mixed case, `SELECTED` versus `SELECT`, quoted separators, `O''Brien`, decimals, adjacent operators, invalid characters, unterminated strings, and required line-comment handling.

**Acceptance:** Every character is consumed as a token or documented whitespace/comment, or causes a lexical error. Lexing performs no storage operations.

#### Task 7.4.3 - Verify lexer boundaries and progress

**Actions:**

- Assert exact token sequences and spans independently from parser tests.
- Ensure every scanner loop advances or returns/raises; test input ending inside each token category.
- Document SQL input-length limits. A token list bounded by that limit is acceptable; it must never include table rows.
- Retain semicolon tokens for the parser. The lexer must not stop at the first semicolon or discard a following statement.
- Define LexicalError using the shared query-error interface; Task 7.7 completes engine-facing diagnostics.

**Acceptance:** Invalid suffixes cannot be hidden, and empty input yields EOF for the parser to reject as a missing statement.

### Task 7.5 - Implement parser utilities, expressions, and SELECT

**Objective:** Construct the approved AST directly from tokens using the adopted manual technique.

#### Task 7.5.1 - Implement token navigation and statement entry

**Actions:**

- Implement a parser cursor with `peek`, `advance`, `match`, `expect`, and `at_end`, or existing equivalents.
- `match` consumes only a matching token; `expect` consumes a required token or raises a location-aware error. EOF access must remain safe.
- Define a single public `parse_statement(sql)` or equivalent that lexes, dispatches by the leading keyword, parses one statement, consumes at most one optional final semicolon, and requires EOF.
- Add SELECT dispatch now; connect INSERT/DELETE handlers in Task 7.6. Unsupported handlers must reject explicitly.
- Internal routines stop at their grammar-defined delimiters; only the public statement entry requires EOF.
- Keep all parser state per invocation. Parsing a later query must not reuse an earlier cursor or error state.
- Guarantee progress for list/clause loops and bound recursive nesting with a documented limit and a controlled error.

**Tests:** Required/optional tokens, EOF errors, empty query, statement dispatch, repeated invocations after success/failure, extra semicolons, and trailing tokens.

**Acceptance:** Both SELECT and mutation parsers can reuse these mechanics without duplicating state management.

#### Task 7.5.2 - Parse literals, references, and Boolean expressions

**Actions:**

- Share literal parsing between predicates and INSERT; support optional numeric signs without permitting arbitrary unary arithmetic.
- Parse unqualified/qualified column references without Catalog lookup.
- Use explicit precedence levels, from weakest to strongest: OR, AND, NOT, comparison. Parentheses override these levels.
- For recursive descent, implement equivalents of `parse_or`, `parse_and`, `parse_not`, and `parse_predicate`.
- Use loops for repeated AND/OR terms; nested NOT and parentheses must respect the nesting policy.
- A predicate is a supported scalar comparison or parenthesized Boolean expression. Reject chained comparisons such as `a < b < c` unless explicitly adopted with semantics.
- Build AST nodes as tokens are consumed. No intermediate concrete parse tree or separate tree-to-AST transformer is required.
- Preserve source spans and compatible Stage 6 expression semantics. Do not use Python `eval` or `exec`.

**Tests:** Assert AST structure for `a = 1 OR b = 2 AND c = 3`, `NOT a = 1`, `(a = 1 OR b = 2) AND c = 3`, repeated NOT, signed numbers, qualified names, and missing operands/parentheses.

**Acceptance:** Precedence is demonstrated by AST tests independently of the executor; shared expression parsing is ready for DELETE.

#### Task 7.5.3 - Parse SELECT clauses and construct its AST

**Actions:**

- Implement SELECT lists, star, approved aggregate-call forms, and AS aliases.
- Distinguish SELECT `*` from COUNT(*) and ordinary arguments. Do not accept arbitrary function calls as supported aggregates.
- Implement FROM with adopted relation aliases and the supported JOIN/INNER JOIN plus ON syntax.
- Parse WHERE with Task 7.5.2, then GROUP BY and ORDER BY in their allowed order; support the adopted ASC/DESC defaults.
- Share comma-separated-list handling while rejecting missing items and trailing commas unless explicitly supported.
- Keep alias scopes, table existence, type compatibility, grouping validity, and aggregate signatures in the binder. The parser checks structure.
- Preserve all accepted baseline SQL and existing AST consumers. Do not simplify the language by dropping required query families.

**Tests:** Each clause, combined clauses, joins/aliases, COUNT(*), ordering keys, wrong clause order, duplicate clauses, missing ON, malformed lists, and full-input checks.

**Acceptance:** Every supported SELECT constructs an unambiguous AST, with no Catalog access or execution side effects.

### Task 7.6 - Parse INSERT and DELETE manually

**Dependencies:** Tasks 7.3-7.4 and 7.5.1-7.5.2. SELECT clause parsing in 7.5.3 is not required for these handlers.

**Objective:** Recognize the write statements through the same handwritten parser without mutating anything.

**Actions:**

- Implement `parse_insert` and `parse_delete` or equivalent methods and register them in the public statement dispatcher.
- Parse INSERT INTO table VALUES (one row), using the shared literal and comma-list helpers; support an optional column list only if adopted.
- Retain literal kinds and values without validating table constraints or applying storage encodings.
- Parse DELETE FROM table WHERE predicate using the shared expression parser, including identical Boolean precedence.
- Preserve the adopted whole-table DELETE behavior when WHERE is absent; apply the same validation, stable-target discovery, and index-maintenance policy as filtered DELETE.
- Construct InsertStatement/DeleteStatement nodes directly, retaining useful spans.
- Reject multi-row VALUES, UPDATE, RETURNING, and INSERT SELECT unless explicitly adopted across all layers.
- Let the public entry point own the optional terminator and EOF check; do not return a successful prefix from a handler.

**Tests:** Valid writes, optional column-list policy, signed numeric literals, escaped quotes, commas/semicolons inside strings, missing values, malformed punctuation, whole-table DELETE, compound DELETE predicates, multiple rows, and two statements in one submission.

**Acceptance:** Parsing a write never changes table/index bytes. INSERT and DELETE use the same lexical, literal, error, and statement-boundary contracts as SELECT.

### Task 7.7 - Provide manual-parser diagnostics and failure guarantees

**Objective:** Produce actionable errors while refusing partial success.

**Actions:**

- Integrate lexical and syntactic error categories into the project's query-error hierarchy. Reuse existing domain errors where appropriate.
- Report the offending lexeme or EOF, expected token/category where known, and source location; provide a concise context excerpt if useful.
- Distinguish unsupported syntax from malformed supported syntax when the parser can do so reliably. Do not build a full SQL parser solely to classify unsupported features.
- Fail fast for one-statement submissions; do not recover to an executable prefix or execute a later statement after an error.
- Require EOF at every public complete-statement entry, while allowing internal expression/clause routines to return at their delimiters.
- Reject an invalid suffix even when the prefix forms valid SQL. Lexical errors anywhere in an eagerly scanned submission occur before planning.
- Surface input/nesting-limit failures as controlled query errors, not raw recursion or indexing exceptions. Avoid masking unrelated implementation bugs with broad exception handling.
- Do not expose Python stack traces as the normal SQL error response.

**Tests:** Invalid characters, EOF at required positions, duplicate clauses, invalid suffixes, second statements, reserved transaction syntax, malformed strings/comments, limits just below/above the threshold, and a valid parse immediately after a failed one.

**Acceptance:** Invalid SQL yields neither an executable plan nor a storage mutation. No malformed input hangs the parser; locations follow the documented convention.

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
- Provide a mutation-plan variant for INSERT and DELETE. Add a separate resolved CREATE command and explanation wrapper in the extension; DDL need not masquerade as a row operator.
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

INSERT/DELETE and CREATE TABLE execute synchronously once and return completed command results, rather than relying on row iteration to trigger writes. EXPLAIN returns a plan result; EXPLAIN ANALYZE returns a completed analysis result. Task 7.38 defines the compatible result extension.

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
- Reuse the Python describe/inspect API for mandatory SQL EXPLAIN SELECT and EXPLAIN ANALYZE SELECT in Tasks 7.36–7.37. Explanation wrappers around mutations/DDL remain unsupported and must never execute those commands.

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

**Handwritten lexer/parser coverage:**

- Assert exact token kinds, values, and source spans for representative inputs.
- Compare AST structure against manually specified expected trees, especially Boolean precedence; do not rely only on a parser/pretty-printer round trip.
- Test every supported statement with missing delimiters, operands, and truncated suffixes.
- Include strings containing keywords, comments, commas, and semicolons, plus escaped quotes.
- Verify limits and progress with bounded generated/mutated token sequences and nested predicates; no parser-generator oracle is required.
- Verify fresh parser state after both errors and successful statements.
- Test the complete SQL API to show lexical/syntax rejection leaves permanent state unchanged.
- Keep unit tests alongside Tasks 7.4-7.7; this task adds cross-layer and regression evidence.

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
- Record the team's handwritten lexer/parser decision in PROJECT_CONTEXT.md and reconcile stale recommendations in AGENTS.md and PLAN.md where present. Keep REQUIREMENTS.md focused on academic scope.
- Document grammar productions, their parsing functions, token/span conventions, precedence, limits, and direct AST construction.
- Remove parser-generator-specific dependencies/imports and obsolete grammar artifacts only when present and unused after migration; do not delete the human-readable grammar or unrelated packages.
- Verify the public parser/AST contract remains compatible with binding, planning, and execution.
- Update PROJECT_CONTEXT.md with AST/binding/plan boundaries, result ownership, access rules, and mutation failure semantics.
- Record actual aggregate/join/null/case support instead of copying proposed features as implemented.
- Retain existing programmatic fixtures and document SQL CREATE TABLE setup for the new acceptance scenario. No frontend is required for engine-level verification.
- Record real commands and verification results.
- While implementing, set current-stage pointers to Stage 7 and ETAPA_07.md.
- Preserve the historical baseline closure, label Tasks 7.31–7.40 pending until verified, and record extension closure separately. Stage 8 remains unimplemented; preserve the already authorized emergency Stage 9 ordering if present.
- Identify transaction-integration points: execution context/session ownership, write services, active cursors, and error states.
- Preserve the explicit distinction between current ordinary-failure handling and future transaction/concurrency guarantees.

**Tests/evidence:** Run the documented demo from persisted fixtures and verify the examples match supported grammar.

**Acceptance:** Stage 8 can add transaction/concurrency behavior around a tested SQL engine without reconstructing missing contracts.


### Task 7.31 - Inspect the completed baseline and freeze the extension contract

**Status:** Complete on 2026-09-19. Decisions and inspected evidence are in
`docs/ETAPA_07_TASK_7_31_DECISIONS.md`.

**Dependencies:** Completed baseline; current repository documentation and tests.

**Objective:** Extend the existing engine without repeating Stages 1–7 or shrinking accepted SQL.

**Actions:**

- Read current AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, this plan, docs/sql-grammar.md, and docs/sql.md. Record the checked-out commit and actual test commands.
- Inspect lexer/parser/AST, SqlEngine preparation and results, immutable schemas, organization metadata, Catalog factories, unique-index metadata, shared mutation maintenance, and metric ownership.
- Confirm the current no-NULL dialect, line-comment handling, unique-index capabilities, single-active-result rule, and existing schema-signature checks.
- Record this revision's CREATE/EXPLAIN/one-statement decisions as approved team scope. Synchronize conflicting current-scope documentation immediately; describe unimplemented features as planned, not working.
- Select the engine-owned database registry location/format, versioning and clean-reopen boundary, default table organization, unique primary-key index route, and explanation result representation. Proposed minimum: HeapFile plus an existing unique unclustered B+ index for the primary key. Preserve an equally valid established route.
- Keep pure Catalog metadata independent from live storage handles. Put creation/open orchestration in a database/DDL service rather than adding storage dependencies to basic schema classes.
- Inventory ordinary-failure cleanup points and any existing persisted-format compatibility constraints. Do not require a new transaction manager to proceed.

**Tests/evidence:** Reproduce the single-statement SELECT/comment baseline, record existing test results, and map each extension to its affected modules.

**Acceptance:** A concrete compatibility/design note identifies every affected Stage 1–7 component. No unverified historical test count is presented as current evidence.

**Frozen outcome:** The engine-level database owner uses a versioned canonical
manifest, opaque UUID-backed physical file identities, Heap storage by default,
and an existing unique unclustered B+ primary-key index. Logical names remain
exact and case-sensitive. `VARCHAR(n)` accepts 1–4075 Unicode code points while
physical UTF-8 row limits and the 255-byte VARCHAR B+ key limit remain separate.
Legacy definition-driven databases keep an explicit non-migrating open path.
Engine and Stage 9 statement/result dispatch use explicit allowlists and fail
closed for future enum members. See the decision note for ownership,
publication, compensation, result, and module-boundary details.

**Verification:** The post-change warnings-as-errors gates passed 97 API tests
and 97 lexer/parser/architecture tests. The decision note records the exact
commands and the corrected pre-existing API test fragility. The historical
2,556-test baseline count remains attributed only to its 2026-09-18 audit.

### Task 7.32 - Extend the handwritten lexer, AST, and statement parser

**Status:** Complete on 2026-09-19. The handwritten parser now produces
fully-spanned `CreateTableStatement` and SELECT-only `ExplainStatement` trees,
supports LF/CRLF/CR/EOF comments, preserves contextual-keyword identifiers,
and rejects malformed, nested, unsupported-child, and multi-statement input
before binding or execution. A manifest-backed `SqlEngine` now binds and
executes CREATE through Tasks 7.33–7.35. EXPLAIN and EXPLAIN ANALYZE execute
through the result contract defined by Tasks 7.36–7.38.

**Dependencies:** 7.31; existing Tasks 7.3–7.7.

**Actions:**

- Add or reuse token recognition for CREATE, TABLE, INT, INTEGER, VARCHAR, PRIMARY, KEY, EXPLAIN, and ANALYZE. Recognize whole keywords; do not split identifiers containing keyword text.
- Add parser-independent CreateTableStatement, ColumnDefinition/TypeSpecification, and ExplainStatement with a SELECT child and an analyze flag, preserving source spans.
- Parse the Section 5 grammar with existing manual helpers. Parse VARCHAR parentheses independently from the CREATE column-list parentheses.
- EXPLAIN delegates to SELECT parsing without giving the child ownership of the final semicolon/EOF. Reject nested wrappers and unsupported child statement kinds.
- Keep one public submission boundary. Parse the entire input before binding or execution; reject a second statement even when the first is valid CREATE or EXPLAIN.
- Retain `--` comments before/between/after tokens, at EOF, and on different newline styles. Preserve commas, semicolons, doubled quotes, accents, and comment-looking text inside strings.
- Empty or comment-only input returns the established empty-input diagnostic without side effects. Do not add script splitting, statement arrays, or execute-many functions.

**Tests:** All six exact submissions in Section 12.M; lowercase/mixed-case keywords; CRLF and EOF comments; `'Pérez, Juan'`, `'O''Brien'`, and `'A; -- B'`; malformed length and parentheses; missing KEY; second statements; unsupported block comments and EXPLAIN children.

**Acceptance:** All required statements produce the correct AST; malformed suffixes and extra statements cannot cause partial execution.

**Verification:** The focused Task 7.32 parser/lexer/AST/API gate passed 181
tests under warnings-as-errors. Broader query/API/architecture results are
recorded in `docs/ETAPA_07_TASK_7_32.md`.

### Task 7.33 - Extend schema metadata and validate CREATE definitions

**Status:** Complete on 2026-09-20. Backward-compatible immutable table
constraints, CREATE binding, and shared logical/physical record validation are
implemented without changing physical schema or row formats.

**Dependencies:** 7.31–7.32.

**Actions:**

- Represent declared VARCHAR length and the optional single-column primary key
  in backward-compatible immutable `TableMetadata` constraints. Keep physical
  `Column`/`Schema` layout identity unchanged, preserve column order and
  existing construction patterns, and retain old unrestricted VARCHAR
  definitions.
- Preserve current identifier normalization and reject duplicate table/column identities according to it. Require at least one column and at most one primary key for the supported DDL subset.
- Map INT/INTEGER consistently. Validate integer length parameters in the
  frozen 1–4075 range and reject unsupported constraints instead of ignoring
  them.
- Define one shared value/constraint validator used by SQL insertion and normal database write services. Count VARCHAR code points; distinguish declaration length, integer range, and physical record-size errors.
- Enforce the documented no-NULL policy and full-row insertion contract. Optional INSERT column lists may reorder complete values but cannot invent omitted NULL/default values.
- Audit schema equality, signatures, codecs, organization headers, and index
  factories affected by new metadata. Keep the current physical schemas and
  `OrganizationMetadata` v1 unchanged; persist logical constraints in the
  version-1 database manifest and cross-check its names/types against physical
  headers. Do not reinterpret an old format silently.
- Do not assume that extending Column automatically requires rewriting record pages. Keep byte layouts unchanged where compatible; document and test any necessary metadata-version migration separately.

**Tests:** Compatible old schema construction; ordered metadata round trips; duplicate columns/keys; INT aliases; VARCHAR lengths 0, negative, fractional, oversized, 100, and 101-character values; accented/multibyte strings; NULL/None rejection.

**Acceptance:** Definitions and constraints are represented and validated consistently; primary-key and VARCHAR syntax is never accepted then discarded.

### Task 7.34 - Execute CREATE TABLE and persist database registration

**Status:** Complete on 2026-09-20. The engine-owned database service supports
strict manifest create/open, side-effect-free preparation, compensated CREATE,
opaque managed files, and fresh-process schema/index discovery.

**Dependencies:** 7.33; existing storage/index creation and open APIs.

**Actions:**

- Add a resolved CREATE command and engine-owned DDL/database service callable
  from the ordinary SQL entry point through an injected narrow protocol. The
  parser/binder/prepare path remains free of creation side effects, and the
  query layer does not import the API.
- Validate predictable errors before mutation. Create the selected base organization and optional unique primary-key index with existing code. No data rows are inserted by CREATE.
- Register the table/index only after successful initialization. Persist the
  frozen `MINIDB_CATALOG` version-1 manifest so the database can reopen without
  a hard-coded Python `TableDefinition` or caller-supplied schema.
- Persist logical names, ordered types and VARCHAR bounds, primary-key definition, organization, relative file identities, index metadata, validity markers, and format version. Reuse metadata already stored by each structure rather than creating inconsistent parallel definitions.
- Distinguish persistent database discovery metadata from the in-memory Catalog and existing per-file schema headers. On reopen, reconstruct metadata and handle ownership and cross-check referenced files before exposing the table.
- Keep database files under the configured database directory. Use the frozen
  `t_<uuid32>.heap` and `i_<uuid32>.bpt` managed identities with containment
  validation; never treat SQL identifiers as file paths.
- Publish success only after the documented clean-reopen persistence boundary. On ordinary exceptions, close owned handles and remove only files created by this failed operation or leave a documented unavailable state. Preserve pre-existing files and earlier tables.
- Repeated CREATE of an existing table must fail without replacement. Concurrent sessions, WAL, transaction rollback, and crash atomicity remain outside this stage.
- Preserve existing programmatically defined databases through the explicit
  legacy definition-driven open mode. Do not infer or migrate a legacy
  directory silently; SQL CREATE requires manifest-backed mode.

**Tests:** Empty table immediately queryable; repeated CREATE retains original rows/files; injected allocation/index/registry failures; repeated create failure followed by valid CREATE; missing/malformed registry and missing index; fresh-process reopen without fixture definitions; old database compatibility.

**Acceptance:** SQL creation produces usable empty storage and a durable discoverable schema. Failure cannot advertise a half-created table as valid.

### Task 7.35 - Integrate constraints with INSERT, DELETE, and indexes

**Status:** Complete on 2026-09-20. SQL and managed database inserts share
pre-write validation and the existing mutation maintenance path; primary-key
uniqueness, DELETE/reinsert, restart, and index consistency are verified.

**Dependencies:** 7.33–7.34; existing Tasks 7.23–7.25.

**Actions:**

- Route SQL writes through the shared validation/maintenance service. Validate type, character length, and required values before predictable invalid writes.
- Enforce primary-key uniqueness with the selected existing unique index/maintenance route, checking duplicates before modifying base storage and using the existing failure policy if a later write fails.
- Maintain all secondary indexes along with the primary-key index. Preserve the existing RID relocation/rebuild rules for each supported organization.
- After deleting a row, allow its key to be inserted again; persist this behavior across reopen.
- Revalidate constraints on execution when a prepared operation could otherwise use stale metadata. Do not add an unbounded schema cache.
- Treat raw storage APIs as documented low-level primitives or make them use the shared validator; do not claim universal database constraint enforcement while a normal write path bypasses it.

**Tests:** Duplicate primary key before/after reopen leaves rows and indexes unchanged; overlength Unicode string leaves no row; correct boundary-length insert; DELETE/reinsert key; forced-scan/index agreement; existing failure-repair behavior; multiple existing indexes.

**Acceptance:** Constraints hold for normal SQL/database writes and survive restart. PRIMARY KEY does not merely label a column.

**Verification:** Focused binder/executor tests pass 84 cases, architecture
tests pass 19 cases, and the complete warnings-as-errors repository suite passes
2,724 tests. Detailed evidence and scope limits are recorded in
`docs/ETAPA_07_TASK_7_33_7_35.md`.

### Task 7.36 - Execute EXPLAIN SELECT without executing SELECT

**Status:** Complete on 2026-09-20. The SELECT child uses the ordinary binder
and physical planner, while execution performs identity validation and returns
the immutable prepared descriptor without constructing a row operator.

**Dependencies:** 7.32; existing bind/plan/describe APIs and Task 7.26.

**Actions:**

- Bind and plan the SELECT child using the same planning options and index-selection rules used by normal execution.
- Return a structured explanation identifying operators, table/index names, predicates, sort keys/direction, output columns, and parent/child relationships.
- Reuse prepared.describe() or its actual equivalent. Do not open row cursors, consume rows, create sort runs, or execute mutations.
- Mark `executed=false`; actual row counts and runtime timing are absent/null, not fabricated zero measurements. Metadata reads during preparation are allowed and must not be mislabeled as executed scan I/O.
- Report only defined cost estimates if a model already exists. Cost estimation and PostgreSQL-compatible formatting are not required.
- Unknown tables or columns still fail semantic validation. Unsupported explanation children fail before side effects.

**Tests:** Explain the target filter/sort query; spies show no row-operator open/next calls and no temporary sort files; unchanged table/index contents; unknown names; correct selected index and scan fallback descriptions.

**Acceptance:** The result describes the real prepared plan and cannot be confused with measurements of a completed query.

**Verification:** Focused tests prove that operator instantiation and temporary
workspace creation do not occur, index selection and forced-scan policy agree
with SELECT planning, semantic errors retain their categories, and table/index
contents remain unchanged.

### Task 7.37 - Execute EXPLAIN ANALYZE SELECT once and measure completion

**Status:** Complete on 2026-09-20. Analysis constructs one fresh physical
tree, drains it once to EOF without retaining rows, closes all execution-owned
resources, and publishes the actual Stage 6 report only after successful
cleanup.

**Dependencies:** 7.36; existing operator metrics and lifecycle.

**Actions:**

- Instantiate and execute the planned SELECT exactly once. Consume it to EOF in bounded batches while counting final output rows; discard ordinary result rows after counting.
- Reuse Stage 6 sorting, predicates, indexes, and temporary-file cleanup. Do not replace ExternalSort with a full in-memory list or run the query once for rows and again for metrics.
- Return the plan and real execution metrics, including final output count and elapsed execution time. Reuse available per-operator rows, logical page reads/writes, temporary I/O, run/pass counts, and memory counters with their precise units and scope.
- Separate planning time from execution time if both are measured. Query-local measurements use isolated counters or documented deltas; they must not include an earlier query. Do not call logical page counters physical device reads.
- Mark `executed=true` and `complete=true` only after successful EOF and cleanup. Report errors/partial work according to existing failure contracts and never present a failed analysis as complete.
- Report actual fallback operators where execution deviates from the planned strategy. Do not sum inclusive operator timing as if each value were exclusive.
- Plain SELECT previews can remain bounded; their row cap must not truncate ANALYZE execution. A real cancellation or resource failure must remain explicitly incomplete.
- Preserve permanent table/index data. Temporary sort writes during ANALYZE are legitimate execution work and should be measured.

**Tests:** Empty table yields actual output rows 0; seeded query yields 2; execution counter proves one run; repeated analyses isolate counters; tiny memory budget triggers real external runs; injected operator error cleans resources and permits a later query.

**Acceptance:** Analysis describes one completed execution with truthful metrics and bounded memory. Unsupported INSERT/DELETE/DDL analysis never mutates anything.

**Verification:** Empty and populated executions report exact cardinality;
fresh-run counters remain isolated; a zero SELECT materialization cap does not
truncate analysis; forced external sorting reports real spill I/O and removes
its temporary workspace; and an injected row failure exposes an incomplete
partial report, cleans up, and permits a later valid execution.

### Task 7.38 - Extend the public single-statement result contract

**Status:** Complete on 2026-09-20. Public statement kinds now include CREATE,
EXPLAIN, and EXPLAIN_ANALYZE, while result kinds distinguish rows, mutation
commands, definitions, and explanations. Stage 9 dispatch remains deliberately
unchanged until its later integration task.

**Dependencies:** 7.34, 7.36–7.37.

**Actions:**

- Preserve the existing Python prepare/execute APIs and SELECT/INSERT/DELETE
  results. Add explicit definition and explanation result variants and
  `CREATE`, `EXPLAIN`, and `EXPLAIN_ANALYZE` statement identities.
- CREATE returns command identity, created table identity, and completion state; do not invent an affected-row count of 1 for a table definition. EXPLAIN returns its plan; ANALYZE returns plan plus measured statistics and execution/completion flags.
- Keep SELECT row schema separate from the explanation envelope. Decide and document whether a later adapter renders structured plans as text or a table.
- Preserve the single-active-result rule: callers drain or close a SELECT result before submitting the next statement. A CREATE, EXPLAIN, or completed ANALYZE must release owned resources before the next call.
- Validate the full input before executing any command. A request containing CREATE followed by SELECT is rejected, with no table created. Apply the same rule to INSERT followed by another statement.
- Document engine error categories for unsupported SQL, invalid definitions, duplicate table/key, invalid values, storage failures, and incomplete analysis. Preserve useful source spans.
- Publish an adapter-facing contract describing one input and one result/error
  per editor submission. Freeze explicit Stage 9 allowlists and exhaustive
  result dispatch, but do not implement frontend rendering within these Stage
  1–7 tasks.

**Tests:** Separate CREATE then SELECT calls against the same database; early-close ownership; explanation variants; double-statement rejection with unchanged state; valid call after each error; existing clients remain compatible.

**Acceptance:** All six user statements are callable individually through one engine interface. This stage makes no unsupported claim that an existing editor adapter is already wired to the new result types.

**Verification:** Explanation results carry a separate plan envelope, explicit
execution/completion flags, nullable runtime evidence, and no row schema or
affected-row fiction. Synchronous results leave no active engine result;
unconsumed SELECT streams still block every later statement. Complete-input
rejection precedes CREATE and INSERT effects.

**Regression:** The complete repository suite passes 2,734 tests under
warnings-as-errors. Detailed implementation and verification evidence is in
`docs/ETAPA_07_TASK_7_36_7_38.md`.

### Task 7.39 - Verify the exact scenario, restart, and regression behavior

**Dependencies:** 7.35–7.38.

**Actions:**

- Execute each Section 12.M code block with a separate engine call against one new database, retaining the actual comments and accented text.
- Test both a freshly created empty table and the deterministic populated fixture. Never pre-create alumnos outside SQL in the new acceptance tests.
- Verify constraints, clean reopen from persisted definitions, and the distinction between EXPLAIN and EXPLAIN ANALYZE.
- Add negative tests for batch input, malformed suffixes, unsupported DDL, unsupported explanation children, invalid schema metadata, duplicate keys, and overlength values.
- Verify ordinary error cleanup and scan/index equivalence after inserts and deletes; run the existing Stage 1–7 regression gates required by AGENTS.md.
- Use the current project test paths, not illustrative paths copied blindly from this plan. Record commands, environment limitations, pass/fail counts, and the checked-out revision.

**Acceptance:** Section 12.M passes end to end; failures have explicit expected behavior; previous accepted SQL and external algorithms remain functional. Missing tests or tools are recorded, not represented as passes.

### Task 7.40 - Synchronize documentation and close the extension

**Dependencies:** Begin scope corrections during 7.31; finalize after 7.39.

**Objective:** Prevent contradictory scope, grammar, architecture, examples, and completion claims.

| Document | Required action |
|---|---|
| ETAPA_07.md | Preserve baseline history; record each extension task and acceptance result; keep one-statement execution and Stage 8 exclusions explicit. |
| PROJECT_CONTEXT.md | Record schema/constraint metadata, VARCHAR character semantics, no-NULL policy, registry persistence, DDL ownership, primary-key enforcement, result kinds, EXPLAIN behavior, failure guarantees, and pending/verified status. Replace blanket claims that SQL has no DDL or that tables can only be declared in Python. |
| docs/sql-grammar.md | Add CREATE and explanation productions and their parser mapping. Require line comments and whole-input EOF validation. Preserve unsupported multi-statements and block comments. |
| docs/sql.md or equivalent | Add each individually executable example, errors, empty/populated results, VARCHAR/primary-key rules, and the restricted no-NULL dialect. |
| PLAN.md | Amend Stage 7 scope, deliverables, and closure references that conflict with this extension; preserve the authorized roadmap order. |
| AGENTS.md | Correct explicit obsolete scope/status restrictions and pointers, where present. Preserve general operating and testing rules. |
| README.md and applicable examples | Synchronize supported-statement lists, startup/reopen instructions, explanation output, and current limitations. |
| Existing audit/review records | Preserve dated historical evidence. Add a new extension audit or explicit dated addendum; do not silently rewrite old results. |
| REQUIREMENTS.md | Review for consistency; do not add team-selected features as official requirements or change academic scope without evidence of an assignment change. |
| ETAPA_01.md–ETAPA_06.md | Preserve historical plans. Document affected components in Stage 7 and current architecture; rewrite earlier plans only if a genuine current contradiction requires a small note. |

**Actions:**

- Track proposed, implemented, and verified status separately. Update documentation alongside the relevant implementation, not only at the end.
- Search current documentation for conflicting phrases such as "no DDL", "CREATE TABLE unsupported", "EXPLAIN optional", "Python-only table creation", "comments optional", and outdated completion claims. Classify historical notes before editing them.
- Explicitly retain "multiple statements unsupported"; it is a deliberate requirement, not an obsolete limitation.
- Keep Stage 8 transactions/concurrency listed as pending and distinguish clean-close persistence and ordinary failure handling from crash recovery or atomic rollback.
- If emergency Stage 9 documentation exists, record the adapter handoff and any resulting stale capability claims as follow-up work. Do not expand this Stage 1–7 implementation into frontend/API work or claim editor support without verification.
- Deliver a concise changed-document list and link real validation evidence. Generating this plan alone does not update those other files.

**Tests/evidence:** Review grammar, examples, feature tables, architecture decisions, and scope/status references against the tested implementation; run each documented new example individually.

**Acceptance:** No current document contradicts the implemented supported subset, one-statement boundary, persistence policy, or Stage 8 status. The extension cannot be closed while required documentation synchronization is unfinished.

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
| engine/query/tokens.py | Token kinds, lexemes, decoded values, and source spans |
| engine/query/lexer.py | Handwritten character scanning and lexical errors |
| docs/sql-grammar.md | Human-readable grammar, precedence, and production-to-function mapping |
| engine/query/ast.py | Parser-independent syntax model |
| engine/query/parser.py | Handwritten token navigation, statement/expression parsing, and direct AST construction |
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
| A. Syntax | 7.1-7.4; 7.5.1-7.5.2; then 7.5.3 and 7.6; finally 7.7 | Handwritten parsing covers complete accepted SQL; invalid input fails without side effects |
| B. Semantics | 7.8-7.12 | Every name/type/aggregate/write target is validated |
| C. Physical planning | 7.13-7.20 | Bound statements map to real compatible operators |
| D. Execution and results | 7.21-7.22 | Streaming SELECT executes and closes correctly |
| E. Mutations | 7.23-7.25 | INSERT/DELETE preserve the documented consistency contract |
| F. Baseline evidence and handoff | 7.26-7.30 | Preserve existing evidence and regression coverage |
| G. Definition and creation | 7.31–7.35 | SQL creates a durable table with enforced constraints |
| H. Explanations and interface | 7.36–7.38 | One-statement results distinguish planning from execution |
| I. Extension verification and docs | 7.39–7.40 | Exact scenario, regressions, and documentation synchronization pass |

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


### M. Required alumnos scenario — one statement per submission

Each code block below is a separate editor/engine submission. Keep one database open between submissions (or reopen it from persisted registration). Do not submit the blocks together, and do not split or batch them internally.

**Submission 0 — create the table:**

~~~sql
-- Crear la tabla
CREATE TABLE alumnos (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    carrera_id INT,
    nota INT
);
~~~

Expected: successful CREATE command; column order is id, nombre, carrera_id, nota; the table is empty; its schema and primary key are persisted. A second submission of the same CREATE produces a duplicate-table error and preserves existing contents.

**Submission 1 — exact string equality:**

~~~sql
-- 1
SELECT * FROM alumnos
WHERE nombre = 'Pérez, Juan';
~~~

**Submission 2 — range predicate and ascending ordering:**

~~~sql
-- 2
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
~~~

**Submission 3 — absent key:**

~~~sql
-- 3
SELECT * FROM alumnos
WHERE id = 999;
~~~

**Submission 4 — plan without execution:**

~~~sql
-- 4
EXPLAIN
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
~~~

**Submission 5 — plan with one complete execution:**

~~~sql
-- 5
EXPLAIN ANALYZE
SELECT * FROM alumnos
WHERE nota >= 14
ORDER BY id;
~~~

**Phase A: fresh empty table.** Submit 0–5 individually. Submissions 1–3 return empty results with all four output columns. Submission 4 describes the chosen filter/sort plan with no actual runtime metrics. Submission 5 executes successfully with actual final output count 0. Never infer that missing rows mean a failed SELECT.

**Phase B: populated fixture.** After Phase A, submit these INSERT statements separately using the existing INSERT capability:

~~~sql
INSERT INTO alumnos VALUES (3, 'Pérez, Juan', 1, 17);
~~~

~~~sql
INSERT INTO alumnos VALUES (1, 'Ana', 2, 14);
~~~

~~~sql
INSERT INTO alumnos VALUES (2, 'Luis', 1, 10);
~~~

Repeat submissions 1–5 individually:

| Submission | Required outcome |
|---|---|
| 1 | One row: `(3, 'Pérez, Juan', 1, 17)` |
| 2 | Exactly `(1, 'Ana', 2, 14)` followed by `(3, 'Pérez, Juan', 1, 17)` |
| 3 | Empty successful result, preserving its output schema |
| 4 | Description of the same planned SELECT; no executed-row count or invented timings |
| 5 | One full execution; actual final output rows = 2; truthful timing/I/O and completion state |

For the reviewed baseline, expect a table access, residual filter, ExternalSort on id ASC, and final output projection as applicable. Assert meaningful operator properties rather than one printed tree layout. Use the actual eligible access path and retain correctness if a valid runtime fallback occurs. A primary-key index on id does not turn the predicate on nota into an index range on nota.

**Phase C: durability and constraints.** Close all results and handles, discard objects, and reopen through a fresh database owner using only the database location and persisted metadata. Repeat queries and verify the same outputs. Reject another INSERT with id 1 without changing either base rows or index contents. Test a string of exactly 100 code points and one of 101 using an isolated fixture. Test deletion and subsequent reuse of a primary-key value separately so Phase B expectations remain deterministic.

**Phase D: one-statement rejection.** In an isolated empty database, submit a CREATE followed by SELECT in the same request. Expect a structured error and verify that no table was created. Also reject two SELECTs and INSERT followed by SELECT. Accept an optional final semicolon followed only by comments/whitespace; preserve semicolons in strings. The editor's one-statement policy must be enforced at the engine boundary, even if the UI also checks it.

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
| Syntax | Token/span tests, expected ASTs, precedence, accepted/rejected coverage, progress/limit checks, and EOF checks |
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

The original 63-item baseline below is preserved verbatim as completed
historical evidence. The extension is complete only when that baseline still
passes and the separate Tasks 7.31–7.40 checklist is implemented and verified.

### Contracts and parsing

- [x] Actual Stage 6 prerequisites and baseline tests were inspected.
- [x] Supported SQL syntax and optional features are explicitly documented.
- [x] The adopted handwritten lexer/parser is implemented without a parser generator.
- [x] The documented grammar maps to parsing functions and the accepted feature matrix.
- [x] Tokens retain original lexemes, meaningful decoded values, source spans, and EOF.
- [x] Shared parser utilities serve SELECT, INSERT, and DELETE.
- [x] The parser constructs parser-independent AST nodes directly.
- [x] No parser/token-stream state leaks into binder/planner/executor interfaces.
- [x] Lexer/parser loops make progress; input and nesting limits fail predictably.
- [x] Parsing after a failed invocation uses fresh state.
- [x] Source locations support useful diagnostics.
- [x] Keywords, identifiers, strings, numeric literals, and punctuation follow the adopted policy.
- [x] Boolean precedence and parentheses are tested.
- [x] Every required statement family parses.
- [x] Trailing garbage, extra statements, and unsupported syntax are rejected.
- [x] Parsing and plan inspection do not mutate storage.

### Semantic analysis

- [x] Tables and columns resolve through Catalog.
- [x] Ambiguous/unknown names and duplicate relation aliases fail clearly.
- [x] Types and literals follow Stage 6 semantics.
- [x] SELECT output schema and aliases are correct.
- [x] Hidden ORDER BY keys survive until sorting and disappear from final output.
- [x] Grouped projections and aggregate signatures are validated.
- [x] Join references and key types are correct.
- [x] INSERT/DELETE validation happens before predictable invalid writes.
- [x] NULL behavior, if supported, is consistent across predicates, indexes, grouping, and joins.

### Physical planning

- [x] A table-scan baseline can execute the supported SELECT subset.
- [x] Eligible equality queries use compatible hash or B+ indexes.
- [x] Eligible ranges use B+ with correct endpoints.
- [x] OR/NOT and residual predicates preserve the complete Boolean meaning.
- [x] Index availability, key types, and coverage are checked.
- [x] ORDER BY demonstrably reaches ExternalSort.
- [x] GROUP BY reaches the Stage 6 required optimized route.
- [x] JOIN reaches the Stage 6 required optimized route.
- [x] Plans reference real implemented operators and use fresh execution state.
- [x] Predicate/projection rewrites have equivalence tests.

### Execution and results

- [x] Public Python prepare/execute interfaces work independently of HTTP/UI.
- [x] SELECT results are streamed under the Stage 6 resource contract.
- [x] Output rows preserve required duplicate multiplicity.
- [x] Empty and combined-clause queries are correct.
- [x] Full consumption, early stop, and exceptions close owned resources.
- [x] Partial result delivery and final completion are distinguished.
- [x] Repeated execution cannot reuse corrupt live state or repeat a mutation accidentally.
- [x] Planned descriptions and measured execution details are distinguished.

### Mutations

- [x] INSERT updates the base storage and every affected index.
- [x] DELETE discovers and applies a stable target set.
- [x] Large DELETE target sets remain within the memory contract.
- [x] RID movement/reorganization cannot delete the wrong row or stale remaining targets.
- [x] Ordinary validation failures leave permanent state unchanged.
- [x] Mid-operation failures follow a tested compensation/repair/unavailable-state policy.
- [x] Failed statements do not return success or invented affected counts.
- [x] Incomplete indexes cannot be selected silently after a failure/reopen.
- [x] Successful writes persist according to the adopted flush boundary.
- [x] Transaction isolation and crash atomicity are not falsely claimed.

### Verification and handoff

- [x] End-to-end SQL tests cover every required family.
- [x] SQL output agrees with manual and unoptimized physical baselines.
- [x] Tiny-budget SQL tests demonstrate required external behavior.
- [x] Restart tests create fresh storage/index managers and operator objects.
- [x] Read-only SQL preserves permanent data.
- [x] Invalid syntax, semantic errors, corruption, and resource failures are tested.
- [x] The configured Stage 1-7 regression suite passes.
- [x] Descriptors and metrics report the operators actually executed.
- [x] Documentation reflects implemented capabilities and known limits.
- [x] Stage 8 integration points are documented without implementing its features.

### Required extension completion checklist (Tasks 7.31–7.40)

- [x] Current baseline and adopted capabilities are recorded without resetting verified progress.
- [x] Manual parsing supports CREATE TABLE with INT/INTEGER, VARCHAR(n), and one inline PRIMARY KEY.
- [x] The exact accented string and required line comments parse without altering their meaning.
- [x] Exactly one statement is accepted; second statements are rejected before any execution.
- [x] CREATE validation rejects duplicate names, unsupported definitions, and invalid lengths.
- [x] SQL creation delegates to existing storage and primary-key index services.
- [x] Schema, constraints, table discovery, and index registration survive fresh-process reopen.
- [x] Existing persisted data has an explicit compatible-open or migration policy.
- [x] VARCHAR character limits, physical byte limits, integer ranges, and no-NULL behavior are documented and tested.
- [x] Duplicate keys and invalid values cannot create successful inconsistent writes.
- [x] Failed CREATE cleanup preserves pre-existing tables/files and leaves no usable partial registration.
- [x] EXPLAIN binds/plans but never executes row operators or creates sort runs.
- [x] EXPLAIN ANALYZE executes SELECT exactly once to EOF within the memory contract.
- [x] Execution counts, elapsed time, and available counters have precise scopes and no fabricated values.
- [ ] Empty and populated alumnos scenarios produce the specified outputs.
- [x] Command, row, explanation, and analysis results have compatible, documented ownership and completion semantics.
- [x] EXPLAIN wrappers around writes/DDL and nested EXPLAIN fail without mutation.
- [x] Ordinary errors close resources and permit subsequent valid statements.
- [x] Stage 1–7 regression results and extension evidence are recorded for the actual implementation.
- [ ] Task 7.40 documentation updates are completed with historical claims preserved and current contradictions resolved.
- [x] The single-statement editor contract is documented without claiming unverified API/UI integration.
- [x] Stage 8 remains pending; no transaction, concurrency, WAL, or crash-atomicity claims are introduced.

## 15. Main risks and controls

| Risk | Control |
|---|---|
| Lexer splits keywords inside identifiers or delimiters inside strings | Full-identifier recognition and string-state token tests |
| Manual parser loops or overflows on malformed nesting | Progress invariants, bounded nesting, and negative tests |
| Expression precedence differs between SELECT and DELETE | Shared expression parser and expected-AST tests |
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
2. Add AST, documented grammar, token model, handwritten lexer, parser utilities, expressions, statement parsers, and diagnostics. Split this increment into reviewable commits corresponding to Tasks 7.3-7.7.
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

### Current extension prompt

~~~text
Read the current AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_07.md, docs/sql-grammar.md, and docs/sql.md. Preserve completed
Stages 1–7 and the team's handwritten parser. Start with Task 7.31;
then implement the next incomplete dependency-ready extension task.

Required additions: limited CREATE TABLE with durable schema registration,
VARCHAR character-length and primary-key enforcement, EXPLAIN SELECT,
and EXPLAIN ANALYZE SELECT. Keep exactly one statement per submission
and require -- comments outside strings. Do not add SQL script execution.

Use existing storage/index/operators and mutation-maintenance services.
Keep Stage 8 transactions/concurrency unimplemented. Follow Task 7.40
to synchronize current documentation alongside the code; distinguish
planned, implemented, and verified behavior. Validate every Section 12.M
statement separately and record actual test evidence before closure.
~~~

The older prompts below describe baseline implementation. Use them only for
an identified baseline gap; do not restart the completed 30 tasks.

### Inspection prompt

~~~text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, ETAPA_06.md,
and ETAPA_07.md. Stage 6 is reported complete.

Complete Task 7.1 only. Inspect actual operators, bound expressions,
schemas, aggregate/join capabilities, index cursors, Catalog, memory
contracts, and mutation-maintenance services. Inspect existing manual
lexer/parser code and record the team decision to avoid parser generators.
Run the configured baseline
tests and report evidence, gaps, and conflicts. Do not modify code yet.
~~~

### Design checkpoint prompt

~~~text
Complete Task 7.2. Freeze the supported SQL subset and the parser/AST/
binder/planner/executor boundaries. Adopt a handwritten lexer/parser;
document tokens, grammar, lookahead, precedence, spans, progress, and limits.
Use recursive descent unless a compatible manual approach is already adopted.
Preserve actual Stage 6 semantics. Do not introduce a parser generator.

Define alias/type/null rules, index eligibility, result ownership,
INSERT/DELETE validation, stable DELETE targets, index-maintenance failure
behavior, and persistence limits. Distinguish project decisions from
official requirements. Do not implement transactions or the frontend.
~~~

### First implementation prompt

~~~text
Implement Tasks 7.3-7.4 using the approved design: parser-independent AST
nodes, source spans, tokens, and a handwritten lexer. Add tests for case
handling, quoted strings, signed-number tokenization, punctuation, EOF,
locations, and lexical errors. Preserve the original SQL text for diagnostics.

Do not implement binding, planning, live operators, or mutations yet.
Reuse existing compatible modules and run the relevant tests.
~~~

### Handwritten parser implementation prompt

~~~text
Implement Task 7.5.1 and then 7.5.2 using the approved manual design.
Add shared token navigation, one-statement dispatch, literal/reference
parsing, Boolean precedence, source spans, progress, and nesting limits.
Construct AST nodes directly. Do not use a parser generator or eval/exec.

Then implement 7.5.3 and 7.6, reusing the shared utilities. Complete 7.7's
structured diagnostics and full-input rejection. Add exact token/AST tests
and verify that malformed suffixes cannot yield executable statements.
Do not implement new SQL features, binding, or execution in these tasks.
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
families end to end, handwritten lexer/parser coverage, exact precedence
ASTs, parser/binder rejection, progress/limit behavior, optimized-versus-baseline
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

Before starting Stage 8, use or update its plan against the then-current implementation and PROJECT_CONTEXT.md. This revision does not implement transactions, cancel the approved emergency Stage 9 order, or claim that an uninspected Stage 8 plan exists.

Stage 8 adds BEGIN TRANSACTION / END TRANSACTION, concurrency control, and the required thread-based race-condition/protected-execution demonstration. Its design must establish the transactional guarantees that Stage 7 explicitly leaves unimplemented.
