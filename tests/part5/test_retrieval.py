"""Check the academic application's REST contract with controlled replies."""

import asyncio
import json

import httpx2
import pytest

from api.academic_retrieval import (
    CHUNK_FIELDS,
    PAPER_FIELDS,
    EngineUnavailable,
    InvalidEngineResponse,
    InvalidQuestion,
    retrieve_academic,
)
from scripts import check_academic_retrieval


BASE = "http://127.0.0.1:8000/parte5"
TEXT_PATH = "/parte5/api/text/query"
PAPER_PATH = "/parte5/api/query"


def reply(fields, rows, *, text, **overrides):
    body = {
        "kind": "query" if text else "rows",
        "statement": "TEXT_SEARCH" if text else "SELECT",
        "columns": [{"name": field, "position": i} for i, field in enumerate(fields)],
        "rows": rows, "returned_rows": len(rows), "total_rows": len(rows),
        "result_complete": True, "truncated": False,
        **overrides,
    }
    return httpx2.Response(200, json=body)


def text_reply(*rows, **overrides):
    return reply(CHUNK_FIELDS, rows, text=True, **overrides)


def paper_reply(*rows):
    return reply(PAPER_FIELDS, rows, text=False)


def run(responder, question="Graph hierarchy?"):
    async def request():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(responder)) as client:
            return await retrieve_academic(question, base_url=BASE + "/", client=client)
    return asyncio.run(request())


def test_reordered_columns_keep_rank_and_deduplicate_paper_lookups():
    calls = []

    def respond(request):
        assert request.url.host == "127.0.0.1"
        assert "X-Session-Token" not in request.headers
        assert request.extensions["timeout"]["read"] == 10
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == TEXT_PATH:
            fields = ("content", "position", "relevancia", "paper_id", "chunk_id")
            descriptors = [{"name": field, "position": i} for i, field in enumerate(fields)]
            return reply(fields, [
                ["First full passage.", "1", 5.0, "7", "19"],
                ["Second full passage.", 2, 4.0, 7, 18],
                ["Third full passage.", 1, 4.0, 2, 10],
            ], text=True, columns=descriptors[::-1])
        paper_id = 7 if len(calls) == 2 else 2
        return reply(("abstract", "title", "authors", "paper_id", "year"),
                     [[f"Abstract {paper_id}", f"Title {paper_id}", f"Author {paper_id}",
                       str(paper_id), "2021"]], text=False)

    result = run(respond, "  Graph hierarchy?  ")
    assert [path for path, _ in calls] == [TEXT_PATH, PAPER_PATH, PAPER_PATH]
    assert calls[0][1] == {
        "table": "chunks", "column": "content", "query": "Graph hierarchy?", "model": "BM25",
        "order": "score_desc", "limit": 3, "max_rows": 3, "use_indexes": True,
    }
    assert [payload for _, payload in calls[1:]] == [
        {"sql": f"SELECT paper_id, authors, year, title, abstract FROM papers WHERE paper_id = {i};",
         "max_rows": 2, "use_indexes": True} for i in (7, 2)
    ]
    assert result["status"] == "context"
    assert [(s["label"], s["chunk_id"], s["paper_id"], s["score"]) for s in result["sources"]] == [
        ("S1", 19, 7, 5.0), ("S2", 18, 7, 4.0), ("S3", 10, 2, 4.0),
    ]
    assert result["sources"][1] == {
        "label": "S2", "chunk_id": 18, "paper_id": 7, "position": 2,
        "title": "Title 7", "authors": "Author 7", "year": 2021, "abstract": "Abstract 7",
        "content": "Second full passage.", "score": 4.0,
    }


@pytest.mark.parametrize("question", [None, True, "", " \n\t", "a" * 4097])
def test_invalid_questions_never_send_http(question):
    with pytest.raises(InvalidQuestion):
        run(lambda request: pytest.fail("HTTP requested for invalid question"), question)


def test_zero_matches_requests_no_metadata():
    def respond(request):
        assert request.url.path == TEXT_PATH
        assert len(json.loads(request.content)["query"]) == 4096
        return text_reply()

    assert run(respond, " " + "a" * 4096 + " ") == {"status": "no_context", "sources": []}


@pytest.mark.parametrize("bad_id", [True, 1.0, 0, -1, 2**53, str(2**53), "1.0", " 1", "1 OR 1=1"])
def test_invalid_paper_id_never_reaches_sql(bad_id):
    def respond(request):
        assert request.url.path == TEXT_PATH
        return text_reply([1, bad_id, 1, "Passage", 1.0])

    with pytest.raises(InvalidEngineResponse, match="paper_id"):
        run(respond)


@pytest.mark.parametrize("rows,overrides,detail", [
    ([], {"kind": "command"}, "successful"),
    ([], {"result_complete": False, "truncated": True}, "incomplete"),
    ([], {"total_rows": 1}, "incomplete"),
    ([], {"returned_rows": False}, "incomplete"),
    ([], {"columns": [{"name": "chunk_id"}] * 5}, "column"),
    ([[1, 1, 1, "Passage"]], {}, "width"),
    ([[1, 1, 1, "Passage", "Infinity"]], {}, "finite"),
    ([[1, 1, 1, "Passage", True]], {}, "finite"),
    ([[1, 1, 0, "Passage", 1]], {}, "position"),
    ([[1, 1, 1, " ", 1]], {}, "content"),
    ([[1, 1, 1, "Passage", 1], [1, 2, 1, "Other", 1]], {}, "Duplicate chunk_id"),
    ([[1, 1, 1, "Passage", 1], [2, 1, 2, "Other", 2]], {}, "descending"),
    ([[i, 1, i, "Passage", 1] for i in range(1, 5)], {}, "bound"),
])
def test_malformed_text_response_stops_before_metadata(rows, overrides, detail):
    def respond(request):
        assert request.url.path == TEXT_PATH
        return text_reply(*rows, **overrides)

    with pytest.raises(InvalidEngineResponse, match=detail):
        run(respond)


@pytest.mark.parametrize("rows,detail", [
    ([], "one metadata"),
    ([[1, "Author", 2020, "Title", "Abstract"]] * 2, "one metadata"),
    ([[2, "Author", 2020, "Title", "Abstract"]], "does not match"),
    ([[1, "Author", True, "Title", "Abstract"]], "year"),
    ([[1, "", 2020, "Title", "Abstract"]], "authors"),
    ([[1, "Author", 2020, "Title", " "]], "abstract"),
])
def test_invalid_metadata_fails_without_partial_context(rows, detail):
    def respond(request):
        if request.url.path == TEXT_PATH:
            return text_reply([1, 1, 1, "Passage", 1])
        return paper_reply(*rows)

    with pytest.raises(InvalidEngineResponse, match=detail):
        run(respond)


@pytest.mark.parametrize("status,error", [(404, EngineUnavailable), (503, EngineUnavailable),
                                          (422, InvalidEngineResponse)])
def test_engine_error_is_not_an_empty_result(status, error):
    with pytest.raises(error, match=f"HTTP {status}"):
        run(lambda request: httpx2.Response(status))


def test_invalid_json_is_not_an_empty_result():
    with pytest.raises(InvalidEngineResponse, match="valid JSON"):
        run(lambda request: httpx2.Response(200, text="not JSON"))


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_cli_reports_transport_errors_and_closes_client(monkeypatch, capsys, error):
    def fail(request):
        raise error("transport test", request=request)

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(fail))
    monkeypatch.setattr(check_academic_retrieval.httpx2, "AsyncClient", lambda **kwargs: client)
    assert check_academic_retrieval.main(["--base-url", BASE, "--question", "Graph?"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "EngineUnavailable" in captured.err
    assert client.is_closed
