"""HTTP transport for the Stage 9 demonstration: thin routes over EngineService.

Routes validate transport input, delegate to :class:`EngineService`, and wrap
the outcome in JSON. They contain no SQL semantics and no storage, indexing,
planning or execution logic.

Every response carries a request ID. Errors share one envelope with a stable
code, a message, the request ID and, for SQL errors, the parser's source
location. Tracebacks and local paths stay in the server log.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .demo import Preset
from .engine_service import EngineService
from .errors import ServiceError
from .schemas import (
    DEFAULT_PREVIEW_ROWS,
    ERROR_STATUS,
    IMPORT_ROUTES,
    MAX_IMPORT_REQUEST_BYTES,
    MAX_PREVIEW_ROWS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SQL_BYTES,
    SESSION_HEADER,
    SESSION_SWEEP_INTERVAL_SECONDS,
    CreateTableRequest,
    CsvPreviewRequest,
    QueryRequest,
)
from .sessions import SessionSweeper
from .table_import import MAX_CSV_BYTES, MAX_IMPORT_ROWS


logger = logging.getLogger("minidbms.api")

#: Limits the frontend displays and respects; the server enforces them anyway.
LIMITS = {
    "default_preview_rows": DEFAULT_PREVIEW_ROWS,
    "max_preview_rows": MAX_PREVIEW_ROWS,
    "max_sql_bytes": MAX_SQL_BYTES,
    "max_response_bytes": MAX_RESPONSE_BYTES,
    "max_csv_bytes": MAX_CSV_BYTES,
    "max_import_rows": MAX_IMPORT_ROWS,
}


def _envelope(
    request: Request,
    code: str,
    message: str,
    **extra: Any,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    for key in ("location", "details"):
        if extra.get(key) is not None:
            error[key] = extra.pop(key)
        else:
            extra.pop(key, None)
    # Other extras (statement, plan, mode, session status) sit beside "error".
    body = {"error": error, **{k: v for k, v in extra.items() if v is not None}}
    return JSONResponse(status_code=ERROR_STATUS[code], content=body)


SessionToken = Annotated[str | None, Header(alias=SESSION_HEADER)]


def create_app(
    service: EngineService,
    *,
    presets: tuple[Preset, ...] = (),
    frontend_dir: object | None = None,
    sweep_interval_seconds: float = SESSION_SWEEP_INTERVAL_SECONDS,
) -> FastAPI:
    """Build the API around a service that already owns an open engine."""

    if not isinstance(service, EngineService):
        raise TypeError("create_app requires an EngineService")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Expires idle sessions so an abandoned tab cannot hold locks forever.
        sweeper = SessionSweeper(service.sessions, sweep_interval_seconds)
        sweeper.start()
        try:
            yield
        finally:
            sweeper.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="MINI-DBMS",
        version="0.9.0",
        description="Interfaz HTTP de la demo de la Etapa 9 sobre el motor SQL.",
    )
    app.state.service = service

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid4().hex
        declared = request.headers.get("content-length")
        # Only the CSV routes may carry a large body.
        limit = (
            MAX_IMPORT_REQUEST_BYTES
            if request.method == "POST" and request.url.path in IMPORT_ROUTES
            else MAX_REQUEST_BYTES
        )
        if declared is not None and declared.isdigit() and int(declared) > limit:
            response = _envelope(
                request,
                "REQUEST_TOO_LARGE",
                f"El cuerpo excede el límite de {limit} bytes.",
            )
        else:
            try:
                response = await call_next(request)
            except Exception:
                # Caught here rather than by an app-level handler so the 500
                # carries the same envelope and header as every other response.
                # Details go to the server log only.
                logger.exception(
                    "request %s failed unexpectedly", request.state.request_id
                )
                response = _envelope(
                    request,
                    "INTERNAL_ERROR",
                    "Error inesperado del servidor; revisa el log con este request_id.",
                )
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        logger.info(
            "request %s failed with %s", request.state.request_id, error.code
        )
        return _envelope(
            request,
            error.code,
            error.message,
            location=error.location,
            details=error.details,
            session=error.session,
            statement=error.statement,
            execution_plan=error.execution_plan,
            plan_status="prepared" if error.execution_plan else None,
            mode=service.mode,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        fields = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        return _envelope(request, "INVALID_REQUEST", f"Petición inválida: {fields}")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {**service.health(), "limits": LIMITS}

    @app.get("/api/presets")
    def list_presets() -> list[dict[str, str]]:
        return [
            {"label": preset.label, "purpose": preset.purpose, "sql": preset.sql}
            for preset in presets
        ]

    @app.get("/api/tables")
    def list_tables() -> list[dict[str, Any]]:
        return service.list_tables()

    @app.get("/api/tables/{table_id}")
    def get_table(table_id: str) -> dict[str, Any]:
        return service.describe_table(table_id)

    @app.post("/api/import/preview")
    def preview_import(payload: CsvPreviewRequest) -> dict[str, Any]:
        return service.preview_csv(payload)

    @app.post("/api/tables", status_code=201)
    def create_table(
        payload: CreateTableRequest, request: Request, token: SessionToken = None,
    ) -> dict[str, Any]:
        body = service.create_table(payload, request.state.request_id, token)
        logger.info(
            "request %s created table %s rows=%s",
            request.state.request_id,
            body["table"]["name"],
            body["loaded_rows"],
        )
        return body

    @app.post("/api/sessions", status_code=201)
    def open_session() -> dict[str, Any]:
        return service.open_session()

    @app.get("/api/session")
    def session_status(token: SessionToken = None) -> dict[str, Any]:
        return service.session_status(token)

    @app.post("/api/session/cancel")
    def cancel_session(token: SessionToken = None) -> dict[str, Any]:
        return service.cancel_session(token)

    @app.delete("/api/session")
    def close_session(token: SessionToken = None) -> dict[str, Any]:
        return service.close_session(token)

    @app.post("/api/query")
    def query(payload: QueryRequest, request: Request, token: SessionToken = None) -> dict[str, Any]:
        body = service.execute(payload, request.state.request_id, token)
        logger.info(
            "request %s %s rows=%s truncated=%s",
            request.state.request_id,
            body.get("statement"),
            body.get("returned_rows"),
            body.get("truncated"),
        )
        return body

    if frontend_dir is not None:
        directory = Path(frontend_dir)
        if (directory / "index.html").is_file():
            # Mounted last, so every /api route above takes precedence.
            app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")

    return app
