# ETAPA_10.md

## Stage 10 — Experiments, Integration, and Delivery

**Revision:** 2026-10-01  
**Part:** Relational Database  
**Starting point:** Stage 9 formally closed on 2026-10-01 (`docs/ETAPA_09_AUDIT.md`)  
**Status:** **Formally closed 2026-10-04** — Tasks 10.1–10.14 and all Definition of Done criteria complete; Part 1 is complete. Evidence: `docs/ETAPA_10_AUDIT.md`. Every change to earlier stages is logged in `docs/ETAPA_10_CAMBIOS_MODULOS_PREVIOS.md`.  
**Objective:** Produce the required comparative evidence (REQUIREMENTS §9), prove that every Part 1 layer works together, and assemble the delivery material (REQUIREMENTS §10).

## 1. Sources and scope

- `REQUIREMENTS.md` §9 (experimental comparison), §10 (delivery) and §14 (Part 1 checklist).
- `PART_01/PLAN_PARTE_01.md` §15 (Stage 10 roadmap).
- `PROJECT_CONTEXT.md` for the implemented storage, index, operator and engine contracts.
- `AGENTS.md` benchmark policy: separate code, reproducible datasets, recorded configuration, no fabricated values.

Required comparisons, verbatim in substance:

| Experiment | Structures | Measurements | Sizes |
|---|---|---|---|
| File organization | Heap File vs Paged Sequential File | insertion time, primary-key search time, disk space, reorganization time | 1,000 / 10,000 / 100,000 |
| Index comparison | Clustered B+, unclustered B+, Extendible Hashing | construction time, query time (equality, range, sorting), extra disk space, behavior under frequent insertions/deletions | same sizes |
| Presentation | — | comparative charts, advantages/disadvantages table, conclusions on when to use each structure | — |

Out of scope: Part 2+ features, changing algorithms to win a benchmark, a cost-based optimizer.

## 2. Task 10.1 — Inspection and feasibility (done 2026-10-01)

`benchmarks/` contains only `.gitkeep`; no benchmark code, dataset generator or
result exists. `matplotlib` is not installed. Machine used: Linux (WSL2), 8 CPUs,
7 GiB RAM, Python 3.11.9.

Measured on the closed Stage 2–5 code (schema `id INTEGER, name VARCHAR, age INTEGER`):

| Operation | Rows | Measured cost |
|---|---:|---:|
| HeapFile insert | 1,000 / 5,000 | ~3.0 ms/row (linear) |
| PagedSequentialFile insert, random order | 500 / 1,000 | ~52 ms/row; 262 pages for 1,000 rows |
| PagedSequentialFile insert, ascending order | 1,000 | ~125 ms/row; 8 pages |
| Unclustered B+ build from a Heap | 1,000 / 5,000 | ~3.7–4.3 ms/row |
| Extendible Hash build from a Heap | 1,000 / 5,000 | ~4.4–4.6 ms/row |
| Hash index reopen (coverage check) | 1,000 / 5,000 | ~2.0–2.7 ms/row |
| Heap primary-key search by full scan | 2,000 | ~25 ms/key |

**Root cause.** `engine/storage/page.py::Page._inspect` re-validates the whole
page (header plus every slot) on each call, and `read`, `insert`, `delete`,
`header` and `slots` each call it. Walking the k records of one page therefore
costs O(k²) validations; profiling a sequential insert attributes over 90 % of
its time to `_inspect`, `SlotEntry.deserialize` and `validate_page_layout`.

**Consequence.** At the measured rates one 100,000-row Paged Sequential load
takes roughly 1.5–3.5 hours, and its cost grows with the file. With repetitions
and three sizes, the required experiment does not fit in a working day.

**Prototype (not committed).** Memoizing `_inspect` per page-buffer state,
outside the repository, gave on 2,000 rows: sequential ascending 7.5 ms/row
(16× faster), sequential random 9.5 ms/row, Heap 0.25 ms/row (12× faster).
Logical results were identical.

Other observations to carry into the analysis, not to "fix" silently:

- `PagedSequentialFile.search(key)` is a linear scan with early stop, not a
  binary search; a primary-key search on the sequential file is therefore O(n).
- Random-order sequential insertion leaves many partly filled pages
  (262 pages for 1,000 rows versus 8 for ascending input); reorganization is
  what recovers that space.

## 3. Task 10.2 and the remaining decision

**Task 10.2 — done (2026-10-02, approved by the user after checking the
official assignment).** `Proyecto_Final (3).docx` §2.1.1 requires a Heap with
free-space reuse and a sequential file with ordered insertion, lazy deletion
and reorganization, and §2.1.6 measures those techniques. It does not forbid
internal optimizations, and `REQUIREMENTS.md` matches it for Part 1. `Page` now
reuses its full validation while the buffer bytes are unchanged; see
`PROJECT_CONTEXT.md`, section "Page". Evidence:

| Check | Before | After |
|---|---:|---:|
| HeapFile insert, 5,000 rows | ~3.0 ms/row | ~0.33 ms/row |
| Unclustered B+ / Hash build, 5,000 rows | ~4.3 / ~4.6 ms/row | ~3.2 / ~3.9 ms/row |
| Complete strict suite | 2889 passed in 276.8 s | 2889 passed in 138.6 s |
| Storage suite incl. in-place corruption cases | — | 952 passed; 2 new regression tests in `tests/storage/test_page.py` |

**Task 10.2b — done (2026-10-02, approved by the user; option A below).** The sequential file is still impractical at
100,000 rows, now because of its insertion algorithm:
`PagedSequentialFile._find_insertion_target` reads pages from the first one and
decodes and order-checks every record until it meets a larger key. Each insert
is O(n) and a load is O(n²). Measured after 10.2 on ascending input: 17, 33, 48
and 63 ms/row while the file grows from 2,000 to 8,000 rows. Extrapolated, one
100,000-row load takes roughly 5–11 hours.

| Option | Effect |
|---|---|
| **A (recommended)** — locate the target page by binary search over the ordered pages (reading only their boundary keys), and use the same search for `search(key)` | Still "inserción manteniendo el orden"; pages, lazy deletion, the 30 % reorganization and the file format stay. Per insert, O(log P) page reads plus the target page. Global order is still validated on reopen and by the existing validation paths, no longer on every insert. A Stage 3 algorithm change; it needs the complete strict suite and is reported in the experiment. |
| B — measure the current algorithm and run 100,000 rows once, overnight | Truthful but slow, with no repetitions at 100,000; the O(n) insertion becomes a reported finding. |
| C — measure 1,000 and 10,000 rows with the current algorithm and extrapolate 100,000 | Fast, but REQUIREMENTS §9 asks for measured 100,000-row results. |

Result of 10.2b: `_find_insertion_target` and `search` use binary search over
the ordered pages (`PROJECT_CONTEXT.md`, "Paged Sequential policy"); 7 new
tests compare the file with a sorted model under random insertions,
duplicates and deletions that empty whole pages, and bound the pages read.
Complete strict suite: **2898 passed**. Measured with 20,000 rows of the
benchmark schema:

| Load order | Cost per row while the file grows | Data pages at 20,000 rows | Primary-key search |
|---|---|---:|---:|
| Ascending | 9.5, 9.6, 9.8, 9.8 ms (flat) | 234 | 2.5 ms |
| Random | 8.8, 16.2, 31.6, 51.7 ms (growing) | 4,149 | 0.9 ms |

Ascending loads are now linear (100,000 rows ≈ 16 min). Random-order loads are
still super-linear because of the split policy, not page location:

**Task 10.2c — done (2026-10-02, approved by the user; option A below).** `_partition_items` fills the first page to
capacity and puts the overflow (usually one record) on a new page. With random
keys those pages stay almost empty (about 5 rows per page versus 86 with
ascending input), and every split shifts all following pages one position
because data pages are contiguous. Both effects grow with the file.

| Option | Effect |
|---|---|
| **A (recommended)** — split a full page into two halves of similar size | Pages stay about half full or more, so splits and suffix shifts become far rarer. Ordering, lazy deletion, retained tombstones, the 30 % reorganization, the contiguous layout and the file format stay. Stage 3 algorithm change, full strict suite required. |
| B — keep the policy; measure random-order loads at 1,000 and 10,000 rows and ascending loads at all three sizes | No engine change; the random-order 100,000-row load is reported as impractical with its measured growth. |
| C — keep the policy and run the random-order 100,000-row load once, overnight | Truthful, very slow, no repetitions. |

Result of 10.2c: `_partition_items` spreads a split over the minimum page
count by cumulative bytes, and appends at the end keep the greedy fill
(`PROJECT_CONTEXT.md`, "Paged Sequential policy"). 3 new tests in
`tests/storage/test_paged_sequential_split.py`; complete strict suite **2901
passed**. Random-order load of the same 20,000 rows:

| Measure | Before 10.2c | After 10.2c |
|---|---:|---:|
| Cost per row in the four 5,000-row blocks | 8.8, 16.2, 31.6, 51.7 ms | 11.5, 12.2, 12.2, 13.4 ms |
| Data pages at 20,000 rows | 4,149 | 333 |
| Primary-key search | 0.9 ms | 1.5 ms |
| Ascending load | 9.5–9.8 ms/row, 234 pages | unchanged layout (234 pages) |

The remaining slow growth comes from the contiguous layout: a split still
shifts the following pages. That is the file's design and is reported, not
changed.

**Task 10.2d — done (2026-10-02, approved by the user; option A, extended to the
Hash for a fair comparison). Found in the first official 1,000-row results.** B+ index costs are dominated by validation, not by the tree
algorithm, in closed Stage 4 code:

1. `range_records` (clustered and unclustered) re-runs a complete exact
   `tree.search(key)` for every row it returns, to prove the RID is not stale.
   A range of k rows costs k full descents instead of one descent plus a leaf
   walk.
2. Every B+ node read re-validates every key of the node (about 3 ms per node
   read; 144,240 key validations to read 204 nodes for one 100-row range).

Median of 5 repetitions at 1,000 rows:

| Query | Clustered B+ | Unclustered B+ | Hash (heap scan + filter) |
|---|---:|---:|---:|
| Range, 10 % (100 rows) | 178 ms | 208 ms | 8.8 ms |
| Ordered retrieval, whole table | 1.81 s | 2.03 s | 0.06 s (ExternalSort) |
| Equality, one key | 1.82 ms | 2.07 ms | 1.89 ms |

| Option | Effect |
|---|---|
| **A (recommended)** — reuse the validated keys of an unchanged node (as `Page` does) and, in `range_records`, check each row against the leaf entry it came from instead of a second full descent | Same guarantees: a stale RID or a key outside the bounds still raises. The experiment then compares B+ against Hash/scan on algorithmic cost. Stage 4 change; complete strict suite required; the official runs restart. |
| B — keep Stage 4 as is | The report must state that B+ ranges and ordered retrieval lose to a full scan because of per-row re-verification, which is a property of this implementation, not of B+ trees. |

## 4. Benchmark contract (frozen by Task 10.3, 2026-10-02)

Implemented in `benchmarks/` (`python -m benchmarks run --help`); tested by
`tests/benchmarks/test_benchmarks.py`.

- **Dataset** (`benchmarks/datasets.py`). Schema `id INTEGER` (unique key),
  `name VARCHAR`, `career VARCHAR`, `age INTEGER`, `score INTEGER`. Seed
  `20,261,000 + size`; `id` is a random permutation of `1..size`, which is the
  arrival order used by every load. The same logical rows feed every
  structure; generation is never inside a measurement.
- **Isolation.** Every measured run builds fresh files in its own temporary
  directory under `data/generated/bench/` and deletes it afterwards. In the
  index experiment each structure works on its own copy of the base file.
- **Timing.** `time.perf_counter`, structure-level APIs (the storage and index
  classes the planner uses). Sorting without an ordered index goes through the
  real SQL engine (`SELECT ... ORDER BY` → `ExternalSort`, default memory
  budget). Page cache is warm: files are freshly written.
- **Repetitions.** 5 for 1,000 and 10,000 rows; 3 for 100,000 rows. Reports
  use median, minimum and maximum.
- **File organization** (`benchmarks/file_organization.py`): load of all rows
  (random order; the sequential file also ascending), 100 present + 20 absent
  primary-key searches, file bytes and pages, lazy deletion of 40 % of the rows
  with the resulting wasted-space ratio, `reorganize()` time and sizes, and for
  the Heap the reinsertion of as many new rows to show free-space reuse.
- **Indexes** (`benchmarks/indexes.py`): build time, index bytes and entries;
  200 present + 50 absent equality searches; 10 ranges at each selectivity of
  0.1 %, 1 % and 10 %; full ordered retrieval; a mixed workload alternating
  insertions of new keys and deletions of random existing keys, bounded by 200
  operations **and** a 60-second budget, followed by `validate_structure()`.
  Extendible Hashing has no order: its range rows measure a Heap scan with a
  filter and its sorting row measures the SQL engine's ExternalSort; each row
  records that access path.
- **Output.** One JSON line per measurement with configuration, environment
  (platform, Python, CPU count, git commit, dirty flag and `source_sha256`, a
  digest of every `engine/` and `benchmarks/` source file) and raw values.
  Official results (versioned): `benchmarks/results/part1_results.jsonl`
  (1,000 and 10,000 rows, run `official-1k-10k`) and, for 100,000 rows, one
  file per experiment, `part1_results_100k_files.jsonl` and
  `part1_results_100k_indexes.jsonl`, produced by two processes running in
  parallel on separate cores (one core each). Scratch runs go to
  `benchmarks/results/scratch/` (ignored); pre-10.2d runs are in
  `benchmarks/results/archive/`.
- **Provenance note.** Run `official-1k-10k` recorded `source_sha256`
  `d864d634…`. Later code differs from it only in the last line of
  `benchmarks/report.py::_format` (number formatting of the report, never
  executed during a measurement); recomputing the digest with that line
  restored gives `d864d634…` again. The 100,000-row runs
  (`official-100k-files`, `official-100k-indexes`) ran on clean commit
  `075eae8` with `source_sha256` `1697f753…`. Afterwards only
  `benchmarks/report.py` changed again (direct labels pushed apart when two
  lines end at the same value); the report is never executed during a
  measurement.

Findings already visible in the smoke run (300 rows) were confirmed at 1,000
and 10,000 rows after Task 10.2d: the Heap reuses freed space (no growth when
reinserting after deletions); full ordered retrieval through a B+ is still
slower than a Heap scan plus `ExternalSort` (one record read per RID versus a
sequential scan and an in-memory sort), and a 10 % range loses to a scan while
a 1 % range wins; the clustered B+ rebuilds itself after every insertion
(sequential RIDs move), so it completes far fewer workload operations within
the budget.

## 5. Task sequence

| Task | Work | Depends on |
|---|---|---|
| 10.1 | Inspection and feasibility (Section 2) | — (done) |
| 10.2 | Page-validation cache (Section 3) | done 2026-10-02 |
| 10.2b | Sequential-file page location by binary search (Section 3) | done 2026-10-02 |
| 10.2c | Random-order sequential split policy (Section 3) | done 2026-10-02 |
| 10.2d | B+ node reuse and leaf-checked ranges; same reuse for Hash buckets (Section 3) | done 2026-10-02 |
| 10.3 | Freeze the benchmark contract (Section 4) | done 2026-10-02 |
| 10.4 | Dataset generator, harness, experiments and CLI, with tests | done 2026-10-02 |
| 10.5 | File-organization experiment: insertion, primary-key search (present and absent keys), disk space, reorganization time after lazily deleting 40 % of the rows (`reorganize()` is explicit by design; the measured wasted-space ratio and the 30 % predicate are recorded); Heap free-space reuse as its counterpart | done 2026-10-04 |
| 10.6 | Index construction and extra disk space | done 2026-10-04 |
| 10.7 | Index queries: equality (present/absent), ranges of three selectivities, ordered retrieval (clustered B+ scan, unclustered B+ ordered scan, Hash plus `ExternalSort`) | done 2026-10-04 |
| 10.8 | Frequent insertions/deletions on each index, with structure validation afterwards | done 2026-10-04 |
| 10.9 | SQL-level confirmation: the planner's chosen access path and plan for the same queries | done 2026-10-04 |
| 10.10 | Charts (matplotlib, `bench` optional dependency) and summary tables generated from results | done 2026-10-04 |
| 10.11 | Experiment report `docs/EXPERIMENTOS.md`: method, results, advantages/disadvantages table, conclusions that follow from the data | done 2026-10-04 |
| 10.12 | Final integration check of the full path (frontend → API → engine → operators → indexes/storage → pages → disk), restart, table loading, SQL errors, concurrency | done 2026-10-04 |
| 10.13 | Delivery documents: README/installation manual, architecture, data domain, algorithm explanations, incremental report, demo-video script and presentation outline | done 2026-10-04 |
| 10.14 | Stage 10 and Part 1 closure audit against REQUIREMENTS §14 | done 2026-10-04 |

## 6. Definition of Done

- [x] Datasets of 1,000, 10,000 and 100,000 rows are reproducible from their seeds.
- [x] Every REQUIREMENTS §9 measurement exists for every structure and size, from real runs.
- [x] Raw results, configuration and environment are stored and versioned.
- [x] Charts and tables are regenerated from raw results by one command.
- [x] Conclusions state when each structure is preferable and follow from the data.
- [x] Benchmark code stays outside `engine/` and `api/`.
- [x] The full-path integration check passes after a clean restart.
- [x] The complete strict test suite and frontend checks pass.
- [x] Delivery documents listed in REQUIREMENTS §10 exist (the video and the live presentation are recorded by the team).
- [x] `PROJECT_CONTEXT.md`, `PLAN_PARTE_01.md`, `AGENTS.md` and `README.md` record the closure.
