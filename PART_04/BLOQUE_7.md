# Part 4 — Phase 7: measurements

Date: 2026-11-06. Scope: phase 7 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10
under the user's authorization for phases 2–8. Report:
[docs/EXPERIMENTOS_MULTIMEDIA.md](../docs/EXPERIMENTOS_MULTIMEDIA.md).

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| Required matrix at all three sizes | [2026-11-06](../benchmarks/results/multimedia/2026-11-06/): 12 builds, 36 query runs | Done: 1,080 timed searches, 30 distinct queries per run |
| Independent reference | `exact_top10_<N>.json` (VectorScan, verified store) | Done; Recall@10 computed against it |
| Memory | VmHWM reset per phase, fresh process per build and per query run | Done |
| Gallery | [galeria.png](../docs/figuras/multimedia/galeria.png) | Done: a representation failure with perfect recall, and an index failure |
| Honest failures, reproducible figures | Recall drop at 100k reported and diagnosed, never retuned | Done |

## Run

- **Command:** `python -m benchmarks.multimedia.experiment run --nprobe 16`,
  run at commit `26d1e2c` (phase 6). The only untracked file was
  `results.py`, which is not part of the measured code.
- **Reuse:** the 1k and 10k builds and exact references were reused from the
  phase 6 pilot, with the same engine code (`environment_pilot.json`). The
  100k builds, all exact references not yet computed, and every query run were
  produced by this run.
- **Isolation:** each build and each query run is a separate process. Query
  runs do a warm-up pass and then one timed pass, and the order of the four
  configurations rotates in each of the 3 repetitions.
- **Frozen parameters:** IVF `nprobe = 16` and HNSW `efSearch = max(64, k)`,
  chosen on the tuning set in phase 6.
- **Determinism:** results are identical across repetitions in all 12
  (size, configuration) pairs. No query reported `shortfall`.

## Main results (N = 100,000)

| | IVF euclidean | IVF cosine | HNSW euclidean | HNSW cosine | VectorScan euc / cos |
|---|---:|---:|---:|---:|---:|
| Build | 61.2 s | 57.4 s | 708.6 s | 496.0 s | — |
| Query mean | 8.18 ms | 3.66 ms | 1.94 ms | 1.73 ms | 73.1 / 29.9 ms |
| Recall@10 | 0.723 | 0.800 | 0.683 | 0.693 | 1 |
| Index files | 1.4 MiB | 1.4 MiB | 12.7 MiB | 12.7 MiB | vectors 97.7 MiB shared |
| Loaded / query peak RSS | 38 / 172 MiB | 38 / 158 MiB | 256 / 258 MiB | 256 / 258 MiB | — |

## Findings

1. **Recall falls with N under fixed parameters**, for both indexes. For
   HNSW it went from 0.93 at 10k to 0.69 at 100k. Before reporting it, it was
   checked as a possible defect:
   - layer-0 reachability is 99.93 % (euclidean) and 99.96 % (cosine), and
     the hierarchy has 5 layers;
   - recall rises steadily with efSearch (0.69, 0.82, 0.92, 0.97 at
     ef 64, 128, 256, 512).
   - The cause is distance concentration: in cosine, the exact 1st and 10th
     neighbours differ by only 0.026 on average.

   The search-width sweep
   ([diagnostic_search_width_100000.json](../benchmarks/results/multimedia/2026-11-06/diagnostic_search_width_100000.json))
   is a post-hoc diagnostic on the final queries. It is reported as such and
   does not replace the frozen measurements.
2. **Euclidean versus cosine in time** is an implementation effect. The
   Euclidean score materializes `x − q` for each block of rows, while cosine
   is a dot product. This shows in VectorScan and IVF, but barely in HNSW.
3. **Gallery.** A query with perfect recall whose exact neighbours are
   visually unrelated: a keyboard matched with an owl, a pizza, signs, ducks
   and a lit building. Bag-of-SIFT-words similarity is not semantic
   similarity. The other case is an index miss (recall 0.4). The verifiable
   perceptual success is the audio collection: 4 of 5 queries rank the same
   song first.
4. **During the phase.** The gallery loader read the exact top-10 lists from
   the wrong file. The lists are now copied into the results directory
   (`exact_top10_<N>.json`), which also makes the reference reproducible. The
   gallery titles were also reworded so that a representation failure is not
   labelled "best match".

## Outputs

- **[benchmarks/multimedia/results.py](../benchmarks/multimedia/results.py).**
  Refuses incomplete matrices, writes the CSV tables (summary, per-query rows
  with all fields required by plan §9.3, and builds), the four figures in the
  palette validated in Part 3, the gallery, and `resumen_multimedia.json`.
- **[docs/figuras/multimedia/](../docs/figuras/multimedia/).**
  `construccion.png`, `consultas.png`, `recall.png`, `memoria.png`,
  `galeria.png` and the CSV/JSON tables.
