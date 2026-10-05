"""Copy completed measurements only; exclude disposable database files."""

import argparse
from pathlib import Path
import shutil

from benchmarks.spatial.results import generate, load_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--figures", type=Path, required=True)
    args = parser.parse_args()
    load_results(args.source)
    args.destination.mkdir(parents=True, exist_ok=False)
    for path in sorted(args.source.iterdir()):
        if path.is_file() and (path.suffix in {".json", ".jsonl"} or path.name == "source.tar.gz"):
            shutil.copy2(path, args.destination / path.name)
    validation = generate(args.destination, args.figures)
    print(f"Conserved {validation['samples']} measurements; {validation['gist_plans_checked']} GiST plans")


if __name__ == "__main__":
    main()
