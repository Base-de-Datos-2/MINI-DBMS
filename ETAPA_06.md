# ETAPA_06.md

> Documentation baseline: context v2.9 and the formal Stage 5 closure. This is
> an implementation plan, not a change to the academic requirements.

## Stage 6 - Relational Operators and External Algorithms

**Part:** Relational Database  
**Prerequisite:** Stage 5 complete  
**Previous stage:** Stage 5 - Extendible Hashing  
**Next stage:** Stage 7 - SQL Parser, Planner, and Executor  
**Roadmap:** PLAN.md, Section 11  
**Review status (2026-09-13):** The independent review found resource, cleanup
and observability gaps. Corrections to tasks 6.5, 6.11, 6.15 and 6.16 are
documented in `docs/ETAPA_06_REVIEW_6_5_6_11_6_15_6_16.md`. The closure below
records the historical audit, not a new ratification of all 31 tasks. The
follow-up review of 6.19 and 6.27–6.30 is in
`docs/ETAPA_06_REVIEW_6_19_6_27_6_30.md`. Stage 7 remains unstarted.

**Status:** **Complete — formally closed on 2026-09-11.** All tasks 6.1-6.31
and all 59 Definition of Done criteria are satisfied.

The closure evidence, criterion by criterion, is in `docs/ETAPA_06_AUDIT.md`,
with one report per increment: `docs/ETAPA_06_INCREMENTO_A.md` through
`docs/ETAPA_06_INCREMENTO_F.md`, plus the task 6.1 inspection and the task 6.2
decisions. The strict suite passes 2252 tests with warnings as errors: 1772
from the reviewed Stages 1-5 plus 480 added by Stage 6. (The closure ran 2196
before the Stage 5 review blocks 5.16-5.27 were merged from main.) The three required external
algorithms of REQUIREMENTS.md section 5 are implemented and demonstrated by
forced disk spills. Task 6.26 was implemented as an optional addition on top of
the required external-hashing routes, never instead of them.

Stage 7 has not started. `ETAPA_07.md` does not exist yet and must be generated
and reconciled with the current PROJECT_CONTEXT.md before any SQL work begins.

## 1. Purpose and expected result

Stage 6 turns the storage and indexes already implemented into composable physical query operators. It must be possible to assemble and run a query directly from Python objects, without SQL, a parser, a planner, an API, or a frontend.

The minimum operator families from PLAN.md are:

| Family | Responsibility |
|---|---|
| TableScan | Stream active records from a storage file |
| IndexScan | Obtain records using a compatible B+ or hash access path |
| Filter | Retain rows satisfying a typed predicate |
| Projection | Produce the requested columns and output schema |
| ExternalSort | Sort data with disk runs and bounded k-way merging |
| Group | Group rows and compute the adopted aggregate functions |
| Join | Combine rows using a baseline and a required optimized strategy |

At the end, a manually constructed plan such as the following must execute over real paged storage. Arrows represent row flow, not the direction of iterator calls.

~~~mermaid
flowchart TD
    S["TableScan: students"] --> F["Filter: age > 20"]
    E["TableScan: enrollments"] --> J["GraceHashJoin: student_id"]
    F --> J
    J --> G["ExternalHashGroup: career and COUNT(*)"]
    G --> O["ExternalSort: count descending"]
    O --> P["Projection: career and count"]
~~~

This is an illustrative plan, not a mandatory application schema.

## 2. Authority, sources, and continuity

| Document | Role in Stage 6 |
|---|---|
| REQUIREMENTS.md | Defines the official obligations, especially Section 5 |
| Proyecto_Final.pdf | Original assignment; Section 2.1.2 requires the external algorithms |
| PROJECT_CONTEXT.md | Supplies accepted storage, index, type, and architecture decisions |
| PLAN.md | Defines Stage 6 scope and the boundary with Stage 7 |
| ETAPA_05.md | Supplies the completed-stage handoff and hash capabilities |
| AGENTS.md | Governs implementation behavior, permitted tools, and testing |
| ETAPA_06.md | Breaks the current stage into executable tasks |

Source material consulted for this plan includes the original assignment, the coordination documents, and relevant portions of the supplied file-organization and data-structure material:

- Proyecto_Final.pdf, Section 2.1.2: external sorting with k-way merge and optimized grouping/joins.
- PLAN.md, Section 11: operator set, manual physical execution, and the SQL boundary.
- REQUIREMENTS.md, Section 5: permitted grouping/join optimization alternatives.
- PROJECT_CONTEXT.md: relational operators, external algorithms, and unresolved memory/aggregate decisions.
- ETAPA_05.md: persistent equality access, RID integration, and Stage 6 prerequisites.
- 02 Organizacion de Archivos 2.pdf: existing file organizations underlying scans.
- 03 Organizacion de Archivos 3.pdf: B+ and hash access properties.
- EDA__Basic.pdf, Section 8.1: external data exceeds main memory. Its external-quicksort example is background, not a substitute for the required k-way merge algorithm.

These sources do not prescribe every class name, aggregate function, memory size, or join variant below. Such details are project-level proposals that must be reconciled in Task 6.2.

The available v1.1 coordination documents contain historical Stage 1 status fields. Do not use those stale fields to discard the user's reported progress. At implementation time, inspect the current repository versions and update current-stage pointers to Stage 6 as appropriate.

Generating this plan does not update other coordination files, implement operators, or certify previous-stage completion.

## 3. Requirement traceability and selected implementation route

| Obligation | Proposed Stage 6 implementation | Evidence required for closure |
|---|---|---|
| Physical query execution before SQL | Shared operator lifecycle and manually assembled pipelines | Plans run directly against real storage |
| ORDER BY using External Sorting with k-way merge | ExternalSort with run generation, bounded merge fan-in, and multiple passes | Forced disk spills and more runs than merge fan-in |
| GROUP BY using External Hashing and/or strategic indexes | ExternalHashGroup with disk partitions and bounded aggregation | More distinct group states than the memory allowance |
| JOIN using External Hashing and/or strategic indexes | GraceHashJoin with a bounded build/probe kernel | Inputs that force disk partitioning |
| Useful indexed access | IndexScan over both B+ variants and Extendible Hashing | Equality and B+ range results agree with a filtered scan |
| Later truthful execution-plan display | Operator descriptors and measured runtime statistics | Descriptors identify the operators actually run |

The default implementation route is **ExternalHashGroup plus GraceHashJoin**, with NestedLoopJoin as a simple correctness baseline. This is a project-level choice that satisfies the external-hashing alternative. The assignment does not require every join algorithm.

An already-approved index-driven grouping/join design may replace the corresponding external-hashing route if Task 6.2 records the alternative and its evidence. A bare in-memory dictionary, an unused index, or a baseline nested loop does not satisfy the optimization requirement by itself.

The default-route tasks below are required for this proposed plan unless an equivalent source-compatible alternative is explicitly accepted. Task 6.26 contains optional additional index-driven strategies; implementing every alternative is not a closure requirement.

### Important distinction: two uses of hashing

| Stage 5: Extendible Hash index | Stage 6: external hash processing |
|---|---|
| Persistent table access structure | Temporary query execution strategy |
| Directory, global/local depth, bucket splitting | Partition input, process one partition at a time |
| Maps an indexed key to record locations | Computes groups or matches two row streams |
| Survives queries and restarts | Temporary files normally disappear after query completion |

Reuse canonical key semantics, hash helpers where compatible, page I/O, and metrics. Do not rebuild Stage 5 or call a loop of index insertions an external aggregation/join algorithm.

## 4. Scope and boundaries

### Included

- operator lifecycle, output schemas, typed predicates, and row ownership;
- scans through storage/index interfaces;
- filtering and bag-preserving projection;
- an explicit memory budget and temporary-file ownership;
- disk-backed temporary rows, runs, and partitions;
- external sorting with bounded k-way merge and multiple passes;
- a small adopted aggregate set;
- external grouping and an optimized join route;
- bounded handling of skew, collisions, and high duplicate multiplicity;
- manually assembled physical pipelines;
- measured operator/resource statistics and descriptive metadata;
- tests for spill behavior, cleanup, reopened storage, and composition.

### Excluded

- SQL grammar, parser AST, name resolution from SQL text, planner, and optimizer;
- the production Stage 7 executor orchestration layer;
- INSERT/DELETE/UPDATE statement operators and new transaction semantics;
- concurrent mutation, locks, WAL, MVCC, or crash-resumable query execution;
- frontend execution-plan rendering and API transport;
- DISTINCT, windows, outer joins, correlated subqueries, and full SQL conformance unless already required by an accepted project decision;
- full benchmark campaigns and final 1K/10K/100K comparison reports;
- spatial, vector, text, multimedia, and distributed algorithms.

A small lifecycle helper used to run manually constructed operators is in scope. A SQL-facing execution engine is not.

## 5. Non-negotiable execution invariants

1. Each operator advertises a stable output schema compatible with every row it emits.
2. Row occurrences are preserved unless the operator's semantics explicitly change cardinality.
3. Projection is not implicit DISTINCT. An inner equijoin with m left and n right matches emits m*n pairs.
4. Streaming operators do not collect their whole input. Blocking operators honor their memory contract.
5. B+ may supply equality and range access; Extendible Hashing supplies equality only.
6. A comparison, grouping key, and join key use compatible typed-value semantics. Hash equality is followed by full key equality.
7. Every temporary file belongs to one execution context. Cleanup cannot remove base tables or indexes.
8. Exhaustion, early termination, and exceptions release owned resources.
9. Query execution is read-only over base storage in this stage. Temporary writes do not constitute base-table mutations.
10. Memory limits apply to simultaneously live work, including child operators and retained output state, not merely to an isolated algorithm.
11. Metrics count real work; expected costs and observed I/O are separate.
12. External behavior is demonstrated by forced spills, not inferred from a class name.

## 6. Decision checkpoint

Resolve these in Task 6.2 before wide implementation:

| Decision | Recommended starting point; preserve accepted repository choices |
|---|---|
| Lifecycle | Existing open/next/close contract or one equivalent iterator model |
| End of stream | StopIteration or an explicit sentinel, never ambiguous with a nullable row |
| Re-execution | New operator instances by default; reopening only where explicitly supported |
| Row representation | Existing values/schema model with qualified column identity |
| Provenance | Optional relation-qualified base RIDs; not fabricated for derived rows |
| Predicate subset | Typed comparisons and Boolean composition needed by the planned SQL subset |
| NULL/float semantics | Follow existing type policy; document unknown values, NaN, and signed zero |
| Sort specification | Explicit column positions, direction, null placement, and tie policy |
| Aggregates | COUNT(*) first; recommend COUNT(column), SUM, MIN, MAX, AVG as a small adopted set |
| Group semantics | Group keys plus aggregate outputs, not arbitrary ungrouped columns |
| Join semantics | Inner equijoin minimum; baseline predicate join if already useful |
| Optimized routes | ExternalHashGroup and GraceHashJoin by default |
| Budget model | Explicit bytes/page reservations with implementation overhead accounted for |
| Temporary format | Schema-aware sequential paged row stream with bounded readers/writers |
| Large intermediate row | Support multi-page framing or reject above a documented bound |
| Spill policy | Deterministic partitioning, bounded fan-out and recursion, terminating fallback |
| Temporary lifecycle | Query-owned files, deterministic close, no crash-resume promise |
| Observability | Real I/O, row counts, peak accounted memory, spill/run/partition statistics |

COUNT/SUM/etc., an exact byte budget, and the number of tasks are implementation choices, not newly invented official requirements.

## 7. Task index and dependencies

| Task | Work item | Main prerequisites |
|---|---|---|
| 6.1 | Inspect Stage 5 and establish baseline | Reported Stage 5 completion |
| 6.2 | Resolve semantics and algorithm decisions | 6.1 |
| 6.3 | Define execution rows and output schemas | 6.2 |
| 6.4 | Implement the operator lifecycle | 6.3 |
| 6.5 | Implement execution context and memory accounting | 6.2, 6.4 |
| 6.6 | Implement typed expression evaluation | 6.3 |
| 6.7 | Implement TableScan | 6.4-6.5 |
| 6.8 | Implement IndexScan | 6.6-6.7 |
| 6.9 | Implement Filter | 6.6-6.7 |
| 6.10 | Implement Projection | 6.3-6.4 |
| 6.11 | Implement temporary-file ownership | 6.5 |
| 6.12 | Implement temporary row readers/writers | 6.3, 6.11 |
| 6.13 | Define one ordering/comparison policy | 6.3, 6.6 |
| 6.14 | Generate bounded sorted runs | 6.5, 6.12-6.13 |
| 6.15 | Implement bounded k-way merge | 6.14 |
| 6.16 | Complete multi-pass ExternalSort | 6.15 |
| 6.17 | Implement aggregate state functions | 6.3, 6.6 |
| 6.18 | Implement the bounded hash-group kernel | 6.5, 6.17 |
| 6.19 | Implement reusable external partitioning | 6.5, 6.12 |
| 6.20 | Implement ExternalHashGroup | 6.18-6.19 |
| 6.21 | Handle grouping skew and partition limits | 6.16, 6.20 |
| 6.22 | Implement NestedLoopJoin baseline | 6.6, 6.12 |
| 6.23 | Implement the bounded hash-join kernel | 6.5, 6.22 |
| 6.24 | Implement GraceHashJoin | 6.19, 6.23 |
| 6.25 | Handle join skew and large outputs | 6.22, 6.24 |
| 6.26 | Add optional index-assisted strategies | 6.8, 6.17, 6.22 |
| 6.27 | Compose and execute manual physical plans | Core operators above |
| 6.28 | Add measured statistics and descriptors | 6.5, 6.27 |
| 6.29 | Test persistence boundaries and cleanup failures | External operators |
| 6.30 | Add differential and resource stress tests | 6.27-6.29 |
| 6.31 | Document decisions and prepare Stage 7 handoff | Required tasks complete |

## 8. Detailed tasks

### Task 6.1 - Inspect the completed Stage 5 implementation

**Objective:** Identify the actual reusable interfaces and prerequisites.

**Actions:**

- Read the current repository's AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, and ETAPA_05.md.
- Verify Stage 5's Definition of Done using code and tests; do not just inspect checklist marks.
- Locate storage cursors, codecs, RID resolution, index cursors, Catalog metadata, and actual I/O counters.
- Inspect whether scan and index APIs stream or eagerly allocate entire result lists.
- Inspect the Stage 1 operator contract and any existing later-stage code; preserve compatible work.
- Record schema, duplicate-key, NULL, float, and RID movement policies.
- Run the configured Stage 1-5 suite and record baseline failures.
- Check current-stage documentation pointers without inferring implementation from their historical values.

**Deliverable:** A compatibility map and test baseline, with prerequisites/conflicts listed explicitly.

**Tests/evidence:** Record the actual Stage 1-5 regression command and its results; identify any skipped persistence or index-integration checks instead of treating them as passed.

**Acceptance:** No existing abstraction is duplicated and no claim of previous-stage verification lacks actual evidence.

### Task 6.2 - Approve execution semantics and the external-algorithm route

**Objective:** Convert Section 6's proposals into explicit project decisions.

**Actions:**

- Select the lifecycle, row/schema contract, comparison policy, aggregates, and join subset.
- Approve memory accounting, buffer reservations, spill format, cleanup, and large-row limits.
- Select the grouping and join optimization routes independently.
- For the default route, approve ExternalHashGroup and GraceHashJoin, including bounded skew fallbacks.
- Decide whether same-process temporary-reader reopen is sufficient; do not require query crash resume.
- Record which Stage 4/5 lookup APIs need backward-compatible streaming adapters.
- Define the boundary between this stage's physical execution helper and Stage 7 orchestration.

**Tests/evidence:** Review a small semantic matrix: duplicate rows, NULL predicates, equal-key joins, empty aggregates, and unsupported operations.

**Acceptance:** There are no silent choices about SQL-like semantics or memory behavior. An alternative strategy has its own concrete requirement-evidence mapping.

### Task 6.3 - Define execution rows, column identity, and output schemas

**Objective:** Represent base and derived rows without confusing them with persisted records.

**Actions:**

- Reuse Schema, DataType, and Record where compatible; add a small execution-row wrapper only if necessary.
- Resolve references through qualified column identity or pre-bound positions. Two joined tables may both contain an id column.
- Define row ownership: a consumer retaining a row must not observe its values mutate when the producer advances.
- Provide optional provenance using relation identity plus RID; a bare RID is not globally unique across tables.
- Preserve appropriate provenance through scans/filters; define projection/sort propagation deliberately.
- Give grouped rows a derived identity, and joined rows combined or absent provenance. Never fabricate one base-table RID.
- Define derived output schemas for projections, joins, and aggregates.

**Tests:** Same-named columns, aliases, type preservation, schema/value length mismatch, retained-row stability, and joined rows wider than base records.

**Acceptance:** Every output row conforms to a known schema; base persistence formats remain unchanged.

### Task 6.4 - Implement the operator lifecycle

**Objective:** Make operators composable and predictable.

Conceptual API; use the existing repository equivalent:

~~~python
operator.open(context)
row = operator.next()  # or next(operator); exhaustion is explicitly defined
operator.close()
~~~

**Actions:**

- Define legal transitions between created, open, exhausted, failed, and closed states.
- Make close idempotent and safe after partial open.
- Each parent owns and closes its child cursors, not externally owned table/index handles.
- Support empty input, repeated exhaustion, early consumer stop, and exceptions.
- Decide whether repeated open resets the operator or is unsupported; do not assume every iterator rewinds.
- Implement a small test runner that guarantees close in a finally block and normally streams to a sink.
- Do not make the core runner return an unbounded list.

**Tests:** Invalid lifecycle calls, partial-open failure, next failure, early close, empty input, and two independent scans of one table.

**Acceptance:** There is one lifecycle contract, and resource ownership survives failure paths.

### Task 6.5 - Implement execution context and memory accounting

**Objective:** Give external algorithms a real, testable resource boundary.

**Actions:**

- Define ExecutionContext with a budget, resource owner, and statistics collector.
- Account for simultaneously live child buffers, operator state, row copies, sort workspace, merge heads, and output buffers.
- Define whether the budget means controlled page/byte working memory rather than total Python process RSS; expose it under the correct name.
- Budget decoded-object overhead explicitly or use compact retained buffers with a documented conservative accounting model.
- Reserve memory before retaining/growing state; release it when spilled or closed.
- Bound open file handles independently from byte limits.
- Specify minimum feasible budgets and a deterministic oversized-row error.
- Avoid an unbounded list of run/partition metadata; keep descriptors disk-backed, bounded, or under an explicit supported limit.
- Inspect lower-layer caches and eager RID lists so they cannot silently bypass the documented bound.
- Ensure nested blocking operators reserve compatible budgets; divide/transfer reservations or fail before execution if impossible.

**Tests:** Tiny budgets, reservation/release, nested sorts/grouping, failed allocation, wide rows, and peak-accounted-memory assertions.

**Acceptance:** The complete pipeline has a coherent resource model. A per-operator limit is not advertised as a whole-process memory guarantee.

### Task 6.6 - Implement typed expression evaluation

**Objective:** Evaluate already-bound expressions without SQL parsing or storage coupling.

**Actions:**

- Reuse or add minimal column-reference, literal, comparison, and Boolean expression objects.
- Implement only the approved predicate subset; equality and ordered comparisons should cover the planned use cases.
- Validate column/type compatibility before consuming data where possible.
- Define numeric coercion and string comparison once, consistently with index semantics.
- If NULL is supported, define TRUE/FALSE/UNKNOWN and make Filter retain only TRUE.
- Define grouping equality separately from predicate UNKNOWN: NULL group keys may share one group while NULL equality join keys do not match.
- If NULL or non-finite floats are unsupported, reject them explicitly rather than relying on Python defaults.
- Do not use eval, exec, or SQL strings as predicates.

**Tests:** Bound columns, literals, valid/invalid types, nested Boolean expressions, null truth tables if supported, signed zero, and accepted/rejected non-finite values.

**Acceptance:** Predicates, hash keys, and sort comparisons cannot disagree silently about supported value equality.

### Task 6.7 - Implement TableScan

**Objective:** Stream active rows through the existing storage interface.

**Actions:**

- Support HeapFile and the completed PagedSequentialFile through their public scan contracts.
- Skip deleted slots, tombstones, and physical metadata pages.
- Emit complete values with their correct schema and optional relation-qualified RID.
- Retain only the bounded cursor/page state required for iteration.
- Do not claim a sorted property for HeapFile.
- Expose a sequential-file ordering property only when the adopted physical/logical scan guarantees it.
- Close cursor resources without closing externally owned storage.
- Execute over reopened tables as well as newly created ones.

**Tests:** Empty, one-row, one-page, multipage, deleted/reused slots, early termination, and two interleaved independent cursors.

**Acceptance:** Each active row occurrence is returned exactly once and no full-table list is created.

### Task 6.8 - Implement IndexScan

**Objective:** Convert valid index results into a row stream.

| Access path | Required capability |
|---|---|
| Unclustered B+ | Exact lookup and range traversal followed by RID fetch |
| Clustered B+ | Exact/range lookup using the actual Stage 4 storage adapter |
| Extendible Hashing | Exact lookup only |

**Actions:**

- Accept an explicitly selected index and bound search specification; do not implement planner selection.
- Define inclusive/exclusive range bounds and empty/inverted ranges.
- Preserve all matching row occurrences and fetch the correct base record.
- Handle invalid, deleted, and reused-slot RIDs through the established consistency policy; default to a clear stale-index error rather than silently returning another row.
- When needed, verify the fetched key still matches the index/search condition.
- Stream large duplicate RID sets and B+ ranges; add compatible cursor APIs if the existing public methods materialize all results.
- Reject unsupported hash ranges; do not label a fallback table scan as a hash range scan.
- Advertise order only when actually preserved; RID/page batching must not silently destroy B+ order.

**Tests:** Empty index, duplicate keys across pages, bounded/open-ended ranges, invalid RID, reopened indexes, and equality equivalence among all compatible access paths.

**Acceptance:** IndexScan returns the same row multiset as the corresponding TableScan plus predicate and exposes honest access properties.

### Task 6.9 - Implement Filter

**Objective:** Stream only rows whose predicate evaluates to TRUE.

**Actions:**

- Pull rows until a match or end of stream.
- Preserve output schema, row values, and permitted provenance.
- Keep constant bounded state; do not build a filtered list.
- Count rows examined and emitted.
- Preserve child order without claiming new ordering.

**Tests:** All/none/some matches, empty input, null predicates if supported, predicate failure, early stop, and composition over both scan types.

**Acceptance:** Filtering changes membership only, with no accidental mutation or deduplication.

### Task 6.10 - Implement Projection

**Objective:** Produce selected fields in the requested output order.

**Actions:**

- Resolve selections and aliases against child schema before reading rows.
- Construct the output schema independently of the child's physical storage schema.
- Preserve duplicate input occurrences.
- Support select-all through the approved schema API.
- Reject unknown/ambiguous columns; define repeated-column selection behavior.
- Track ordering metadata only for keys that remain representable after projection.
- Reject an invalid manual plan that projects away a downstream sort/group key, unless that key is deliberately carried as an internal field.

**Tests:** Reordered/subset/all columns, aliases, duplicate-valued rows, missing fields, and use before or after Filter.

**Acceptance:** Projection is streaming and is not DISTINCT.

### Task 6.11 - Implement query-owned temporary-file management

**Objective:** Own and clean up disk intermediates safely.

**Actions:**

- Allocate a unique execution directory with a temporary-directory facility.
- Register exact paths or file IDs created by this execution.
- Separate temporary runs/partitions from permanent table and index files.
- Keep ownership until every consumer has released a run/partition.
- Close handles before deleting files, including on platforms that disallow deleting open files.
- Clean up after success, early stop, validation errors, and I/O exceptions.
- Preserve the original error if cleanup also fails; report any unreclaimed exact paths.
- Do not implement a broad startup deletion of all files in a shared directory.
- Define optional debug retention explicitly and disable it in normal cleanup tests.

**Tests:** Two independent contexts, partial file creation, early close, read/write failure, cleanup twice, and protected base-file sentinels.

**Acceptance:** Cleanup touches only execution-owned temporary artifacts.

### Task 6.12 - Implement temporary row readers and writers

**Objective:** Reuse page I/O without pretending every intermediate is a base-table Record.

**Actions:**

- Build a schema-aware sequential temporary-row stream with bounded buffering.
- Record format version, output schema information, and complete record framing.
- Handle variable-length fields and intermediate rows wider than a base record.
- Either support records spanning temporary pages or reject a documented maximum row size before unsafe allocation; do not silently truncate.
- Distinguish EOF from truncated/corrupt framing.
- Support closing and reopening a completed temporary file within its owner's lifetime.
- Store data needed by the next operator, not only RIDs that may be meaningless for derived rows.
- Route temporary reads/writes through observable I/O; do not hide files from counters.

**Tests:** Empty/multipage streams, Unicode, duplicates, supported nulls, joined-row widths, framing boundaries, close/reopen, truncated final record, and incompatible version.

**Acceptance:** Temporary storage round-trips every supported execution row with bounded buffers.

### Task 6.13 - Define sort specifications and comparison keys

**Objective:** Use exactly the same ordering in initial runs and all merge passes.

**Actions:**

- Define SortSpec using bound columns, ASC/DESC, and null placement.
- Specify whether equal-key rows are stable. Recommended: preserve input order using an internal sequence value retained across spills.
- Ensure heap entries break ties without trying to compare arbitrary row objects.
- Use one comparator/key policy for numeric, text, nullable, and accepted floating values.
- Support multiple sort keys if adopted; at minimum do not prevent later extension.
- Define empty sort specification behavior.
- Do not assume lexicographic encoded bytes match logical order unless the codec proves it.

**Tests:** Ascending/descending, equal keys, mixed directions if adopted, Unicode, negatives, null placement, and the same result before and after spilling.

**Acceptance:** Internal sorting and merge comparisons induce the same documented order.

### Task 6.14 - Generate memory-bounded sorted runs

**Objective:** Implement the first phase of ExternalSort.

**Algorithm:**

1. Pull rows until the next retained row and sort workspace would exceed the granted budget.
2. Sort the current bounded chunk using the approved SortSpec.
3. Write a sorted run to an execution-owned temporary file.
4. Release chunk memory and continue, then flush the final nonempty chunk.

**Rules:**

- Standard-library sort is allowed on an admitted chunk, never on the entire unknown-size input.
- Keep the pending row safe when the previous chunk spills.
- Count initial runs and their rows/bytes.
- Handle zero rows, exactly-full chunks, and a single supported large row.
- A small-input in-memory fast path is optional; tests must still force disk-backed runs.

**Tests:** Empty input, exact memory boundary, one extra row, variable widths, duplicates, and several individually sorted runs whose combined multiset equals the input.

**Acceptance:** No row is lost between chunks, and more-than-memory input produces real disk runs.

### Task 6.15 - Implement bounded k-way merging

**Objective:** Merge only as many runs as memory and handle limits permit.

**Actions:**

- Open one bounded reader per active run and retain its current head.
- Use a priority queue such as heapq for the smallest next row according to SortSpec.
- Refill only the reader whose head was emitted.
- Reserve an output buffer and comparator/heap overhead.
- Derive fan-in from available resources, not from the total number of runs.
- In the simplified one-page-input/one-page-output model, k <= B-1; actual k must also leave room for row heads and implementation overhead.
- Require k >= 2 when merging multiple runs, or fail a too-small configuration clearly.
- Stream output to a bounded writer or downstream consumer.

**Tests:** Unequal run lengths, empty runs, duplicates across runs, ASC/DESC, exhausted readers, read failure, and fan-in/peak-memory assertions.

**Acceptance:** Merging does not load entire runs, exceed the handle limit, or change row multiplicity.

### Task 6.16 - Complete multi-pass ExternalSort

**Objective:** Handle more initial runs than one merge can consume.

**Actions:**

- Merge groups of at most k runs into next-pass runs.
- Repeat until one final run remains, or stream the last bounded merge directly.
- Reclaim previous-pass files only after replacement output is complete and no reader owns them.
- Count initial runs, merge passes, maximum active fan-in, and temporary I/O separately.
- Define whether the final result is materialized or streamed; do not assume both have identical write costs.
- Keep run descriptors bounded as the number of runs grows.
- Integrate open/next/close and early-stop cleanup.

**Tests:** Force initial_run_count > k and at least two merge passes; compare exact sorted output with a small test-only in-memory oracle. Test early close during the final merge and failures during intermediate passes.

**Acceptance:** ExternalSort handles arbitrary numbers of runs within the documented resource limits without reopening every run simultaneously.

### Task 6.17 - Implement aggregate state functions

**Objective:** Maintain one small state per group rather than storing its member rows.

**Actions:**

- Introduce an aggregate interface equivalent to initialize, accumulate, merge, and finalize.
- Implement COUNT(*) first; add the aggregate set adopted in Task 6.2.
- Distinguish COUNT(*) from COUNT(column) when nulls are supported.
- Use sum and non-null count for AVG; never merge averages by averaging their final values.
- Define output types, integer overflow behavior, and numeric rounding/tolerance.
- Define grouped-empty input as zero groups; for adopted global aggregation, empty input produces one aggregate row with COUNT=0 and other results following the documented policy.
- Reject non-grouped, non-aggregated output references.
- Keep DISTINCT aggregates, array collection, and arbitrary unbounded aggregate states out of scope.

**Tests:** Multiple aggregates, all-null and empty inputs if applicable, negative numbers, merge associativity under the documented numeric tolerance, and invalid argument types.

**Acceptance:** Supported aggregate state has bounded size per group and can be serialized/merged if the spill design requires it.

### Task 6.18 - Implement a bounded in-memory hash-group kernel

**Objective:** Aggregate one input segment only while its group states fit the granted budget.

**Actions:**

- Use canonical grouping keys, with full equality checks for collisions.
- Permit an internal dictionary for bounded per-partition state; it does not replace the external algorithm.
- Account for key bytes, map/container overhead, and aggregate states.
- Update the state for an existing group without retaining every row.
- Signal capacity exhaustion before admitting an unaccounted new group.
- Define how the caller preserves the triggering row.
- Do not emit a final group result until that group's complete input is known.
- Keep result iteration bounded, rather than copying the state map into another full result list.

**Tests:** One group with many rows, many distinct groups, duplicate values, constant-hash collisions, boundary admission, and oracle agreement.

**Acceptance:** Memory growth follows distinct live groups, not all input rows; capacity exhaustion is explicit and lossless.

### Task 6.19 - Implement reusable disk partitioning

**Objective:** Provide bounded temporary hash partitions for both grouping and joins.

**Actions:**

- Hash normalized typed keys into a configured partition count.
- Use the same equality normalization on both sides of a join. Equal supported keys must route to the same partition.
- Reuse stable hash primitives from Stage 5 only where compatible; keep recursion seed/bit choices local to the query.
- Bound active partition buffers and file handles. Under a simplified B-page model, output partition fan-out must leave an input buffer and overhead.
- Record partition row counts, byte sizes, level, and hash parameters without loading all partition contents.
- Release empty partitions or represent them cheaply.
- For recursion, change the partitioning seed or selected bits consistently; repeating an identical partition function does not make progress.
- Provide a no-progress check and maximum recursion depth.
- Define completion/publication of a partition file so truncated writes cannot be consumed as valid data.

**Tests:** Multiset conservation, all-equal keys, many distinct keys, full-hash collisions, empty partitions, paired join routing, and handle/memory bounds.

**Acceptance:** Each input row occurrence belongs to exactly one partition at a given level, and partitioning itself is memory-bounded.

### Task 6.20 - Implement ExternalHashGroup

**Objective:** Complete the proposed GROUP BY optimization using disk partitioning.

**Recommended first implementation:**

1. Partition the raw input rows by the complete grouping key.
2. Close the writers and process one partition at a time.
3. Use the bounded hash-group kernel for that partition.
4. If it fits, stream finalized group rows and release the partition.
5. If it does not fit, repartition the entire unconsumed logical partition before emitting results, then process its children.

This partition-first route is easier to validate than adaptive partial aggregation. A small-input fast path can be added later.

**Critical rules:**

- Equal keys must not be finalized independently in separate partitions.
- If a partition overflows after partial accumulation, discard that tentative state and reprocess the complete original partition, or implement a precisely specified partial-state merge. Never double-count.
- Measure fit by aggregate-state memory, not only raw partition-file length.
- Keep grouped output unordered unless a verified strategy guarantees order.
- Do not build one global map after partitioning; that defeats the external design.

**Tests:** Distinct group states exceeding memory, groups crossing input pages, repeated keys, multiple aggregates, and output equivalence to the bounded kernel on small data.

**Acceptance:** The forced-spill case performs real partition I/O, computes one correct result per group, and respects the budget.

### Task 6.21 - Handle grouping skew, collisions, and repartition limits

**Objective:** Guarantee termination when additional hashing does not reduce a difficult partition.

**Actions:**

- Distinguish many rows in one group from too many distinct groups: a fixed-size aggregate can process a very large single group.
- Detect non-shrinking recursive partitions and full-hash collisions.
- Cap recursion depth and release parents only after child processing is safe.
- Provide a bounded correctness fallback. Recommended: ExternalSort the problematic partition by group key, then aggregate adjacent equal keys with one group's state.
- Identify the fallback in runtime statistics; do not claim it is hash-only execution.
- Preserve the initial external-hashing route as the demonstrated normal optimization. Sort-only grouping is not substituted silently for the requirement.
- Reject unsupported oversized keys/states explicitly; resource-limit errors must not be represented as complete results.

**Tests:** A dominant key, all rows equal, distinct keys under a constant test hash, failed repartition progress, fallback output, and cleanup after failure.

**Acceptance:** Supported skewed inputs finish with correct results; no infinite repartition loop or unbounded group-member list exists.

### Task 6.22 - Implement NestedLoopJoin as the baseline

**Objective:** Establish a simple independent join implementation for correctness comparison and fallback.

**Actions:**

- Define inner-join output schema with qualified columns from both inputs.
- Compare pairs through the typed predicate evaluator.
- Produce every matching pair, including the full m*n multiplicity of duplicate join keys.
- Never assume the inner iterator can rewind.
- Recreate/reopen a documented repeatable scan, or spool a non-repeatable inner child once to a temporary row stream and reopen that stream for each outer row/block.
- Start with tuple nested loop; bounded block nested loop is recommended for the skew fallback.
- Stream result pairs; the join output itself may be much larger than both inputs.

**Tests:** Empty left/right, no/all matches, one-to-many, many-to-many, same-named columns, a non-rewindable inner producer, null join keys if supported, and early termination.

**Acceptance:** Correct baseline behavior is independent of hashing. It is not presented as the required optimized join by itself.

### Task 6.23 - Implement a bounded build/probe hash-join kernel

**Objective:** Join one partition pair when one build side fits the budget.

**Actions:**

- Admit the chosen build input only while retained rows, keys, and map overhead fit.
- Store all build row occurrences for a key, not only the last one.
- Probe with a streaming input and compare full keys after hashing.
- For each probe row, emit matching build rows incrementally.
- Keep logical left/right output column order even when the physical build side is swapped.
- Apply residual predicates after equality matches if adopted.
- Exclude null equality keys under the selected SQL-like inner-join semantics.
- Signal build overflow before any output based on an incomplete build table is published.

**Tests:** Build-side fit and overflow, collisions, duplicate multiplicity, both build-side choices, nonmatching probes, and a probe row with many matches.

**Acceptance:** The kernel never loads the probe side or the complete result, and it reports capacity exhaustion to its caller.

### Task 6.24 - Implement GraceHashJoin

**Objective:** Complete the proposed external-hashing join route.

**Algorithm:**

1. Partition both inputs on their respective bound join keys using compatible hash parameters.
2. For each matching partition pair, select a build side that fits the available state budget.
3. Build and probe using Task 6.23.
4. Release the pair after its result stream is exhausted.
5. Repartition an oversized pair consistently on both sides before emitting that pair's output.

**Actions:**

- Use partition byte/row metadata to guide build-side choice, but confirm actual admitted state fits.
- Do not scan an input into memory just to estimate its size.
- Preserve pair identity and hashing parameters across recursion.
- Reprocess an overflowing pair from complete temporary input, avoiding skipped or duplicate pairs.
- Reuse Task 6.19 instead of building a second partition-file manager.
- Keep both source tables/indexes unchanged.

**Tests:** Both inputs larger than the budget, multiple partition pairs, build-side swapping, empty counterpart partitions, spill evidence, and bag-equivalence with NestedLoopJoin.

**Acceptance:** At least one large-input optimized join executes through real disk partitions under the declared budget.

### Task 6.25 - Handle join skew and oversized outputs

**Objective:** Finish joins even when equal keys cannot be separated through further hashing.

**Actions:**

- Detect no-progress repartitioning and enforce a recursion cap.
- Recognize that repeated occurrences of one key cannot be separated by changing the key hash while preserving co-location.
- Fall back to a bounded block nested loop for the problematic partition pair, using the reusable baseline/spool mechanism.
- Keep only an admitted block from one side and stream/rescan the other side.
- Emit the Cartesian product of matching occurrences incrementally.
- Do not use list(build_matches), a giant cross-product list, or a result cache that grows with total output.
- Record fallback counts and explain that skew can increase runtime even when memory remains bounded.

**Tests:** All rows share one key; m and n small inputs produce exactly m*n rows. Also test constant hashes for unequal keys, multiple skew levels, early stop during a large result, and memory/handle peaks.

**Acceptance:** Supported skewed joins terminate correctly without unbounded memory or a silent loss of duplicate matches.

### Task 6.26 - Add optional index-assisted strategies

**Objective:** Reuse persistent indexes strategically where a verified access property helps.

This is optional when both default external-hashing routes are completed. If Task 6.2 selects an index-based route as the requirement-satisfying alternative, its corresponding implementation and tests become required.

**IndexNestedLoopJoin:**

- Stream the outer input and probe an existing compatible inner equality index.
- Support B+ and/or Extendible Hashing through the shared interface.
- Stream all matching inner RIDs and fetch the correct records.
- Preserve m*n output multiplicity, residual predicates, and stale-RID checks.
- Do not build an unbounded cache of every probe key.
- Identify actual index probes in metrics.

**IndexOrderedGroup:**

- Use a B+ traversal whose leading key order is compatible with the complete grouping key.
- Maintain one adjacent group's aggregate state at a time.
- Verify that the index covers every input row required by the grouping semantics, including any nullable-key exclusion policy.
- Fetch required non-indexed columns through storage; do not invent index-only coverage.
- Never assume a hash index yields ordered groups.

**Tests:** Compare with baseline results, demonstrate the index is actually used, and reject incompatible indexes/orderings.

**Acceptance:** A selected strategic-index route has explicit preconditions and measured evidence; an index's mere presence is not sufficient.

### Task 6.27 - Compose and run manual physical plans

**Objective:** Prove that operators can work together before SQL exists.

**Actions:**

- Use bound Python objects to assemble plans; do not parse strings or select access paths automatically.
- Add a small physical-pipeline runner or context manager that opens, streams, and closes a root.
- Give each execution fresh state and exclusive cursor ownership.
- Validate compatible schemas, bound fields, supported access properties, and resource reservations.
- Demonstrate TableScan + Filter + Projection.
- Demonstrate equivalent equality plans through B+ and hash IndexScan.
- Demonstrate B+ range results against a filtered scan.
- Demonstrate ExternalHashGroup followed by ExternalSort.
- Demonstrate GraceHashJoin followed by Filter/Projection and, separately, grouping plus sorting.
- Include a plan with nested blocking operators whose simultaneous memory fits the context.

**Tests:** Exact schemas, row bags, sorted output where requested, empty intermediates, failures in a child, and early consumer stop.

**Acceptance:** Manually composed physical plans return correct results without SQL, HTTP, or UI dependencies. The runner does not become the Stage 7 parser/planner/executor.

### Task 6.28 - Add truthful descriptors, metrics, and domain errors

**Objective:** Leave a useful interface for the future execution-plan panel and benchmark stage.

**Suggested descriptor fields:**

| Field | Meaning |
|---|---|
| operator_id/type | Stable identity within one physical execution |
| children | Actual input operators |
| output_schema | Actual emitted columns/types |
| table/index identity | Real source/access path when applicable |
| predicate/sort/group/join specification | Bound operation, not invented SQL |
| strategy/order properties | External hash, B+ range, merge sort, fallback, etc. |

**Suggested measured statistics:**

- rows consumed per input and rows emitted;
- actual base/index/temp page reads and writes;
- bytes spilled and peak live temporary bytes;
- initial sorted runs, merge passes, and active fan-in;
- partition counts, maximum recursion level, and skew fallbacks;
- hash/index probe counts where meaningful;
- peak accounted working memory and maximum open temporary handles;
- elapsed time with its measurement boundary.

**Rules:**

- Derive descriptors from actual operator instances, without creating a planner.
- Distinguish estimates from observations.
- Define exclusive local I/O versus inclusive subtree totals; never sum overlapping counters.
- Define whether timing includes child work; do not add inclusive timings as if independent.
- Reuse lower-layer counters so one physical I/O is counted once at the appropriate level.
- Give failures stable domain errors: invalid schema/expression, unsupported access, stale index/RID, insufficient budget, oversized temporary row, and corrupt temporary file.
- A fallback must change actual runtime statistics/description, not remain hidden behind a static strategy label.

**Tests:** Small predictable counters, reset/re-execution, partial consumption, failure, and actual run/spill evidence.

**Acceptance:** Stage 7 can coordinate execution and Stage 9 can visualize it using the same truthful operator descriptions.

### Task 6.29 - Test persistence boundaries, cleanup, and failure safety

**Objective:** Prove correct use of persisted inputs and real temporary I/O without introducing crash recovery.

**Required tests:**

- Create tables/indexes, flush and close them, destroy their managers, then reopen through Catalog and run new operator instances.
- Write temporary runs/partitions, close their handles, open fresh readers, and recover the same row stream.
- Inject truncated records, unsupported temporary formats, and I/O read/write failures.
- Stop after only a few sorted/joined/grouped output rows and close the root.
- Fail a parent after a child has created temporary files.
- Verify every execution-owned handle and temporary path is released, except an explicitly reported cleanup failure.
- Compare base-file contents or logical snapshots before/after read-only queries; temporary I/O must not modify them.
- Keep a test-only unrelated file in the parent temp location to prove cleanup is scoped.

**Boundary:** Reopening persisted source data and completed temporary files is required. Resuming an interrupted query after process crash is not.

**Acceptance:** Success, early stop, and ordinary exceptions preserve base data and leave no unexplained execution-owned resources.

### Task 6.30 - Add differential, semantic, and resource stress tests

**Objective:** Verify correctness across input sizes, data shapes, and budgets.

**Oracle policy:**

- Use simple test-only loops, lists, maps, and sorting on deliberately bounded fixtures.
- Compare multisets for unordered results; compare sequences for explicitly ordered results.
- Do not compare plain sets where duplicate occurrences matter.
- Use tolerances only for documented floating aggregation differences.
- Do not depend on pandas or an external DBMS to execute production operators.

**Required fixture dimensions:**

| Dimension | Required cases |
|---|---|
| Cardinality | Empty, one row, one page, multipage, more than memory |
| Width | Small/fixed, variable strings, large supported intermediate rows |
| Duplicates | Identical values in separate records, repeated group/join keys |
| Distribution | Uniform, sorted, reverse-sorted, dominant key, all one key |
| Hash behavior | Normal, collisions, deliberately constant hash |
| Lifecycle | Full consumption, early stop, exception, fresh execution |
| Storage | Heap, sequential, reopened B+, reopened hash |
| Resources | Different valid budgets, below-minimum budget, handle cap |
| Composition | Several streaming operators, nested blocking operators |

**Hard evidence gates:**

- Force initial sort runs greater than merge fan-in and at least two merge passes.
- Force distinct group states beyond the memory grant.
- Force GraceHashJoin partitioning rather than only its in-memory kernel.
- Verify skew fallbacks and no-progress termination.
- Validate complete-pipeline peak reservations and temporary handle limits.
- Prove output row counts/multisets are independent of a changed valid memory budget.
- Run the complete earlier-stage regression suite.

**Acceptance:** A deterministic, reproducible test command exercises the external paths and all configured tests pass. No benchmark measurements are invented.

### Task 6.31 - Update architecture documentation and prepare the handoff

**Objective:** Make the execution layer understandable to the Stage 7 implementation.

**Actions when implementing the stage:**

- Update PROJECT_CONTEXT.md with approved row/schema, lifecycle, predicate, aggregate, and join semantics.
- Record budget accounting, temporary formats, fan-in/fan-out, recursion limits, large-row policy, and fallback rules.
- Record each index's supported scan capabilities and any compatible streaming API extensions.
- Document the default external routes or the explicitly accepted index-assisted alternatives.
- Describe how to manually run plans and read their metrics.
- Add the new operator modules/tests to architecture documentation without rewriting storage/index internals.
- Record actual test evidence and remaining optional features.
- While implementing, point current-stage fields to Stage 6 and ETAPA_06.md.
- After the Definition of Done is satisfied, record Stage 6 completion and next planned stage. Do not mark Stage 7 implemented or point to a nonexistent stage file as though it already exists.

**Acceptance:** Stage 7 can bind parsed expressions, construct physical operators, consume results, close resources, and obtain real plan statistics without reverse-engineering missing contracts.

## 9. Recommended implementation increments

| Increment | Tasks | Exit condition |
|---|---|---|
| A. Contracts and streaming | 6.1-6.10 | Typed scan/filter/projection pipelines work; lifecycle and memory decisions are explicit |
| B. Temporary storage and sorting | 6.11-6.16 | Disk-backed multipass ExternalSort works and cleans up |
| C. Grouping | 6.17-6.21 | External grouping exceeds memory safely and handles skew |
| D. Joins | 6.22-6.25 | Baseline and GraceHashJoin agree, including duplicate/skew cases |
| E. Optional index strategies | 6.26 | Implement only if selected or useful after required paths are stable |
| F. Integration and handoff | 6.27-6.31 | Manual plans, measured evidence, failure cleanup, and regression suite pass |

Develop tests alongside each task. The final testing tasks extend and integrate those tests; they are not a reason to postpone unit tests until the end.

If an approved strategic-index alternative replaces C or D, update this table and its corresponding closure gates before implementation. Do not leave contradictory mandatory checklists.

## 10. Suggested modules and deliverables

Names are illustrative; follow the actual repository organization.

| Location | Responsibility |
|---|---|
| engine/operators/base.py | Operator lifecycle and shared contracts |
| engine/operators/context.py | Execution resources and memory accounting |
| engine/operators/expressions.py | Bound typed expressions, if no compatible module exists |
| engine/operators/scan.py | Storage and index scan adapters |
| engine/operators/filter.py | Predicate selection |
| engine/operators/projection.py | Output field selection |
| engine/operators/external_sort.py | Runs, merge scheduling, sort facade |
| engine/operators/aggregation.py | Aggregate state and grouping operators |
| engine/operators/join.py | Baseline, hash, and optional indexed joins |
| engine/operators/partitioning.py | Reusable external partition logic |
| engine/storage/temp_files.py | Temporary ownership and paged row streams |
| tests/unit/operators/ | Isolated operator/codec/semantic tests |
| tests/integration/operators/ | Persisted input and composed-plan tests |
| tests/external/ | Forced-spill, multipass, skew, and resource tests |
| docs/operators.md | Contracts, manual examples, and capabilities |
| docs/external-algorithms.md | Budgets, run/partition format, fallbacks, and evidence |

Do not put parser-specific AST types in storage or move stable storage/index code merely to match these suggested paths.

**Expected handoff artifacts:**

- tested operator code and support utilities;
- deterministic tiny-memory fixtures;
- at least one manual execution example;
- actual test results and measured external-path counters;
- updated stable architecture decisions;
- completed stage checklist with optional alternatives clearly identified.

## 11. Manual acceptance examples

These are physical specifications to instantiate through the project's API. They are not requests to implement SQL yet.

### Example A - Filtered projection

Input students:

| id | name | career | age |
|---|---|---|---:|
| 1 | Ana | CS | 22 |
| 2 | Luis | EE | 19 |
| 3 | Sol | CS | 24 |
| 4 | Omar | EE | 23 |

Apply TableScan, Filter(age > 20), then Projection(name, career).

Expected row multiset: (Ana, CS), (Sol, CS), (Omar, EE). No ordering guarantee is required unless explicitly supplied by the plan.

### Example B - Group, then sort

On the same input, group by career with COUNT(*) and, if adopted, AVG(age). Sort by career ascending.

| career | COUNT(*) | AVG(age), if adopted |
|---|---:|---:|
| CS | 2 | 23 |
| EE | 2 | 21 |

The large-input variant must exceed the distinct-group memory grant. Merely replicating one key many times is not sufficient to force aggregate-state overflow.

### Example C - Preserve join multiplicity

Left join-key values: [7, 7, 9]. Right join-key values: [7, 7, 7, 10].

For an inner equality join:

- key 7 contributes 2*3 = 6 output pairs;
- keys 9 and 10 contribute zero;
- total output is six rows, even when projected values happen to look identical.

Run this against NestedLoopJoin, GraceHashJoin, and IndexNestedLoopJoin if selected.

### Example D - Force external sorting

Choose a valid tiny budget and input wide enough to create more initial runs than the allowed fan-in. Require:

- disk run writes greater than zero;
- at least two merge passes;
- maximum active merge fan-in within the limit;
- sorted output with exactly the input row multiset;
- no temporary files/handles left after close.

### Example E - Close and rerun

Build source storage and indexes, close all managers, reopen them, then construct a fresh group/join/sort pipeline. It must reproduce the same logical answer under at least two valid budgets.

## 12. Validation commands and evidence

Use configured repository commands, not invented dependencies. Examples, after the corresponding paths exist:

~~~bash
pytest -q
pytest -q tests/unit/operators
pytest -q tests/integration/operators
pytest -q tests/external
~~~

Run the existing formatter/linter/type checker if AGENTS.md or project configuration requires it.

Retain a concise stage report containing:

| Evidence | What to record |
|---|---|
| Test baseline and final run | Commands, pass/fail/skip counts, unrelated failures |
| Sort external path | Budget, input width/rows, initial runs, passes, max fan-in |
| Group external/index path | Budget, groups, spills/partitions or actual index traversal |
| Join optimized path | Input sizes, build budget, partitioning or actual index probes |
| Skew handling | Trigger, fallback, result count, termination |
| Resources | Peak accounted memory, active handles, residual temp paths |
| Restart | New managers/cursors used and results recovered |
| Regression | Stage 1-5 tests still passing |

Wall-clock speedups are not required for correctness closure. Do not assert universal performance gains from tiny fixtures. Final controlled experiments remain in Stage 10.

## 13. Definition of Done

The default-route checklist below assumes ExternalHashGroup and GraceHashJoin are the adopted optimizations. If Task 6.2 approves alternatives, replace only the relevant algorithm-specific gates with equivalent strategic-index evidence; never remove the official GROUP BY/JOIN optimization obligations.

### Prerequisites and contracts

- [ ] Stage 5 completion was checked against the actual repository.
- [ ] Previous-stage baseline failures were reported.
- [ ] Decisions in Section 6 are explicit and approved.
- [ ] Operators share one documented lifecycle and exhaustion convention.
- [ ] Output schemas and qualified columns are correct.
- [ ] Derived rows do not masquerade as single persisted records.
- [ ] Duplicate, null, float, grouping, and join semantics are tested.
- [ ] Memory and temporary-resource ownership are defined.

### Streaming operators and access paths

- [ ] TableScan streams active HeapFile and sequential-file records.
- [ ] B+ IndexScan supports exact and range access.
- [ ] Extendible Hash IndexScan supports equality without false range claims.
- [ ] Large scan/range/duplicate results do not bypass the memory model.
- [ ] Stale/invalid RIDs are handled explicitly.
- [ ] Filter retains only matching rows without materializing its input.
- [ ] Projection preserves row multiplicity and emits the correct schema.

### External sorting

- [ ] Initial chunks and sort workspace fit their granted memory.
- [ ] Sorted runs are written to real temporary storage.
- [ ] One comparison/tie policy is used across runs and passes.
- [ ] K-way merging has bounded buffers and file handles.
- [ ] More runs than fan-in are handled with multiple passes.
- [ ] A test forces at least two merge passes.
- [ ] Output is sorted and has exactly the input row multiset.
- [ ] Early close and failure clean up intermediate runs.

### Grouping

- [ ] The adopted aggregate set has tested accumulation/finalization semantics.
- [ ] Empty/global/grouped aggregate behavior is explicit.
- [ ] ExternalHashGroup partitions and processes more distinct groups than fit in memory.
- [ ] Partial partition overflow cannot double-count or lose a triggering row.
- [ ] Hash collisions use full key equality.
- [ ] A hot key does not create an unbounded member-row list.
- [ ] Repartitioning terminates through progress checks and a tested fallback.
- [ ] Grouped output makes no unsupported ordering promise.
- [ ] The approved grouping optimization has observable evidence.

### Joins

- [ ] NestedLoopJoin provides an independent correct baseline.
- [ ] Non-repeatable inner inputs are handled through bounded spooling or an explicit rescan contract.
- [ ] The hash-join kernel stores all matching build occurrences.
- [ ] GraceHashJoin demonstrably partitions inputs beyond its memory grant.
- [ ] Paired partitions use compatible key normalization and hash parameters.
- [ ] Build-side swapping preserves logical output column order.
- [ ] Duplicate keys produce m*n matches as a stream.
- [ ] Skew/no-progress cases terminate with a bounded fallback.
- [ ] The approved join optimization has observable evidence.

### Composition, persistence, and cleanup

- [ ] Manual plans execute without SQL, HTTP, or frontend dependencies.
- [ ] Group/join/sort compositions have compatible simultaneous reservations.
- [ ] The root runner does not collect arbitrary-size results.
- [ ] Completed temporary files reopen with fresh readers.
- [ ] New operators execute correctly over reopened tables/indexes.
- [ ] Read-only operators preserve base tables and indexes.
- [ ] Success, early stop, and ordinary exceptions release owned resources.
- [ ] Truncated/corrupt temporary files fail through controlled domain errors.
- [ ] Cleanup never touches unrelated or permanent files.

### Observability and handoff

- [ ] Descriptors describe actual operators and access paths.
- [ ] Real I/O is distinguished from estimates and is not double-counted.
- [ ] Peak accounted memory, temporary space, and handle counts are observable.
- [ ] Differential tests preserve multiset semantics.
- [ ] Different valid budgets produce equivalent logical results.
- [ ] All required Stage 6 and previous-stage regression tests pass.
- [ ] Stable decisions and limitations are documented.
- [ ] Current-stage metadata accurately records completion and the Stage 7 handoff.
- [ ] No future-stage implementation has been mixed into the required work.

## 14. Main risks and controls

| Risk | Control |
|---|---|
| Sort loads the whole input | Admission accounting and forced multipass tests |
| Many runs exhaust memory/handles | Bounded fan-in and bounded/disk-backed descriptors |
| Every child independently consumes the full budget | Query-context reservations over simultaneous live state |
| HashGroup retains all member rows | Fixed aggregate state per distinct key |
| A raw partition fits on disk but not as decoded state | Actual memory admission and overflow fallback |
| Repartition repeats forever | Progress detection, depth cap, and terminating fallback |
| Join overwrites duplicate keys | Store all build occurrences and verify m*n multiplicity |
| Output is larger than both inputs | Stream output rather than collecting pairs |
| Predicate/hash/order disagree | Shared normalized typed semantics |
| Hash index is treated as an ordered cursor | Capability checks and rejection |
| Index APIs return huge eager lists | Compatible streaming adapters or explicit accounted limits |
| Child iterator cannot rewind | Factory/rescan contract or temporary spool |
| Cleanup removes permanent data | Query-owned registry with exact targets |
| A plan displays an algorithm it did not use | Instance-derived descriptions and actual fallback metrics |
| Temporary persistence is mistaken for crash recovery | Explicit source-reopen versus query-resume boundary |
| SQL scope leaks into Stage 6 | Bound expression objects and manual plan assembly only |

## 15. Suggested incremental commits

1. Document decisions and establish operator row/schema/lifecycle contracts.
2. Add context, typed expressions, and streaming scans.
3. Add Filter and Projection with manual pipeline tests.
4. Add owned temporary row storage and failure cleanup.
5. Add bounded run generation and k-way merge.
6. Add multipass ExternalSort and tiny-budget evidence.
7. Add aggregate states and external partitioning.
8. Add ExternalHashGroup and skew fallback.
9. Add NestedLoopJoin and bounded build/probe kernel.
10. Add GraceHashJoin and skew/duplicate tests.
11. Add any selected strategic-index alternative.
12. Add composed-plan statistics and resource stress tests.
13. Record full-suite evidence and complete architecture handoff.

Keep each implementation increment reviewable and tested. Actual git commits require the user's repository workflow; this list is a recommended organization, not an instruction to push changes.

## 16. Recommended prompts for working with Codex

### Inspection prompt

~~~text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, ETAPA_05.md,
and ETAPA_06.md. Stage 5 is reported complete. Inspect the actual code and
tests before assuming its contracts or verification status.

Complete Task 6.1 only. Report the Stage 5 baseline, existing operator
interface, storage/index streaming capabilities, row/schema policies,
I/O counters, and conflicts. Do not modify code yet.
~~~

### Design-checkpoint prompt

~~~text
Complete Task 6.2. Propose the operator lifecycle, execution-row schema,
typed predicates, null/float semantics, aggregate set, inner-join semantics,
query-level memory accounting, temporary row format, merge fan-in, hash
partitioning, and bounded skew fallbacks.

Use ExternalHashGroup and GraceHashJoin as the default optimization route
unless the current approved architecture already selects a compliant
strategic-index alternative. Distinguish academic requirements from
project decisions. Do not implement the SQL parser, planner, or executor.
~~~

### First implementation prompt

~~~text
Implement Tasks 6.3-6.5 as approved: execution rows/output schemas,
operator lifecycle, and ExecutionContext/resource accounting.

Reuse existing types and contracts. Add tests for retained-row ownership,
EOF, partial-open failure, idempotent close, early stop, and simultaneous
memory reservations. Do not implement sorting, grouping, joins, or SQL yet.
Run the relevant tests and report changes and remaining decisions.
~~~

### Incremental task prompt

~~~text
Implement only the next incomplete required task in ETAPA_06.md.
Verify its prerequisites, preserve previous-stage contracts, and add
the listed tests as part of the implementation. Do not advance into
optional or future-stage work automatically. Run relevant tests and
report actual evidence plus any blockers.
~~~

### Stage-closure prompt

~~~text
Audit ETAPA_06.md against the actual repository and run the configured
tests. Verify forced multipass sorting, the adopted GROUP BY and JOIN
optimization routes, duplicate/skew cases, memory/handle limits, cleanup,
and execution over reopened storage. Distinguish implemented, verified,
optional, and missing items. Do not mark Stage 6 complete if a required
Definition of Done item lacks evidence. Do not implement Stage 7.
~~~

## 17. Condition for starting Stage 7

Stage 7 may begin when the approved Stage 6 Definition of Done is satisfied and the physical layer can:

- receive already-bound expressions and explicit access specifications;
- stream scan/filter/projection results;
- sort beyond its available memory through k-way merging;
- group and join using the demonstrated required optimization routes;
- compose these operations safely within the resource contract;
- expose real schemas, operator descriptions, errors, and measured statistics;
- release resources reliably after completion or failure.

Generate and reconcile ETAPA_07.md with the then-current PROJECT_CONTEXT.md before implementing that next stage.

Stage 7's new responsibility will be to translate the required SQL subset into these tested physical operators and coordinate execution. It should not need to reimplement their storage, sorting, partitioning, grouping, or join algorithms.
