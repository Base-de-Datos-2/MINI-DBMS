"""Repeat only ambiguous-provenance small runs using the existing harness."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from benchmarks import file_organization, indexes
from benchmarks.harness import ResultWriter, environment
from benchmarks.report import render
from benchmarks.spatial.experiments import snapshot
from benchmarks.spatial.results import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    code = snapshot(args.output)
    env = {**environment(), "git_commit": args.source_commit, "git_dirty": False,
           "git_context": "copied committed sources without .git; exact archive preserved"}
    metadata = {"sizes": [1000, 10000], "repetitions": 5, "workload_budget_seconds": 60,
                "source_snapshot": code, "environment": env,
                "driver_sha256": digest(__file__), "reason": "repeat H7 ambiguous small-run provenance",
                "historical_100000_not_repeated": True}
    (args.output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    writer = ResultWriter(args.output / "results.jsonl", "first-delivery-small-20261004",
                          config={"sizes": [1000, 10000], "repetitions": 5, "workload_budget_seconds": 60}, env=env)
    for size in (1000, 10000):
        for repetition in range(1, 6):
            for label, experiment in (("files", file_organization), ("indexes", indexes)):
                started = perf_counter()
                experiment.run(size, repetition, writer, args.workdir)
                print(f"{label} N={size} repetition={repetition}: {perf_counter() - started:.2f}s", flush=True)
    for path in render([writer.path], args.figures):
        print(f"Generated {path}", flush=True)
    metadata["results_sha256"] = digest(writer.path)
    metadata["figure_sha256"] = {path.name: digest(path) for path in args.figures.iterdir() if path.is_file()}
    (args.output / "completed.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
