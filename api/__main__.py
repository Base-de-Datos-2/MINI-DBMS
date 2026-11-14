"""Serve the Stage 9 demonstration: ``python -m api [options]``.

Prepare the data first, with the server stopped:

    python scripts/setup_demo.py

The server then reopens that directory. It runs one process with one worker
and no auto-reload, because one process must own the data directory.

``python -m api --all`` serves every prepared part on one port, one tab each
(prepare them with ``python scripts/setup_all.py``; see api/unified.py).

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

from .academic_config import AcademicConfigError, load_academic_settings
from .app import create_app
from .database import Database, DatabaseDefinition, DatabaseSetupError
from .demo import DEMO_MEMORY_BUDGET_BYTES, demo_database
from .engine_service import EngineService
from .unified import PRESETS_BY_KIND, SETUP_COMMAND, close_parts, create_unified_app, open_parts


REPOSITORY = Path(__file__).resolve().parents[1]
#: Root that scripts/setup_all.py prepares: one subdirectory per part.
ALL_DIRECTORY = REPOSITORY / "data" / "generated" / "todas"


class _Server(uvicorn.Server):
    """Uvicorn server that cancels running statements as soon as it must stop."""

    def __init__(self, config: uvicorn.Config, *services: EngineService) -> None:
        super().__init__(config)
        self._services = services

    def handle_exit(self, sig, frame) -> None:
        # Off the signal handler: cancellation takes engine locks.
        for service in self._services:
            threading.Thread(target=service.begin_shutdown, daemon=True).start()
        super().handle_exit(sig, frame)


def port_is_free(host: str, port: int) -> bool:
    """Report whether ``host:port`` can be bound right now.

    Checked before the database is opened: a second server must fail without
    ever touching the data directory the first one owns.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            # Match Uvicorn on POSIX: TIME_WAIT is not an active listener.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
        default=None,
        help="directorio preparado (con --all: la raíz que prepara scripts/setup_all.py)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true",
                      help="sirve todas las partes preparadas con setup_all.py en un solo puerto")
    mode.add_argument('--text', action='store_true', help='abre colecciones preparadas con setup_text.py')
    mode.add_argument("--spatial", action="store_true",
                        help="abre la muestra de Parte 02 preparada con setup_spatial.py")
    mode.add_argument("--multimedia", action="store_true",
                      help="abre las colecciones de imágenes/audio preparadas con setup_multimedia.py")
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
        help="habilita INSERT, DELETE, CREATE INDEX, UPDATE y DROP en la demo (base desechable; con --all, solo Partes 1 y 2)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.all:
        _serve_all(args)
        return
    kind = "text" if args.text else "spatial" if args.spatial else "multimedia" if args.multimedia else "demo"
    if args.data_dir is None:
        args.data_dir = REPOSITORY / "data/generated" / kind
    setup_script = {"text": "setup_text.py", "spatial": "setup_spatial.py",
                    "multimedia": "setup_multimedia.py", "demo": "setup_demo.py"}[kind]
    definition = demo_database() if kind == "demo" else DatabaseDefinition(kind)

    if not port_is_free(args.host, args.port):
        sys.exit(
            f"El puerto {args.port} ya está en uso: probablemente ya hay un servidor "
            "de la demo corriendo. Deténlo o usa --port. No se abrió ningún archivo."
        )
    started = perf_counter()
    try:
        if args.text and not (args.data_dir / 'text_tables.json').is_file():
            raise DatabaseSetupError('Falta el registro de colecciones textuales publicadas')
        if args.spatial and not (args.data_dir / "spatial_tables.json").is_file():
            raise DatabaseSetupError("Falta el mapeo de la muestra espacial")
        if args.multimedia and not (args.data_dir / "multimedia_tables.json").is_file():
            raise DatabaseSetupError("Falta el registro de colecciones multimedia publicadas")
        database = Database.open(
            definition, args.data_dir, memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES
        )
    except DatabaseSetupError as error:
        sys.exit(
            f"No se pudo abrir la base de demo: {error}\n"
            f"Prepárala primero con: python scripts/{setup_script}"
        )
    service = EngineService(database, allow_writes=args.allow_writes)
    print(
        f"Base de demo abierta en {perf_counter() - started:.1f} s · modo {service.mode}",
        flush=True,
    )
    try:
        app = create_app(service, presets=PRESETS_BY_KIND[kind],
                         frontend_dir=args.frontend_dir)
        _run(app, args, service)
    finally:
        try:
            service.close()
        except Exception as error:  # noqa: BLE001 - reported, not hidden
            sys.exit(
                f"El cierre no terminó de forma segura ({error}). Los archivos quedaron "
                "abiertos por seguridad; revisa el directorio antes de reabrirlo."
            )


def _run(app, args, *services: EngineService) -> None:
    # Running statements are cancelled when the stop is requested, so open
    # connections get a real answer; the bound only caps a stuck client.
    config = uvicorn.Config(
        app, host=args.host, port=args.port, workers=1, reload=False,
        timeout_graceful_shutdown=5,
    )
    try:
        _Server(config, *services).run()
    except KeyboardInterrupt:
        # Uvicorn may re-raise SIGINT after completing its graceful shutdown.
        pass


def _serve_all(args) -> None:
    """Open every prepared part under one root and serve them on one port."""

    root = args.data_dir if args.data_dir is not None else ALL_DIRECTORY
    if not port_is_free(args.host, args.port):
        sys.exit(
            f"El puerto {args.port} ya está en uso: probablemente ya hay un servidor "
            "de la demo corriendo. Deténlo o usa --port. No se abrió ningún archivo."
        )
    started = perf_counter()
    parts = open_parts(root, allow_writes=args.allow_writes)
    ready = [part for part in parts if part.service is not None]
    if not ready:
        sys.exit(f"No hay ninguna parte preparada en {root}.\nPrepáralas primero con: {SETUP_COMMAND}")
    print(f"Partes abiertas en {perf_counter() - started:.1f} s:", flush=True)
    for part in parts:
        state = (f"/{part.spec.id} · modo {part.service.mode}" if part.service is not None
                 else f"no disponible ({part.problem})")
        print(f"  Parte {part.spec.number} {part.spec.title:11} {state}", flush=True)
    try:
        academic_settings = None
        if any(part.spec.id == "parte5" for part in ready):
            try:
                academic_settings = load_academic_settings(port=args.port)
            except AcademicConfigError as error:
                logging.getLogger("minidbms.api").warning("Academic RAG configuration: %s", error)
        app = create_unified_app(parts, frontend_dir=args.frontend_dir, academic_settings=academic_settings)
        _run(app, args, *(part.service for part in ready))
    finally:
        problems = close_parts(parts)
        if problems:
            sys.exit(
                "El cierre no terminó de forma segura (" + "; ".join(problems) + "). "
                "Los archivos quedaron abiertos por seguridad; revisa el directorio antes de reabrirlo."
            )


if __name__ == "__main__":
    main()
