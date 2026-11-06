"""Part 4 image features for the experiment: vocabulary once, word counts for all.

    python -m benchmarks.multimedia.features vocabulary   # SIFT on the 1,000 subset + K-Means
    python -m benchmarks.multimedia.features counts       # SIFT + word counts, every image

The vocabulary (K = 256) is trained once on a seeded descriptor sample of the
first 1,000 gallery images and reused at every size (PLAN_PARTE_04 §4.3).
Counts are computed in parallel processes (one OpenCV thread each) and stored
as an int32 matrix in split order (gallery, then queries, then tuning). IDF
is fitted later per size N from these counts. Rejected images (no SIFT
keypoint, undecodable) are recorded, never padded with fabricated vectors.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import resource
import time

import numpy as np

from engine.multimedia.contracts import ImageFeatureParameters, TrainingParameters
from engine.multimedia.features import (
    FeatureExtractionError, fit_vocabulary, image_descriptors, sample_descriptors, word_counts,
)

DATA = Path("data/generated/multimedia")
COCO = DATA / "coco"
FEATURES = DATA / "features"
TRAINING_OBJECTS = 1_000


def peak_rss_mib() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def split():
    payload = json.loads((COCO / "split.json").read_text(encoding="utf-8"))
    return payload


def media_path(coco_id: int) -> Path:
    return COCO / "images" / f"{coco_id:012d}.jpg"


def vocabulary(args) -> None:
    FEATURES.mkdir(parents=True, exist_ok=True)
    target = FEATURES / "codebook.npy"
    if target.exists():
        raise SystemExit(f"{target} exists; delete it explicitly to retrain")
    parameters, training = ImageFeatureParameters(), TrainingParameters()
    ids = split()["gallery"][:TRAINING_OBJECTS]
    started = time.perf_counter()
    sets = [image_descriptors(media_path(i), parameters) for i in ids]
    extracted = time.perf_counter()
    sample = sample_descriptors(sets, training.max_training_descriptors, training.seed)
    codebook = fit_vocabulary(sample, parameters.vocabulary_size, training)
    finished = time.perf_counter()
    np.save(target, codebook, allow_pickle=False)
    report = {"training_objects": len(ids), "descriptors_total": int(sum(len(s) for s in sets)),
              "descriptors_sampled": int(len(sample)), "vocabulary_size": int(len(codebook)),
              "extract_seconds": extracted - started, "kmeans_seconds": finished - extracted,
              "peak_rss_mib": peak_rss_mib(), "seed": training.seed,
              "kmeans": {"restarts": training.kmeans_restarts, "max_iterations": training.kmeans_max_iterations}}
    (FEATURES / "vocabulary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


_CODEBOOK = None


def _init(codebook_path: str) -> None:
    global _CODEBOOK
    import cv2
    cv2.setNumThreads(1)
    _CODEBOOK = np.load(codebook_path, allow_pickle=False)


def _count(coco_id: int):
    started = time.perf_counter()
    try:
        descriptors = image_descriptors(media_path(coco_id))
    except FeatureExtractionError as error:
        return coco_id, None, error.reason, time.perf_counter() - started, 0
    counts = word_counts(descriptors, _CODEBOOK).astype(np.int32)
    return coco_id, counts, None, time.perf_counter() - started, len(descriptors)


def counts(args) -> None:
    info = split()
    order = info["gallery"] + info["queries"] + info["tuning"]
    codebook_path = FEATURES / "codebook.npy"
    codebook = np.load(codebook_path, allow_pickle=False)
    matrix = np.zeros((len(order), len(codebook)), dtype=np.int32)
    position = {coco_id: index for index, coco_id in enumerate(order)}
    descriptors = np.zeros(len(order), dtype=np.int32)
    seconds = np.zeros(len(order), dtype=np.float64)
    rejected = {}
    pending = order
    reused = 0
    if args.reuse and (FEATURES / "counts.npy").exists():
        # Rows depend only on (image, codebook): keep them, extract only new ids.
        old_matrix = np.load(FEATURES / "counts.npy", allow_pickle=False)
        old_order = np.load(FEATURES / "order.npy", allow_pickle=False).tolist()
        previous = json.loads((FEATURES / "counts.json").read_text(encoding="utf-8"))
        old_position = {coco_id: index for index, coco_id in enumerate(old_order)}
        for coco_id in order:
            if coco_id in old_position and str(coco_id) not in previous["rejected"]:
                matrix[position[coco_id]] = old_matrix[old_position[coco_id]]
                descriptors[position[coco_id]] = -1          # reused (descriptor count not kept)
        pending = [coco_id for coco_id in order if descriptors[position[coco_id]] == 0]
        reused = len(order) - len(pending)
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init,
                             initargs=(str(codebook_path),)) as pool:
        for done, (coco_id, row, reason, elapsed, count) in enumerate(
                pool.map(_count, pending, chunksize=64), 1):
            index = position[coco_id]
            seconds[index], descriptors[index] = elapsed, count
            if row is None:
                rejected[str(coco_id)] = reason
            else:
                matrix[index] = row
            if done % 10_000 == 0:
                print(f"{done} images, {time.perf_counter() - started:.0f} s", flush=True)
    wall = time.perf_counter() - started
    if reused:
        previous_report = json.loads((FEATURES / "counts.json").read_text(encoding="utf-8"))
        (FEATURES / "counts.first_pass.json").write_text(json.dumps(previous_report, indent=2) + "\n")
    np.save(FEATURES / "counts.npy", matrix, allow_pickle=False)
    np.save(FEATURES / "order.npy", np.array(order, dtype=np.int64), allow_pickle=False)
    fresh = descriptors > 0
    report = {"objects": len(order), "gallery": len(info["gallery"]), "queries": len(info["queries"]),
              "tuning": len(info["tuning"]), "rejected": rejected, "workers": args.workers,
              "reused_rows": reused, "extracted_now": len(pending),
              "wall_seconds": wall, "cpu_seconds_per_image_mean": float(seconds[fresh].mean()),
              "cpu_seconds_per_image_median": float(np.median(seconds[fresh])),
              "descriptors_mean": float(descriptors[fresh].mean()),
              "descriptors_min": int(descriptors[fresh].min()),
              "objects_with_256_descriptors": int((descriptors == 256).sum())}
    (FEATURES / "counts.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rejected"} | {"rejected": len(rejected)}),
          flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("vocabulary")
    counting = sub.add_parser("counts")
    counting.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    counting.add_argument("--reuse", action="store_true",
                          help="keep rows of unchanged images from the previous counts.npy")
    args = parser.parse_args(argv)
    {"vocabulary": vocabulary, "counts": counts}[args.command](args)


if __name__ == "__main__":
    main()
