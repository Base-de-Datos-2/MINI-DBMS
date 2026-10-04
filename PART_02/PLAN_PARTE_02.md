# PLAN_PARTE_02.md — Minimum Complete Spatial Delivery

**Revision:** 2.0 — two-day delivery scope, 2026-10-02 (America/Bogota).
**Purpose:** Deliver a functional, understandable Part 2 that meets the assignment, while completing the outstanding Part 1 work.
**Status:** E1.1–E1.5 and E2.1–E2.6 completed and verified (2026-10-03).
E3–E5 remain planned.
PostgreSQL/PostGIS is prepared in Docker. Part 1 Stage 10 closed on
2026-10-04 (`../docs/ETAPA_10_AUDIT.md`); its official 100k results are the WSL
runs, so the Windows E1.5 runs are only supplementary.

**E1 progress:**

- [x] E1.1: inspected `d07dec3e412ae15ea86ccce8c0214108cf277fc1`;
  selected `api.database.Database`; Stage 9 closed, Stage 10 remains open.
- [x] E1.2: local domain, explicit coordinate mapping, identity, units,
  origin, polygon boundary and tie conventions recorded in `PROJECT_CONTEXT.md`.
- [x] E1.3: nine-row `tiendas`/`restaurantes` fixtures loaded and reopened;
  `--spatial` startup and real application HTTP query verified.
- [x] E1.4: 1,000/10,000/100,000-row CSVs and 100 query centers generated;
  exact counts, reproducibility, domains and SHA-256 verified.
- [x] E1.5: Docker comparator prepared with PostgreSQL 17.5 / PostGIS 3.5.2.
  Loaded 1k/10k/100k points and 100 shared query centers into separate bases;
  exact CSV values, coordinate axes, valid GiST indexes, radius/k-NN index
  plans and persistence after container restart verified. The actual sphere
  matches the adopted radius within 1e-6 m. Evidence:
  `../benchmarks/results/spatial_e1_setup.json` and its three setup logs.
  Both existing Part 1 100k experiments were started with three repetitions,
  separate Windows results and one logical CPU each. Their completion,
  analysis and Stage 10 closure remain pending; see
  `../benchmarks/results/part1_e1_5_launch.json`. No E4 measurements are claimed.

**Verification (2026-10-03):** 296 focused tests passed in 125.96 seconds
with warnings as errors: `tests/spatial`, `tests/api`, `tests/benchmarks`,
`tests/transactions`, `tests/database`. This is not a full repository suite.
Environment: Windows, bundled Python 3.12.14, pytest 8.4.2 with the local
venv dependencies. Test temporaries and matplotlib cache were isolated
outside project data. Syntax parsing passed for all 10 affected Python files.

Commands, remaining Part 1 work and limits: `../docs/spatial.md`.
No R-Tree, spatial SQL, map or performance results are claimed by E1.
**E2 progress (2026-10-03):**

- [x] E2.1: validated local points/MBRs, metre-based Haversine and fixed-plane
  Euclidean, simple concave polygons with included boundary.
- [x] E2.2: real Heap radius/polygon scans and bounded exhaustive k-NN baseline.
- [x] E2.3: original quadratic-split R-Tree, capacity/occupancy policy,
  root growth and structural validation.
- [x] E2.4: actual indexed traversals, conservative metric bounds, exact
  residuals, stable-ID ties, real counters and Heap RID resolution.
- [x] E2.5: versioned/checksummed atomic save, validated reopen, INSERT
  maintenance, once-per-DELETE rebuild and existing physical undo/reopen.
- [x] E2.6: differential geometry/tree/Heap tests, duplicates/boundaries,
  mutation/rollback, save failure, locks, cancellation and clean restart.

Independent evidence: `../benchmarks/results/spatial_e2_100k_smoke.json`
(100k core entries, synthetic RIDs, 36 differential distance-query cases,
polygon and reopen; not an E4 measurement or a 100k Heap load), and
`../benchmarks/results/spatial_e2_owner_smoke.json` (real nine-row fixtures,
both metrics, polygon and fresh reopen). Automated loading covers a real
1k Heap dataset and exactly one index build. Commands for larger offline
loads are provided for E4 without changing the HTTP import limit.

Focused regression: **325 tests passed in 126.12 s** with warnings as errors
before the final small-polygon precision test. The complete engine regression
ran **2,964 cases in 2035.07 s** with warnings as errors: **2,963 passed**
and one architecture policy test did not recognize the new `spatial` layer.
That test was updated to allow only the spatial core's actual dependencies;
maintenance/transactions are permitted only in its lifecycle adapter.
Its final rerun passed **22 architecture tests in
66.32 s**, including three new isolated spatial imports.
All other engine sources stayed unchanged after the full run. Together the
two runs verify **2,967 distinct final cases**; this is not presented
as a second successful full-suite invocation.
The broken local venv interpreter was left untouched; verification used an
isolated temporary Python 3.12.14 environment with local dependencies and
project resolution available to isolated child interpreters. Evidence:
`../benchmarks/results/spatial_e2_verification.json` and
`../benchmarks/results/logs/spatial-e2-tests.log`, plus the final architecture
log `../benchmarks/results/logs/spatial-e2-architecture.log`.
Spatial SQL, HTTP and map remain E3 work.

**Source:** `Proyecto_Final.pdf`, §2.2, physical page 3; deliverables and partial-delivery milestone in §§3–4, physical page 5.

## 1. What this revision changes

This revision replaces the previous eleven-phase implementation checklist with **five delivery blocks**. It keeps the academic requirements and the engineering needed for correct results, persistent data and a usable demonstration. It removes broad infrastructure work from the critical path.

The earlier repository review was performed on September 30 at commit `14c2dc99b8ac5df09cfe713398420e89dcfd1df7`. At that snapshot, transactions were implemented, Stage 9 formal closure and Stage 10 remained pending, and spatial SQL was unsupported. **This revision does not claim a fresh review of current main.** At implementation start, inspect changes since that snapshot and reuse completed work rather than rebuilding it.

The original assignment remains authoritative for academic requirements. This file defines the reduced implementation approach. Architectural choices below are project decisions, not extra requirements attributed to the instructor. Preserve useful work already implemented under the earlier plan; simplification is not a reason to remove working features.

## 2. Required scope and evidence

| ID | Assignment requirement | Minimum acceptance evidence |
|---|---|---|
| R1 | Original R-Tree for 2D geographic points | Own node, MBR, subtree-selection, insertion/split and traversal code; a multi-level tree works on the required datasets |
| R2 | Range/radius queries | Correct point identities for a selected center and radius; indexed results match exhaustive search |
| R3 | k nearest neighbors | Correct distance order and result size, including duplicate locations and k larger than the dataset |
| R4 | Intersection with polygons | Points inside/on the adopted polygon boundary are found using an exact predicate after MBR filtering |
| R5 | Euclidean and Haversine distances | Both implemented, selectable, demonstrated and checked against reference cases |
| R6 | Spatial SQL | Both printed assignment examples execute through the existing SQL entry, one statement at a time |
| R7 | Interactive map with highlighted results | Stored points appear on the map; highlights correspond to actual engine results |
| R8 | Sequential search vs own R-Tree vs PostgreSQL GiST | All three methods run equivalent queries over identical data |
| R9 | N=1,000/10,000/100,000; radii 1/5/10 km; k=10/50/100 | Complete experiment matrix with actual measurements |
| R10 | Build time, mean query time over 100 queries, memory/disk space | Raw measurements and an explicit measurement procedure |
| R11 | Comparative graphs and technique-selection summary | Reproducible figures and a table explaining observed trade-offs |
| R12 | Incremental delivery documentation | Updated README, report with experiments and reproducible demonstration material |

Neither the map alone nor a standalone R-Tree script completes Part 2. The spatial engine must be reachable from the existing application, and the required experiments must be included. PostgreSQL is the external comparator, never the backend implementing the mini-DBMS spatial queries.

## 3. Small implementation scope, clear quality standard

### 3.1 Fixed decisions for this delivery

Use these defaults unless equivalent functionality already exists. Record any necessary adjustment briefly in `PROJECT_CONTEXT.md`; do not spend the deadline comparing multiple architectures.

| Topic | Delivery decision |
|---|---|
| Data domain | One local geographic area, such as metropolitan Lima, with documented bounds and finite valid coordinates |
| Point convention | SQL `POINT(latitude, longitude)` follows the assignment; adapters convert explicitly for map/GeoJSON/PostGIS conventions |
| Data storage | Existing persistent Heap records with stable RIDs; reuse an existing POINT type if implemented, otherwise use two FLOAT columns with an explicit logical `ubicacion` mapping |
| Spatial metadata | Table name, latitude/longitude columns, logical location name, index identity/path and fixed metric configuration; persist only what reopening requires |
| Application integration | One supported owner path from data loading through SQL/API to the map; prefer the path already serving the frontend |
| R-Tree | Original implementation, with a simple deterministic split strategy such as quadratic split |
| Default SQL distance | Haversine in metres; Euclidean available through a small explicit metric option |
| Polygon scope | Simple local polygons, including concave shapes, without holes or date-line crossing; boundary included |
| Loading | One documented CSV schema or deterministic setup script; no new generic import wizard |
| Map | Basic interactive map, query center, radius/k controls and predefined polygon selection; highlighted results |
| SQL scope | Required spatial expressions and LIMIT; existing manual parser and one-statement/comment behavior retained |
| Experiments | One full prescribed matrix using Haversine; smaller correctness/demonstration cases for Euclidean |

Using two FLOAT columns does not mean pretending that a VARCHAR is a geometry. Define a real internal point value assembled by the binder/evaluator from the registered coordinate pair. The logical name `ubicacion` must resolve explicitly for any registered spatial table, not through hardcoded table names or string replacement. A raw coordinate pair can remain the physical representation without extending every persistent record format.

If that approach is used, `SELECT *` can return the physical columns. The result metadata must identify the coordinate pair so the map does not guess it. A missing or ambiguous spatial mapping must produce a clear error.

### 3.2 Persistence and writes

Keep base records persistent through existing storage. Save the R-Tree structure and the small amount of spatial metadata needed to reopen it, using the simplest explicit, validated format compatible with the chosen owner. Reuse existing paged index infrastructure if that is already the shortest route.

A new buffer pool, page allocator, general migration system or sophisticated free-page scheme is not a delivery requirement. An in-memory traversal structure with an explicit persisted representation is an allowed project simplification because §2.2 does not prescribe a page layout. Document this choice, measure its actual memory and disk footprint, and distinguish load time from query time. Do not claim page-level I/O advantages that the implementation does not provide.

Preserve consistency for the data operations the application exposes:

- INSERT must add the spatial association; DELETE must remove it. Rebuilding the index once after a DELETE statement is an acceptable initial strategy instead of implementing CondenseTree.
- Initial bulk loading builds the index once after loading the data; it must not rebuild it after every imported row.
- Use existing session/table locks and rollback machinery. Register spatial files and refresh/reopen cached tree objects after restoration. Do not let the restored base file coexist with a stale tree.
- A failed build or mutation must leave the previous usable state intact or make the affected state explicitly unavailable. Never publish a partial tree as ready.
- Support clean close/reopen. Preserve the existing limits on crash recovery; do not add new crash-recovery mechanisms for this delivery.

These are consistency obligations, not a request for a new transaction subsystem. If a particular write route cannot yet maintain the index, reject that route before mutation and record the limitation; do not silently disable all existing relational writes or treat broken spatial writes as complete.

### 3.3 Correctness rules that remain mandatory

1. Use metres for radius comparisons. Do not compare kilometre inputs with degrees or mix latitude/longitude order.
2. Apply exact distance checks after candidate pruning. Preserve strict `<` versus inclusive `<=` semantics.
3. Test actual polygon membership; an MBR match alone is insufficient.
4. Compute exact k-NN under the selected metric. Do not rank by Euclidean distance and assume the Haversine ranking is identical.
5. Keep different records at the same location. Use stable IDs/RIDs to track results and define a repeatable tie policy.
6. Return complete engine results independently of how many markers the map can display.
7. Use the existing query/session lifecycle, resource cleanup and cancellation points where available.
8. Compare indexed answers against exhaustive answers on small known cases and seeded datasets.

## 4. Execution plan: five delivery blocks

Blocks E1–E5 replace the previous P2.0–P2.10 completion sequence. These identifiers are local to this revision and do not renumber Part 1 stages. No separate phase documents or approval round is required for each task once implementation is requested.

### E1 — Fix the integration path and prepare the data

**Objective:** Establish one working foundation quickly and start the experimental setup early.

**Tasks**

- **E1.1:** Inspect current main and the existing spatial work, if any. Record the commit, selected owner path, data-loading entry and remaining Part 1 tasks in one short checklist. Run the relevant existing smoke tests.
- **E1.2:** Adopt the conventions in section 3: coordinate mapping, supported area, point identity, polygon boundary and metric selection. Preserve any compatible completed implementation.
- **E1.3:** Define a small fixture, for example `id,nombre,latitud,longitud`, with asymmetric coordinates, repeated locations, known neighbors and points inside/outside a concave polygon. Register it through the selected owner.
- **E1.4:** Create a seeded generator for 1,000, 10,000 and 100,000 points, plus 100 fixed query centers. Make it usable by both the mini-DBMS and PostgreSQL.
- **E1.5:** Start the PostgreSQL/GiST comparator setup and outstanding Part 1 experiments immediately as a separate team workstream. Do not wait for the map.

**Done when:** a fixture loads and reopens, its coordinate pair is discoverable, the application path is known, and benchmark data/setup commands are reproducible.

### E2 — Implement the spatial engine

**Objective:** Deliver the actual algorithms with correct answers and simple persistence.

**Tasks**

- **E2.1 — Geometry and metrics:** implement point validation, MBR operations, Euclidean distance, Haversine and point-in-polygon with boundary handling. Keep these functions independent of HTTP and frontend code.
- **E2.2 — Exhaustive baseline:** scan stored points for radius/polygon queries and rank by distance for k-NN. Use this as both the required sequential comparator and the correctness reference.
- **E2.3 — R-Tree:** implement leaf/internal entries, subtree selection by enlargement, insertion, split propagation and root growth. Use a documented capacity/occupancy rule. Validate parent coverage, balanced leaf depth and entry counts.
- **E2.4 — Searches:** implement MBR traversal, exact radius filtering, exact polygon filtering and k-NN traversal using valid metric bounds. Resolve returned RIDs through existing storage.
- **E2.5 — Lifecycle:** implement build, save, open, basic validation and index maintenance. Use the simple deletion/rebuild strategy when appropriate, and reuse the existing rollback/reopen lifecycle.
- **E2.6 — Tests:** compare the tree with exhaustive results after build, INSERT, DELETE, rollback and clean reopen. Cover empty data, duplicates, no matches, boundary points and a multi-level tree.

**Distance implementation guidance**

Haversine uses a documented spherical radius, radians internally and numerical clamping. For local Euclidean distance, use a fixed local plane in metres, for example:

`x = R * cos(phi0) * (lambda - lambda0)`

`y = R * (phi - phi0)`

Angles are radians, and the origin is fixed in the dataset metadata. Euclidean distance is measured in that plane; it is an approximation of local Earth-surface distance. It must not be presented as another exact geodesic formula.

For Haversine tree pruning, use a proven conservative bound. A simple safe starting bound is `R * delta_phi`, where `delta_phi` is the angular gap between the query latitude and the node's latitude interval, or zero inside that interval. It can prune poorly but cannot discard a closer point. Improve it only if needed after obtaining a correct working implementation. A point-to-planar-MBR distance in degrees is not a valid substitute for a spherical bound in metres.

For k-NN, process promising nodes using a priority queue, retain the best k candidates, and stop only when unexplored bounds cannot improve the result under the tie policy. Count actual visited nodes/candidates so the R-Tree path cannot accidentally be a full scan mislabeled as indexed search. Exact exhaustive fallback is acceptable for valid query shapes without an optimization, but not as the only implementation of indexed radius/k-NN.

**Done when:** all three spatial query families return correct results, both metrics work, and saved data/index state survives the tested lifecycle. The implementation does not depend on a third-party R-Tree or spatial-query engine.

### E3 — Connect spatial SQL and the map

**Objective:** Produce one complete user workflow using the existing application.

**Tasks**

- **E3.1 — Manual parsing/binding:** add POINT construction, the registered logical location reference, `distancia`, distance ordering and LIMIT. Keep changes narrow; no general-purpose function/plugin system is needed. Retain one complete statement, optional final semicolon and `--` comments.
- **E3.2 — Query context:** provide `mi_ubicacion` as a typed point supplied with the request or selected in the UI. Freeze it for that execution; report a missing value or ambiguous name. Do not interpolate raw coordinate text into SQL.
- **E3.3 — Planning/execution:** recognize the required radius and nearest-neighbor shapes and select the ready R-Tree. Preserve exact residual filtering and existing scalar behavior. Additional filters must be applied before final top-k selection; unsupported combinations get an explicit error or a correct scan plan.
- **E3.4 — API:** send results and spatial metadata through the existing API/session owner. Include actual access method, metric, units and execution metrics already available. Preserve existing EXPLAIN/ANALYZE behavior where exposed; a truthful basic spatial plan description is enough.
- **E3.5 — Polygon entry:** provide one simple route, such as predefined polygon selection through a typed API request invoking the engine under the existing session lifecycle. A polygon drawing editor and a polygon SQL language are not required.
- **E3.6 — Map:** add an interactive map panel, center/radius/k inputs, a metric selector and polygon selector. Display stored points, highlight returned identities and show matching rows. Keep the existing four panels usable.
- **E3.7 — Usability checks:** show loading, validation errors, no results and cancellation outcomes. For large datasets, render a clearly labeled bounded preview plus query results; never claim the preview is the whole dataset. Coordinate validation and bounds must be visible in documentation.

**Mandatory SQL acceptance: submit each example individually**

```sql
-- Radius query. POINT arguments are latitude, longitude.
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

```sql
-- The request provides mi_ubicacion as a typed point.
SELECT * FROM restaurantes
ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
```

Use Haversine for the two-argument `distancia` form. A small optional third argument such as `'euclidean'` can select the other metric; document and test the chosen syntax. A general `CREATE TABLE ... POINT` or `CREATE INDEX ... USING RTREE` extension is unnecessary if setup/loading already creates and registers spatial tables correctly.

**Done when:** the two example statements execute from the editor, a polygon query executes from the application, highlights match engine results, and restarting the application preserves the prepared data and usable index.

### E4 — Complete the required experiments

**Objective:** Produce the empirical evidence required for both the spatial delivery and unfinished Part 1 work.

**Tasks**

- **E4.1:** Run equivalent sequential, own-R-Tree and PostgreSQL GiST queries on the same generated records and query centers. Choose access methods explicitly in the harness and record the method actually used.
- **E4.2:** Verify results before timing. Compare identities and distances, not just counts; handle tied k-NN boundary distances consistently.
- **E4.3:** Run every configuration in section 5. Save raw samples and resource measurements. A slow or failing configuration is a finding to resolve/report, not a row to omit.
- **E4.4:** Generate comparison graphs and the required summary table from saved measurements. Explain when construction overhead, selectivity and dataset size favor each method; do not assume the R-Tree wins every query.
- **E4.5:** Finish the Part 1 Stage 10 comparisons from the original assignment: Heap vs Sequential; clustered B+ vs unclustered B+ vs Hash; their stated operations and metrics. Keep their tables and conclusions separate from Part 2.

**Done when:** all required configurations have real evidence, figures can be regenerated, and the report contains both Part 1 and Part 2 results.

### E5 — Verify and package the delivery

**Objective:** Deliver a usable system and an accurate report, not just individually working components.

**Tasks**

- **E5.1:** Run the focused acceptance matrix in section 6, affected regressions and the repository's required final test/build commands. Record actual results for the delivered commit; fix regressions caused by this work.
- **E5.2:** Verify a clean setup/reopen demonstration: load the fixture, run radius/k-NN/polygon queries, select both metrics, inspect the map and show one committed change and one rollback.
- **E5.3:** Apply the concise documentation updates in section 7. Explain the algorithms, data domain, simplifications and measurements in the Spanish LaTeX report.
- **E5.4:** Prepare the README/runbook and the assignment's 5–10-minute demo video. Final whole-project presentation preparation is deferred to its scheduled milestone.
- **E5.5:** Check the original requirements for Parts 1 and 2. Close remaining Stage 9/10 items with evidence where still pending. List any unmet requirement honestly; a good-looking map cannot substitute for it.

**Done when:** another team member can reproduce the delivered workflow from the documented commands, with no manual repair or hidden local data dependency.

## 5. Minimum experiment protocol

| Dimension | Required delivery values |
|---|---|
| Methods | Sequential search; own R-Tree; PostgreSQL GiST |
| Dataset size | 1,000; 10,000; 100,000 points |
| Radius | 1 km; 5 km; 10 km |
| k | 10; 50; 100 |
| Query sample | 100 seeded query centers per setting; same inputs for comparable methods |
| Main metric | Haversine, with equivalent spherical semantics across methods |
| Measurements | Index build time; mean query time; memory consumption; data/index disk space |
| Outputs | Raw CSV/JSON, graphs, interpretation table and reproducible commands |

This gives **54 method/size/query-setting configurations and 5,400 timed query executions** for one full metric matrix. Build and space measurements are taken per applicable method/dataset, not repeated unnecessarily for every radius or k. The sequential method has no index-build cost; mark it N/A.

Both metrics remain required functionality. The assignment does not explicitly prescribe repeating the entire performance matrix for both. This plan therefore uses Haversine for the full comparison and a smaller set of Euclidean correctness/demonstration runs, labeled as such. Do not omit either metric's implementation.

### Measurement rules

1. Prepare PostgreSQL/GiST on day one. Match spherical distance, coordinate order, units and boundary semantics to the engine; check the installed comparator's documentation and representative plans. Do not mix spheroidal distance with Haversine or call a sequential PostgreSQL plan a GiST query.
2. For strict radius queries, ensure both methods apply the same strict final predicate even if their candidate filters are inclusive. Use the same stable IDs for correctness comparison.
3. Measure build separately from initial data loading, index loading after restart, query execution and rendering. Document whether build includes serialization/flush; include it consistently when reporting a ready persistent index.
4. Time complete query execution and result consumption with a monotonic clock. Exclude map rendering. If client transport is included for PostgreSQL, disclose it and use comparable boundaries or label the measurements distinctly.
5. Use one documented warmup/cache policy; do not attempt a complex cold-cache experiment under this deadline. Retain each of the 100 elapsed times and report their arithmetic mean. Percentiles and extra repeated matrices are optional.
6. Measure actual base and index file sizes. Record memory using a stated process/server measurement procedure and sampling interval. Distinguish peak process memory, incremental estimates and database shared buffers; do not equate Python-only allocations with total PostgreSQL memory.
7. Save the environment, commit, dataset seed and commands. At minimum, raw query rows contain method, metric, N, radius/k, query ID, elapsed time, result count and validation outcome.
8. Produce range and k-NN timing graphs, index construction/space summaries and a short comparison table. Polygon correctness must be demonstrated; a separate polygon performance matrix is optional.

## 6. Focused acceptance tests

Implement these meaningful checks rather than a large new testing framework. Reuse existing test helpers.

| Check | Expected result |
|---|---|
| Empty dataset, no matches, k>N | Valid empty/short results; no crashes |
| Known points and duplicate coordinates | Correct distances; separate records retained |
| Radius boundary | Strict and inclusive predicates behave as specified |
| Simple concave polygon and boundary points | Exact membership; points only in its MBR are excluded |
| Multi-level R-Tree on seeded points | Same radius/polygon sets and nearest-neighbor results as exhaustive search |
| Euclidean vs Haversine | Each matches its own reference cases and declared units; do not expect identical rankings |
| Invalid/out-of-domain point, negative radius/k | Clear controlled error before data mutation |
| Required SQL with comments | Correct execution from the public entry; second statements still rejected |
| INSERT/DELETE and transaction rollback | Base rows, tree associations and reopened state agree |
| Clean restart | Records, mapping and usable R-Tree are recovered |
| API/map | Returned identities match highlighted points; axis order is correct |
| Largest required dataset | Load/build/query completes under documented available resources |
| Part 1 regression | Existing relational queries, indexes, sessions and panels still work |

For k-NN with equal distances, document a tie policy. Use a stable secondary ID internally, or validate any mathematically valid tied subset when the external system has a different unspecified ordering. Never report a farther point while omitting a strictly nearer one.

## 7. Documentation changes required

Update documentation while implementing, using concise additions. Do not create a separate audit document for every task.

| Document | Minimum update |
|---|---|
| `PLAN_PARTE_02.md` | Track these five blocks and acceptance evidence; this revision supersedes the earlier broad scope |
| `PROJECT_CONTEXT.md` | Actual coordinate/metric conventions, representation, selected owner path, persistence and supported limits |
| `REQUIREMENTS.md` | Separate Part 2 requirements from project choices; transcribe §2.2 accurately |
| `AGENTS.md` and `PLAN.md` | Link the active plan and preserve truthful Part 1 status |
| SQL guide/grammar | Spatial expressions, logical `ubicacion`, `mi_ubicacion`, metric selection and LIMIT |
| `README.md` / demo guide | Setup, loading, startup, sample queries, map, comparator and benchmark commands |
| Report | Design, algorithms, experiments, graphs, interpretation and limitations |

Existing closed stage plans/audits remain historical evidence. Add a short link or correction only where a statement otherwise contradicts current behavior. No rewrite of all stage documents is required. The documentation must not continue declaring eleven phases or dual-owner support mandatory for this reduced delivery.

## 8. Two-day coordination and checkpoints

Treat these as planning targets, not a promise that unknown implementation work fits into a fixed number of hours. They describe elapsed team time, with workstreams overlapping.

| Target window | Engine/application work | Parallel experiments/documentation |
|---|---|---|
| First 1–2 hours | E1: inspect, select one path, freeze conventions | Start PostgreSQL/GiST, fixtures and remaining Part 1 runs |
| First working day | E2: correct engine; E3: begin SQL/API integration | Prepare harness, obtain preliminary data and draft report structure |
| By the start of day two | One complete spatial SQL-to-map workflow; then finish missing required query families | Run required matrix on the integrated engine; populate actual result tables |
| Middle of day two | Feature freeze; fix correctness, reopen and integration defects | Finish experiments and figures; synchronize docs |
| Final 6–8 hours | Regression/build, clean demo rehearsal and fixes | Final report, video and delivery buffer |

Suggested team ownership: one person for spatial core, one for SQL/API/map, and one for experiments/report if team size allows. Agree on point/result/context contracts first; do not have everyone editing the parser or owner independently. These are suggested human workstreams, not a requirement to launch automated agents.

**If behind schedule:** remove optional UI polish, extra query syntax, duplicate integration paths and additional experiment repetitions first. Do not remove polygon queries, a distance metric, PostgreSQL GiST, a required dataset size or the Part 1 experiments and still describe the delivery as complete.

## 9. Explicitly deferred work

The following are outside this deadline unless already implemented and stable:

- New persistent POINT DDL throughout all storage formats; a generic CRS/geometry type system.
- Mandatory spatial support in both managed and GUI owner paths, or every storage organization.
- A new buffer pool, sophisticated R-Tree page reclamation, online format migration, WAL or crash recovery.
- CondenseTree and optimized online deletion when correct rebuilding is sufficient.
- Global GIS optimizations, antimeridian/polar handling beyond the declared local domain, polygons with holes and general spatial joins.
- Generic SQL scalar-function extensibility, general polygon literals, new SQL index-management commands and multi-statement scripts.
- GUI coordinate-mapping/import wizards, polygon drawing, browser geolocation, offline tiles and advanced map clustering.
- Disk spilling for the nearest-neighbor frontier unless required to complete the prescribed datasets; no silent memory failure is acceptable.
- A second full metric matrix, multiple distribution studies, polygon timing studies and elaborate cache experiments.
- New per-task approval processes, separate phase files, exhaustive migration/failure frameworks and preparation of the final whole-project presentation.

## 10. Delivery checklist

- [x] Own R-Tree actually performs indexed spatial traversal.
- [x] Radius, exact k-NN and polygon intersection work on stored points.
- [x] Euclidean and Haversine are implemented with explicit units and scope.
- [ ] Both assignment SQL examples execute one at a time through the application.
- [ ] The map is interactive and highlights the engine's actual results.
- [x] Data/index reopening and exposed mutation/rollback paths are consistent.
- [x] Relevant correctness and Part 1 regression checks pass (E2 full suite;
  final E3–E5 delivery must rerun affected checks).
- [ ] All required sizes, radii and k values have sequential/R-Tree/GiST measurements.
- [ ] Query averages use 100 queries; build, memory and disk measurements are included.
- [ ] Graphs, summary table, report, README and demo are reproducible and accurate.
- [x] Outstanding Part 1 requirements, including Stage 10, are completed for the combined delivery
  (Stage 10 closed 2026-10-04, `../docs/ETAPA_10_AUDIT.md`).

**Implementation instruction:** Read the repository instructions and this revision, inspect the current implementation, then execute E1–E5 in small working increments. Reuse completed components and the selected application path. Keep optional items deferred and maintain a short progress checklist. Resolve routine choices using the defaults above; ask only about an actual blocker or material conflict. Completion is defined by the assignment coverage and demonstrated behavior, not by the size of the architecture.
