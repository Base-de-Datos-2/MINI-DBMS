# ETAPA_10.md

## Stage 10 — Experiments, Integration, and Delivery

**Revision:** 2026-10-01  
**Part:** Relational Database  
**Starting point:** Stage 9 formally closed on 2026-10-01 (`docs/ETAPA_09_AUDIT.md`)  
**Status:** Tasks 10.1, 10.2 and 10.2b complete (2026-10-02). **Task 10.2c needs a team decision** about random-order sequential loading (Section 3).  
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

**Task 10.2c — decision required.** `_partition_items` fills the first page to
capacity and puts the overflow (usually one record) on a new page. With random
keys those pages stay almost empty (about 5 rows per page versus 86 with
ascending input), and every split shifts all following pages one position
because data pages are contiguous. Both effects grow with the file.

| Option | Effect |
|---|---|
| **A (recommended)** — split a full page into two halves of similar size | Pages stay about half full or more, so splits and suffix shifts become far rarer. Ordering, lazy deletion, retained tombstones, the 30 % reorganization, the contiguous layout and the file format stay. Stage 3 algorithm change, full strict suite required. |
| B — keep the policy; measure random-order loads at 1,000 and 10,000 rows and ascending loads at all three sizes | No engine change; the random-order 100,000-row load is reported as impractical with its measured growth. |
| C — keep the policy and run the random-order 100,000-row load once, overnight | Truthful, very slow, no repetitions. |

## 4. Benchmark contract (frozen by Task 10.3)

Proposed defaults, to be confirmed in Task 10.3 after Task 10.2:

- **Dataset.** `id INTEGER` (unique key), `name VARCHAR`, `career VARCHAR`,
  `age INTEGER`, `score INTEGER`; generated by `benchmarks/datasets.py` from a
  fixed seed per size, with `id` a random permutation of `1..N`. The same
  logical rows feed every structure. Generation is timed separately and never
  inside a measurement.
- **Isolation.** Every measured run builds fresh files in its own temporary
  directory under `data/generated/bench/` (git-ignored) and deletes them after
  recording sizes.
- **Timing.** `time.perf_counter`; storage/index APIs are measured directly
  (structure-level comparison), and a smaller SQL-level check confirms that
  the planner chooses the same access paths (Task 10.9).
- **Repetitions.** 5 runs for 1,000 and 10,000 rows; 3 for 100,000 rows.
  Report median, minimum and maximum. Page cache state is documented (files
  are freshly written, so reads are warm).
- **Counters.** Besides time, record engine page counters and file bytes when
  the APIs expose them.
- **Output.** One JSON Lines file per run in `benchmarks/results/` with the
  environment (OS, CPU count, Python, git commit, dirty flag), configuration,
  structure, operation, size, repetition and raw values. Charts and tables are
  generated only from these files.

## 5. Task sequence

| Task | Work | Depends on |
|---|---|---|
| 10.1 | Inspection and feasibility (Section 2) | — (done) |
| 10.2 | Page-validation cache (Section 3) | done 2026-10-02 |
| 10.2b | Sequential-file page location by binary search (Section 3) | done 2026-10-02 |
| 10.2c | Random-order sequential split policy (Section 3) | team decision |
| 10.3 | Freeze the benchmark contract; scaling probe at 10,000 rows to budget 100,000 | 10.2c |
| 10.4 | Dataset generator and harness (`benchmarks/datasets.py`, `benchmarks/harness.py`), with tests | 10.3 |
| 10.5 | File-organization experiment: insertion, primary-key search (present and absent keys), disk space, reorganization after deletions above the 30 % threshold; Heap free-space reuse as its counterpart | 10.4 |
| 10.6 | Index construction and extra disk space | 10.4 |
| 10.7 | Index queries: equality (present/absent), ranges of three selectivities, ordered retrieval (clustered B+ scan, unclustered B+ ordered scan, Hash plus `ExternalSort`) | 10.6 |
| 10.8 | Frequent insertions/deletions on each index, with structure validation afterwards | 10.6 |
| 10.9 | SQL-level confirmation: the planner's chosen access path and plan for the same queries | 10.7 |
| 10.10 | Charts (matplotlib, `bench` optional dependency) and summary tables generated from results | 10.5–10.9 |
| 10.11 | Experiment report `docs/EXPERIMENTOS.md`: method, results, advantages/disadvantages table, conclusions that follow from the data | 10.10 |
| 10.12 | Final integration check of the full path (frontend → API → engine → operators → indexes/storage → pages → disk), restart, table loading, SQL errors, concurrency | 10.4 |
| 10.13 | Delivery documents: README/installation manual, architecture, data domain, algorithm explanations, incremental report, demo-video script and presentation outline | 10.11–10.12 |
| 10.14 | Stage 10 and Part 1 closure audit against REQUIREMENTS §14 | all |

## 6. Definition of Done

- [ ] Datasets of 1,000, 10,000 and 100,000 rows are reproducible from their seeds.
- [ ] Every REQUIREMENTS §9 measurement exists for every structure and size, from real runs.
- [ ] Raw results, configuration and environment are stored and versioned.
- [ ] Charts and tables are regenerated from raw results by one command.
- [ ] Conclusions state when each structure is preferable and follow from the data.
- [ ] Benchmark code stays outside `engine/` and `api/`.
- [ ] The full-path integration check passes after a clean restart.
- [ ] The complete strict test suite and frontend checks pass.
- [ ] Delivery documents listed in REQUIREMENTS §10 exist (the video and the live presentation are recorded by the team).
- [ ] `PROJECT_CONTEXT.md`, `PLAN_PARTE_01.md`, `AGENTS.md` and `README.md` record the closure.
