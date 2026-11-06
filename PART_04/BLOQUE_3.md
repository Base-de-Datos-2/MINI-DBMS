# Part 4 — Phase 3: IVF

Date: 2026-11-06. Scope: phase 3 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10
under the user's authorization for phases 2–8.

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| Coarse training, lists, metric routing, persistence | [engine/multimedia/ivf.py](../engine/multimedia/ivf.py), [kmeans.py](../engine/multimedia/kmeans.py) | Done |
| `nprobe = nlist` equals the exact oracle for all three measures | `test_ivf.py` | Done: identical ids **and** scores, including ties |
| Limited probes measured | `test_ivf.py` (recall, effective probes, candidates) | Done on fixtures; scale numbers belong to phase 7 |

## Own K-Means (decision D1)

The vocabulary keeps scikit-learn (phase 2). The IVF partition uses
[kmeans.py](../engine/multimedia/kmeans.py), since it is part of the index the
assignment asks us to implement:

- seeded k-means++ initialization;
- Lloyd iterations, with squared distances in float64 batches;
- deterministic refill of empty clusters with the farthest point;
- a cluster left empty keeps its previous center;
- the best of 3 seeded restarts.

On ten separated Gaussian blobs it reaches scikit-learn's optimum
(`n_init=10`) with every seed tried. A single start sometimes ended in a local
optimum (seed 3 gave 4.8 times the inertia), which is why the restarts exist.

## IVF design

- **Two coarse spaces.** `raw` (unnormalized vectors) serves Euclidean and
  dot; `unit` (L2-normalized vectors) serves cosine. Only the spaces needed by
  the requested metrics are built.
- **Build.** Train on a seeded sample of at most 50,000 vectors, assign every
  vector to its nearest center (L2), and persist `centers_*.npy`,
  `offsets_*.npy` and `rows_*.npy` (rows grouped by list, ascending).
  - The manifest records `nlist`, `nprobe`, the seed, training statistics
    (iterations, inertia, empty lists, largest list) and checksums.
  - It is bound to the vector store's identity: model fingerprint, shape, and
    the `ids` and `vectors` checksums.
- **Defaults.** `nlist = min(N, max(1, round(√N)))` and `nprobe = min(8, nlist)`.
- **Search.**
  - Order the lists by the query objective against the centers: squared
    distance for Euclidean, 1 − cosine for cosine, −dot for dot. Ties go to
    the lower list.
  - Probe `nprobe` lists, and keep probing while there are fewer than
    `min(k, N)` candidates.
  - Score every candidate exactly on the stored vectors, then keep the
    best-first top-k.
  - The result reports the requested and effective `nprobe`, the candidates
    and the centroid evaluations.
- **Exact scores.** `batch_scores` now uses `einsum` for the dot product, so a
  row's score does not depend on which rows are computed with it. This is what
  makes exhaustive IVF equal to `VectorScan` bit for bit.
- **Open.** Checks version, store binding, shapes, offsets and that every row
  appears exactly once. `verify=True` also rehashes. Opening never retrains,
  which a test enforces by disabling `kmeans`.

A shared [files.py](../engine/multimedia/files.py) now holds the write-once,
checksummed array and JSON helpers used by the feature model, the vector store
and the IVF index.

## Regression

| Check | Result |
|---|---|
| `tests/multimedia` (Python 3.12) | 163 passed |
| Full suite, Python 3.12, `-n 4 -W error` | **3,724 passed** (86.82 s) |
