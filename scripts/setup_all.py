"""Prepare every part for ``python -m api --all`` in a NEW directory (server stopped).

    python scripts/setup_all.py [--data-dir DIR] [--only parte3 ...]

Each part is built by its own setup script into ``DIR/<part>``:

    parte1  scripts/setup_demo.py        relational demo
    parte2  scripts/setup_lima.py        spatial demo with OpenStreetMap Lima
    parte3  scripts/setup_text.py        text demo collections (data/text_demo)
    parte4  scripts/setup_multimedia.py  real images and audio (data/multimedia_demo)

A part whose directory already exists is left untouched and reported, so the
script never replaces data; delete that subdirectory to rebuild it. Part 4
needs the ``multimedia`` extra (OpenCV, librosa) to extract features.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import perf_counter

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database  # noqa: E402
from api.unified import PARTS  # noqa: E402

DEFAULT_DIRECTORY = REPOSITORY / "data" / "generated" / "todas"
MULTIMEDIA_ASSETS = REPOSITORY / "data" / "multimedia_demo"


def _prepare_part(identifier: str, directory: Path) -> None:
    if identifier == "parte1":
        from scripts.setup_demo import prepare
        prepare(directory, reset=False)
    elif identifier == "parte2":
        from scripts.setup_lima import prepare_lima
        prepare_lima(directory)
    elif identifier == "parte3":
        from scripts.setup_text import prepare
        prepare(directory)
    elif identifier == "parte4":
        from scripts.setup_multimedia import asset_sources
        Database.prepare_multimedia(directory, asset_sources(MULTIMEDIA_ASSETS))
    else:  # pragma: no cover - PARTS and this function change together
        raise ValueError(f"Unknown part {identifier}")


def prepare_all(root: Path, only: set[str] | None = None) -> dict[str, str]:
    """Prepare each missing part; return ``{part: created|exists|error message}``."""

    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    outcome = {}
    for spec in PARTS:
        if only and spec.id not in only:
            continue
        directory = root / spec.id
        if directory.exists():
            outcome[spec.id] = "exists"
            print(f"Parte {spec.number}: {directory} ya existe; no se modifica.", flush=True)
            continue
        print(f"Parte {spec.number} ({spec.title}) → {directory}", flush=True)
        started = perf_counter()
        try:
            _prepare_part(spec.id, directory)
        except (Exception, SystemExit) as error:  # noqa: BLE001 - report and go on with the others
            outcome[spec.id] = f"{type(error).__name__}: {error}"
            print(f"  ERROR: {outcome[spec.id]}", flush=True)
            if directory.exists():
                print(f"  Borra {directory} antes de volver a intentarlo.", flush=True)
            continue
        outcome[spec.id] = "created"
        print(f"  lista en {perf_counter() - started:.1f} s", flush=True)
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--only", nargs="+", choices=[spec.id for spec in PARTS],
                        help="prepara solo estas partes")
    args = parser.parse_args(argv)
    outcome = prepare_all(args.data_dir, set(args.only) if args.only else None)
    failed = [part for part, state in outcome.items() if state not in ("created", "exists")]
    if failed:
        print(f"Partes con error: {', '.join(failed)}", flush=True)
        return 1
    print(f"Listo. Inicia el servidor con: python -m api --all --data-dir {args.data_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
