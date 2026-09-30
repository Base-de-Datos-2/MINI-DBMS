# PLAN_PARTE_02.md — Spatial Database: Coordinates and Maps

**Status:** Advance implementation plan; no Part 2 implementation or closure is claimed.
**Reviewed:** 2026-09-30.
**Repository:** https://github.com/Base-de-Datos-2/MINI-DBMS
**Baseline:** `main` at `14c2dc99b8ac5df09cfe713398420e89dcfd1df7`.
**Academic source:** `Proyecto_Final.pdf`, section 2.2, physical page 3; delivery requirements in sections 3–4, physical page 5.
**Language:** English, consistent with the project's coordination documents.

## 1. Purpose and authority

Extend the existing mini-DBMS with persistent geographic points, an original R-Tree, exact spatial queries, spatial SQL, an interactive map, and the required experimental comparison. Reuse the completed storage, index-management, operator, handwritten SQL, and transaction layers.

This is a roadmap for Part 2. It does not replace `PLAN.md`, close Stage 9, or waive Stage 10. It also does not authorize code implementation merely by existing. Phase identifiers use **P2.0–P2.10** to avoid colliding with the ten Part 1 stages.

Documentation responsibilities remain:

| Document | Responsibility |
|---|---|
| `Proyecto_Final.pdf` | Original academic assignment, including Part 2 |
| `REQUIREMENTS.md` | Academic requirements transcribed from the assignment; currently concentrated on Part 1 |
| `PROJECT_CONTEXT.md` | Accepted architecture and verified current state |
| `PLAN.md` | Part 1 roadmap, including its pending closure work |
| `PLAN_PARTE_02.md` | Part 2 sequence, dependencies, deliverables, and acceptance gates |
| Future `PARTE_02_FASE_XX.md` files | Detailed work for the next authorized Part 2 phase, if needed |
| `AGENTS.md` | Repository operating instructions |

The requirement IDs below are planning references, not new academic obligations. Recommended choices are explicitly identified and must be recorded as accepted decisions before implementation. If a transcription conflicts with the assignment, resolve the discrepancy rather than silently implementing the weaker version.

## 2. Findings from current `main`

### 2.1 Existing foundation and actual gaps

| Area | Evidence in the reviewed commit | Consequence for Part 2 |
|---|---|---|
| Part 1 status | `PLAN.md`, `AGENTS.md`, and `PROJECT_CONTEXT.md`: Stage 8 closed; Stage 9 HTTP/session integration implemented; Stage 9 formal closure and Stage 10 pending | Keep these outstanding items visible throughout Part 2 planning |
| Persistent storage | `engine/storage/`: Heap, Paged Sequential, records, RIDs, page manager; `binary.py` fixes 4,096-byte pages | Reuse storage contracts and page geometry; do not design an independent in-memory spatial database |
| Types | `engine/catalog/types.py`: INTEGER, FLOAT, BOOLEAN, VARCHAR | POINT requires explicit logical validation, encoding, schema support, and result serialization |
| Indexes | `engine/catalog/metadata.py`, `engine/indexes/index_catalog.py`: BPLUS and EXTENDIBLE_HASH | Add RTREE deliberately to metadata, runtime dispatch, maintenance, reopening, and validation |
| Index interfaces | `engine/indexes/base.py`: scalar key/RID operations; `OrderedIndex` means scalar ordering | Add spatial capabilities without claiming that R-Tree traversal provides SQL scalar order |
| Relational operators | Scans, filtering, projection, joins, aggregation, external sorting and query budgets in `engine/operators/` | Build spatial access operators and reuse existing composition/resource management |
| SQL | Handwritten lexer and recursive-descent parser; `ast.py` has aggregate calls but no general scalar function node or SELECT limit | Extend lexer/parser/AST/binder/planner/executor together; retain the manual parser |
| Managed database | `engine/database/manifest.py`: strict version 1, INTEGER/VARCHAR SQL tables, Heap storage and B+ primary-key indexes | Spatial schema/index discovery requires a compatible format and owner extension |
| GUI database path | `api/database.py`, `api/gui_tables.py`: separate persistent GUI definitions, Heap/Sequential and B+/Hash support | Cover both ownership paths explicitly; a manifest-only change would not enable the existing demo UI |
| Transactions | `engine/transactions/`: table S/X locks, schema gate, registered physical file sets, bounded before-image undo and runtime reopen | R-Tree files and handles must participate in this lifecycle |
| API/frontend | Session-aware API and four existing panels, with read-only mode, cancellation and truthful transaction outcomes | Add the map and spatial values through existing sessions; preserve all four panels |
| Current correction | `docs/ETAPA_09_REVISION_2026_09_30.md`: failed undo is `ABORT_FAILED`, quarantines the owner, and must not be described as successful rollback | Spatial errors must preserve this behavior |
| Requirements document | `REQUIREMENTS.md` mentions spatial features as future work, but does not detail section 2.2 | Add a clearly separated Part 2 requirements section before implementation |

### 2.2 Verification performed for this plan

The review inspected the pinned code and current coordination/audit documents, read the assignment, and consulted the spatial course material. A direct `parse_sql` smoke check against this commit produced:

| Input | Observed result |
|---|---|
| Existing `SELECT ... WHERE nota >= 14 ORDER BY id` | Accepted as `SelectStatement` |
| Existing `EXPLAIN ANALYZE SELECT ...` | Accepted as `ExplainStatement` |
| Assignment radius query using `distancia(..., POINT(...))` | Rejected at the function-call opening parenthesis |
| Assignment k-NN query using `distancia(..., mi_ubicacion) LIMIT 10` | Rejected at the function-call opening parenthesis |
| Plain `SELECT * FROM alumnos LIMIT 10` | Explicitly rejected as unsupported |
| `CREATE TABLE ... ubicacion POINT` | Explicitly rejected as an unsupported CREATE type |

These are parser checks, not an end-to-end execution audit. No complete test suite was rerun for this document: the review's Python environment did not have `pytest` installed. Repository audit results are historical evidence, not fresh results from this review. For example, the September 30 revision records 246 API/transaction tests and 32 frontend tests; it explicitly does not claim a full-suite rerun.

### 2.3 Relationship with unfinished Part 1 work

1. **Now:** approve the Part 2 scope, data model, experiment design, and integration contracts; prepare deterministic dataset specifications. These activities do not require Stage 10 to be complete.
2. **Before implementation:** refresh the baseline, establish a passing relevant regression baseline, and explicitly authorize the next Part 2 phase. Isolate Part 2 changes from ongoing Stage 10 work.
3. **Before changing benchmark-sensitive foundations:** preserve the Part 1 baseline commit, fixture checksums, environment, and benchmark procedure so later spatial changes cannot invalidate the Part 1 comparison.
4. **Preferred sequence:** formally close Stage 9 and complete Stage 10 while Part 2 design proceeds. If implementation overlaps, keep two separately tracked workstreams and resolve shared-file dependencies before merging.
5. **Before declaring the partial delivery complete:** close Stage 9, finish Stage 10, and satisfy every Part 2 acceptance item. The assignment's week-8 milestone requires both Parts 1 and 2; it does not excuse Part 1 experiments.

## 3. Assignment traceability

| ID | Required by `Proyecto_Final.pdf` | Planned coverage | Acceptance evidence |
|---|---|---|---|
| S2-01 | Own R-Tree for 2D geographic points (latitude, longitude), §2.2.1 | P2.1–P2.4 | Original paged implementation, structural validator, reopen tests |
| S2-02 | Range search, including a radius query | P2.2, P2.5–P2.7 | Exact results match exhaustive distance filtering |
| S2-03 | k nearest neighbors | P2.5–P2.7 | Ordered results match exhaustive ranking, including ties and duplicates |
| S2-04 | Intersection with polygons, e.g. points inside a district | P2.2, P2.5, P2.7–P2.8 | MBR filtering plus exact point-in-polygon tests, boundary cases |
| S2-05 | Both Euclidean and geodesic/Haversine distances | P2.1–P2.2, P2.5, P2.9 | Explicit metric/units, independent reference cases, differential tests |
| S2-06 | Interactive map showing points and highlighted spatial results, §2.2.2 | P2.7–P2.8 | Browser demonstration connected to actual engine results |
| S2-07 | Spatial SQL, including both printed examples, §2.2.3 | P2.6–P2.7 | Exact example statements execute individually through the public SQL entry |
| S2-08 | Sequential scan vs own R-Tree vs PostgreSQL GiST, §2.2.4 | P2.9 | Reproducible runs, raw measurements, verified access plans |
| S2-09 | Radii 1/5/10 km; k=10/50/100; N=1,000/10,000/100,000 | P2.9 | Complete parameter matrix with no omitted slow configurations |
| S2-10 | Construction time; mean query time over 100 queries; memory/disk use | P2.9 | Measurement definitions, raw samples, aggregate tables |
| S2-11 | Comparative graphs and a table explaining when to use each technique | P2.9–P2.10 | Exportable figures and conclusions supported by observed results |
| S2-12 | Incremental repository, README, report and demonstration deliverables, §§3–4 | P2.10 | Updated artifacts and a reproducible demo runbook |

An R-Tree stored on disk, its mutation/undo integration, and the exact internal POINT encoding are project architecture choices needed to extend this repository coherently. Section 2.2 does not prescribe a binary layout, split algorithm, particular map library, or SQL syntax for polygons/index creation.

## 4. Scope and proposed architecture

### 4.1 Target data and supported behavior

- Store geographic **points** as typed values in ordinary records. Recommended first spatial table organization: Heap with stable RIDs and an unclustered R-Tree over one POINT column.
- Preserve other scalar columns and existing B+/Hash indexes on them. Different records may share the same location.
- Support exact radius, rectangle, k-NN, and point/polygon intersection queries. Rectangles are an implementation primitive as well as a useful diagnostic query.
- Keep SELECT, INSERT, DELETE, EXPLAIN, EXPLAIN ANALYZE, and transaction controls working through owner-created sessions.
- Treat polygons as query-region values initially. The assignment does not require a general geometry database, persistent route geometries, spatial joins, routing, geocoding, or arbitrary polygon-to-polygon topology.
- Preserve one complete SQL statement per submission, optional final semicolon, and existing `--` comment behavior. Multi-statement scripts remain outside scope.
- Do not introduce Lark, another parser generator, or a database/spatial-index library that performs the assigned R-Tree or search algorithms. PostgreSQL/PostGIS belongs only in the external benchmark adapter.

### 4.2 Proposed module boundaries

Names are suggestions to adapt to existing modules, not instructions to create empty files.

| Layer | Proposed responsibilities |
|---|---|
| `engine/spatial/` | Immutable point/rectangle/polygon-query values, validation, metrics, exact geometric predicates and conservative bounds |
| `engine/storage/` and `engine/catalog/` | POINT records/codecs/schema metadata, RTREE metadata, format compatibility |
| `engine/indexes/rtree_*.py` | Node/header codecs, paged I/O, insertion/deletion, structural validation, spatial search, Catalog adapter |
| `engine/operators/` | Spatial scan, exact residual evaluation, distance expressions, LIMIT/top-k integration, budgets and statistics |
| `engine/query/` | Manual spatial grammar, AST, binding, planning, explanation and execution integration |
| `engine/database/`, `engine/maintenance/`, `engine/transactions/` | Persistent discovery, index maintenance, file ownership, undo/reopen, locks, cancellation |
| `api/` and `frontend/src/` | Typed spatial payloads, per-request query context, import, map interactions and result highlighting |
| `benchmarks/spatial/`, `tests/spatial/`, `docs/` | Dataset generation, correctness oracles, comparative measurements, decisions and delivery evidence |

The geometry/metric layer must not depend on HTTP or map components. The frontend renders results; it does not choose membership or substitute browser distance calculations for engine queries.

### 4.3 Decisions to freeze in P2.1

| Topic | Recommended starting decision | Required clarification |
|---|---|---|
| SQL point convention | `POINT(latitude, longitude)`, matching the assignment example | GeoJSON/PostGIS adapters explicitly convert to longitude,latitude |
| Internal rectangle axes | x=longitude, y=latitude | Name coordinates explicitly; never infer tuple order |
| POINT binary representation | Two finite float64 components using the existing explicit byte order | Preserve old record schemas; document new schema/type tags and version handling |
| Coordinate validation | Latitude in [-90,90]; documented longitude normalization; reject NaN/infinity | Canonicalize equivalent representations consistently for equality/index maintenance |
| Default distance | `distancia(a,b)` uses Haversine and returns metres | Freeze Earth radius, numerical tolerance, and strict/inclusive radius behavior |
| Euclidean mode | A documented local Cartesian coordinate system measured in metres | Freeze projection/domain once per dataset; do not label raw degrees as kilometres |
| Polygon semantics | Simple closed rings in a documented local, non-wrapping domain; include boundary points | State whether holes are supported; reject unsupported regions explicitly |
| R-Tree | Original Guttman-style tree; quadratic split as the initial recommendation | Derive capacity from actual bytes, fix occupancy and deterministic tie rules |
| Base file | Heap for the first spatial release | Do not advertise R-Tree on RID-relocating organizations until maintenance is verified |
| Index creation | Owner-mediated build/registration operation plus a reproducible setup/import route | General `CREATE INDEX` SQL is optional, not a hidden prerequisite of the assignment |
| Persistence owners | Add explicit spatial support to both managed and GUI discovery paths through shared engine services | Do not silently replace the GUI owner and lose Sequential/Hash support |
| Query variables | Typed, immutable execution binding for `mi_ubicacion` | Define missing-binding and column-name collision behavior |

For Euclidean mode, one implementable proposal is a fixed local equirectangular plane: `x = R*cos(phi0)*(lambda-lambda0)` and `y = R*(phi-phi0)`, with angles in radians, a persisted origin, and a bounded non-wrapping operating region. Euclidean distance is then the ordinary distance in this plane; it is not an exact Earth-surface distance. Its affine transform allows conservative rectangle bounds. A suitable projected CRS is another valid choice. Choose one, document its domain, and feed identical x/y values to the external comparator.

Haversine models distance on a **sphere**, not ellipsoidal geodesics. This distinction must remain explicit even though the assignment groups it under geodesic distance.

## 5. Roadmap and dependencies

| Phase | Outcome | Depends on |
|---|---|---|
| P2.0 | Repository baseline, requirement mapping, and Part 1 coordination | Current review |
| P2.1 | Accepted spatial and persistence contracts | P2.0 |
| P2.2 | Typed points, metrics, polygon predicates, exhaustive oracle | P2.1 |
| P2.3 | Persistent R-Tree core and mutation invariants | P2.2 |
| P2.4 | Catalog, owner, maintenance and transaction integration | P2.3 |
| P2.5 | Exact spatial operators and bounded execution | P2.2–P2.4 |
| P2.6 | Spatial SQL parsing, binding and physical planning | P2.1–P2.2; final execution depends on P2.5 |
| P2.7 | Public execution/API and spatial import | P2.4–P2.6 |
| P2.8 | Interactive map and end-to-end demonstration | P2.7 |
| P2.9 | Required comparative experiments | Methodology starts in P2.1; measured runs require stable P2.5–P2.7 |
| P2.10 | Documentation, audit and Part 2 closure | P2.8–P2.9 and Part 1 delivery gates |

Contracts, dataset design and parser fixtures can be prepared in parallel with index design. A mock map can validate layout early, but cannot count as completed spatial functionality. Do not integrate a writable spatial table before its file ownership and rollback behavior are complete.

## 6. Phase tasks

### P2.0 — Establish the baseline and preserve Part 1 obligations

**Tasks**

1. Refresh `main`; inspect `AGENTS.md`, requirements, context, Part 1 plan and current Stage 8/9 evidence. Record the actual starting SHA and working-tree state.
2. Inventory existing type dispatches, codecs, index factories, owner registries, mutation services, transaction resources, query result variants and API limits. Turn the gaps in section 2 into an implementation checklist.
3. Record Stage 9 closure and Stage 10 as separate outstanding work. Preserve a reproducible Part 1 benchmark baseline before changing shared formats or execution paths.
4. Establish relevant test commands/environment; run affected baseline tests before implementation. Report failures rather than attributing historical test counts to the current environment.
5. Add Part 2 academic requirement traceability and identify proposed architecture decisions separately.

**Deliverables:** baseline inspection note, requirements matrix, shared-file dependency list, Part 1/Part 2 status table.

**Exit gate:** the team can identify what is implemented, what remains in Part 1, and which Part 2 work is authorized next. No earlier stage is marked complete by inference.

### P2.1 — Freeze contracts, coordinate semantics and experimental design

**Tasks**

1. Resolve all decisions in section 4.3, including ownership, schema compatibility, coordinate order, metrics, polygon domain, duplicate points, tie rules, and index capabilities.
2. Define a `SpatialIndex` contract with equality/key-RID maintenance plus rectangle, radius, and nearest-neighbor operations. Preserve existing `Index` integration or introduce an explicit compatible adapter; do not force spatial range into `OrderedIndex.range_search`.
3. Define closable iterators, returned row identity, result ordering, empty-result behavior, invalid-argument errors, cancellation, and index readiness.
4. Specify metric-aware lower bounds and conservative candidate envelopes. Require proof or an independently verified derivation before a bound can discard a subtree.
5. Define persistent index metadata: format version, coordinate/metric configuration where applicable, root page, height, counts, node capacity/occupancy and free-page policy. Distinguish immutable configuration from mutable statistics.
6. Freeze benchmark fixtures, seeds, query centers, radius/k values, metric equivalence and measurement boundaries before optimizing.

**Tests/design checks:** trace every requirement to a public entry point; walk through a duplicate location, a root split, a rolled-back split, a query near the date line, and the two required SQL examples.

**Exit gate:** a short accepted architecture decision document is sufficient to implement one compatible system without inventing per-module conventions.

### P2.2 — Implement spatial values and a correct exhaustive baseline

**Tasks**

1. Add immutable POINT values and validation to Catalog/Schema/Record and the value/record codecs. Cover temporary-run codecs, row footprint estimation, copying and result schemas wherever records can pass.
2. Add schema persistence support and backward-compatible reading of existing databases. Bump only formats whose contracts change; never reinterpret existing v1 bytes silently. Define explicit migration/refusal for unsupported versions.
3. Implement rectangles: containment, overlap, union, area/enlargement and point envelope. Reject inverted/non-finite bounds and document edge inclusion.
4. Implement Haversine with degree-to-radian conversion, a fixed documented radius, and numerical clamping. Implement the chosen Euclidean coordinate conversion and distance independently.
5. Implement exact point-in-polygon behavior for the supported domain, including point-on-edge/vertex, concave rings, orientation and malformed rings. Reject self-intersections or unsupported holes instead of silently giving an ambiguous result.
6. Implement sequential radius, rectangle, polygon and k-NN reference operations over persisted records. Use a bounded top-k structure for k-NN, with explicit deterministic ties.
7. Create seeded fixtures with dense clusters, uniform points, duplicate locations, empty tables, known inside/outside/boundary points and invalid coordinates.

**Tests:** binary round trips and truncation; actual close/reopen; known distances including identical/near-antipodal points; coordinate-order mistakes; concave polygons; k=0 policy, negative/non-integer k, k>N, duplicate distances; independent expected results rather than only comparing two consumers of the same faulty helper.

**Exit gate:** persisted spatial records and exhaustive queries are correct before any R-Tree acceleration is trusted.

### P2.3 — Build the original persistent R-Tree

**Tasks**

1. Implement validated file/node headers and codecs. Leaf entries identify points and RIDs; internal entries contain child-page IDs and covering MBRs. Derive separate leaf/internal capacities from encoded sizes and 4,096-byte pages.
2. Implement create/open/flush/close, root metadata, allocation and the adopted free-page policy using the established paged I/O approach. Keep actual I/O counters separate from logical node visits.
3. Implement insertion: subtree selection, leaf insertion, deterministic overflow split, redistribution, ancestor MBR adjustment and root growth. Persist every changed header/node.
4. Implement deletion by exact point/RID association, retaining other rows at identical coordinates. Implement underflow handling/CondenseTree, reinsertion at the correct tree level, ancestor MBR repair and root shrinkage.
5. Implement streaming build from existing Heap records, duplicate handling, failed-build cleanup and a readiness flag published only after successful validation.
6. Implement a structural validator: balanced leaf depth, occupancy exceptions for roots, parent coverage, valid page references, reachability, no cycles, no double ownership, correct counts and complete base-record association coverage.
7. Add close/reopen, randomized insert/delete, malformed-file, capacity-boundary and multi-level-tree tests. Force small test capacities only through a controlled compatible fixture mechanism.

**Exit gate:** the tree survives clean reopen, splits and deletion without losing or duplicating associations, and has a validator capable of detecting deliberately corrupted structures. Merely serializing an in-memory tree at shutdown is insufficient for the adopted paged architecture.

### P2.4 — Integrate persistence, maintenance and transactions

**Tasks**

1. Add RTREE metadata and capability dispatch in Catalog, index factories and `QueryEnvironment`. Equality on POINT must not accidentally grant scalar sorting, B+ range capabilities, or a spatial primary key.
2. Extend the managed manifest and GUI table registry deliberately. Persist definitions, opaque file identities, point schemas and spatial configuration; reopen through shared index builders/openers. Keep old databases readable under the adopted compatibility policy.
3. Provide owner-mediated table/index creation and streaming import/build. Use the schema gate, staged publication, compensating cleanup and generation invalidation; preserve the current refusal of unsupported schema changes inside explicit groups.
4. Integrate `MaintenanceService` insertion/deletion. All writes through SQL, API and import must maintain spatial associations or refuse the unsupported combination before changing data.
5. Register every R-Tree permanent file in `TableFiles`; extend runtime flush/close/reopen/validation and the bounded before-image undo lifecycle. Restore both base data and index state, including root changes and new pages.
6. Reuse table S/X locks and physical-handle protection. Keep read statements inside the owning session and transaction; ensure long searches/builds poll cancellation.
7. Cover failure during a split, index maintenance, commit publication and restoration. Preserve quarantine and `ABORT_FAILED`; do not claim automatic crash recovery.

**Tests:** INSERT/DELETE then ROLLBACK restores exact query results; committed changes survive reopen; two sessions correctly wait/release; cancelled search frees resources; failed restoration refuses later work; malformed or unready indexes cannot produce partial answers.

**Exit gate:** a spatial table can safely coexist with scalar indexes under the same ownership and in-process transaction guarantees as Part 1. No independent spatial file escapes snapshot, reopen or cleanup accounting.

### P2.5 — Implement exact spatial search operators

**Tasks**

1. Implement R-Tree rectangle traversal, pruning only disjoint MBRs and resolving candidates through the base file.
2. Implement radius search as conservative candidates followed by the selected exact distance predicate. Preserve the difference between `< radius` and `<= radius`.
3. Implement polygon search as MBR overlap followed by exact point-in-polygon evaluation. A point in a polygon's bounding rectangle is not automatically a match.
4. Implement best-first k-NN using a priority queue of admissible node bounds and bounded candidate storage. Continue through tied bounds as required by the deterministic tie policy; return exactly `min(k, qualifying_rows)` for a positive k.
5. Integrate ordinary relational predicates correctly. Apply filters before selecting the final k qualifying rows, or continue traversal until k qualifying neighbors are proven; never fetch k first and silently discard filtered rows afterward.
6. Handle Haversine envelopes across ±180° and near poles without false negatives. Split wrapped envelopes or use a conservative wider region. For unsupported optimized bounds, fall back to exact scanning and report that fallback.
7. Add spatial operator descriptors and actual counters: nodes/pages read, candidates examined, exact distance/polygon evaluations, returned rows, metric, execution time, budget use and cancellation.
8. Account for the k-NN frontier as well as candidate storage. Use existing query memory/handle budgets; spill if implemented or return a controlled resource error and close everything. Do not assume the frontier is always O(k).

**Correctness rule:** planar rectangle `MINDIST` in degrees cannot prune a Haversine search measured in metres. A latitude-only spherical lower bound can be a conservative initial implementation, but may prune poorly. Record that limitation and improve it only with proof and differential tests. A zero bound is correct but does not demonstrate effective spatial acceleration.

**Tests:** compare result identity/multiplicity and k-NN ordering with exhaustive results for both metrics; empty/all-identical/clustered datasets; broad radii; exact boundaries; date-line/polar Haversine cases; early iterator close; cancellation and budget exhaustion. Differential tests must include trees with several levels.

**Exit gate:** the index changes the access path without changing query meaning. Performance claims depend on later measurements, not the existence of a tree.

### P2.6 — Extend the handwritten SQL frontend and planner

**Tasks**

1. Update the EBNF specification, then the manual lexer/parser. Add POINT type/constructor, scalar function calls, nested function arguments, and an optional non-negative integer `LIMIT` after ORDER BY. Keep source spans, precedence, parser limits and single-statement rejection.
2. Introduce AST nodes for scalar calls and typed query bindings, distinct from aggregate calls; add SELECT limit without breaking existing AST consumers. Permit POINT construction in INSERT and supported expression positions.
3. Extend binding with explicit signatures: POINT accepts numeric coordinates; `distancia(POINT, POINT)` returns finite FLOAT metres. Local numeric-literal conversion for these functions must not silently relax all existing exact-type rules.
4. Support the assignment's bare `mi_ubicacion` through a documented typed execution context. Bind it immutably before planning; missing values are semantic errors. Define column-name precedence and reject ambiguous collisions clearly. No textual SQL interpolation or implicit browser geolocation is permitted.
5. Add an explicit way to select Euclidean/Haversine behavior. Recommended project syntax: optional third literal argument, e.g. `distancia(a,b,'euclidean')`; the two-argument assignment form retains its Haversine default. Persist/attach the required planar context.
6. Expose polygon queries through a bounded typed region binding, e.g. proposed `intersecta(ubicacion, mi_poligono) = TRUE`. This name/syntax is a project choice; general WKT/GeoJSON parsing in SQL is not required.
7. Extend bound expressions and physical plans for radius, polygon and nearest-neighbor access, exact residual filtering, computed ORDER BY expressions and LIMIT. Recognize eligible shapes conservatively; handle other valid shapes through exact sequential evaluation and sorting.
8. Maintain correct logical order: filtering before ranking/limit; projection must retain hidden fields needed to calculate distance/sort. Only elide a sort when the chosen operator guarantees the complete requested ordering. Guard reused plans against schema/runtime/context changes.
9. Extend EXPLAIN descriptors without executing rows; EXPLAIN ANALYZE must report one real execution using the same path, metric and context as the query.

**Mandatory SQL acceptance — submit each statement separately:**

```sql
-- Assignment radius example: POINT arguments are latitude, longitude.
SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000;
```

```sql
-- mi_ubicacion is a typed POINT provided in this execution's context.
SELECT * FROM restaurantes
ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10;
```

**Proposed setup statement, also executed separately:**

```sql
CREATE TABLE tiendas (
    id INT PRIMARY KEY,
    nombre VARCHAR(100),
    ubicacion POINT
);
```

Setup must also demonstrate an INSERT with a POINT and creation of a ready spatial index through the agreed owner API/setup route. The examples must work without an index via exact scans and with an eligible ready R-Tree via the planned access path.

**Tests:** both exact assignment statements, comments and negative decimals; unknown functions/arity/point types; unavailable context; invalid LIMIT; scalar calls versus aggregates; unsupported compound shapes with correct fallback; existing Part 1 syntax and multi-statement rejection.

**Exit gate:** parsing, binding, explanation and physical execution agree; accepting a token sequence alone does not complete spatial SQL.

### P2.7 — Expose spatial execution and import through the public API

**Tasks**

1. Extend result schemas/serialization with a named point encoding, coordinate convention, metric and distance units. Keep integer IDs lossless and support spatial values in ordinary table results and explanations.
2. Extend the query request with a bounded typed spatial context for selected map location and polygon, validated before engine binding. Keep it isolated per request/session; one user's location must not leak into another session.
3. Route queries through `SqlSession.execute` and existing policy/result dispatch. Preserve token ownership, read-only mode, single active call per token, error semantics, transaction state and cancellation.
4. Extend GUI table creation/import with explicit latitude/longitude column mapping, POINT validation and optional R-Tree selection. Use existing streaming and size limits; report invalid rows precisely and define all-or-nothing publication.
5. Ensure spatial definitions reopen in both supported owner paths. Make any route-specific restrictions explicit in the UI and tests rather than letting one path silently lose indexes.
6. Provide bounded map-data access using the same engine/session boundaries. State response truncation, pagination/sampling and total-count availability truthfully; distinguish display limits from SQL LIMIT.
7. Verify transaction outcomes for spatial changes across HTTP, including failed undo and unavailable owners. Keep engine/API timing separate from browser rendering time.

**Tests:** exact SQL through HTTP, typed point round-trip, importer axis errors, context isolation between two sessions, cancellation while waiting/searching, read-only refusal, reopen, and response limits without fabricated counts.

**Exit gate:** all data shown by the frontend comes from the actual engine; no route opens an independent spatial backend or bypasses transaction coordination.

### P2.8 — Add the interactive map panel

**Tasks**

1. Add a map panel while retaining editor, results, plan and files panels. Leaflet is a reasonable proposed choice; freeze the dependency/version during implementation after checking compatibility.
2. Render stored points and highlight query-result identities with a distinct style. Popups show useful row fields, selected metric and distance when returned.
3. Add a selectable query center, radius in kilometres with explicit conversion to metres, a k selector, and polygon drawing/selection. Show the generated single statement and its typed context before/with execution.
4. Synchronize map and tabular results. Ensure marker order/selection reflects the same result set, even when rows have identical coordinates. Do not recompute membership in the browser.
5. Show actual plan/metric, loading, no matches, truncated display, validation failures, cancellation and transaction status. Distinguish provisional rows in the user's transaction from committed data.
6. Use bounded rendering, clustering/canvas or viewport loading for large datasets. Explain which points are currently displayed; the map must not imply that a sample is the whole table.
7. Define tile attribution and an offline/no-tile demo fallback that preserves coordinate overlays and engine queries. Browser location is optional and permission-based; typed map selection is sufficient.

**Tests:** asymmetric lat/lon fixture renders in the expected location; radius and polygon overlays match queries; duplicate markers remain selectable; result-table selection works; two-session commit/rollback refresh; no-match/error/cancel states; 100,000-point dataset does not require 100,000 DOM markers.

**Exit gate:** a demonstrator can load points, run radius/k-NN/polygon searches and inspect highlighted engine results and the chosen access path from the existing interface.

### P2.9 — Run the required comparative experiments

**Tasks**

1. Implement one reproducible generator/import pipeline producing N=1,000, 10,000 and 100,000 points, stable IDs, checksums and seeded query centers. Use identical data and query inputs for all methods.
2. Implement adapters for a forced own-engine sequential scan, the own R-Tree, and PostgreSQL/PostGIS with GiST. The external database must not provide query results to the mini-DBMS application.
3. Validate result sets and k-NN order before recording performance. Align coordinate systems, distance metric, Earth radius, strict boundary semantics and tie handling.
4. Run the matrix in section 7, including mean execution time over 100 queries per configuration, index construction time, memory and disk space. Keep build/load/query phases separate.
5. Capture own-engine plans/counters and PostgreSQL `EXPLAIN (ANALYZE, BUFFERS)` evidence for representative configurations outside the normal timed batch. Record actual GiST use or planner fallback; do not label a PostgreSQL scan as an indexed result.
6. Export raw CSV/JSON, environment metadata and reproducible plotting scripts. Produce graphs and the required decision table based on measured performance/selectivity/build cost.
7. Add an additional polygon correctness/demo workload; label polygon performance measurements as useful supplementary evidence rather than an extra matrix prescribed by §2.2.4.

**Exit gate:** every prescribed dataset/query setting has real, reproducible measurements and verified semantics. A missing comparator or failed large case remains an open requirement, not a blank chart treated as completion.

### P2.10 — Audit, document and close Part 2

**Tasks**

1. Run affected unit, differential, persistence, transaction, API, frontend and integrated acceptance tests. Then run the required complete regression gates for release; record actual commands, environment, commit and results.
2. Demonstrate the printed SQL examples, both distance modes, polygon search, map highlighting, clean reopen, committed mutation and rollback on spatially indexed tables.
3. Complete the documentation synchronization checklist in section 9. Preserve earlier audits as historical evidence rather than rewriting their dates/results.
4. Add report sections for domain, data/coordinate conventions, R-Tree design, spatial SQL, map architecture, experimental methodology/results and limitations.
5. Prepare the assignment's 5–10-minute demonstration video and updated README/install/runbook. Prepare material for the eventual 15-minute final presentation plus 5-minute questions; the final presentation is a whole-project deliverable.
6. Check Stage 9 formal closure and Stage 10 evidence independently. Record the Part 2 completion decision and any remaining whole-project work explicitly.

**Exit gate:** section 10 is satisfied with linked evidence, and the team can reproduce the partial delivery from a clean checkout.

## 7. Experiment protocol

### 7.1 Required matrix

| Dimension | Values |
|---|---|
| Methods | Own sequential scan; own R-Tree; PostgreSQL/PostGIS GiST |
| Dataset sizes | 1,000; 10,000; 100,000 points |
| Radius workload | 1 km; 5 km; 10 km |
| Nearest-neighbor workload | k=10; k=50; k=100 |
| Queries | 100 fixed, reproducible query inputs per workload setting; report arithmetic mean |
| Build measurement | Index construction time separately from data loading; scan index-build cost is N/A |
| Space/resources | Base-data bytes, additional index bytes, peak memory during build and queries |
| Outputs | Raw samples, comparative charts, environment description, interpretation table |

Run the matrix for **both metrics as this plan's recommended experimental policy**. The PDF requires both metrics to be implemented, but does not explicitly prescribe doubling the experimental matrix. With this policy there are 54 method/size/query-setting cells per metric and 108 cells overall, or 10,800 measured query executions before warmups/repetitions. Build measurements are separate; a shared physical index need not be rebuilt for every radius or k.

Use the same 100 centers across comparable settings. Include a documented local geographic dataset for the map and planar mode, plus synthetic distributions for diagnosis. Keep correctness edge cases separate from timing fixtures when necessary, and report selectivity/result counts.

### 7.2 Fair metric and access-path comparison

- **Euclidean:** compare identical projected x/y coordinates and metre thresholds. PostgreSQL geometry/GiST can operate on that same plane. Do not compare projected mini-DBMS metres with PostGIS geometry distances in geographic degrees.
- **Haversine:** compare spherical distances. PostGIS geography `ST_DWithin` defaults to spheroidal distance; explicitly select its spherical mode for the relevant comparator. Establish the exact sphere/radius used by the selected versions and harmonize it with the engine or apply a documented exact scale conversion.
- Geography `<->` supports spherical nearest-neighbor ordering; geometry `<->` supports planar distance ordering. Use matching semantics, prove deterministic boundary-tie handling, and inspect the actual execution plan. Re-ranking an arbitrary fixed number of neighbors under a different metric does not prove exact k-NN.
- `ST_DWithin` is inclusive. To compare the assignment's strict `< 5000` predicate, use conservative candidate selection plus the same strict final distance test.
- For tests, explicitly force/select the own-engine access method and record it; a planner fallback is a separate measurement. If PostgreSQL chooses a sequential scan for a broad radius, report it honestly and separately document any diagnostic forced-index experiment.
- Verify equality of record identities, multiplicities and ranking, not only matching counts. Define floating tolerances for validation without silently expanding the SQL radius predicate.

### 7.3 Measurement boundaries

Record hardware, OS, Python/PostgreSQL/PostGIS versions, commit, page sizes, memory budgets, dataset seed/checksum, index configuration, cache protocol and query order. Use a monotonic high-resolution clock. Report build time with the stated flush policy; distinguish warm-cache and cold-cache runs only when actually controlled.

Measure comparable engine execution plus complete result consumption, with map rendering excluded. If PostgreSQL transport is included, include comparable client overhead for the other methods or publish separate engine-only and end-to-end measurements. Run correctness validation outside timed intervals. Report standard deviation or percentiles in addition to the mandated mean when practical.

Define peak-memory instrumentation explicitly: Python allocation tracking alone is not comparable to whole PostgreSQL server RSS. Report process/server memory, shared-cache configuration and any incremental estimates separately. Measure actual index/base file sizes rather than deriving them from row counts. Track temporary space separately. Do not count Stage 8 undo snapshots as R-Tree index bytes.

Export long-form samples with at least: method, metric, N, radius or k, query ID, actual access path, elapsed time, result count, validation status and cache mode. Store build/memory/disk measurements in linked configuration records. Every graph must be regenerable from these files.

## 8. Critical risks and release checks

| Risk | Required response |
|---|---|
| Latitude and longitude reversed between SQL, map and PostGIS | Named fields, explicit adapters and asymmetric-coordinate acceptance fixtures |
| Incorrect geodesic pruning loses valid points | Proven conservative bounds and exhaustive differential tests; explicit exact fallback |
| R-Tree returns only polygon bounding-box matches | Exact point-in-polygon residual predicate |
| LIMIT applied before spatial/relational filtering | Operator-order tests with qualifying neighbors beyond the first k candidates |
| POINT works in Heap but fails in sort/temp files/JSON | Cross-layer type-dispatch inventory and pipeline round-trip tests |
| New index skipped by undo or reopening | Registered complete file set and failure-injection tests across split/restore |
| GUI and managed databases discover different definitions | Shared builders and separate reopen/import tests for both owners |
| Long searches block cancellation or exceed memory silently | Safe points, measured frontier budget and controlled resource errors |
| Map truncation misrepresented as complete results | Separate execution counts, returned counts, display limits and visible status |
| PostGIS spherical/spheroidal or strict/inclusive mismatch | Comparator equivalence tests before timing |
| Large index builds exceed the existing undo budget | Staged unpublished build for creation and explicit capacity preflight for transactional changes; no disabling undo |
| Stage 10 disappears from the roadmap | Separate Part 1 checklist and partial-delivery gate |

## 9. Required documentation synchronization

Documentation updates are part of implementation, not an optional cleanup after the demo.

| File | Required change when Part 2 implementation is authorized |
|---|---|
| `REQUIREMENTS.md` | Add a separately scoped Part 2 section transcribing §2.2; preserve all Part 1 requirements and distinguish recommendations |
| `PROJECT_CONTEXT.md` | Record accepted POINT/metric/CRS, R-Tree, owner/format, SQL/API and map decisions; update actual phase/status |
| `AGENTS.md` | Link this plan and the active Part 2 phase; clarify the authorized spatial scope while keeping no-library-substitution rules |
| `PLAN.md` | Add Part 2 handoff/reference and preserve Stage 9/10 pending status until their own evidence closes them |
| `ETAPA_07.md` | Add a forward reference to Part 2 SQL extensions; preserve the closed Stage 7 baseline and its historical acceptance |
| `ETAPA_08.md` | Document spatial file/lifecycle integration boundaries and link new tests; do not claim stronger crash guarantees |
| `ETAPA_09.md` | Reference spatial API/map additions and their actual status; keep existing closure requirements accurate |
| `docs/sql-grammar.md`, `docs/sql.md` | Update manual grammar, POINT, functions, LIMIT, context bindings, examples and unsupported syntax |
| `docs/transactions.md` | Explain R-Tree snapshot/restore, schema publication, cancellation and quarantine behavior |
| `README.md`, `docs/demo.md` | Add installation, dataset setup, map use, separate comparator setup and reproducible demonstration |
| New spatial design/benchmark/audit docs | Record formats, algorithm invariants, decisions, experimental protocol, raw-result locations and final evidence |

Only promote resolved choices into stable architecture documentation. Use new dated addenda for changed behavior; keep old closure audits intact. This planning deliverable does not itself modify those files or claim their updates are already complete.

## 10. Part 2 Definition of Done

- [ ] All S2-01–S2-12 requirements have implementation and evidence links.
- [ ] Geographic POINT values persist and reopen without breaking existing tables.
- [ ] An original paged R-Tree supports build, lookup, insertion, deletion, validation and clean reopening.
- [ ] Rectangle/radius/k-NN/polygon results match exhaustive expected results, including duplicates and boundaries.
- [ ] Euclidean and Haversine metrics have explicit coordinate systems, units, numerical rules and exact-query tests.
- [ ] Both assignment SQL examples execute individually, including `mi_ubicacion` binding and LIMIT.
- [ ] Existing manual parser, comment and single-statement contracts remain intact.
- [ ] EXPLAIN shows the actual intended access path; ANALYZE measures one real execution.
- [ ] Spatial changes participate in existing locks, file ownership, undo, restoration and cancellation.
- [ ] API/import/reopen tests cover both supported ownership paths and existing table/index families.
- [ ] The interactive map displays stored points and highlights actual query results with truthful display limits.
- [ ] Required sequential/R-Tree/GiST experiments are complete for all prescribed sizes, radii and k values.
- [ ] Mean query time uses 100 queries per configuration; build, memory and disk measurements are published.
- [ ] Comparative graphs and the technique-selection summary table are backed by reproducible raw results.
- [ ] Documentation, report and demonstration artifacts match actual capabilities and limitations.
- [ ] Relevant and full release regressions pass, with commands/environment/commit recorded.
- [ ] Stage 9 formal closure and Stage 10 are independently complete before claiming the combined Parts 1–2 delivery.

## 11. Suggested first implementation instruction

> Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md and PLAN_PARTE_02.md. Inspect the current main commit and the latest Stage 8/9 evidence. Execute only P2.0 and prepare the decision record for P2.1. Preserve Stage 9 formal closure and Stage 10 as separate obligations. List the exact shared interfaces and persistence paths affected, propose coordinate/metric and owner-compatibility contracts, and establish the relevant regression baseline. Do not implement R-Tree nodes, alter file formats or extend SQL until those contracts are resolved and implementation is authorized.

## 12. Sources and reviewed evidence

1. **Original assignment:** `Proyecto_Final.pdf`, §2.2 (physical p.3), §§3–4 (physical p.5). The full assignment was read and the Part 2 page visually checked.
2. **Repository snapshot:** [main commit 14c2dc9](https://github.com/Base-de-Datos-2/MINI-DBMS/tree/14c2dc99b8ac5df09cfe713398420e89dcfd1df7). Paths named in this document refer to that snapshot unless stated otherwise.
3. **Current status:** `AGENTS.md`, `PROJECT_CONTEXT.md`, `PLAN.md`, `docs/ETAPA_08_AUDIT.md`, `docs/ETAPA_08_STAGE_9_HANDOFF.md`, `docs/ETAPA_09_REVISION_2026_09_25.md`, and `docs/ETAPA_09_REVISION_2026_09_30.md`. Audit test counts are attributed to their recorded dates.
4. **Course material:** `06 BD Espaciales - GiST - RTree.pdf`, sections on spatial predicates, distances, leaf/internal entries, covering MBRs, range search and nearest-neighbor/MINDIST. Its planar illustrations must not be applied unmodified to spherical distance pruning.
5. **External comparator documentation, consulted 2026-09-30:** [PostGIS ST_DWithin](https://postgis.net/docs/ST_DWithin.html), [PostGIS nearest-neighbor distance operator](https://postgis.net/docs/geometry_distance_knn.html), and [PostGIS ST_DistanceSphere](https://postgis.net/docs/ST_DistanceSphere.html). Recheck behavior against the versions pinned for the actual experiment.

This document specifies future work. It reports no Part 2 implementation, performance measurements, repository commits or successful release tests that have not actually occurred.
