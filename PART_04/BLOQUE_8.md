# Part 4 — Phase 8: delivery and closure

Date: 2026-11-06. Scope: phase 8 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10.
**Part 4 is complete**; Part 5 (application) is not included.

## Phases and branches

Each phase is a branch that starts from the previous one. All commits are
authored by the user, and nothing was pushed.

| Phase | Branch | Evidence |
|---|---|---|
| 1. Baseline and contracts | `feat/parte-04-fase-1` | [BLOQUE_1.md](BLOQUE_1.md) |
| 2. Features and exact scan | `feat/parte-04-fase-2` | [BLOQUE_2.md](BLOQUE_2.md) |
| 3. IVF | `feat/parte-04-fase-3` | [BLOQUE_3.md](BLOQUE_3.md) |
| 4. HNSW | `feat/parte-04-fase-4` | [BLOQUE_4.md](BLOQUE_4.md) |
| 5. Integration | `feat/parte-04-fase-5` | [BLOQUE_5.md](BLOQUE_5.md) |
| 6. Data and scale gate | `feat/parte-04-fase-6` | [BLOQUE_6.md](BLOQUE_6.md) |
| 7. Measurements | `feat/parte-04-fase-7` | [BLOQUE_7.md](BLOQUE_7.md), [EXPERIMENTOS_MULTIMEDIA.md](../docs/EXPERIMENTOS_MULTIMEDIA.md) |
| 8. Delivery | `feat/parte-04-fase-8` | this file |

## Delivered in this phase

- **Docker Compose.** The `build: add docker compose with one service per
  part` commit was brought in from `build/docker-compose`, which was never
  pushed. On top of it:
  - the image installs the `multimedia` extra and builds the Part 4 demo from
    the committed real media;
  - `parte4` serves it on port 8003.

  Verified with `docker compose up --build`: all four services are healthy;
  both PDF queries return `VectorIndexScan` results identical to the local
  demo; media is served; parts 1–3 still answer.
- **Documentation.**
  - [README.md](../README.md): Part 4 demo, features row, API routes,
    experiments row and the `multimedia` extra in the installation commands.
  - [docs/multimedia.md](../docs/multimedia.md): user guide.
  - [docs/informe/informe_parte_04.md](../docs/informe/informe_parte_04.md):
    report section.
  - Plan checklist §12 ticked, with the two gaps stated there.
- **Real-browser check of the real demo inside Docker** (Chromium 156):
  - 10 COCO thumbnails, the query image and the HNSW plan;
  - 5 audio players and the score note with IVF;
  - `VectorScan` with indexes off;
  - traversal returns 404.

  Recorded in [multimedia_browser.json](../docs/evidence/multimedia_browser.json).
- **Structured evidence:**
  [multimedia_closure.json](../docs/implementacion/evidencias/multimedia/multimedia_closure.json).

## Regression

| Check | Result |
|---|---|
| Full backend suite, Python 3.12.3, `-n 4 -W error` | **3,784 passed** (127.48 s) |
| Full backend suite, Python 3.11.9 (librosa 0.11), `-n 4 -W error` | **3,784 passed** (160.34 s) |
| Frontend `vitest` / `tsc --noEmit` / `vite build` | 46 passed / clean / built |
| Docker Compose, 4 services | healthy; Part 4 SQL, media and the Part 1–3 health checks verified |

The 3,784 tests are the 3,561 of the Part 3 closure plus 223 for Part 4:
- 216 in `tests/multimedia`: contracts, fixtures, features, vectors, IVF,
  HNSW and integration;
- 7 benchmark helper tests.

## Video demo script (about 4 minutes)

Preparation, with the server stopped:

```bash
python scripts/setup_multimedia.py --assets data/multimedia_demo
python -m api --multimedia
```

You can also use `docker compose up --build` and open port 8003.

| Time | Action | What to say |
|---|---|---|
| 0:00 | Files: select `imagenes`, then show its IVF and HNSW indexes. | "Each image becomes a 256-word histogram: SIFT, our K-Means vocabulary and TF-IDF. IVF and HNSW are our own indexes." |
| 0:30 | Ejemplos SQL → «Imágenes similares (PDF)», then Ejecutar. | Point at the query image, the thumbnails, the cosine score and `VectorIndexScan · HNSW` in the plan. |
| 1:00 | «Misma consulta con IVF», then uncheck «Usar índices». | "Same query with IVF; without indexes it runs the exact search, `VectorScan`, which is our reference for Recall@10." |
| 1:30 | «Euclidiana frente a coseno». | "The order changes with the metric; with Euclidean the score is minus the distance, so higher is still better." |
| 1:50 | «Canciones con reproductor», then play the query and the first result. | "The query is seconds 15–25 of a song; the first result is seconds 0–10 of that same song. MFCC plus an audio vocabulary." |
| 2:30 | «Plan con EXPLAIN ANALYZE». | Evaluated vectors, `ef_search`, and extraction versus search milliseconds. |
| 2:50 | Try an `INSERT` with `--allow-writes`. | "The collection is sealed: the engine rejects it before writing anything." |
| 3:05 | Show [EXPERIMENTOS_MULTIMEDIA.md](../docs/EXPERIMENTOS_MULTIMEDIA.md): queries, recall, gallery. | "At 100,000 images HNSW answers in about 2 ms against 30–70 ms for the exact search, and IVF builds 8–12 times faster. With fixed parameters recall drops with N; a wider search recovers it. Perfect recall is not the same as images a person finds similar." |

## Limits

- **Audio scale.** Audio is a functional collection of 30 clips; the 1k/10k/100k
  curve uses images (plan §2.8). Video is not implemented.
- **One run.** One experimental run on WSL2: no confidence intervals. The
  search-width sweep at 100k is a labelled post-hoc diagnostic.
- **Representation.** Bag-of-SIFT-words similarity is texture similarity, not
  semantic similarity; the gallery shows it.
- **Windows.** The plan asks for tests on Windows (MP3 decoding, release of
  memory maps). They were not run, because all work used Linux/WSL2. The
  vector store drops its maps on close instead of force-closing them, which
  is what Windows needs before deletion, but this is unverified there.
- **No uploads.** There is no upload action for queries: queries are
  registered files of each collection.
- **Engine limits** are unchanged from Parts 1–3: a single owner process, no
  WAL, and immutable published collections (rebuild into a new directory to
  change them).
