"""Generate Part 2 inputs without executing experiments."""

import argparse
from pathlib import Path

from .datasets import REQUIRED_SIZES, SEED, export


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m benchmarks.spatial")
    parser.add_argument("--output", type=Path, default=Path("data/generated/spatial_inputs"))
    parser.add_argument("--sizes", type=int, nargs="+", default=REQUIRED_SIZES)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    manifest = export(args.output, args.sizes, args.seed)
    print(f"Inputs generated in {args.output}; sizes={manifest['sizes']}; queries=100")


if __name__ == "__main__":
    main()
