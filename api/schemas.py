"""The frozen Stage 9 presentation contract: limits, error codes and requests.

These values implement ETAPA_09.md Sections 5-7. They are project defaults for
the emergency demonstration, not academic requirements.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


#: Rows shown when a request does not ask for a specific preview size.
DEFAULT_PREVIEW_ROWS = 100

#: Hard server-side cap on the preview, independent of any client validation.
MAX_PREVIEW_ROWS = 500

#: SQL text limit in UTF-8 bytes. It is stricter than the engine's own
#: 65,536-character lexer limit, so the transport rejects oversized input first.
MAX_SQL_BYTES = 32 * 1024

#: Largest HTTP request body accepted before JSON parsing.
MAX_REQUEST_BYTES = 64 * 1024

#: Byte budget for one encoded query response, metadata included.
MAX_RESPONSE_BYTES = 1024 * 1024

#: Bounds on a serialized plan tree, so a descriptor can never be oversized.
MAX_PLAN_NODES = 128
MAX_PLAN_DEPTH = 32

#: Largest integer JavaScript represents exactly. Larger INTEGER values travel
#: as decimal strings so the browser never rounds them.
JS_SAFE_INTEGER = 2**53 - 1

#: Presentation modes reported by health and by every query response.
READ_ONLY = "read-only"
SERIALIZED_WRITES = "serialized-writes"

#: Stable error codes, with the HTTP status each one is sent with.
ERROR_STATUS = {
    "INVALID_REQUEST": 422,
    "SQL_ERROR": 422,
    "EXECUTION_REFUSED": 422,
    "RESULT_TOO_LARGE": 422,
    "STATEMENT_DISABLED": 403,
    "NOT_FOUND": 404,
    "ENGINE_BUSY": 409,
    "REQUEST_TOO_LARGE": 413,
    "ENGINE_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
}


class QueryRequest(BaseModel):
    """One SQL statement plus the real planner options the GUI exposes.

    ``use_indexes`` and ``join_strategy`` are passed straight to
    ``SqlEngine.prepare``; they change what actually executes, never a label.
    """

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(min_length=1)
    max_rows: int = Field(default=DEFAULT_PREVIEW_ROWS, ge=0, le=MAX_PREVIEW_ROWS)
    use_indexes: bool = True
    join_strategy: Literal["AUTO", "GRACE_HASH", "NESTED_LOOP"] = "AUTO"
