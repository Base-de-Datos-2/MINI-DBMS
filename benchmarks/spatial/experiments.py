"""Reproducible scan/R-Tree/GiST matrix with isolated worker processes."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from time import perf_counter
from uuid import uuid4

from benchmarks.harness import REPOSITORY, environment
from engine.storage import HeapFile, Record

from .datasets import REQUIRED_SIZES, SEED, export, query_centers
from .gist import measure_gist
from .measurement import NEIGHBORS, RADII, SCHEMA, measure_native, read_points
from .validation import oracle


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def snapshot(output):
    files = sorted(path for name in ("engine", "api", "benchmarks", "scripts")
                   for path in (REPOSITORY / name).rglob("*.py"))
    files.append(REPOSITORY / "pyproject.toml")
    manifest = {path.relative_to(REPOSITORY).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    with tarfile.open(output / "source.tar.gz", "x:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(REPOSITORY).as_posix())
    return {"files": manifest, "archive_sha256": hashlib.sha256((output / "source.tar.gz").read_bytes()).hexdigest()}


def prepare_size(output, inputs, size, centers):
    points_path = inputs / f"points_{size}.csv"
    points = read_points(points_path)
    references = {str(identity): oracle(points, (latitude, longitude), RADII, NEIGHBORS)
                  for identity, latitude, longitude in centers}
    reference_path = output / f"oracle_{size}.json"
    write_json(reference_path, {"centers": centers, "references": references,
                               "points_sha256": hashlib.sha256(points_path.read_bytes()).hexdigest()})
    heap_path = output / f"points_{size}.heap"
    started = perf_counter()
    with HeapFile.create(heap_path, SCHEMA) as storage:
        for values in points:
            storage.insert(Record(SCHEMA, values))
        storage.flush()
    return heap_path, reference_path, perf_counter() - started


def run_matrix(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = output / "inputs"
    generated = export(inputs, args.sizes, args.seed)
    centers = query_centers(args.seed)[:args.query_count]
    run_id = uuid4().hex
    metadata = {"format": "MINIDBMS_SPATIAL_EXPERIMENTS", "version": 1, "run_id": run_id,
                "official_matrix": set(args.sizes) == set(REQUIRED_SIZES) and args.query_count == 100,
                "input_manifest": generated, "environment": environment(), "source_commit": args.source_commit,
                "source_snapshot": snapshot(output), "methods": ["scan", "rtree", "gist"],
                "timing_scope": "complete projected/serialized/decoded results; PostgreSQL client transport included",
                "plans": "actual GiST access checked with EXPLAIN ANALYZE in preflight; diagnostics excluded from timed samples",
                "distance_tolerance_metres": 1e-5, "sizes": []}
    write_json(output / "manifest.json", metadata)
    for size in args.sizes:
        heap, expected, load_seconds = prepare_size(output, inputs, size, centers)
        for method in metadata["methods"]:
            command = [sys.executable, "-m", "benchmarks.spatial.experiments", "--worker", "--method", method,
                       "--size", str(size), "--points", str(inputs / f"points_{size}.csv"), "--heap", str(heap),
                       "--oracle", str(expected), "--index", str(output / f"points_{size}.rtree"),
                       "--output", str(output / f"{method}_{size}.jsonl"), "--container", args.container,
                       "--database", args.database, "--docker", args.docker,
                       "--schema", f"minidbms_s6_{run_id}_{size}"]
            subprocess.run(command, check=True)
        metadata["sizes"].append({"size": size, "heap_load_seconds": load_seconds,
                                   "oracle_sha256": hashlib.sha256(expected.read_bytes()).hexdigest()})
        print(f"N={size}: tres métodos completos", flush=True)
    write_json(output / "completed.json", metadata)


def run_worker(args):
    references = json.loads(args.oracle.read_text(encoding="utf-8"))
    if hashlib.sha256(args.points.read_bytes()).hexdigest() != references["points_sha256"]:
        raise ValueError("Benchmark point input checksum differs from its oracle")
    points = read_points(args.points)
    if len(points) != args.size:
        raise ValueError("Benchmark input has the wrong size")
    action = measure_gist if args.method == "gist" else measure_native
    resources = action(args, points, references)
    write_json(args.output.with_suffix(".resources.json"), resources)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", default="minidbms_bench")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--sizes", type=int, nargs="+", default=REQUIRED_SIZES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--query-count", type=int, choices=range(1, 101), default=100)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--method", choices=("scan", "rtree", "gist"))
    parser.add_argument("--size", type=int)
    for name in ("points", "heap", "oracle", "index"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--schema")
    args = parser.parse_args(argv)
    if not args.worker and (len(set(args.sizes)) != len(args.sizes) or any(size not in REQUIRED_SIZES for size in args.sizes)):
        parser.error("Use distinct official sizes")
    if args.worker:
        run_worker(args)
    else:
        run_matrix(args)


if __name__ == "__main__":
    main()
