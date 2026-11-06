# Part 4 — Phase 4: HNSW

Date: 2026-11-06. Scope: phase 4 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10
under the user's authorization for phases 2–8.

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| Real hierarchy, construction, search, serialization | [engine/multimedia/hnsw.py](../engine/multimedia/hnsw.py) | Done |
| Structural invariants | `_validate_graph` on every build/open; `test_hnsw.py` | Done |
| Reproducible reopening | Fixed seed, identical arrays; reopen without insertion | Done |
| Measured recall, no disguised scan | `test_hnsw.py` against `VectorScan` | Done on synthetic data; scale numbers are phase 7 |

## Design (Malkov & Yashunin, arXiv:1603.09320)

- **Levels:** seeded `floor(−ln U · mL)` with `mL = 1/ln M`, capped at 16.
  The entry point is an element on the top layer.
- **Insertion (Algorithm 1):**
  - greedy descent with ef = 1 down to the element's level;
  - best-first search with `efConstruction` on each lower layer (Algorithm 2);
  - neighbour choice with the heuristic of Algorithm 4.
- **Links:** reciprocal. A node that exceeds its cap (M on upper layers,
  M0 = 2M on layer 0) is shrunk with the same heuristic.
- **Search:**
  - greedy descent to layer 1, then layer 0 with `efSearch = max(64, k)`;
  - the ef candidates are rescored exactly on the stored vectors, and the
    top-k (score DESC, id ASC) is returned;
  - the result reports efSearch, the maximum level, the candidates, the
    distance evaluations and a `shortfall` flag. There is never a silent
    fallback to a scan.
- **Thread safety:** visited arrays and evaluation counters are local to each
  search, so concurrent readers are safe (tested with 8 threads).
- **Persistence:**
  - `levels.npy` and `layer0.npy` (N × M0, padded with −1);
  - `nodes_l.npy` and `links_l.npy` for each upper layer;
  - a manifest with parameters, entry point, statistics (edges, nodes per
    layer, nodes reachable from the entry on layer 0, construction distance
    evaluations), checksums and the vector store identity.
- **Validation on open:** shapes, padding, ranges, self and duplicate links,
  layer membership, entry point on the top layer, and layer counts.

## Findings while testing

1. **Out-of-distribution queries.** Random dense queries over sparse data gave
   a Euclidean Recall@10 of 0.74 at 20,000 vectors. Queries drawn from the data
   distribution gave 0.97 (ef 64) to 0.997 (ef 256). The real benchmark uses
   real images as queries.
2. **keepPrunedConnections.** Without it, the heuristic left degrees as low as
   1 and 26 of 20,000 nodes unreachable. With it (paper option), the minimum
   degree on layer 0 is 16, 3 of 20,000 nodes are unreachable, and recall at
   ef 64 rises to 0.987. Construction is about twice as slow (90 s for 20,000
   vectors of dimension 64). Reachability is now recorded in every manifest.
3. **Dot product.** Building on −dot directly left 198 of 1,500 test nodes
   unreachable, because high-norm vectors attract every link. The dot graph is
   now built on augmented vectors `[x, sqrt(M² − ‖x‖²)]` with queries `[q, 0]`
   (Bachrach et al., 2014). There, `‖q' − x'‖² = ‖q‖² + M² − 2 q·x`, so the
   order is exactly descending dot, and the graph is built on a true metric.
   - Reachability became 1,499 of 1,500.
   - Recall at M = 16 is 0.996.
   - Maximum inner product search remains harder: with M = 8 it needs ef 128
     to exceed 0.9.

## Regression

| Check | Result |
|---|---|
| `tests/multimedia` (Python 3.12) | 185 passed |
| Full suite, Python 3.12, `-n 4 -W error` | **3,746 passed** (80.62 s) |
