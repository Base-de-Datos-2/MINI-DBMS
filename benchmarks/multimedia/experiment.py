"""Part 4 experiment: IVF vs HNSW, Euclidean vs cosine, k = 10, N = 1k/10k/100k.

Steps (each heavy step runs in a fresh process, see ``run``):

    prepare --size N   IDF for this N from the frozen word counts, vector store
    build   --size N --config ivf-euclidean|ivf-cosine|hnsw-euclidean|hnsw-cosine
    exact   --size N   exact top-10 (VectorScan) for the 30 queries and both metrics
    query   --size N --config C --repetition r   warm-up pass + one timed pass
    run     [--sizes ...]  orchestrates everything into one results directory

Boundaries (PLAN_PARTE_04 §9.3):
* common preparation (SIFT, vocabulary, counts) is done once by
  ``benchmarks.multimedia.features`` and never charged to an index;
* construction = prepared vectors -> closed, persisted, reopenable index;
* query = prepared query vector -> ordered ids/scores (routing/traversal,
  exact candidate scoring, top-k); feature extraction is excluded;
* memory: VmHWM is reset (``/proc/self/clear_refs``) before each measured
  phase; baseline, peak construction, loaded-index and peak query RSS.
Search parameters are the frozen defaults unless ``--nprobe``/``--ef`` are
given, and every result records the values used.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from engine.multimedia import HnswParameters, Metric, Modality, recall_at_k
from engine.multimedia.contracts import ImageFeatureParameters, TrainingParameters, default_nlist
from engine.multimedia.features import FeatureModel, counts_to_features, tfidf
from engine.multimedia.hnsw import HnswIndex
from engine.multimedia.ivf import IvfIndex
from engine.multimedia.vectors import VectorStore

DATA = Path("data/generated/multimedia")
FEATURES = DATA / "features"
WORK = DATA / "experiment"
SIZES = (1_000, 10_000, 100_000)
CONFIGS = ("ivf-euclidean", "ivf-cosine", "hnsw-euclidean", "hnsw-cosine")
K = 10
REPETITIONS = 3


# --- memory ------------------------------------------------------------------

def status_kib(field: str) -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return int(line.split()[1])
    raise KeyError(field)


def reset_peak() -> None:
    gc.collect()
    Path("/proc/self/clear_refs").write_text("5")


def memory() -> dict:
    return {"rss_mib": status_kib("VmRSS") / 1024, "peak_mib": status_kib("VmHWM") / 1024}


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


# --- inputs ------------------------------------------------------------------

def frozen_inputs():
    counts = np.load(FEATURES / "counts.npy", mmap_mode="r", allow_pickle=False)
    order = np.load(FEATURES / "order.npy", allow_pickle=False)
    split = json.loads((DATA / "coco" / "split.json").read_text(encoding="utf-8"))
    report = json.loads((FEATURES / "counts.json").read_text(encoding="utf-8"))
    if report["rejected"]:
        raise SystemExit("Some images were rejected; the frozen split must be repaired first")
    gallery, queries = len(split["gallery"]), len(split["queries"])
    return counts, order, gallery, queries


def size_dir(size: int) -> Path:
    return WORK / f"n{size}"


def parse_config(config: str):
    method, metric = config.split("-")
    return method, Metric(metric)


# --- steps -------------------------------------------------------------------

def prepare(args) -> dict:
    counts, order, gallery, _ = frozen_inputs()
    codebook = np.load(FEATURES / "codebook.npy", allow_pickle=False)
    directory = size_dir(args.size)
    directory.mkdir(parents=True, exist_ok=False)
    reset_peak()
    started = time.perf_counter()
    features = counts_to_features(Modality.IMAGE, order[:args.size], np.asarray(counts[:args.size]), codebook,
                                  ImageFeatureParameters(), TrainingParameters())
    features.model.save(directory / "model")
    VectorStore.create(directory / "store", features.ids, features.vectors,
                       model_fingerprint=features.model.fingerprint).close()
    elapsed = time.perf_counter() - started
    return {"step": "prepare", "size": args.size, "seconds": elapsed, "memory": memory(),
            "store_bytes": directory_bytes(directory / "store"), "model_bytes": directory_bytes(directory / "model"),
            "vector_matrix_bytes": int(features.vectors.nbytes), "fingerprint": features.model.fingerprint}


def build(args) -> dict:
    method, metric = parse_config(args.config)
    directory = size_dir(args.size)
    target = directory / args.config
    baseline = memory()
    store = VectorStore.open(directory / "store")
    reset_peak()
    started = time.perf_counter()
    if method == "ivf":
        index = IvfIndex.build(target, store, metrics=(metric,))
    else:
        index = HnswIndex.build(target, store, metric, parameters=HnswParameters())
    index.close()
    elapsed = time.perf_counter() - started
    peak = memory()
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    store.close()
    return {"step": "build", "size": args.size, "config": args.config, "seconds": elapsed,
            "memory_baseline": baseline, "memory_peak": peak, "index_bytes": directory_bytes(target),
            "parameters": {k: manifest[k] for k in ("nlist", "nprobe", "m", "m0", "ef_construction", "seed")
                           if k in manifest},
            "statistics": manifest.get("statistics") or manifest.get("training")}


def query_vectors(size: int):
    counts, order, gallery, queries = frozen_inputs()
    model = FeatureModel.load(size_dir(size) / "model")
    rows = np.asarray(counts[gallery:gallery + queries])
    return order[gallery:gallery + queries].tolist(), tfidf(rows, model.idf).astype(np.float64)


def exact(args) -> dict:
    ids, vectors = query_vectors(args.size)
    store = VectorStore.open(size_dir(args.size) / "store", verify=True)
    reference = {}
    timings = {}
    for metric in (Metric.EUCLIDEAN, Metric.COSINE):
        reference[metric.value], seconds = [], []
        for vector in vectors:
            started = time.perf_counter()
            result = store.search(vector, metric, K)
            seconds.append(time.perf_counter() - started)
            reference[metric.value].append([[n.object_id, n.score] for n in result.neighbors])
        timings[metric.value] = {"mean_seconds": float(np.mean(seconds)), "median_seconds": float(np.median(seconds))}
    store.close()
    (size_dir(args.size) / "exact.json").write_text(json.dumps({"queries": ids, "top10": reference}) + "\n")
    return {"step": "exact", "size": args.size, "vectorscan": timings}


def query(args) -> dict:
    method, metric = parse_config(args.config)
    ids, vectors = query_vectors(args.size)
    reference = json.loads((size_dir(args.size) / "exact.json").read_text())["top10"][metric.value]
    baseline = memory()
    store = VectorStore.open(size_dir(args.size) / "store")
    reset_peak()
    if method == "ivf":
        index = IvfIndex.open(size_dir(args.size) / args.config, store)
        search = lambda v: index.search(v, metric, K, nprobe=args.nprobe)
    else:
        index = HnswIndex.open(size_dir(args.size) / args.config, store)
        search = lambda v: index.search(v, metric, K, ef_search=args.ef)
    loaded = memory()
    for vector in vectors:                            # warm-up pass, not recorded
        search(vector)
    reset_peak()
    rows = []
    for query_id, vector, exact_top in zip(ids, vectors, reference):
        started = time.perf_counter()
        result = search(vector)
        elapsed = time.perf_counter() - started
        found = [n.object_id for n in result.neighbors]
        rows.append({"query": query_id, "seconds": elapsed, "ids": found,
                     "scores": [n.score for n in result.neighbors],
                     "recall": recall_at_k(found, [i for i, _ in exact_top], K),
                     "evaluated": result.evaluated, "details": result.details})
    peak = memory()
    index.close()
    store.close()
    return {"step": "query", "size": args.size, "config": args.config, "repetition": args.repetition,
            "memory_baseline": baseline, "memory_loaded": loaded, "memory_query_peak": peak, "rows": rows}


def tune(args) -> dict:
    """Recall@10 on the separate tuning images (never the final queries).

    Defaults first; one modest alternative per method is measured so that a
    single adjustment can be justified if the defaults are unusable.
    """
    counts, order, gallery, queries = frozen_inputs()
    model = FeatureModel.load(size_dir(args.size) / "model")
    tuning = tfidf(np.asarray(counts[gallery + queries:]), model.idf).astype(np.float64)
    store = VectorStore.open(size_dir(args.size) / "store")
    report = {"step": "tune", "size": args.size, "tuning_queries": len(tuning), "results": []}
    for config in CONFIGS:
        method, metric = parse_config(config)
        exact = [[n.object_id for n in store.search(v, metric, K).neighbors] for v in tuning]
        if method == "ivf":
            index = IvfIndex.open(size_dir(args.size) / config, store)
            settings = [("nprobe", None), ("nprobe", 16)]
            run = lambda v, value: index.search(v, metric, K, nprobe=value)
        else:
            index = HnswIndex.open(size_dir(args.size) / config, store)
            settings = [("ef_search", None), ("ef_search", 128)]
            run = lambda v, value: index.search(v, metric, K, ef_search=value)
        for name, value in settings:
            recalls, seconds = [], []
            for vector, truth in zip(tuning, exact):
                started = time.perf_counter()
                result = run(vector, value)
                seconds.append(time.perf_counter() - started)
                recalls.append(recall_at_k([n.object_id for n in result.neighbors], truth, K))
            report["results"].append({"config": config, name: value if value is not None else "default",
                                      "mean_recall": float(np.mean(recalls)),
                                      "min_recall": float(np.min(recalls)),
                                      "mean_seconds": float(np.mean(seconds))})
        index.close()
    store.close()
    return report


# --- orchestration -----------------------------------------------------------

def child(output: Path, name: str, *arguments: str) -> dict:
    target = output / f"{name}.json"
    if target.exists():
        return json.loads(target.read_text())
    command = [sys.executable, "-m", "benchmarks.multimedia.experiment", *arguments, "--emit", str(target)]
    subprocess.run(command, check=True)
    return json.loads(target.read_text())


def environment() -> dict:
    def version(module):
        try:
            return __import__(module).__version__
        except ImportError:
            return None
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "engine", "benchmarks/multimedia"],
                           capture_output=True, text=True).stdout.splitlines()
    sources = sorted(Path("engine/multimedia").glob("*.py")) + sorted(Path("benchmarks/multimedia").glob("*.py"))
    digest = hashlib.sha256()
    for path in sources:
        digest.update(path.as_posix().encode() + b"\0" + path.read_bytes())
    memory_total = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                        if line.startswith("MemTotal:"))
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    return {"date": date.today().isoformat(), "commit": commit, "dirty_measured_files": dirty,
            "measured_source_sha256": digest.hexdigest(), "python": platform.python_version(),
            "platform": platform.platform(), "cpu": cpu, "logical_cpus": os.cpu_count(),
            "memory_total_mib": memory_total // 1024,
            "libraries": {m: version(m) for m in ("numpy", "cv2", "sklearn", "librosa", "soundfile")},
            "k": K, "repetitions": REPETITIONS, "sizes": list(SIZES), "configs": list(CONFIGS),
            "hnsw": asdict(HnswParameters()),
            "nlist": {str(n): default_nlist(n) for n in SIZES},
            "vocabulary": json.loads((FEATURES / "vocabulary.json").read_text()),
            "counts": json.loads((FEATURES / "counts.json").read_text()),
            "counts_first_pass": (json.loads((FEATURES / "counts.first_pass.json").read_text())
                                  if (FEATURES / "counts.first_pass.json").exists() else None),
            "split_sha256": hashlib.sha256((DATA / "coco" / "split.json").read_bytes()).hexdigest(),
            "codebook_sha256": hashlib.sha256((FEATURES / "codebook.npy").read_bytes()).hexdigest(),
            "counts_sha256": hashlib.sha256((FEATURES / "counts.npy").read_bytes()).hexdigest()}


def run(args) -> None:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "environment.json").write_text(json.dumps(environment(), indent=2) + "\n")
    extra = []
    if args.nprobe is not None:
        extra += ["--nprobe", str(args.nprobe)]
    if args.ef is not None:
        extra += ["--ef", str(args.ef)]
    for size in args.sizes:
        if not (size_dir(size) / "store").exists():
            child(output, f"prepare_{size}", "prepare", "--size", str(size))
        for config in CONFIGS:
            child(output, f"build_{size}_{config}", "build", "--size", str(size), "--config", config)
        child(output, f"exact_{size}", "exact", "--size", str(size))
        if args.builds_only:
            continue
        for repetition in range(REPETITIONS):
            shift = repetition % len(CONFIGS)
            for config in CONFIGS[shift:] + CONFIGS[:shift]:
                child(output, f"query_{size}_{config}_r{repetition}", "query", "--size", str(size),
                      "--config", config, "--repetition", str(repetition), *extra)
        print(f"N={size} done", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "build", "exact", "query", "tune"):
        step = sub.add_parser(name)
        step.add_argument("--size", type=int, required=True, choices=SIZES)
        step.add_argument("--emit", type=Path, required=True)
        if name in ("build", "query"):
            step.add_argument("--config", required=True, choices=CONFIGS)
        if name == "query":
            step.add_argument("--repetition", type=int, required=True)
            step.add_argument("--nprobe", type=int)
            step.add_argument("--ef", type=int)
    runner = sub.add_parser("run")
    runner.add_argument("--output", default=f"benchmarks/results/multimedia/{date.today().isoformat()}")
    runner.add_argument("--sizes", type=int, nargs="+", default=list(SIZES))
    runner.add_argument("--builds-only", action="store_true")
    runner.add_argument("--nprobe", type=int)
    runner.add_argument("--ef", type=int)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args)
        return
    result = {"prepare": prepare, "build": build, "exact": exact, "query": query, "tune": tune}[args.command](args)
    args.emit.write_text(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
