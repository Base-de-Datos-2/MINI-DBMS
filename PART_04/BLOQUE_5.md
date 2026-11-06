# Part 4 — Phase 5: integration

Date: 2026-11-06. Scope: phase 5 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10
under the user's authorization for phases 2–8.

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| Single owner | `api.database.Database.prepare_multimedia` / `_open_multimedia` | Done |
| Guards on every mutation route | Sealed Heap (Part 3 storage seal) + read-only collection files | Done, tested via SQL and HTTP with `--allow-writes` |
| SQL, operator, API, results view | Parser/binder/planner, `VectorIndexScan`/`VectorScan`, `/api/multimedia/*`, Results panel | Done |
| Both PDF examples through the UI | Real browser (Chromium, Playwright) | PASS, [multimedia_browser.json](../docs/evidence/multimedia_browser.json) |
| Existing behaviour preserved | Full suite | See regression |

## Engine

- **[collection.py](../engine/multimedia/collection.py), `MultimediaCollection`.**
  One published collection holds:
  - its fitted model, vector store, `rids.npy` (id → vector row → RID), IVF,
    and an HNSW graph per metric;
  - `media/`, where gallery files are hard-linked when possible and copied
    otherwise;
  - `queries/`, the registered query files.

  `build_collection` builds everything from an unsealed Heap and aborts on any
  feature failure, so rows are never dropped silently. `open` restores the
  handles without extracting, training or building. `search` resolves a
  registered key (queries first, then gallery), encodes it with the fitted
  model and runs IVF, HNSW or, with indexes disabled, the exact `VectorScan`.
  There is never a silent fallback. Extraction and search times are recorded
  separately.
- **[sealing.py](../engine/multimedia/sealing.py).** The same one-way storage
  seal as Part 3: the declared secondary indexes, then the Heap, with
  descriptor (collection id, generation). At publication it checks every RID
  against its id and media file.
- **[registry.py](../engine/multimedia/registry.py).** `multimedia_tables.json`
  is published exclusively, once, and read strictly.
- **[operators.py](../engine/multimedia/operators.py).** `VectorIndexScan` and
  `VectorScan` read the Heap row of each neighbour and project columns and
  `SIMILARITY_SCORE()`. EXPLAIN ANALYZE shows the requested and executed
  method, metric, k, evaluations, `nprobe`/`nprobe_used` or
  `ef_search`/`max_level`/`shortfall`, the model fingerprint, and the
  extraction and search milliseconds.

## SQL

- **AST.** New `SimilarTo(media, k)`; `SelectStatement.vector_method` and
  `vector_metric` stay separate from Part 3's `text_model`.
- **Parser.**
  - `SIMILAR_TO('<key>', k=<n>)` as the WHERE condition.
  - `USING <method> WITH METRIC=<metric>` is routed before the text-model
    branch: the conflict found in phase 1.
  - `SIMILARITY_SCORE()` is accepted in the projection and in `ORDER BY`.
  - Located errors for a missing `WITH METRIC`, k ≤ 0, `WITH METRIC` without
    `SIMILAR_TO`, and `SIMILAR_TO` combined with other conditions.
- **[vector_binding.py](../engine/query/vector_binding.py).**
  - Checks method and metric names, the published collection, the key's
    modality and that the requested index exists.
  - Projection: columns, `*` and `SIMILARITY_SCORE()`.
  - Order: none, or score DESC with an optional `id ASC`.
  - LIMIT applies after the best-first k.
  - Rejected: JOIN, GROUP BY, aggregates and other orders.
- **Planner and environment.** `VectorScanSpec` re-validates the borrowed
  collection on every run (stale plans fail), like text and spatial.
  `QueryEnvironment.register_multimedia` requires a sealed Heap whose seal
  matches the collection.

## Owner, API and interface

- **Owner.** `Database.prepare_multimedia(directory, [MultimediaSource...])`
  follows `prepare_text`:
  1. create the Heap tables;
  2. close every handle;
  3. build, seal and register;
  4. validate with a fresh owner.

  Opening imports numpy and the media stack only if `multimedia_tables.json`
  exists, so Parts 1–3 servers start without them. The Files panel lists
  `IVF (metrics)` and `HNSW (metric)` indexes with their sizes.
- **HTTP.**
  - `GET /api/multimedia/tables` lists modality, key column, size, dimension,
    methods and registered queries.
  - `GET /api/multimedia/{table}/media/{key}` serves only registered files.
    Traversal, keys of the wrong modality, unknown keys and unknown tables all
    return 404.
  - SQL still goes through `POST /api/query`.
- **Launch.** `python -m api --multimedia` opens
  `data/generated/multimedia`. The Ejemplos SQL menu offers both PDF queries,
  a variant that plays the songs, IVF, Euclidean and EXPLAIN ANALYZE.
- **Interface.** The Results panel
  ([multimedia.ts](../frontend/src/multimedia.ts)) detects a real vector-scan
  plan and then:
  - renders thumbnails or `<audio>` players for the key column;
  - shows the query media and a note on the score ("score = −distancia
    euclidiana");
  - keeps relational results on the same tables as plain text.
- **Setup.** `scripts/setup_multimedia.py` builds the fixture collections, or
  real demo media with `--assets <dir>/collections.json`.

## Verification

| Check | Result |
|---|---|
| `tests/multimedia/test_integration.py` | 31 passed: both PDF examples, index = scan on the tiny collections for 2 methods × 3 metrics, LIMIT after k, 11 rejected forms, unregistered key, EXPLAIN/ANALYZE, relational SQL on the same table, INSERT/DELETE rejected before effects, fresh-process reopen, registry mismatch, no reuse of a directory, HTTP listing/media/presets/writes |
| Frontend `vitest` / `tsc` / build | 46 passed (3 new) / clean / built |
| Real browser (Chromium 156) | PASS: 8 thumbnails and the query image loaded, HNSW plan; 5 audio players and the score note, IVF plan; `VectorScan` with indexes off; traversal 404 |
| Full suite, Python 3.12, `-n 4 -W error` | **3,777 passed** (131.28 s) |

The browser check found and fixed two display issues: the Files panel labelled
HNSW as "Hash extensible", and long plan keys overlapped their values (keys
are now `requested`, `executed`, `evaluations`, `nprobe_used`...). The PDF's
audio query projects no media column, so a variant that adds `media_key` is
offered to play each song.
