# Part 4 — Phase 1: baseline and contracts

Date: 2026-11-06. Scope: phase 1 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10,
explicitly requested by the user. Phases 2–8 are not included.

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| Actual Part 3 baseline recorded | `main` at `7766e22` (Part 3 closed, plan added) | Done |
| Owner and seal confirmed | [Contract §1](../docs/multimedia-contract.md#1-integration-map-inspected-not-assumed) | Done: one owner, generic storage seal |
| Modality, score and SQL contracts fixed | [docs/multimedia-contract.md](../docs/multimedia-contract.md), [engine/multimedia/contracts.py](../engine/multimedia/contracts.py) | Done |
| No competing owners or ambiguous order semantics | Contract §§1, 4, 5 | Done |
| Tiny fixtures ready | [tests/multimedia/fixtures/](../tests/multimedia/fixtures/README.md) | Done: 20 files, 392 KB |
| Data gate started | [multimedia_feasibility.json](../docs/implementacion/evidencias/multimedia/multimedia_feasibility.json) | Started, PENDING |

## What was inspected

- **Owner:** `api.database.Database` is the only owner used by setup, API and
  UI. `prepare_text` creates a new directory, closes every handle, seals,
  publishes `text_tables.json` and validates with a fresh owner. Part 4
  follows the same sequence with its own registry.
- **Seal:** the one-way policy lives in storage (`HeapFile.offline_publication`,
  `HeapFile.seal`). `seal_text_collection` only adds text checks and the
  enumeration of B+/hash secondary indexes, so a multimedia wrapper can reuse
  it without touching the text code.
- **SQL:** the current lexer already tokenizes both PDF examples (`WITH` is a
  keyword; the rest are identifiers, `=` and literals). The parser rejects them
  today with `SqlUnsupportedError` ("Function 'SIMILAR_TO' is not supported").
  A conflict to resolve in phase 5: `USING <identifier>` is stored as
  `text_model` and `is_text_select` treats any `USING` as text, so the
  multimedia form must be routed before that branch.
- **Architecture rule:** `tests/test_architecture.py` allowed only standard
  library imports inside `engine/`. The plan needs numpy, OpenCV and librosa.
  This phase adds a `multimedia` layer and a narrow, tested exception (numpy
  anywhere in `engine.multimedia`; OpenCV/librosa only in
  `engine.multimedia.features`). Probe modules confirmed that numpy in
  `engine.text`, OpenCV outside the feature adapter and scikit-learn anywhere
  are rejected, while numpy in `engine.multimedia` is accepted.

## What was added

- `engine/multimedia/contracts.py`: modalities, media-key validation, the three
  measures, score and internal objective, best-first ordering, k/LIMIT output
  size, exact top-k reference, Recall@k, TF-IDF weights and the starting
  parameters. Pure Python with `math.fsum`: it is the independent oracle for
  the numpy implementation of phase 2, not the fast path.
- `tests/multimedia/make_fixtures.py` and its committed outputs: eight gallery
  images, one JPEG query (`foto_consulta.jpg`), six gallery WAV clips, one MP3
  query (`audio_query.mp3`), and four files that must be rejected (blank image,
  silence, two undecodable files). PNG/WAV regeneration was byte-identical.
- `tests/multimedia/test_contracts.py` (69 tests) and `test_fixtures.py`
  (9 tests), including three objects whose order differs under each measure,
  ties, k > N, invalid k/vectors/keys, hand-computed TF-IDF, the
  1,748-byte worst-case `canciones` row and Heap persistence after reopen.

## Storage finding and data strategy

The WSL root reports 817 GB available, but it is a virtual disk stored on the
Windows drive, which has about 32 GB free. COCO `train2017.zip` is 19.3 GB, so
the zip plus its extraction does not fit. The plan's candidate stays, acquired
image by image (URL and original SHA-256 recorded, ≤512 px copy kept, which is
the first preprocessing step). COCO single-image downloads and HTTP byte ranges
on both COCO and FMA zips were probed successfully; FMA clips can be read as
individual zip members without downloading the 7.7 GB archive. Nothing was
downloaded; all gate checks remain PENDING.

## Regression

| Check | Result |
|---|---|
| Full suite, Python 3.12.3, `-n 4 -W error` | **3,639 passed** (72.92 s) |
| Full suite, Python 3.11.9, `-n 4 -W error` | **3,639 passed** (93.44 s) |
| New multimedia tests | 78 passed |
| Architecture tests | 23 passed; policy negative checks as described above |

The 3,639 tests are the 3,561 of the Part 3 closure plus the 78 new ones.

## Open decisions for phase 2

1. **D1 — K-Means:** own seeded numpy implementation (proposed) or a library,
   which the plan allows.
2. **Dependencies:** a `multimedia` extra (numpy, opencv-python-headless,
   librosa) and its addition to the Docker image and test environment.
3. **Audio scale:** the plan measures images at 1k/10k/100k and keeps audio
   functional (~30 clips). The PDF says "imágenes/audios"; confirm that
   interpretation before phase 6.
