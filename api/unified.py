"""One server, one port: every project part behind its own path prefix.

``python -m api --all`` opens the database of each part that has been
prepared (``scripts/setup_all.py``) and mounts the ordinary Stage 9 API of each
one under ``/parte<N>``:

    /api/parts                  which parts exist and whether they are ready
    /parte1/api/...             Part 1, relational demo
    /parte2/api/...             Part 2, spatial demo (Lima)
    /parte3/api/...             Part 3, text collections
    /parte4/api/...             Part 4, image and audio collections
    /                           the frontend, one tab per part

Each part keeps its own data directory, owner, sessions and limits: a part is
exactly the server that ``python -m api --<kind>`` would run, only mounted.
Nothing here touches SQL, storage or indexes.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .app import create_app
from .database import Database, DatabaseDefinition, DatabaseSetupError
from .demo import (
    DEMO_MEMORY_BUDGET_BYTES,
    MULTIMEDIA_PRESETS,
    PRESETS,
    SPATIAL_PRESETS,
    TEXT_PRESETS,
    Preset,
    demo_database,
)
from .engine_service import EngineService
from .schemas import SESSION_SWEEP_INTERVAL_SECONDS


@dataclass(frozen=True, slots=True)
class PartSpec:
    """A project part as the unified server exposes it."""

    id: str
    number: int
    title: str
    description: str
    kind: str
    registry: str | None
    writable: bool

    @property
    def prefix(self) -> str:
        return f"/{self.id}"


#: The parts in tab order. ``registry`` is the file a prepared directory must
#: hold; ``writable`` says whether ``--allow-writes`` applies (Parts 3 and 4
#: publish sealed collections, which reject writes anyway).
PARTS = (
    PartSpec("parte1", 1, "Relacional",
             "Heap, archivo secuencial, B+, hashing extensible, SQL y transacciones",
             "demo", None, True),
    PartSpec("parte2", 2, "Espacial", "R-Tree, consultas por radio y k vecinos sobre Lima",
             "spatial", "spatial_tables.json", True),
    PartSpec("parte3", 3, "Texto", "Índice invertido SPIMI con TF-IDF y BM25",
             "text", "text_tables.json", False),
    PartSpec("parte4", 4, "Multimedia", "SIFT y MFCC con índices IVF y HNSW",
             "multimedia", "multimedia_tables.json", False),
)

PRESETS_BY_KIND: dict[str, tuple[Preset, ...]] = {
    "demo": PRESETS,
    "spatial": SPATIAL_PRESETS,
    "text": TEXT_PRESETS,
    "multimedia": MULTIMEDIA_PRESETS,
}

SETUP_COMMAND = "python scripts/setup_all.py"


def definition_for(kind: str) -> DatabaseDefinition:
    return demo_database() if kind == "demo" else DatabaseDefinition(kind)


@dataclass(slots=True)
class OpenedPart:
    """One part after the launcher tried to open it."""

    spec: PartSpec
    service: EngineService | None
    problem: str | None = None

    def describe(self) -> dict[str, Any]:
        ready = self.service is not None
        return {
            "id": self.spec.id,
            "number": self.spec.number,
            "title": self.spec.title,
            "description": self.spec.description,
            "kind": self.spec.kind,
            "base": self.spec.prefix if ready else None,
            "status": "ready" if ready else "missing",
            "mode": self.service.mode if ready else None,
            "problem": self.problem,
            "setup": None if ready else SETUP_COMMAND,
        }


def open_parts(root: Path, *, allow_writes: bool,
               specs: Sequence[PartSpec] = PARTS) -> list[OpenedPart]:
    """Open every prepared part under ``root``; a missing one is reported, not fatal.

    A failure after some parts opened closes them before re-raising, so no
    data directory is left owned by a half-started server.
    """

    opened: list[OpenedPart] = []
    try:
        for spec in specs:
            directory = Path(root) / spec.id
            if spec.registry is not None and not (directory / spec.registry).is_file():
                opened.append(OpenedPart(spec, None, f"No hay datos preparados en {directory.name}/"))
                continue
            try:
                database = Database.open(definition_for(spec.kind), directory,
                                         memory_budget_bytes=DEMO_MEMORY_BUDGET_BYTES)
            except DatabaseSetupError as error:
                opened.append(OpenedPart(spec, None, str(error)))
                continue
            opened.append(OpenedPart(spec, EngineService(
                database, allow_writes=allow_writes and spec.writable)))
    except BaseException:
        close_parts(opened)
        raise
    return opened


def close_parts(parts: Sequence[OpenedPart]) -> list[str]:
    """Close every opened part; return the problems instead of stopping early."""

    problems = []
    for part in parts:
        if part.service is None:
            continue
        try:
            part.service.close()
        except Exception as error:  # noqa: BLE001 - every part must get its chance
            problems.append(f"{part.spec.id}: {error}")
    return problems


def create_unified_app(
    parts: Sequence[OpenedPart],
    *,
    frontend_dir: object | None = None,
    sweep_interval_seconds: float = SESSION_SWEEP_INTERVAL_SECONDS,
) -> FastAPI:
    """Mount the Stage 9 API of each ready part under its prefix."""

    children = {
        part.spec.id: create_app(part.service, presets=PRESETS_BY_KIND[part.spec.kind],
                                 sweep_interval_seconds=sweep_interval_seconds)
        for part in parts if part.service is not None
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Mounted applications do not run their own lifespan: start each
        # part's idle-session sweeper here, and stop them in reverse order.
        async with AsyncExitStack() as stack:
            for child in children.values():
                await stack.enter_async_context(child.router.lifespan_context(child))
            yield

    app = FastAPI(lifespan=lifespan, title="MINI-DBMS", version="0.9.0",
                  description="Todas las partes del proyecto en un solo servidor.")
    app.state.parts = tuple(parts)

    @app.get("/api/parts")
    def list_parts() -> list[dict[str, Any]]:
        return [part.describe() for part in parts]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        # Cached state only, like each part's own /api/health: a hosting health
        # check (Render) sees "ready" while at least one part is serving.
        states = {part.spec.id: (part.service.state if part.service is not None else "missing")
                  for part in parts}
        return {"status": "ready" if "ready" in states.values() else "unavailable",
                "parts": states}

    for identifier, child in children.items():
        app.mount(f"/{identifier}", child, name=identifier)

    if frontend_dir is not None:
        directory = Path(frontend_dir)
        if (directory / "index.html").is_file():
            app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")
    return app


__all__ = ["PARTS", "PRESETS_BY_KIND", "OpenedPart", "PartSpec", "close_parts",
           "create_unified_app", "definition_for", "open_parts"]
