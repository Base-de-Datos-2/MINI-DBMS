"""Run the Stage 10 experiments: ``python -m benchmarks run [options]``.

Examples::

    python -m benchmarks run --experiment files --sizes 1000 10000 --repetitions 5
    python -m benchmarks run --experiment indexes --sizes 100000 --repetitions 3 \\
        --first-repetition 2          # resume a long run where it stopped
    python -m benchmarks report       # charts and tables from raw results

Every measurement is appended to the results file as one JSON line, so a long
run can be split into several invocations writing to the same file.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

from . import file_organization, indexes
from .datasets import REQUIRED_SIZES
from .harness import DEFAULT_RESULTS, DEFAULT_WORKDIR, REPOSITORY, ResultWriter


EXPERIMENTS = {"files": file_organization, "indexes": indexes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m benchmarks")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run experiments and append raw results")
    run.add_argument("--experiment", choices=[*EXPERIMENTS, "all"], default="all")
    run.add_argument("--sizes", type=int, nargs="+", default=list(REQUIRED_SIZES))
    run.add_argument("--repetitions", type=int, default=3)
    run.add_argument("--first-repetition", type=int, default=1)
    run.add_argument("--results", type=Path, default=DEFAULT_RESULTS / "results.jsonl")
    run.add_argument("--workdir", type=Path, default=DEFAULT_WORKDIR)
    run.add_argument("--workload-budget-seconds", type=float, default=60.0)
    run.add_argument("--run-id", default=None)
    report = commands.add_parser("report", help="render charts and tables from raw results")
    report.add_argument("--results", type=Path, nargs="+",
                        default=[DEFAULT_RESULTS / "part1_results.jsonl"])
    report.add_argument("--output", type=Path, default=REPOSITORY / "docs" / "experimentos")
    args = parser.parse_args(argv)

    if args.command == "report":
        from .report import render

        for path in render(args.results, args.output):
            print(f"wrote {path}")
        return 0

    names = list(EXPERIMENTS) if args.experiment == "all" else [args.experiment]
    run_id = args.run_id or uuid4().hex[:12]
    writer = ResultWriter(
        args.results,
        run_id,
        config={
            "sizes": args.sizes,
            "repetitions": args.repetitions,
            "workload_budget_seconds": args.workload_budget_seconds,
        },
    )
    for size in args.sizes:
        for repetition in range(args.first_repetition, args.repetitions + 1):
            for name in names:
                started = perf_counter()
                options = {}
                if name == "indexes":
                    options["workload_budget_seconds"] = args.workload_budget_seconds
                EXPERIMENTS[name].run(size, repetition, writer, args.workdir, **options)
                print(
                    f"[{run_id}] {name} size={size} repetition={repetition}: "
                    f"{perf_counter() - started:.1f}s",
                    flush=True,
                )
    print(f"Results appended to {args.results}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
