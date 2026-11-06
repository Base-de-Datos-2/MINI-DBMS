# Part 4 — Phase 6: data and scale gate

Date: 2026-11-06. Scope: phase 6 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10
under the user's authorization for phases 2–8.

**Result: [multimedia_feasibility.json](../docs/implementacion/evidencias/multimedia/multimedia_feasibility.json)
is PASS.** All seven checks of plan §3.2 are computed by
[gate.py](../benchmarks/multimedia/gate.py) from files on disk.

| Check | Measured evidence |
|---|---|
| Accessible media | 100,080 COCO 2017 train originals downloaded one by one, each with its COCO URL, license and SHA-256. The stored ≤512 px JPEG copies take 5.5 GB. |
| Valid scale | 100,000 gallery images, all with finite, nonzero TF-IDF vectors. 8 byte-identical originals were rejected as duplicates. 1 image without any SIFT keypoint (COCO 456425) was rejected and replaced by the next candidate of the seeded permutation. |
| Experimental split | Nested prefixes 1,000 ⊂ 10,000 ⊂ 100,000, 30 query and 50 tuning images taken from the end of the permutation. Ids are disjoint and no original is byte-identical across sets. The replacement sits at position 57,889, so the 1k and 10k subsets did not change. |
| Real pipeline | Every image passed SIFT and the vocabulary. 100,000 `imagenes` rows were inserted into a Heap and reopened intact (sample checked). |
| Audio path | 30 gallery and 5 query FMA clips (MP3, CC BY, 8 genres) decode and pass MFCC. On the published demo collection, 4 of 5 queries rank the same song first and 1 ranks it second. |
| Resources | Measured: extraction of all images, the vocabulary and pilot builds at 1k and 10k. The 100k projection fits in memory and time (table below). |
| Persistence | Hashes and sizes of the split, codebook, counts and order arrays. The 10k model and store reopen with `verify=True` and without training. |

## Acquisition

- **Images ([coco.py](../benchmarks/multimedia/coco.py)).**
  - `captions_train2017.json` (inside the 253 MB annotations zip) gives the
    image list, licenses and URLs.
  - A seeded permutation (20261106) of all 118,287 train images picks the
    candidates.
  - Each original is hashed and decoded, then stored as an aspect-preserving
    colour copy with a longest side of ≤512 px, at JPEG quality 90.
  - The run took 33.5 min with 32 threads. The downloaded originals were never
    kept together on disk.
  - `--reject-from` appends feature-stage rejections to the append-only log,
    and the next run fetches replacements.
- **Audio ([fma.py](../benchmarks/multimedia/fma.py)).**
  - Both FMA zips are read as remote files through HTTP byte ranges (Zip64
    handled by `zipfile`): 75 MB transferred instead of 7.7 GB.
  - Of the 221 `small` tracks with a Creative Commons license that allows
    derivatives, 30 are chosen round-robin across genres.
  - Gallery clips are seconds 0–10 of each excerpt. Queries are seconds 15–25
    of 5 of the same tracks: a different segment of a song that is in the
    gallery. The first query is `audio_query.mp3`.
  - Re-encoding: mono, 22,050 Hz, 64 kbit/s.
  - A unit test later found that `RemoteFile.readinto` returned short reads
    across a 1 MiB block boundary; it is fixed. The acquired clips were valid:
    `zipfile` checks each member's CRC, and all 35 clips decode.
- **Demo media ([demo_assets.py](../benchmarks/multimedia/demo_assets.py)),
  committed in `data/multimedia_demo/` (10 MB).**
  - The first 120 gallery images whose license allows derivative works, plus
    5 held-out queries (`foto_consulta.jpg` is the first).
  - The 35 audio clips.
  - `collections.json` for `scripts/setup_multimedia.py --assets`, and
    `ATTRIBUTION.md`.

## Features ([features.py](../benchmarks/multimedia/features.py))

- **Vocabulary.**
  - SIFT on the first 1,000 gallery images: 251,019 descriptors, 100,000 of
    them sampled with a seed.
  - scikit-learn K-Means with K = 256 and 3 restarts: 29.7 s, peak 693 MiB.
  - The vocabulary is reused at every size; IDF is recomputed per size (plan §4.3).
- **Word counts.**
  - All 100,080 images were processed in 62.8 min with 7 processes, averaging
    250.6 descriptors per image (93,891 images reached the 256 cap).
  - The load average reached about 27 on 8 logical CPUs, because each worker
    also used multithreaded BLAS. The per-image CPU time recorded (0.26 s on
    average) is therefore inflated by oversubscription; wall time is what
    counts for the projection.
  - The replacement image was extracted afterwards with `--reuse`, which keeps
    the other 100,079 rows; the complete-pass report is
    `counts.first_pass.json`.
- **Storage.** Counts, codebook and order arrays are in
  `data/generated/multimedia/features/` (about 100 MB, not committed); their
  hashes are in the gate file.

## Pilot and frozen parameters

Builds were run in fresh processes by
[experiment.py](../benchmarks/multimedia/experiment.py), with VmHWM reset before
each build. Results are in
[2026-11-06](../benchmarks/results/multimedia/2026-11-06/); the pilot environment
is in `environment_pilot.json`.

| Config | 1k build | 10k build | 10k peak RSS | Projection to 100k (n log n time, linear memory) |
|---|---:|---:|---:|---:|
| IVF euclidean | 0.14 s | 4.05 s | 157 MiB | 51 s, 1.2 GiB |
| IVF cosine | 0.18 s | 3.90 s | 163 MiB | 49 s, 1.3 GiB |
| HNSW euclidean | 4.80 s | 59.1 s | 90 MiB | 12.3 min, 0.6 GiB |
| HNSW cosine | 3.31 s | 42.7 s | 115 MiB | 8.9 min, 0.8 GiB |

**Tuning.** Run on the 50 tuning images at 10k, never on the final queries:

| Config | Default parameters | One alternative | Decision |
|---|---|---|---|
| HNSW euclidean | 0.920 (ef 64) | 0.966 (ef 128) | Keep the default: already above the 0.90 target |
| HNSW cosine | 0.938 (ef 64) | 0.968 (ef 128) | Keep the default |
| IVF euclidean | 0.728 (nprobe 8) | 0.854 (nprobe 16) | **Freeze nprobe = 16**, the single allowed adjustment |
| IVF cosine | 0.732 (nprobe 8) | 0.882 (nprobe 16) | Same |

`nprobe` stays fixed at 16 for every N. Because nlist grows (32, 100, 316),
the fraction of lists probed falls as N grows; phase 7 reports that trade-off
as measured.

## Tests

`tests/benchmarks/test_multimedia_experiment.py` (7 tests) covers:
- the seeded permutation;
- the FMA license filter and the genre spread;
- `RemoteFile` reads across blocks (the test that found the bug above);
- the experiment configurations;
- reuse of results already produced;
- the procfs memory measurements.
