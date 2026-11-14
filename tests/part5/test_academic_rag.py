"""Check academic generation and retrieval without a real provider call."""

import asyncio
import json

import httpx2
import pytest

from api import academic_rag
from api.academic_config import AcademicSettings
from api.academic_retrieval import InvalidQuestion


SETTINGS = AcademicSettings("dummy-provider-secret", "gpt-6-luna", "http://127.0.0.1:8000/parte5")
SOURCE = {
    "label": "S1", "chunk_id": 17, "paper_id": 3, "position": 2,
    "title": "Graph retrieval", "authors": "A. Researcher", "year": 2021,
    "content": 'Layers are searched from the top.\nThe passage includes "quoted" text.',
    "score": 5.25,
}


def install_provider(monkeypatch, responder):
    sdk = pytest.importorskip("openai", reason="the provider adapter uses the optional rag extra")
    original_client = sdk.AsyncOpenAI
    transport_client = httpx2.AsyncClient(transport=httpx2.MockTransport(responder))
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return original_client(http_client=transport_client, **kwargs)

    monkeypatch.setattr(sdk, "AsyncOpenAI", factory)
    return transport_client, calls


def provider_response(*, status="completed", content=None, **fields):
    return httpx2.Response(200, json={
        "id": "resp_test", "model": "gpt-6-luna", "status": status,
        "object": "response", "created_at": 0,
        "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed",
                    "content": content if content is not None else []}],
        "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        **fields,
    })


def test_generation_sends_only_the_passages_and_returns_the_same_sources(monkeypatch):
    requests = []
    engine_clients = []

    async def retrieve(question, *, base_url, client):
        assert question == "How does the graph search work?"
        assert base_url == SETTINGS.engine_base_url
        engine_clients.append(client)
        return {"status": "context", "sources": [{**SOURCE, "abstract": "Internal abstract"}]}

    def respond(request):
        assert engine_clients[0].is_closed
        assert str(request.url) == "https://api.openai.com/v1/responses"
        requests.append(json.loads(request.content))
        return provider_response(content=[{
            "type": "output_text", "text": "  Search starts in the top layer [S1].  ", "annotations": [],
        }])

    monkeypatch.setattr(academic_rag, "retrieve_academic", retrieve)
    client, calls = install_provider(monkeypatch, respond)
    result = asyncio.run(academic_rag.ask_academic("  How does the graph search work?  ", settings=SETTINGS))

    assert result == {"status": "answered", "answer": "Search starts in the top layer [S1].", "sources": [SOURCE]}
    assert len(calls) == len(requests) == 1
    assert calls[0]["max_retries"] == 0 and calls[0]["timeout"] == 45.0
    [payload] = requests
    assert payload["model"] == SETTINGS.model and payload["store"] is False
    assert payload["reasoning"] == {"effort": "none"} and payload["max_output_tokens"] == 500
    assert "insufficient" in payload["instructions"]
    assert json.loads(payload["input"]) == {
        "question": "How does the graph search work?",
        "sources": [{key: SOURCE[key] for key in ("label", "title", "authors", "year", "chunk_id", "content")}],
    }
    assert client.is_closed


def test_no_context_skips_generation_without_a_key(monkeypatch):
    async def retrieve(*args, **kwargs):
        return {"status": "no_context", "sources": []}

    async def generate(*args, **kwargs):
        pytest.fail("Generation ran without sources")

    monkeypatch.setattr(academic_rag, "retrieve_academic", retrieve)
    monkeypatch.setattr(academic_rag, "generate_answer", generate)
    settings = AcademicSettings(None, SETTINGS.model, SETTINGS.engine_base_url)
    assert asyncio.run(academic_rag.ask_academic("Unknown word", settings=settings)) == {
        "status": "no_context", "answer": "No relevant passages were found in the selected papers.", "sources": [],
    }


@pytest.mark.parametrize("question", [None, 123, " \t ", "a" * 4097])
def test_invalid_question_fails_before_retrieval(monkeypatch, question):
    async def retrieve(*args, **kwargs):
        pytest.fail("Retrieval ran with an invalid question")

    monkeypatch.setattr(academic_rag, "retrieve_academic", retrieve)
    with pytest.raises(InvalidQuestion):
        asyncio.run(academic_rag.ask_academic(question, settings=SETTINGS))


def test_missing_key_is_detected_when_generation_is_needed():
    settings = AcademicSettings(None, SETTINGS.model, SETTINGS.engine_base_url)
    with pytest.raises(academic_rag.AnswerNotConfigured):
        asyncio.run(academic_rag.generate_answer("Question", [SOURCE], settings))


@pytest.mark.parametrize(("status", "content", "message"), [
    ("incomplete", [], "did not complete"),
    ("completed", [{"type": "refusal", "refusal": "I decline."}], "no usable text"),
    ("completed", [{"type": "output_text", "text": "  ", "annotations": []}], "no usable text"),
    ("completed", [{"type": "output_text", "text": "Invented source [S2].", "annotations": []}], "unknown source"),
])
def test_unusable_provider_output_is_rejected(monkeypatch, status, content, message):
    client, _ = install_provider(monkeypatch, lambda request: provider_response(status=status, content=content))
    with pytest.raises(academic_rag.AnswerProviderError, match=message):
        asyncio.run(academic_rag.generate_answer("Question", [SOURCE], SETTINGS))
    assert client.is_closed


@pytest.mark.parametrize(("failure", "expected_error"), [
    ("timeout", academic_rag.AnswerProviderTimeout),
    ("connection", academic_rag.AnswerProviderError),
    ("rejection", academic_rag.AnswerProviderError),
])
def test_provider_failures_close_the_client_and_hide_upstream_details(monkeypatch, failure, expected_error):
    requests = []

    def respond(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("dummy-provider-secret", request=request)
        if failure == "connection":
            raise httpx2.ConnectError("dummy-provider-secret", request=request)
        return httpx2.Response(401, json={"error": {"message": "dummy-provider-secret"}})

    client, _ = install_provider(monkeypatch, respond)
    with pytest.raises(expected_error) as error:
        asyncio.run(academic_rag.generate_answer("Question", [SOURCE], SETTINGS))
    assert len(requests) == 1 and client.is_closed
    assert "dummy-provider-secret" not in str(error.value)
