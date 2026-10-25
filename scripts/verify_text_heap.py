"""Isolated, read-only child process for the Part 3 Heap acceptance check."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.text.acceptance import reopen_heap  # noqa: E402


if __name__ == "__main__":
    try:
        print(json.dumps(reopen_heap(*sys.argv[1:])))
    except Exception as error:
        from scripts.sanitize_evidence import sanitize
        print(sanitize(f"{type(error).__name__}: {error}"), file=sys.stderr)
        raise SystemExit(1)
