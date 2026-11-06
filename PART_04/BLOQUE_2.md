# Part 4 — Phase 2: features and exact scan

Date: 2026-11-06. Scope: phase 2 of [PLAN_PARTE_04.md](PLAN_PARTE_04.md) §10,
under the user's authorization to continue phases 2–8. Contract:
[docs/multimedia-contract.md](../docs/multimedia-contract.md).

| Exit evidence required by the plan | Where | Status |
|---|---|---|
| SIFT/MFCC, fitted vocabularies, TF-IDF | [engine/multimedia/features.py](../engine/multimedia/features.py) | Done, both modalities |
| Vector persistence and exact top-k | [engine/multimedia/vectors.py](../engine/multimedia/vectors.py) | Done |
| Known histograms and scores | `test_features.py`, `test_vectors.py` | Done: numpy vs the scalar oracle |
| Reopened model consistency | Same process and a fresh process | Done, no retraining on open |

## Implementation

- **Images:** decode to grayscale with OpenCV (EXIF orientation applied),
  aspect-preserving `INTER_AREA` shrink to a longest side of 512 px (never
  enlarged), SIFT, then the 256 strongest keypoints by response (ties by
  position, size and angle, so the order is deterministic).
- **Audio:** `soundfile` decodes WAV and MP3 from bytes (no fallback decoder
  whose behaviour changes between librosa versions). Clips are downmixed to
  mono and resampled to 22,050 Hz with `soxr_hq`. MFCC uses explicitly pinned
  mel and log-power settings (`MEL_SETTINGS`): 128 mel bands, Slaney norm,
  centred Hann frames, `power_to_db(ref=1, amin=1e-10, top_db=80)`,
  orthonormal DCT-II, 20 coefficients, FFT 2,048 and hop 512.
- **Rejections** (`FeatureExtractionError.reason`): `undecodable`,
  `no_descriptors`, `no_signal` (all samples zero), `too_short` (< 2,048
  samples), `too_long` (> 30 s, checked before full decoding) and
  `too_large` (> 64 MiB file).
- **Vocabulary:** seeded uniform sample of at most 100,000 descriptors, then
  scikit-learn K-Means (k-means++, Lloyd, 3 restarts, seed 20261106). It fails
  clearly when there are fewer distinct descriptors than K.
- **Own code:**
  - nearest-word assignment by squared Euclidean distance, with ties going to
    the lower word;
  - word counts and `df` counted per object;
  - TF-IDF exactly as in the contract, stored as unnormalized float32.
- **`FeatureModel`:** modality, parameters, codebook, `df`, N and library
  versions.
  - Its fingerprint hashes the description, the codebook and `df`.
  - `save` writes once into a new directory (`.npy` without pickle, plus a
    JSON file with checksums).
  - `load` verifies files, IDF and fingerprint, and never trains.
- **Construction paths:**
  - `train_vocabulary`, then `build_collection_features`, for direct
    construction;
  - `counts_to_features`, which lets phase 6 compute word counts in parallel
    and still fit IDF on exactly the gallery.
- **`VectorStore`:**
  - `ids`, `vectors` and `norms` are written once into a new directory, with a
    manifest holding shape, dtype, model fingerprint and checksums.
  - Opening memory-maps them read-only and checks structure; `verify=True`
    also rehashes.
  - `search` scores in float64 batches and keeps a bounded top-k with score
    DESC and id ASC, keeping every tie at the threshold.
  - `score_rows` gives exact scores for candidate rows, for the approximate
    indexes.

## Results on the fixtures

With 16 visual and 8 audio words:
- `foto_consulta.jpg` finds `scene_a` under all three metrics.
- The shifted and mirrored images find their originals.
- `audio_query.mp3` (detuned, MP3) finds `acorde_grave` under all three
  metrics.
- `acorde_grave_variante` (2.5 dB quieter, with noise) is closest to
  `barrido`. This is a genuine limitation of bag-of-MFCC-words with level and
  noise changes. It stays documented as an error case, and no test asserts the
  opposite.

## Dependencies

- New `multimedia` extra, also added to `test`: `numpy`,
  `opencv-python-headless`, `soundfile` and `librosa`; scikit-learn comes with
  librosa.
- Versions used:
  - Python 3.12: numpy 2.5.4, OpenCV 5.0.0, librosa 1.0.0, scikit-learn 1.9.1,
    soundfile 0.14.0 (libsndfile 1.2.2).
  - Python 3.11: librosa 0.11.0 and numpy 2.4.6, with the rest equal.
- Both environments pass. Every fitted model records the versions it was
  built with.
- The architecture test allows `soundfile` and `sklearn` only in the feature
  adapter. Importing `engine.multimedia` does not load any media library.

## Regression

| Check | Result |
|---|---|
| Multimedia + architecture tests, Python 3.12 / 3.11 | 154 passed / 154 passed |
| Full suite, Python 3.12, `-n 4 -W error` | **3,692 passed** (79.36 s): 3,639 earlier + 53 new |

## Started early for phase 6

The COCO downloader of phase 6 (`benchmarks/multimedia/coco.py`, committed
with phase 6) is running in the background, as the plan recommends ("begin
data feasibility early"). Stored copies average about 58 KB, so 100,000
images need about 5.8 GB.
