"""Serve the Stage 9 demonstration: ``python -m api [options]``.

Prepare the data first, with the server stopped:

    python scripts/setup_demo.py

The server then reopens that directory. It runs one process with one worker
and no auto-reload, because one process must own the data directory.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from time import perf_counter

import uvicorn

from .app import create_app
from .database import Database, DatabaseSetupError
from .demo import DEMO_MEMORY_BUDGET_BYTES, PRESETS, demo_database
from .engine_service import EngineService


REPOSITORY = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> None:
    """Open the prepared demo database, serve API and GUI, then close it."""

    parser = argparse.ArgumentParser(prog="python -m api", description=__doc__)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=REPOSITORY / "data" / "generated" / "demo",
        help="directorio preparado con scripts/setup_demo.py",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=REPOSITORY / "frontend" / "dist",
        help="frontend compilado que se sirve en /, si existe",
    )
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="habilita INSERT/DELETE (solo sobre la base de demo desechable)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    started = perf_counter()
    try:
        database = Database.open(
            demo_database(), args.data_dir, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES
        )
    except DatabaseSetupError as error:
        sys.exit(
            f"No se pudo abrir la base de demo: {error}\n"
            "Prepárala primero con: python scripts/setup_demo.py"
        )
    service = EngineService(database, allow_writes=args.allow_writes)
    print(
        f"Base de demo abierta en {perf_counter() - started:.1f} s · modo {service.mode}",
        flush=True,
    )
    try:
        app = create_app(service, presets=PRESETS, frontend_dir=args.frontend_dir)
        uvicorn.run(app, host=args.host, port=args.port, workers=1, reload=False)
    finally:
        service.close()


if __name__ == "__main__":
    main()
