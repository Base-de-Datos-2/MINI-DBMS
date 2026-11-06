# Implementation plan — Part 4: multimedia vector retrieval

> **Update 2026-11-06 (phase 1):** baseline is `main` at `7766e22`, which
> replaces the historical commit cited in §1. Contracts are frozen in
> [docs/multimedia-contract.md](../docs/multimedia-contract.md). The measured
> host has about 32 GB of free physical storage, so §3.1's COCO candidate is
> acquired image by image (≤512 px copies, original URL and SHA-256 kept)
> instead of storing `train2017.zip`; see the contract §8 and
> [BLOQUE_1.md](BLOQUE_1.md). Later phases are recorded in the table of §10.

## 1. Objective, assumptions and scope

Implement **persistent image and audio retrieval using local SIFT/MFCC descriptors, a learned visual/audio vocabulary, TF-IDF histograms, and custom IVF and HNSW indexes**. Expose retrieval through MINI-DBMS SQL and the existing interface; evaluate accuracy, latency, construction cost and memory.

**Scope correction:** the request mentions images and video, but `Proyecto_Final.pdf`, §2.4, page 4, explicitly requires **images and audio**. This plan follows that specification. Video decoding, frame sampling, temporal matching and video-level aggregation are not required and are excluded. They must not replace the required MFCC audio path. If video was intentional, it needs a separate scope decision; the image pipeline alone is not a video search implementation.

Assume Part 3 is correctly implemented, including `api.database.Database` ownership, SQL extension mechanisms, persistent collection publication, engine-level immutability, and lifecycle tests. This document proposes Part 4; it does not claim that the assumed Part 3 implementation or Part 4 has been inspected or executed. The historical integration reference is commit `85db1bec94e0515dfff621dfa1ae8dece4c6ca08`; record the actual Part 3 baseline commit when starting implementation.

The supplied PDF has no separate scored rubric. Its explicit requirements define acceptance; implementation choices below are not additional rubric obligations. The Week 12 milestone includes both Parts 3 and 4. Part 5's application is a separate delivery.

| PDF requirement | Minimum complete implementation | Acceptance evidence |
|---|---|---|
| §2.4.1 ExtractFeatures | SIFT for images and MFCC for audio, followed by vocabulary assignment and TF-IDF | Both media types produce reproducible vectors from actual files |
| Quantization and histograms | One K-Means vocabulary per modality; K-dimensional weighted histograms | Known descriptor assignments, frequencies and weights |
| §2.4.2 IVF and HNSW | Own index construction, search and persistence | Structural tests, exact reference, reopening and measured approximation |
| Three measures | Euclidean distance, dot product and cosine | Both indexes support all three; numerical and ordering tests |
| §2.4.3 SQL | SIMILAR_TO, USING, WITH METRIC, SIMILARITY_SCORE and projection/order | Both supplied examples execute through engine and API |
| §2.4.4 experiments | IVF versus HNSW; Euclidean versus cosine; k=10; N=1,000/10,000/100,000 | Complete matrix on a frozen real-media corpus |
| Measurements | Index construction, query time, Recall@10 and memory | Raw results, configuration and exact-neighbor reference |
| Presentation | Timing curves, success/error gallery and recommendation table | Incremental report and demonstration |

## 2. Scope decisions that avoid unnecessary work

1. Reuse Heap for short metadata, the existing catalog, query environment, sessions, parser, operators, API and frontend. Do not introduce another database service.
2. Maintain separate image and audio collections. Their vocabularies and vector spaces differ; equal dimensionality does not make cross-modal comparison meaningful.
3. Publish collections in batches, then make them immutable using Part 3's engine policy. No online additions, deletions, graph repair or vocabulary updates are required. Rebuild into a new directory.
4. Implement IVF with full vectors, equivalent in scope to **IVFFlat**. Do not add product quantization, residual coding, IVF-PQ or tree quantization: K-Means already satisfies the vocabulary requirement.
5. Implement genuine multilayer HNSW. A single proximity graph or exhaustive search labeled HNSW is insufficient.
6. Use established libraries for media decoding, SIFT, MFCC, arrays and K-Means. Own the histogram/TF-IDF pipeline, measures, IVF/HNSW logic, persistence and integration. Do not use FAISS, hnswlib or a remote vector database as the submitted index implementation. This conservative boundary follows the project's educational “from scratch” intent; the PDF does not enumerate permitted helper libraries.
7. Store one vector per image or explicitly declared audio clip. No region detection, audio fingerprinting, transcript search, learned embeddings, CLIP, face recognition, GPU requirement or neural training.
8. Use a small functional audio collection and images for the full scaling experiment. The wording “images/audios” is interpreted as allowing one primary experimental modality, while both feature pipelines and SQL examples remain implemented. State this interpretation in the report; do not claim 100,000-audio validation. If a separately supplied rubric requires both modalities at all sizes, repeat the same harness for audio rather than changing the engine.

Not included: PostgreSQL/pgvector comparison (not requested in Part 4), hybrid text/image ranking, joins or filters inside ANN search, distributed execution, new crash recovery, background job infrastructure, user accounts or a redesigned frontend.

## 3. Data acceptance gate

### 3.1 Collections

Use `imagenes(id, nombre, media_key)` and `canciones(id, nombre, artista, media_key)` as small relational schemas. Use unique stable IDs and a durable `id → vector_row → RID` association. Store media under a collection-relative media directory; keep large bytes and vectors outside Heap rows. Validate encoded metadata against the real record/page limits, including prefixes and headers.

The candidate scaling source is **COCO 2017 images**, subject to local validation. Do not require annotations, detection models or an annotation database for vector-neighbor recall. Retain original source IDs and usage information. This is a candidate, not an accepted dataset; no download or feasibility run has been performed for this plan.

Prepare a small audio fixture from legally usable files with original names/artists or truthful descriptive metadata. Include WAV and a real MP3 query so the second SQL example is exercised. A collection of short clips is sufficient; record their source, duration and any deterministic clipping. Do not relabel many frames/descriptors as independent songs.

### 3.2 Required PASS before freezing the large corpus

Produce `multimedia_feasibility.json`, initially PENDING, with these measured checks:

| Check | PASS condition |
|---|---|
| Accessible media | Original files are locally available with provenance and usable formats; a URL or precomputed feature-only dataset is insufficient |
| Valid scale | At least 100,000 unique accepted images decode and yield finite, nonzero histograms; duplicate bytes are removed and rejected cases counted |
| Experimental split | Frozen nested subsets of 1,000 ⊂ 10,000 ⊂ 100,000; 30 separate query images plus a small separate tuning set; no byte-identical query/gallery overlap |
| Real pipeline | Selected files pass the final preprocessing/descriptor pipeline; metadata can be inserted and reopened without truncation |
| Audio path | A practical fixture, e.g. 30 valid clips and 5 query clips, passes MFCC, vocabulary, vectorization and SQL, including MP3 decoding |
| Resources | Pilot at 1,000 and 10,000 measures extraction, K-Means and own HNSW time/RSS; projected 100,000 workload fits the team's actual machine and preparation window |
| Persistence | Artifact sizes and hashes, IDs and required files are recorded; reopening does not train models or regenerate vectors |

A pilot projection is not proof that the 100,000-object experiment completed. Record actual final measurements later. If a candidate fails, fix the bottleneck or choose another real corpus and rerun the gate. Do not duplicate objects, count local descriptors as images, silently lower N, or replace SIFT with downloaded embeddings to claim compliance.

No human relevance judgments are needed for the required **ANN Recall@10**, whose reference is exact search in the same vector space (§9). A small manually explained gallery provides complementary evidence about perceptual quality.

## 4. Feature representation and training

### 4.1 One pipeline with two descriptor adapters

Define `ExtractFeatures(object, fitted_model) -> float32[K]`. The fitted model is mandatory at query time. Keep descriptor extraction as an internal step; returning a variable number of SIFT descriptors is not yet the final object vector.

Proposed starting parameters, to freeze after the pilot rather than silently tune on final queries:

| Stage | Images | Audio |
|---|---|---|
| Decode/preprocess | JPEG/PNG; fixed orientation handling; grayscale; preserve aspect ratio, longest side ≤512 pixels | Decode WAV/MP3; mono; resample to 22,050 Hz; short clips with a documented duration limit |
| Local patterns | OpenCV SIFT; cap retained descriptors at 256 per image | MFCC with 20 coefficients, FFT=2,048 and hop=512; each frame is one descriptor |
| Training sample | Seeded bounded sample of descriptors across gallery objects | Seeded bounded sample of MFCC frames across gallery clips |
| Vocabulary | K=256 visual words initially | K=64 audio words initially |

Pin all consequential library defaults in the fitted model, including MFCC mel/log-power parameters. Bound decoded inputs and descriptor batches. Reject corrupt files, unsupported formats and objects with no usable descriptors using explicit errors; do not fabricate a random or zero searchable vector. Audio with no signal must be handled explicitly. Fix a short-input policy before measuring.

Use one ordinary K-Means implementation on a bounded sample, for example at most 100,000 descriptors. The sample must contain enough distinct descriptors for K; tiny fixtures may use a smaller persisted K. Deterministic seeds and a fixed initialization count are sufficient; no broad model search.

### 4.2 Two different centroid sets

| Centroids | Inputs clustered | Meaning | Parameter |
|---|---|---|---|
| Visual/audio vocabulary | Local SIFT descriptors or MFCC frames | Each centroid becomes a histogram dimension | `K_words` |
| IVF coarse partition | Completed K-dimensional object vectors | Each centroid identifies an inverted list of object IDs | `nlist` |

These are separate K-Means jobs in different spaces. Do not reuse descriptor centroids as IVF coarse centroids. Neither set is a list of database records.

### 4.3 Histograms and weights

Assign each local descriptor to its nearest vocabulary centroid, using squared Euclidean distance. The stable centroid number is the dimension number. Count assignments in `h_j(o)` and compute:

```text
tf_j(o)  = 1 + ln(h_j(o)) if h_j(o) > 0; otherwise 0
df_j     = number of gallery objects whose h_j is positive
idf_j    = ln((N + 1) / (df_j + 1)) + 1
x_j(o)   = tf_j(o) * idf_j
```

Persist the unnormalized weighted vector `x`, its norm, vocabulary centroids and IDF. A query uses the same vocabulary and gallery IDF; it never changes N, df or the codebook. Do not replace the bag-of-words pipeline with an average SIFT/MFCC descriptor.

For size comparisons, fit the vocabulary once on a seeded training sample from the 1,000-object subset, then reuse it at all sizes. Compute and persist IDF separately for each N; encode each query using that N's IDF. State that this deliberately fixes vocabulary training while corpus statistics change. IVF and HNSW at a given N always receive identical vectors.

Use disk-backed numeric arrays and batches. At N=100,000 and K=256, one float32 vector matrix occupies 102,400,000 bytes (about 97.7 MiB); this excludes graph, media, temporaries, Python objects and duplicate views. Do not materialize a full N×N distance matrix or retain every raw descriptor in RAM.

## 5. Measures, ranking and SQL semantics

### 5.1 Higher score always means a better match

| SQL metric | Quantity evaluated on weighted vectors | Returned `SIMILARITY_SCORE()` | Best-first order |
|---|---|---|---|
| `euclidean` | `d = sqrt(sum((x_j-q_j)^2))` | `-d` | score DESC, id ASC |
| `dot` | `p = sum(x_j*q_j)` | `p` | score DESC, id ASC |
| `cosine` | `c = dot(x,q)/(norm(x)*norm(q))` | `c` | score DESC, id ASC |

Negative Euclidean distance makes the PDF's audio example with `ORDER BY score DESC` correct. Label it “score = −distance” in the interface; optionally display the nonnegative distance alongside it without adding a new SQL function. Scores are not probabilities, percentages or calibrated across metrics/modalities.

Store unnormalized vectors for Euclidean and dot. Cosine may use an L2-normalized derived view. Do not normalize the only stored matrix: for unit vectors `||x-q||² = 2−cosine(x,q)*2`, so Euclidean and cosine have the same exact ranking. A comparison using that representation must disclose the equivalence, not invent a quality difference. This plan preserves raw weighted vectors so the required comparison examines different objectives.

Use `d²`, `-dot` and `1-cosine` respectively as internal lower-is-better search objectives. Dot product is not a metric distance; graph search using `-dot` is heuristic and its recall must be checked. A graph built for one objective must not silently serve another as though constructed for it.

### 5.2 Supported SQL

Both assignment examples must execute, with prepared matching files and tables:

```sql
SELECT * FROM imagenes
WHERE SIMILAR_TO('foto_consulta.jpg', k=10)
USING HNSW WITH METRIC=cosine;

SELECT nombre, artista, SIMILARITY_SCORE() AS score
FROM canciones
WHERE SIMILAR_TO('audio_query.mp3', k=5)
USING IVF WITH METRIC=euclidean
ORDER BY score DESC;
```

Minimal grammar: one table; SIMILAR_TO as the entire WHERE condition; literal registered media key; positive integer k; required USING IVF/HNSW and WITH METRIC; ordinary projection or `*`, plus score and aliases. Support EXPLAIN and EXPLAIN ANALYZE through existing mechanisms.

To keep ordering correct and simple, permit no ORDER BY, or the score alias DESC with optional `id ASC` tie-break. Reject score ASC, ORDER BY id alone, additional filters, joins and aggregates in this special query form. Ordinary relational/text SQL keeps its existing semantics. If LIMIT is supported here, apply it after retrieval and best-first ordering: the maximum output is `min(k, LIMIT, N)`. It does not replace k or permit a different preselection. No LIMIT means up to k, unlike Part 3's unrestricted MATCH.

`SIMILARITY_SCORE()` outside a valid multimedia query, missing/mismatched modality, nonpositive k, unsupported order, absent metric-specific index or invalid model version must fail clearly. Include the stable ID internally for tie-breaking even if not projected. Reject NaN/Inf and zero-norm vectors before indexing.

Resolve the literal against a registered query/media directory. Never let HTTP/SQL clients read arbitrary server paths or remote URLs. The demo filenames are actual registered assets, not placeholder paths. A small query-upload action may return a safe media key for the existing SQL endpoint.

## 6. Index implementation

### 6.1 Common interface and exact reference

Provide `build`, `open`, `search(query, k)`, `close`, and statistics through a small shared protocol. Results contain unique IDs and exact scores for visited candidates, sorted by score DESC/id ASC. Approximate candidate selection does not permit approximate score calculation when the full vectors are available.

Implement a batched exhaustive `VectorScan` using the same vectors and score contract; maintain a bounded top-k rather than a full pairwise matrix. Use an independent simple scalar oracle for small correctness tests. The existing “Use indexes” toggle selects VectorScan when disabled. EXPLAIN must show the access method actually executed, including requested versus actual strategy when bypassing an index.

### 6.2 IVF with full vectors

Build L2-based coarse partitions on raw vectors for Euclidean/dot and normalized vectors for cosine; persist centroids and each list's vector-row IDs. Use nearest-centroid L2 assignment for these partitions. For dot queries, prioritize coarse centroids by descending dot; for Euclidean/cosine, use the corresponding query objective. These are approximate routing choices, not safe pruning bounds.

Probe `nprobe` lists and score every vector in those lists with the requested measure. Deduplicate IDs and order candidates before returning k. With all lists probed, results must equal VectorScan under every measure, including ties. If visited lists contain fewer than `min(k,N)` candidates, probe more lists until enough exist; record the effective probe count.

Starting choices: `nlist = min(N, max(1, round(sqrt(N))))`, `nprobe = min(8,nlist)`. Constrain training to a seeded bounded vector sample with at least nlist distinct representatives; handle empty clusters explicitly. No PQ, compression or multilevel coarse index. Persist offsets and contiguous IDs so opening does not repartition the collection.

### 6.3 HNSW

Implement seeded random levels, a persisted entry point and maximum level, greedy descent through upper layers, and bounded best-first exploration at layer zero. Construction needs `efConstruction`, bounded adjacency, reciprocal link insertion and the paper's neighbor-selection/pruning heuristic; retain a genuine hierarchy rather than a renamed single-layer graph.

Start with `M=16`, base-layer cap `2M`, `efConstruction=100`, and `efSearch=max(64,k)`; tiny fixtures may use smaller documented parameters. Store vectors once and persist levels/adjacency using compact arrays. Build separate graphs for Euclidean, cosine and dot objectives, or load only the requested graph lazily to control memory. Offline insertion is part of construction; online mutation remains disabled.

Tests must check link bounds, valid references, layer membership and entry-point consistency. Do not promise logarithmic worst-case cost or that a large efSearch proves exactness. Graph quality is established by measured recall, and the exact oracle stays separate. If fewer than `min(k,N)` results appear, surface the shortfall as a failed acceptance check; never silently replace the graph search with scan and report HNSW timing.

## 7. Persistence, owner and engine integration

### 7.1 One concrete ownership path

`api.database.Database` remains the **single owner** used by setup, reopening, API and frontend. Add a multimedia registry alongside Part 3's registry; do not create a second owner under `engine/database/`.

1. An offline setup script creates a new collection through this owner and engine builder functions.
2. Build metadata Heap, media manifest, fitted feature model, vector store, ID/RID map and metric-specific indexes in a private destination.
3. Validate associations and persist every component, then use Part 3's sealing/publication mechanism. Register the complete collection only after successful validation; a failed build must remain unavailable.
4. On open, the owner validates versions, collection/model identity, dimensions, counts and required files; restores the immutable state; opens model/vector/index handles; registers them with the query environment.
5. SQL and programmatic search use existing session read coordination and operator lifecycle. The frontend calls the current query API; no standalone search server.
6. On shutdown or failed open, release graph/list/vector handles and memory maps before storage, and preserve the owner's existing cancellation/cleanup behavior. Closing twice is safe.

Persist model fingerprints, media hashes, preprocessing parameters, codebooks, IDF, vector dtype/dimension, metric, seed, nlist/nprobe or M/ef parameters, stable IDs/RIDs and build baseline commit. Validate cheap structural consistency at open; use full checksum verification during build and explicit integrity tests rather than rehashing 100,000 media files on every query.

Normal reopening must not run feature extraction, K-Means or graph construction. Missing or incompatible components produce a clear error, not a silent rebuild. This is persistence after normal close/reopen, not a new crash-recovery guarantee.

### 7.2 Immutability across all supported paths

Reuse Part 3's persistent storage seal and pre-mutation guards. Published media metadata, vectors, models and indexes must remain consistent. Reject SQL/session writes, MutationService changes, imports, maintenance/reorganization, direct supported Heap mutations and exposed index mutations before any effects, including after reopening and with `--allow-writes`.

Open model/vector/index artifacts read-only in query mode; builders can write only new unpublished destinations. Keep query uploads separate from the immutable corpus. Media files are collection-owned; normal APIs cannot replace them in place. The policy covers supported engine operations, not arbitrary external byte tampering. Do not implement undo snapshots of huge multimedia files for writes that are prohibited in the first place.

### 7.3 Minimal code changes

Paths below are proposed responsibilities; inspect the actual Part 3 interfaces before choosing exact function names.

| Location | Responsibility |
|---|---|
| `engine/multimedia/features.py` | SIFT/MFCC adapters, fitted vocabulary and TF-IDF |
| `engine/multimedia/vectors.py` | Numeric store, ID mapping, measures and exact scan |
| `engine/multimedia/ivf.py`, `hnsw.py` | Own index algorithms and serialization |
| `engine/multimedia/collection.py` | Manifest, build/open validation and model lifecycle |
| `api/database.py` + query environment | Owner registry and shared access handles |
| Existing lexer/AST/parser/binder/planner | Multimedia syntax, validation and physical access choice |
| Existing operator/executor layer | MultimediaSearch with open/next/close and statistics |
| Existing API/frontend | Query assets, gallery/audio results and plan details |
| `scripts/setup_multimedia.py` | Offline build and reopen demo preparation |
| One benchmark script + tests | Frozen experiment and acceptance evidence |

No new repository-wide plugin framework or catalog rewrite is needed. Reuse only genuinely shared Part 3 utilities: lifecycle, policy, ordering infrastructure and tested TF weighting helpers. Text postings and term dictionaries are not the multimedia IVF lists or learned vocabulary.

## 8. Interface and demonstration

Keep the four panels. The Files panel identifies modality, object count, dimension and available indexes/metrics; the SQL panel supplies both example queries; the Results panel renders image thumbnails or audio controls alongside metadata/scores; the Plan panel shows VectorScan/IVF/HNSW, metric, model identity, effective search parameters, candidates/distance evaluations and query timing.

Serve thumbnails/audio through collection-relative controlled endpoints. Basic image display and HTML audio playback are sufficient. Do not implement editing, waveform timelines, streaming infrastructure or an upload-driven permanent ingestion workflow.

Prepare an image query and an audio query with interpretable results, run both SQL examples, switch index and metric, compare ANN IDs with exact search, then close/reopen and rerun. Show one perceptual failure as well as success. Avoid claiming that bag-of-words preserves spatial layout, melody or temporal order.

## 9. Experimental protocol

### 9.1 Matrix and fair inputs

Primary matrix: **3 sizes × 2 indexes × 2 measures × 30 queries × 3 repeats = 1,080 timed searches**, excluding warm-up, construction, exact references and extraction. This count is a proposed protocol, not an assignment requirement. Use k=10, Euclidean/cosine, the same frozen queries and each size's identical fitted representation for both indexes. Dot product is implemented and tested on both modalities/indexes, but a full dot scaling experiment is not required by §2.4.4.

Run one warm-up pass, then interleave method order with a fixed seed. Build each configuration once in a fresh process and report it as one build measurement; do not imply construction averages. Repeat a build only to investigate instability or a failure, keeping its provenance.

Use the small tuning set to choose at most one modest search-parameter adjustment if the pilot gives unusable recall. Then freeze nprobe/efSearch and report them. A suggested engineering target is mean Recall@10 ≥0.90 on tuning queries; it is not a rubric threshold or a guarantee. Final-query results remain visible even if lower. Do not tune on final queries or hide poor runs. Large graph-build cost should be addressed first with compact arrays and batched arithmetic, not a replacement library index.

### 9.2 Recall reference and perceptual quality

For every query, N and measure, compute exact top-10 using exhaustive search over the **same stored vectors**, ordered by exact score DESC and ID ASC:

```text
Recall@10(q) = | ANN_top10(q) intersect Exact_top10(q) | / 10
```

N is at least 1,000 in the benchmark, so the denominator is 10. For tiny tests with N<10, use min(10,N) and label that case separately. Query/gallery separation prevents self-match inflation. Use deterministic ID tie-breaking and report the frequency of boundary ties; do not count arbitrary tie orders as numeric instability. Record each query's result IDs and scores, not only averages.

This measures **index approximation**, not whether a human finds the objects semantically similar. An exact top-10 can still contain visually or acoustically poor matches. The gallery should distinguish (a) ANN misses relative to exact neighbors and (b) poor feature representation despite correct neighbor retrieval. Labels or human notes may support gallery interpretation but must not be confused with the exact-neighbor denominator.

### 9.3 Timing and memory boundaries

| Measurement | Boundary and reporting rule |
|---|---|
| Common preparation | Separate media decoding, descriptor extraction, vocabulary training, histogram/IDF/vector generation; do not charge shared preparation twice to IVF/HNSW |
| Index construction | From prepared vectors to closed, persisted, reopenable index; includes IVF coarse training or HNSW insertion/serialization |
| Index query | Prepared query vector to ordered IDs/scores; includes coarse search/graph traversal, candidate scoring and top-k; excludes UI/media decoding |
| End-to-end example | Separately time query-file decode + ExtractFeatures + index search + metadata fetch; clearly distinguish it from the index timing chart |
| Memory | Fresh process per configuration; baseline RSS, absolute peak construction RSS, loaded-index RSS and peak query RSS; record sampling method and OS |
| Shared/derived memory | Report vector store, norms, optional normalized copy, index structures and temporary buffers; do not confuse array byte counts with process RSS |
| Disk | Supplementary low-cost file-size summary separating media, metadata, vectors/models and each index; memory is the explicitly required measure |
| Reopening | Confirm no training occurs and results remain stable; cold-open time may be reported separately, not mixed into warm query latency |

Include mean and median query time, mean Recall@10 and per-query data. Keep timeouts/errors as explicit failed observations; do not convert them to zeros or omit them from counts. Record actual commit, library versions, CPU/RAM, OS, threads, seeds, manifests and all feature/index parameters. Test on the intended Windows environment, especially MP3 decoding and memory-map release.

CSV fields should at least identify modality, N, query ID, index, measure, repetition, k, search parameters, elapsed time, recall and status. Keep construction and memory results in a companion table so they are not accidentally counted once per query.

### 9.4 Required report output

Produce timing-versus-N charts for construction and queries, plus Recall@10 and memory comparisons, using panels for metrics. Add a compact success/error gallery and a table of observed speed/recall/memory trade-offs and when each approach is preferable. Explain approximation and representation limits. Do not predetermine that HNSW wins or that a particular metric gives more meaningful images.

## 10. Implementation sequence and acceptance gates

| Phase | Work | Exit evidence |
|---|---|---|
| 1. Baseline and contracts — COMPLETED 2026-11-06 | Record actual Part 3 commit; confirm owner/seal; fix modality, score and SQL contracts; start data gate | No competing owners or ambiguous order semantics; tiny fixtures ready; evidence in [BLOQUE_1.md](BLOQUE_1.md) and [multimedia-contract.md](../docs/multimedia-contract.md) |
| 2. Features and exact scan — COMPLETED 2026-11-06 | SIFT/MFCC, fitted vocabularies, TF-IDF, vector persistence and exact top-k | Known histograms/scores, both modalities, reopened model consistency; evidence in [BLOQUE_2.md](BLOQUE_2.md) |
| 3. IVF — COMPLETED 2026-11-06 | Coarse training, lists, metric routing and persistence | nprobe=nlist equals exact oracle for all three measures; limited probes measured; evidence in [BLOQUE_3.md](BLOQUE_3.md) |
| 4. HNSW — COMPLETED 2026-11-06 | Real hierarchy, graph construction/search and serialization | Structural invariants, reproducible reopening and measured recall; no disguised scan; evidence in [BLOQUE_4.md](BLOQUE_4.md) |
| 5. Integration | Single owner, guards, SQL, operator, API and simple results view | Both PDF examples work through UI; all mutation routes tested; existing behavior preserved |
| 6. Data and scale gate | Finish candidate validation, 10,000-object pilot and resource assessment | Feasibility PASS, frozen 100,000 valid objects and query manifests before final benchmark |
| 7. Measurements | Run required matrix, independent reference, memory and gallery | Complete raw results at all three sizes, honest failures and reproducible figures |
| 8. Delivery | README, incremental report, demo and regression | Final checklist complete with evidence links |

Begin data feasibility early while developing on fixtures; do not wait until the UI is finished to discover that the corpus or own HNSW cannot meet the scale. No time estimates are asserted before the pilot.

## 11. Tests that address actual risks

- **Representation:** descriptor-to-centroid assignments, repeated word counts, df by object rather than descriptor count, TF-IDF by hand, query/model compatibility and vocabulary-versus-IVF centroid distinction.
- **Measures:** vectors whose dot/cosine/Euclidean rankings differ; Euclidean negative scores; finite values, zero norms, duplicate scores, k>N and explicit invalid k handling. Compare with independent scalar formulas.
- **IVF:** all objects assigned once; valid offsets; empty clusters/lists; complete probing equals exact results for every measure; fewer-than-k candidate handling records extra probes.
- **HNSW:** multiple layers on an adequate fixture; valid entry point/links/degrees, fixed-seed construction, query-local visited state, known-neighbor recovery and approximate recall against scan. Do not require every approximate query to match exactly.
- **SQL:** both literal PDF examples, score alias and DESC, hidden ID tie-break, LIMIT after k selection, rejection of unsupported order/filter combinations, EXPLAIN versus ANALYZE and honest scan toggle.
- **Persistence:** new-process open through `api.database.Database`; unchanged model/vectors/IDs/scores; original build files absent from temporary directories; malformed manifests, missing graph/list files, wrong dimensions and partial builds rejected. No retraining on open.
- **Immutability:** audit every supported mutation route from Part 3 plus media/vector/index handles. Rejections must leave counts and hashes unchanged before/after reopening, including `--allow-writes`; ordinary relational tables remain writable.
- **API/media:** registered filenames and uploaded keys resolve consistently; invalid keys and traversal rejected; actual MP3 query decodes; wrong modality errors; gallery/audio playback and cleanup work on Windows.
- **Regression:** run applicable Parts 1–3 and frontend checks after integration. Keep the 100,000-object experiment out of quick unit tests.

## 12. Definition of done

- [ ] Required scope is images **and audio**; video is not presented as implemented.
- [ ] ExtractFeatures produces persisted K-dimensional TF-IDF histograms using SIFT/MFCC and fitted K-Means vocabularies.
- [ ] Own IVF and genuine multilayer HNSW build, reopen and search correctly.
- [ ] Both indexes support Euclidean, dot and cosine with explicit score semantics.
- [ ] Exact scan supplies an independent neighbor reference and the no-index UI path.
- [ ] Both assignment SQL examples work through the existing owner, API and interface.
- [ ] Published collection policy is enforced by the engine on every supported mutation path, including after reopen.
- [ ] Feasibility gate passed on actual media; 1,000/10,000/100,000 counts refer to objects, not descriptors or duplicated padding.
- [ ] IVF/HNSW × Euclidean/cosine at k=10 measured at all three sizes; audio functional coverage and the chosen experimental modality are explicit.
- [ ] Construction/query timing, Recall@10 and memory are reported with raw data and boundaries.
- [ ] Figures, success/error gallery, recommendation table and limitations are included in the incremental report.
- [ ] README explains architecture, dependencies, preparation, opening and query commands; all command examples have been run before delivery.
- [ ] Demonstration prepared for the project's combined 5–10-minute video and final presentation, without inventing an extra Part 4-only duration requirement.
- [ ] Existing functionality passes regression checks.

Returning a few similar images is not sufficient: the persistent engine path, audio requirement and full experimental evidence are part of completion.

## 13. Sources and provenance

Normative source: `Proyecto_Final.pdf`, §2.4.1–2.4.4 (page 4), §3 deliverables and §4 milestones (page 5). The document explicitly specifies images/audio, not a Part 4 video requirement. No scored rubric appears in the supplied PDF.

Continuity source: current `PLAN_PARTE_03.md`, particularly §§3.3, 5.1–5.3 and its engine-level immutability contract. This plan assumes those features are complete; it does not reopen Part 3's implementation scope.

Technical references consulted for this plan:

- [Historical database owner](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/85db1bec94e0515dfff621dfa1ae8dece4c6ca08/api/database.py): concrete ownership/lifecycle reference, not evidence of current Part 3 code.
- [OpenCV SIFT reference](https://docs.opencv.org/4.12.0/d7/d60/classcv_1_1SIFT.html): descriptor extraction helper.
- [librosa MFCC reference](https://librosa.org/doc/0.10.2/generated/librosa.feature.mfcc.html): audio descriptor helper; pin the version actually used.
- [Malkov and Yashunin, HNSW](https://arxiv.org/abs/1603.09320): hierarchy, search and neighbor-selection reference.
- [FAISS index descriptions](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes) and [accuracy FAQ](https://github.com/facebookresearch/faiss/wiki/FAQ): IVF terminology and exhaustive-probing reference only, not permission to outsource the required implementation.
- [COCO official dataset site](https://cocodataset.org/#download): candidate media source; local feasibility remains unverified.

Vocabulary sizes, preprocessing caps, index defaults, 30 queries, three repetitions, the image-primary benchmark and the proposed recall target are explicit planning decisions. They must be documented and validated, not attributed to a rubric that does not state them.
