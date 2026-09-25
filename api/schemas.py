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

#: Larger body limit for the two routes that carry a CSV upload. The CSV text
#: itself is capped separately by ``api.table_import.MAX_CSV_BYTES``; JSON
#: escaping can double it, hence the margin.
MAX_IMPORT_REQUEST_BYTES = 17 * 1024 * 1024
IMPORT_ROUTES = frozenset({"/api/import/preview", "/api/tables"})

#: Byte budget for one encoded query response, metadata included.
MAX_RESPONSE_BYTES = 1024 * 1024

#: Bounds on a serialized plan tree, so a descriptor can never be oversized.
MAX_PLAN_NODES = 128
MAX_PLAN_DEPTH = 32

#: Largest integer JavaScript represents exactly. Larger INTEGER values travel
#: as decimal strings so the browser never rounds them.
JS_SAFE_INTEGER = 2**53 - 1

#: Header that carries an opaque client session token.
SESSION_HEADER = "X-Session-Token"

#: Live client sessions one server keeps; each owns one engine SqlSession.
MAX_CLIENT_SESSIONS = 16

#: A token unused for this long expires: its engine session is closed and any
#: open transaction group is aborted, releasing its locks.
SESSION_IDLE_TIMEOUT_SECONDS = 300.0

#: How often the server looks for expired sessions.
SESSION_SWEEP_INTERVAL_SECONDS = 15.0

#: Bounded wait for cancelled work when a session or the server closes.
SHUTDOWN_TIMEOUT_SECONDS = 5.0

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
    "WRITES_DISABLED": 403,
    "DEFINITION_ERROR": 422,
    "CSV_ERROR": 422,
    "TABLE_EXISTS": 409,
    "NOT_FOUND": 404,
    "ENGINE_BUSY": 409,
    "REQUEST_TOO_LARGE": 413,
    "ENGINE_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
    # Stage 8 sessions and transactions over HTTP.
    "SESSION_NOT_FOUND": 404,
    "SESSION_BUSY": 409,
    "SESSION_LIMIT": 429,
    "TRANSACTION_PROTOCOL": 409,
    "TRANSACTION_ABORTED": 409,
    "TRANSACTION_CANCELLED": 409,
    "LOCK_TIMEOUT": 409,
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


ColumnType = Literal["INTEGER", "FLOAT", "BOOLEAN", "VARCHAR"]
Delimiter = Literal[",", ";", "\t", "|"]


class ColumnSpec(BaseModel):
    """One column of a table created from the Files panel."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    type: ColumnType


class IndexSpec(BaseModel):
    """One requested index; the server generates its name."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=64)
    type: Literal["BPLUS", "EXTENDIBLE_HASH"]
    unique: bool = False


class CsvSource(BaseModel):
    """CSV text read by the browser. Its columns map by position."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=255)
    delimiter: Delimiter | None = None


class CreateTableRequest(BaseModel):
    """Create a table, optionally loading the rows of one CSV upload."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    organization: Literal["HEAP", "SEQUENTIAL"] = "HEAP"
    key_column: str | None = None
    columns: list[ColumnSpec] = Field(min_length=1, max_length=32)
    indexes: list[IndexSpec] = Field(default_factory=list, max_length=8)
    csv: CsvSource | None = None


class CsvPreviewRequest(BaseModel):
    """Describe a CSV upload (header, inferred types, samples) without loading it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    filename: str | None = Field(default=None, max_length=255)
    delimiter: Delimiter | None = None
