"""Timing, isolation and raw-result recording shared by every experiment.

Each measurement becomes one JSON object (one line) in a results file, with
the run configuration and environment, so charts and tables can always be
regenerated from raw data. Nothing here estimates or extrapolates a value.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from time import perf_counter
from typing import Any


REPOSITORY = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = REPOSITORY / "benchmarks" / "results"
DEFAULT_WORKDIR = REPOSITORY / "data" / "generated" / "bench"


def _git(*arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=REPOSITORY, capture_output=True, text=True,
            check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip()


def source_digest() -> str:
    """SHA-256 over every engine and benchmark source file (path and bytes).

    It identifies the exact code that produced a result even when the run
    happened on uncommitted changes, which the git commit alone cannot.
    """

    digest = hashlib.sha256()
    for root in ("engine", "benchmarks"):
        for path in sorted((REPOSITORY / root).rglob("*.py")):
            digest.update(path.relative_to(REPOSITORY).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def environment() -> dict[str, Any]:
    """Describe where and on which code a run happened."""

    status = _git("status", "--porcelain")
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": None if status is None else bool(status),
        "source_sha256": source_digest(),
    }


@dataclass
class ResultWriter:
    """Append one JSON line per measurement; flushed after each line."""

    path: Path
    run_id: str
    config: dict[str, Any]
    env: dict[str, Any] = field(default_factory=environment)

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        experiment: str,
        structure: str,
        operation: str,
        size: int,
        repetition: int,
        elapsed_seconds: float | None,
        count: int | None = None,
        **values: Any,
    ) -> dict[str, Any]:
        row = {
            "run_id": self.run_id,
            "experiment": experiment,
            "structure": structure,
            "operation": operation,
            "size": size,
            "repetition": repetition,
            "elapsed_seconds": elapsed_seconds,
            "count": count,
            "per_operation_ms": (
                None if elapsed_seconds is None or not count
                else elapsed_seconds * 1000 / count
            ),
            **values,
            "config": self.config,
            "environment": self.env,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def timed(action: Callable[[], Any]) -> tuple[Any, float]:
    """Run ``action`` once and return its result and wall-clock seconds."""

    started = perf_counter()
    result = action()
    return result, perf_counter() - started


@contextmanager
def workspace(base: Path, label: str) -> Iterator[Path]:
    """A fresh directory for one measured run, removed afterwards."""

    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{label}-", dir=base))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def file_bytes(*paths: Path) -> int:
    """Total on-disk size of existing files."""

    return sum(path.stat().st_size for path in paths if path.exists())


def read_results(path: Path) -> list[dict[str, Any]]:
    """Load every measurement of one results file."""

    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
