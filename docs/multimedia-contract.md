# Part 4 multimedia contract — phase 1

Frozen 2026-11-06 for phase 1 of [PLAN_PARTE_04.md](../PART_04/PLAN_PARTE_04.md).
It fixes the semantics that phases 2–8 implement; it does not describe
executable multimedia SQL yet. The executable reference for the numeric rules
is [engine/multimedia/contracts.py](../engine/multimedia/contracts.py). The
source requirement is `Proyecto_Final.pdf` §2.4 ([REQUIREMENTS §17](../REQUIREMENTS.md)).
Evidence for this phase: [BLOQUE_1.md](../PART_04/BLOQUE_1.md).

**Baseline:** `main` at `7766e22` (Part 3 closed, Part 4 plan added). The plan's
historical reference commit `85db1be` is superseded by this one.

## 1. Integration map (inspected, not assumed)

| Concern | Part 3 mechanism found in the code | Part 4 decision |
|---|---|---|
| Owner | `api.database.Database` (`prepare_text`, `open`, `close`) is the single owner used by setup, API and UI | Add `prepare_multimedia` and multimedia registration to the same owner; no second owner |
| Publication | `prepare_text` builds into a NEW directory, closes every handle, seals, publishes a registry, then reopens a fresh owner to validate | Same sequence for image/audio collections |
| Sealing | Generic at storage level: `HeapFile.offline_publication()` and `HeapFile.seal(collection_id, generation)`; `seal_text_collection` adds text-only checks and seals declared B+/hash secondary indexes | New `seal_multimedia_collection` reusing the storage seal and the same secondary-index enumeration; `seal_text_collection` stays text-only |
| Registry | `text_tables.json`, strict read-only reader, exclusive one-time publication | Separate `multimedia_tables.json` with the same rules |
| Query environment | `QueryEnvironment.register_text/text_for` require a sealed Heap | `register_multimedia/multimedia_for` with the same checks |
| Lexer | `SIMILAR_TO`, `SIMILARITY_SCORE`, `k`, `METRIC`, `IVF`, `HNSW`, metric names are identifiers; `WITH` is already a keyword; `k=10` and `METRIC=cosine` tokenize as identifier, `=`, value | No lexer change needed |
| Parser | Text words are contextual identifiers; `USING <identifier>` after WHERE sets `text_model`; `is_text_select` treats any `USING` as text | Phase 5 must branch before `text_model`: `USING IVF/HNSW WITH METRIC=...` is multimedia, never a text model |
| Current behaviour | Both PDF examples are rejected with `SqlUnsupportedError` (unsupported function) | Must become executable in phase 5 |

## 2. Collections and metadata

One collection holds one modality (`image` or `audio`); vocabularies and
vector spaces are never mixed. Minimal relational schemas:

```text
imagenes(id INTEGER PRIMARY KEY, nombre VARCHAR(200), media_key VARCHAR(128))
canciones(id INTEGER PRIMARY KEY, nombre VARCHAR(200), artista VARCHAR(200), media_key VARCHAR(128))
```

Media bytes and vectors live outside Heap rows. With 4,096-byte pages the
record limit is 4,079 bytes; the widest worst-case `canciones` row (200
four-byte characters in each name plus a 128-byte ASCII key) needs 1,748
bytes. Over-long values are rejected, never truncated. Every accepted object
keeps a durable `id → vector_row → RID` association scoped to its collection
generation.

## 3. Media keys

`SIMILAR_TO('<key>', ...)` takes a **registered file name**, never a path or
URL. A key is 1–128 characters of letters, digits, `.`, `_` or `-`, starts
with a letter or digit, contains no `..`, and ends in a supported extension
(case-insensitive): images `.jpg`, `.jpeg`, `.png`; audio `.wav`, `.mp3`.
The extension must match the collection's modality. The owner resolves the key
inside the collection's registered query/media directory only after this
validation; traversal and absolute paths are rejected before any filesystem
access. Query uploads, if added, receive such a key and stay separate from
the immutable corpus.

## 4. Measures, score and order

All three measures are computed on the stored, **unnormalized** TF-IDF
vectors. A higher `SIMILARITY_SCORE()` is always a better match:

| `WITH METRIC=` | Score returned | Internal objective (lower is better) |
|---|---|---|
| `euclidean` | `−‖x − q‖` | `‖x − q‖²` |
| `dot` | `x · q` | `−(x · q)` |
| `cosine` | `x·q / (‖x‖‖q‖)` | `1 − cosine` |

Best-first order is **score DESC, id ASC**; the stable id is used for ties even
when it is not projected. Scores are not probabilities and are not comparable
across metrics or modalities. The interface labels the Euclidean score as
"−distance".

Raw vectors are kept because, for unit vectors, `‖x − q‖² = 2 − 2·cosine`:
normalizing the only stored copy would make the required Euclidean-versus-
cosine comparison identical by construction. Cosine may use a derived
normalized view. Dot product is not a metric distance; graph search on `−dot`
is heuristic and its recall is measured, not assumed.

Vectors must be finite and have nonzero norm, both at indexing and at query
time. Objects without usable descriptors are rejected by feature extraction;
no random or zero vector is ever fabricated. Short-input policy, fixed before
any measurement: an image is rejected only when SIFT yields no descriptor (no
minimum size); an audio clip is rejected as *no signal* when every decoded
sample is zero, and as *too short* when it has fewer samples than one FFT
window (2,048 at 22,050 Hz), instead of padding frames into existence.

## 5. SQL subset

```ebnf
vector_select = "SELECT", projection, "FROM", table_ref,
                "WHERE", similar_to, "USING", index_method,
                "WITH", "METRIC", "=", metric,
                ["ORDER", "BY", score_ref, "DESC", [",", "id", "ASC"]],
                ["LIMIT", nonnegative_integer], [";"] ;
similar_to    = "SIMILAR_TO", "(", string_literal, ",", "k", "=", positive_integer, ")" ;
index_method  = "IVF" | "HNSW" ;                 (* case-insensitive *)
metric        = "euclidean" | "dot" | "cosine" ;  (* case-insensitive *)
score_expr    = "SIMILARITY_SCORE", "(", ")" ;
```

- Projection: columns, `*` and `SIMILARITY_SCORE()` with optional alias;
  `score_ref` is that alias or the expression itself.
- `SIMILAR_TO` is the entire WHERE condition; one table only.
- `k` is a positive integer with no artificial upper bound; the output has
  `min(k, LIMIT, N)` rows. LIMIT is applied after best-first selection and
  never widens or replaces k. Without LIMIT the output has up to k rows (unlike
  Part 3's unrestricted `MATCH`).
- Rejected with a located error: missing `USING` or `WITH METRIC`, unknown
  method or metric, k ≤ 0 or non-integer, `ORDER BY` score ASC or by id alone,
  extra filters, JOIN, GROUP BY, aggregates, `SIMILARITY_SCORE()` outside a
  multimedia query, a key of the wrong modality, or a collection without the
  requested method/metric index.
- `EXPLAIN` / `EXPLAIN ANALYZE` use the existing mechanism. Plan nodes:
  `VectorIndexScan` (method, metric, effective nprobe or efSearch, candidates
  and distance evaluations) and `VectorScan` (exhaustive; shown with the
  requested method when «Usar índices» is off). An index never silently falls
  back to a scan while reporting index timing.

## 6. Representation

`ExtractFeatures(object, fitted_model) → float32[K]`, always with the fitted
model of the collection:

1. Local descriptors: SIFT for images (grayscale, longest side ≤ 512 px, at
   most 256 strongest keypoints); MFCC for audio (mono, 22,050 Hz, 20
   coefficients, FFT 2,048, hop 512, one descriptor per frame, clips longer
   than 30 s rejected).
2. Vocabulary: K-Means on a seeded sample of at most 100,000 descriptors;
   K = 256 visual words, K = 64 audio words (tiny fixtures may persist a
   smaller K). The vocabulary centroids are not the IVF coarse centroids.
3. Histogram: nearest centroid by squared Euclidean distance; `h_j` counts
   descriptors per word.
4. Weights: `tf_j = 1 + ln(h_j)` if `h_j > 0` else 0;
   `idf_j = ln((N + 1)/(df_j + 1)) + 1` with `df_j` counted per object;
   `x_j = tf_j · idf_j`. Queries use the gallery vocabulary and IDF and never
   change N, df or the codebook.

For the size experiment the vocabulary is trained once on the 1,000-object
subset and reused; IDF is recomputed per N. IVF and HNSW at a given N receive
identical vectors.

## 7. Index and dependency boundaries

- IVF (full vectors): `nlist = min(N, max(1, round(√N)))`, `nprobe = min(8,
  nlist)`; probing every list must equal the exact scan for all measures.
- HNSW: M = 16, base-layer cap 32, efConstruction = 100,
  `efSearch = max(64, k)`; genuine multilayer graph per objective. The dot
  graph is built on the augmented vectors `[x, sqrt(M² − ‖x‖²)]` with queries
  `[q, 0]`, a true metric whose ascending distance equals descending dot
  (phase 4 finding: building on −dot directly left ~13 % of a test graph
  unreachable).
- The exact reference (`exact_top_k`, and later `VectorScan`) defines
  Recall@10 = |ANN top-10 ∩ exact top-10| / min(10, N).
- Third-party code inside `engine/`: only `numpy`, anywhere in
  `engine.multimedia`; `cv2` (OpenCV), `soundfile`, `librosa` and `sklearn`
  only in `engine.multimedia.features`, imported lazily so the package imports
  without them. `tests/test_architecture.py` enforces this; FAISS, hnswlib or a
  vector database cannot enter the engine.
- **Decision D1 (user, 2026-11-06):** the **vocabulary** K-Means uses
  scikit-learn (k-means++, Lloyd, seeded; installed anyway by librosa), as a
  feature-extraction helper. The **IVF coarse partition** uses our own K-Means,
  because it is part of the index the assignment asks us to implement.

## 8. Data acquisition under the measured storage limit

The host has about 32 GB of free physical storage (the WSL virtual disk's
817 GB figure is only its maximum size). Storing COCO `train2017.zip`
(19.3 GB) plus its extraction does not fit. Images are therefore downloaded
individually using the annotations file as list and provenance (URL and
SHA-256 of the original bytes recorded), and kept as ≤ 512 px copies, which
is exactly the first preprocessing step, so features are unaffected. Audio
clips come from FMA as individual zip members read through HTTP byte ranges.
Status and probes: [multimedia_feasibility.json](implementacion/evidencias/multimedia/multimedia_feasibility.json)
(PENDING until phase 6 measures it).
