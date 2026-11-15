"""Retrieve ranked academic passages and paper metadata through engine REST."""

from __future__ import annotations

import math
import re
from typing import Literal, TypedDict

import httpx2

from .academic_schema import CHUNK_COLUMNS, PAPER_COLUMNS
from .schemas import JS_SAFE_INTEGER


TOP_K = 3
MAX_QUESTION_CHARS = 4096
REQUEST_TIMEOUT_SECONDS = 10.0
CHUNK_FIELDS = tuple(name for name, _ in CHUNK_COLUMNS) + ("relevancia",)
PAPER_FIELDS = tuple(name for name, _ in PAPER_COLUMNS)
PAPER_SELECT = f"SELECT {', '.join(PAPER_FIELDS)} FROM papers WHERE paper_id = {{}};"
DECIMAL_INT = re.compile(r"(?:0|-?[1-9][0-9]{0,18})")


class InvalidQuestion(ValueError):
    """The caller's question cannot be sent to the engine."""


class RetrievalError(RuntimeError):
    """Base error for a failed engine interaction."""


class EngineUnavailable(RetrievalError):
    """The configured engine service cannot handle the request."""


class InvalidEngineResponse(RetrievalError):
    """The engine rejected the request or returned inconsistent data."""


class PaperMetadata(TypedDict):
    title: str
    authors: str
    year: int
    abstract: str


class RankedChunk(TypedDict):
    chunk_id: int
    paper_id: int
    position: int
    content: str
    score: float


class Source(PaperMetadata, RankedChunk):
    label: str


class RetrievalResult(TypedDict):
    status: Literal["context", "no_context"]
    sources: list[Source]


def normalize_question(question: object) -> str:
    if not isinstance(question, str):
        raise InvalidQuestion("Question must be a string")
    question = question.strip()
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        raise InvalidQuestion(f"Question must contain 1–{MAX_QUESTION_CHARS} characters after trimming")
    return question


async def _query_rows(
    client: httpx2.AsyncClient,
    url: str,
    payload: dict,
    *,
    kind: str,
    statement: str,
    fields: tuple[str, ...],
) -> list[dict]:
    try:
        response = await client.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS,
                                     follow_redirects=False)
    except httpx2.RequestError as error:
        raise EngineUnavailable(f"{statement} request to the engine failed") from error
    if response.status_code == 404 or response.status_code >= 500:
        raise EngineUnavailable(f"{statement} engine route unavailable (HTTP {response.status_code})")
    if not response.is_success:
        raise InvalidEngineResponse(f"{statement} engine request returned HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise InvalidEngineResponse(f"{statement} did not return valid JSON") from error
    if (not isinstance(body, dict) or "error" in body or body.get("kind") != kind
            or body.get("statement") != statement):
        raise InvalidEngineResponse(f"Expected a successful {statement} response")

    rows = body.get("rows")
    if (not isinstance(rows, list) or len(rows) > payload["max_rows"]
            or body.get("result_complete") is not True or body.get("truncated") is not False
            or any(type(body.get(count)) is not int or body[count] != len(rows)
                   for count in ("returned_rows", "total_rows"))):
        raise InvalidEngineResponse(f"{statement} rows are incomplete or exceed the requested bound")

    columns = body.get("columns")
    if not isinstance(columns, list) or len(columns) != len(fields):
        raise InvalidEngineResponse(f"Unexpected {statement} columns")
    positions = {}
    for column in columns:
        if not isinstance(column, dict):
            raise InvalidEngineResponse(f"Invalid {statement} column descriptor")
        name, position = column.get("name"), column.get("position")
        if (not isinstance(name, str) or name not in fields or name in positions
                or type(position) is not int or not 0 <= position < len(fields)
                or position in positions.values()):
            raise InvalidEngineResponse(f"Invalid {statement} column name or position")
        positions[name] = position

    mapped = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(fields):
            raise InvalidEngineResponse(f"Invalid {statement} row width")
        mapped.append({field: row[positions[field]] for field in fields})
    return mapped


def _integer(value: object, field: str) -> int:
    if isinstance(value, str) and DECIMAL_INT.fullmatch(value):
        value = int(value)
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise InvalidEngineResponse(f"Invalid integer field {field}")
    return value


def _identifier(value: object, field: str) -> int:
    identifier = _integer(value, field)
    if not 1 <= identifier <= JS_SAFE_INTEGER:
        raise InvalidEngineResponse(f"{field} is outside the positive exact-integer range")
    return identifier


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEngineResponse(f"Expected nonempty text for {field}")
    return value


def _score(value: object) -> float:
    if type(value) not in (int, float):
        raise InvalidEngineResponse("Expected a finite numeric BM25 score")
    try:
        score = float(value)
    except OverflowError as error:
        raise InvalidEngineResponse("Expected a finite numeric BM25 score") from error
    if not math.isfinite(score):
        raise InvalidEngineResponse("Expected a finite numeric BM25 score")
    return score


async def retrieve_academic(
    question: object, *, base_url: str, client: httpx2.AsyncClient,
) -> RetrievalResult:
    """Use a caller-owned async client and a server-configured Part 5 base URL."""
    question = normalize_question(question)
    base_url = base_url.rstrip("/")
    rows = await _query_rows(
        client, f"{base_url}/api/text/query",
        {"table": "chunks", "column": "content", "query": question, "model": "BM25",
         "order": "score_desc", "limit": TOP_K, "max_rows": TOP_K, "use_indexes": True},
        kind="query", statement="TEXT_SEARCH", fields=CHUNK_FIELDS,
    )
    if not rows:
        return {"status": "no_context", "sources": []}

    chunks: list[RankedChunk] = []
    chunk_ids = set()
    for row in rows:
        chunk_id = _identifier(row["chunk_id"], "chunk_id")
        if chunk_id in chunk_ids:
            raise InvalidEngineResponse(f"Duplicate chunk_id {chunk_id}")
        chunk_ids.add(chunk_id)
        score = _score(row["relevancia"])
        if chunks and score > chunks[-1]["score"]:
            raise InvalidEngineResponse("Engine returned BM25 scores out of descending order")
        chunks.append({
            "chunk_id": chunk_id,
            "paper_id": _identifier(row["paper_id"], "paper_id"),
            "position": _identifier(row["position"], "position"),
            "content": _text(row["content"], "content"),
            "score": score,
        })

    metadata: dict[int, PaperMetadata] = {}
    for paper_id in dict.fromkeys(chunk["paper_id"] for chunk in chunks):
        rows = await _query_rows(
            client, f"{base_url}/api/query",
            {"sql": PAPER_SELECT.format(paper_id), "max_rows": 2, "use_indexes": True},
            kind="rows", statement="SELECT", fields=PAPER_FIELDS,
        )
        if len(rows) != 1:
            raise InvalidEngineResponse(f"Expected one metadata row for paper_id {paper_id}")
        row = rows[0]
        if _identifier(row["paper_id"], "paper_id") != paper_id:
            raise InvalidEngineResponse(f"Metadata does not match paper_id {paper_id}")
        metadata[paper_id] = {
            "title": _text(row["title"], "title"),
            "authors": _text(row["authors"], "authors"),
            "year": _integer(row["year"], "year"),
            "abstract": _text(row["abstract"], "abstract"),
        }

    sources = [{"label": f"S{rank}", **chunk, **metadata[chunk["paper_id"]]}
               for rank, chunk in enumerate(chunks, 1)]
    return {"status": "context", "sources": sources}
