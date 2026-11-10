# Part 5 Option A contract

Stage 1 proposal for team review. The Part 5 routes below are planned.

## Data and publication

| Heap table | Fields in storage order |
| --- | --- |
| `papers` | `paper_id INTEGER`, `authors VARCHAR`, `year INTEGER`, `title VARCHAR`, `abstract VARCHAR` |
| `chunks` | `chunk_id INTEGER`, `paper_id INTEGER`, `position INTEGER`, `content VARCHAR` |

Use positive, unique manifest paper IDs and globally unique chunk IDs assigned in paper-ID and position order. Positions start at one per paper. Keep IDs within JavaScript's exact integer range and verify every paper association during preparation. Require complete, nonempty metadata and an integer year.

Count whitespace-separated words. Aim for 250 words without overlap, balance the final fragment, and keep every chunk between 200 and 500 words. Preserve original readable text. Validate complete serialized rows against the engine's `MAX_RECORD_SIZE` (4,079 bytes on this baseline). Reject incompatible rows with their source identified.

Prepare both tables in a fresh directory under `data/generated/todas/parte5`. Extend `Database.prepare_text` later to support the unindexed metadata table. Close the preparation owner, build SPIMI on `chunks.content`, seal the indexed collection, publish its registration and verify a fresh reopen. Serve the new part read-only from the existing unified server.

## Engine REST

The Stage 1 baseline exposes the same route shapes under `/parte3`. The Part 5 application will use `GET /parte5/api/text/tables`, `POST /parte5/api/text/query` and `POST /parte5/api/query`.

```json
{
  "table": "chunks",
  "column": "content",
  "query": "How does the method represent passages?",
  "model": "BM25",
  "order": "score_desc",
  "limit": 3,
  "max_rows": 3,
  "use_indexes": true
}
```

Map row arrays using the returned `columns` names. Decode and validate integer IDs before using them in SQL. Deduplicate paper IDs and fetch each through a bounded equality query, for example `SELECT paper_id, authors, year, title, abstract FROM papers WHERE paper_id = 1;`. The score in `relevancia` is a BM25 ranking value. The question goes in the text request JSON.

## Chat application

`POST /parte5/api/rag/ask` accepts `{"question":"How does the method represent passages?"}`. Trim the question, require nonempty text and cap it at 4,096 characters. Retain the existing HTTP body limit.

```json
{
  "status": "answered",
  "answer": "An answer supported by the supplied passage [S1].",
  "sources": [
    {
      "label": "S1",
      "chunk_id": 1,
      "paper_id": 1,
      "position": 1,
      "title": "Example title",
      "authors": "Example authors",
      "year": 2020,
      "content": "Example passage.",
      "score": 1.25
    }
  ]
}
```

The example values illustrate the shape. Number the retrieved context as `S1` through `S3` and return the actual context and relational metadata. A completed answer can state that the supplied evidence is insufficient. When retrieval returns zero chunks, skip generation and return `{"status":"no_context","answer":"No relevant passages were found in the selected papers.","sources":[]}`.

| Condition | Outcome |
| --- | --- |
| Invalid question | 422 with the application's validation error |
| Engine unavailable | 503 with a safe engine error |
| Provider rejection or failure | 502 with a safe application error |
| Provider timeout | 504 with a safe application error |

Keep the existing error envelope. An example provider timeout response is:

```json
{
  "error": {
    "code": "RAG_PROVIDER_TIMEOUT",
    "message": "The answer provider timed out.",
    "request_id": "example-request-id"
  }
}
```

The UI shows pending, answer, empty-context and error states. Render the answer and source passages as text.

## Integration boundaries

- Keep PDF extraction and OpenAI calls outside `engine/`. Reuse the tokenizer, SPIMI and BM25.
- Use a server-configured same-server HTTP base and finite timeouts. Use an async handler and async HTTP client so the unified server can serve its own engine requests. Finish database requests before generation and keep part sessions isolated.
- Use the official OpenAI Python SDK and Responses API. Configure `OPENAI_MODEL` as `gpt-6-luna` initially and read `OPENAI_API_KEY` only on the server. Send the question and bounded, numbered excerpts. Treat source text as evidence and instruct the model to report insufficient evidence when appropriate.
- Add Part 5 through `PartSpec` and the existing tab scope. Keep one port for the project.
