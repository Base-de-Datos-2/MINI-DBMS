"""Serve the Stage 9 demonstration: ``python -m api [options]``.

Prepare the data first, with the server stopped:

    python scripts/setup_demo.py

The server then reopens that directory. It runs one process with one worker
and no auto-reload, because one process must own the data directory.

On Ctrl+C the server stops accepting requests, waits a bounded time, cancels
every session's running statement, aborts open transaction groups and only
then closes the data files.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import socket
import sys
import threading
from time import perf_counter

import uvicorn

from .app import create_app
from .database import Database, DatabaseSetupError
from .demo import DEMO_MEMORY_BUDGET_BYTES, PRESETS, demo_database
from .engine_service import EngineService


REPOSITORY = Path(__file__).resolve().parents[1]


class _Server(uvicorn.Server):
    """Uvicorn server that cancels running statements as soon as it must stop."""

    def __init__(self, config: uvicorn.Config, service: EngineService) -> None:
        super().__init__(config)
        self._service = service

    def handle_exit(self, sig, frame) -> None:
        # Off the signal handler: cancellation takes engine locks.
        threading.Thread(target=self._service.begin_shutdown, daemon=True).start()
        super().handle_exit(sig, frame)


def port_is_free(host: str, port: int) -> bool:
    """Report whether ``host:port`` can be bound right now.

    Checked before the database is opened: a second server must fail without
    ever touching the data directory the first one owns.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


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

    if not port_is_free(args.host, args.port):
        sys.exit(
            f"El puerto {args.port} ya está en uso: probablemente ya hay un servidor "
            "de la demo corriendo. Deténlo o usa --port. No se abrió ningún archivo."
        )
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
        # Running statements are cancelled when the stop is requested, so open
        # connections get a real answer; the bound only caps a stuck client.
        config = uvicorn.Config(
            app, host=args.host, port=args.port, workers=1, reload=False,
            timeout_graceful_shutdown=5,
        )
        _Server(config, service).run()
    finally:
        try:
            service.close()
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            sys.exit(
                f"El cierre no terminó de forma segura ({error}). Los archivos quedaron "
                "abiertos por seguridad; revisa el directorio antes de reabrirlo."
            )


if __name__ == "__main__":
    main()
