# GUIDE_05_S03 — Stage 3: Expose Academic Retrieval Through REST

This guide follows the same two-part structure as the previous stage guides:

- **Part I — Coding agent execution guide:** implementation steps, commands, validation, tests and evidence.
- **Part II — Human guide:** responsibilities of the **single person responsible for Stage 3**, including access assistance when needed, relevance review and acceptance.

**The coding agent starts after you assign the implementation task.** The agent handles coding, technical verification and evidence. You review the retrieved content and completion evidence. No task requires another developer, a team meeting or a second person's sign-off.

**Filename:** `GUIDE_05_S03.md`

**Suggested repository location:** `PART_05/GUIDE_05_S03.md`

**Planning window:** Days 4–5 of the existing ten-day plan, with one human owner assisted by a coding agent. Stage 4 remains Day 6. These are working-day estimates, not calendar deadlines.

**Inspected baseline:** `main` at **`704ee9996faa97a9fc185822e6b2ebc00de5fb95`**, checked on 2026-11-11. Stage 2 is accepted in `PART_05/STAGE_02_RESULTS.md`.

This document describes work to execute. Its checkboxes are not evidence of implementation. Writing or receiving the guide does not execute Stage 3.

## Part I — Coding agent execution guide

**Audience:** The coding agent assigned to implement Stage 3. Follow the accepted data contract, preserve existing data and resolve routine implementation decisions independently. Involve only the single stage owner for the human tasks in Part II.

### A0. Objective and completion boundary

**Objective:** Turn a question into a bounded set of persisted academic passages with their relational paper metadata, using the existing engine REST endpoints under `/parte5` on the unified server.

The intended flow is:

1. Validate the question in application code.
2. Request up to three BM25-ranked chunks from `/parte5/api/text/query`.
3. Fetch metadata for the distinct selected paper IDs through `/parte5/api/query`.
4. Assemble ordered, numbered source records for Stage 4.
5. Return an explicit empty-context result when retrieval yields no chunks.

There is no LLM answer in this stage. The installed OpenAI Developers plugin and existing API key do not require any action here. No provider request, credit purchase or credential verification is needed.

#### A0.1 What Stage 2 already completed

| Accepted input | Stage 3 use |
| --- | --- |
| `PART_05/corpus.json` | Trace the accepted ten papers; do not expand or replace the corpus routinely. |
| `papers(paper_id, authors, year, title, abstract)` | Read metadata through the SQL REST route. |
| `chunks(chunk_id, paper_id, position, content)` | Retrieve passages through the text REST route. |
| Published `chunks.content` SPIMI index | Reopen and query; do not rebuild it at server startup. |
| Sealed `chunks` Heap and ordinary `papers` Heap | Preserve storage state; expose the entire Part 5 service read-only. |
| `scripts/setup_academic.py --verify-only` | Check prepared data while the server is stopped. |
| Existing unified server and per-part sessions | Add Part 5 without introducing another server or database owner. |

Recorded Stage 2 measurements: **10 papers, 393 chunks, 147 PDF pages, 249–254 words per chunk**, maximum complete chunk record **2,395 bytes**, maximum metadata record **1,908 bytes**. The logical row fingerprint is:

```text
640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36
```

The prior independent review reproduced that fingerprint and verified the 217 selected tests. This is baseline evidence, not a substitute for testing Stage 3 changes. The generated database is not tracked in Git: a fresh checkout may need to reproduce Stage 2 into a fresh directory before serving it.

#### A0.2 Keep the stage small

Stage 2 already performed load → close owner → build SPIMI → seal → publish → reopen. Reuse that result. Stage 3 does not need a new tokenizer, ranker, storage format, index builder, SQL operator or data preparation framework.

The minimal implementation consists of:

- Registration of `parte5` and correct setup/readiness information.
- A small reusable asynchronous application retrieval helper.
- A small command-line verification caller for that helper against the running server.
- Focused tests and actual retrieval/restart evidence.

The helper and verification command avoid introducing a temporary public endpoint. Keep the planned `POST /parte5/api/rag/ask` for Stage 4, where it can return a real generated answer. Do not publish a successful placeholder answer now.

The existing frontend discovers tabs through `/api/parts`; registering Part 5 may expose its ordinary text workspace automatically. Make only compatibility corrections required by that registration. The dedicated chat panel, answer display and final interface validation remain Stage 5.

Exclude embeddings, vector search, rerankers, translation, query rewriting, persistent chat, caching, streaming, authentication, cloud deployment, a second service and a new benchmark campaign.

#### A0.3 Responsibility split

| Task | Coding agent | Single stage owner |
| --- | --- | --- |
| Baseline and data readiness | Inspect and verify; reproduce accepted data only if absent. | Provide access only when the agent cannot obtain it. |
| Unified integration | Register Part 5, preserve read-only behavior and existing parts. | No duplicate implementation assignment. |
| Retrieval | Implement REST calls, metadata association and bounded source output. | Review whether sample passages address their questions. |
| Tests and restart | Execute checks and record actual outcomes. | Review evidence; run commands only for an inaccessible environment. |
| Closure | Prepare a concise review package and Stage 4 handoff. | Accept or identify concrete corrections. |

**A0 completion criteria**

- [ ] Stage 2 publication is recognized as an existing input.
- [ ] Stage 3 ends at question → REST retrieval → source metadata.
- [ ] Exactly one human owner is responsible for this stage.

### A1. Establish the implementation baseline

#### A1.1 Inspect before editing

Run from the repository root:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

Read the current checkout versions of:

- `AGENTS.md`, `REQUIREMENTS.md`, and relevant current-state sections of `PROJECT_CONTEXT.md`.
- `PART_05/PART_05_OPTION_A.md`, `PART_05/CONTRACT_P5.md`, `PART_05/GUIDE_05_S02.md` and `PART_05/STAGE_02_RESULTS.md`.
- `api/unified.py`, `api/__main__.py`, `api/app.py`, `api/engine_service.py`, `api/schemas.py`, `api/text_search.py` and `api/serialization.py`.
- `scripts/setup_all.py`, `scripts/setup_academic.py` and existing unified/text HTTP tests.

Preserve uncommitted work. If needed, create a branch from the accepted baseline:

```bash
git switch -c feat/part5-stage3
```

If that branch already exists, inspect it before reusing it. If the checkout has advanced, reconcile relevant differences instead of forcing it back to the pinned commit. Record the actual implementation baseline. Once the owner assigns Stage 3, that instruction authorizes its necessary implementation; do not repeatedly request permission for routine steps.

#### A1.2 Reuse the environment

Use CPython 3.12 with the existing Unicode 15.0.0 text-normalization baseline. PowerShell examples throughout assume the repository root:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -c "import sys, unicodedata; print(sys.version); print(unicodedata.unidata_version)"
& $P5Python -X utf8 -m pip install -e ".[test,api,academic]"
& $P5Python -X utf8 -m pip check
New-Item -ItemType Directory -Force tmp/p5_stage3 | Out-Null
```

Reuse a working environment. The editable install matters for isolated-interpreter architecture tests. Keep `-X utf8` for the Windows encoding behavior already established in previous stages.

For Bash, set `P5_PYTHON="$PWD/.venv/bin/python"` and replace `& $P5Python` with `"$P5_PYTHON"`. Use `mkdir -p tmp/p5_stage3` in place of `New-Item`.

The baseline declares `httpx2>=2,<3` under the test extra. If the application helper uses it at runtime, declare it under the appropriate application/runtime extra as well, preferably the existing `api` extra. Do not rely on a test-only installation to make production imports work. Keep third-party HTTP code outside `engine/`. Use the client's actual installed async interface and verify it with the live acceptance run.

#### A1.3 Verify prepared data before starting the server

With every owner of this directory stopped:

```powershell
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
```

Compare counts, registration and fingerprint with Stage 2. Record the index generation so the restart check can confirm that serving did not rebuild it. A separate rebuild may legitimately have another generation UUID, but the same accepted inputs and extractor should reproduce the logical fingerprint.

If data is absent, use the existing Stage 2 reproduction instructions, pinned PDFs and `pypdf==7.0.0`. Prepare into a fresh directory; do not overwrite an existing one. If data exists but fails verification, diagnose it before proceeding. Do not silently replace it with demo text or call it ready.

Do not run `--verify-only` or a separate `Database.open` against the directory while the unified server owns it. During serving, verify through REST.

**A1 completion criteria**

- [ ] Baseline and environment recorded.
- [ ] Prepared academic data verified or a concrete access gap recorded.
- [ ] Existing work preserved and runtime HTTP dependency planned explicitly.

### A2. Register Part 5 in the unified server

#### A2.1 Add the part using existing abstractions

Extend `PARTS` in `api/unified.py` with a `PartSpec` equivalent to:

```python
PartSpec(
    "parte5", 5, "RAG académico",
    "Recuperación de papers con texto y metadata relacional",
    "text", "text_tables.json", False,
)
```

Preserve the existing sequence for Parts 1–4. Reuse `DatabaseDefinition("text")`; a new database kind is unnecessary. The directory is `<unified-root>/parte5`, normally `data/generated/todas/parte5`.

Use the existing owner, `EngineService`, mounted-app lifecycle and shutdown handling. Each part must retain its own owner and sessions. A global `--allow-writes` must still leave Part 5 read-only, including `papers`, whose Heap is not physically sealed.

Before marking a prepared Part 5 ready, confirm its academic identity using the opened owner: required tables/schemas and the `chunks.content` registration with `chunk_id`. A registry file alone also describes ordinary Part 3 data. Keep this a small Part 5 check; do not re-extract PDFs, hash all rows or build a generic validation framework during startup. Close any owner rejected by this check, and report an actionable unavailable/missing state through existing conventions.

#### A2.2 Account for shared `text` kind

`create_unified_app` currently chooses presets through `PRESETS_BY_KIND[part.spec.kind]`. Part 5 shares the `text` kind, but Part 3's presets query `documentos`, `articulos` and `productos`, which are absent from the academic database.

Apply a small part-specific override: **use an empty preset tuple for Part 5** at this stage. Leave Part 3's presets unchanged. New academic presets are optional and unnecessary for completion.

Also inspect the existing frontend's handling of `origin="prepared"`, introduced by Stage 2 for companion tables. At the inspected baseline, `TableOrigin` and `ORIGIN_LABELS` list only `demo`, `csv` and `empty`. If the ordinary Part 5 workspace displays `papers`, add the small compatible type/label handling so it does not render an undefined origin badge. This does not require a chat interface or workspace redesign.

#### A2.3 Make missing-data instructions accurate

`OpenedPart.describe()` currently gives every missing part the same `setup_all.py` instruction. `scripts/setup_all.py` also iterates over `PARTS`, but `_prepare_part` only handles Parts 1–4. Adding Part 5 to the tuple without addressing these assumptions creates misleading setup behavior.

Use the existing academic preparation command as the authoritative operation:

```powershell
& $P5Python -X utf8 scripts/setup_academic.py --manifest PART_05/corpus.json --pdf-dir data/generated/p5_inputs --data-dir data/generated/todas/parte5
```

For Part 5, show that command with the actual configured root. Explicitly handle Part 5 in the general setup path: preserve an existing directory; for missing data, either delegate to the academic preparation function when its documented inputs are available or report that the explicit command and local PDFs are required. Do not fall through to `Unknown part parte5`, claim creation after a skip, automatically download a corpus, or overwrite data.

A missing Part 5 must not prevent prepared Parts 1–4 from being served. Preserve each part's existing setup behavior. Test the chosen setup behavior and document it; no new general configuration system is needed.

**A2 completion criteria**

- [ ] `/api/parts` lists Part 5 after Part 4 with the correct readiness and base path.
- [ ] Ready Part 5 opens the academic data and stays read-only even with `--allow-writes`.
- [ ] Missing or wrong data produces an actionable message without leaking an owner.
- [ ] Part 3 presets and behavior are unchanged; Part 5 has no invalid demo presets.
- [ ] Setup and shutdown remain coherent with the added part.

### A3. Verify the scoped engine REST endpoints

#### A3.1 Launch on the existing port

Start the server in one terminal after offline verification has finished:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -m api --all --data-dir data/generated/todas --host 127.0.0.1 --port 8000
```

Use the existing one-process, one-worker, no-reload launcher. Do not start another server on the same owned directories. If an existing server already owns them, coordinate its normal shutdown before restarting with new code.

In a second terminal:

```powershell
$P5Base = "http://127.0.0.1:8000/parte5"
Invoke-RestMethod "http://127.0.0.1:8000/api/parts"
Invoke-RestMethod "$P5Base/api/health"
Invoke-RestMethod "$P5Base/api/text/tables"
```

Require `parte5` to be ready, its mode to be read-only, and its published text collection to be `chunks.content`, identified by `chunk_id`. For the accepted corpus, the document count is 393. `papers` must not appear as a published text collection.

#### A3.2 Execute a bounded text query

```powershell
$textPayload = @{
    table = "chunks"
    column = "content"
    query = "How does HNSW use a hierarchy of proximity graphs?"
    model = "BM25"
    order = "score_desc"
    limit = 3
    max_rows = 3
    use_indexes = $true
} | ConvertTo-Json
$hits = Invoke-RestMethod -Method Post -Uri "$P5Base/api/text/query" -ContentType "application/json" -Body $textPayload
$hits | ConvertTo-Json -Depth 12
```

Inspect the real response. It contains `columns` descriptors and `rows` arrays, not ready-made source objects. Locate `chunk_id`, `paper_id`, `position`, `content` and `relevancia` by column name. Verify that returned rows are complete, bounded and score-ordered, and record the reported index access path. Do not claim index use merely because the request set `use_indexes=true`.

#### A3.3 Read relational metadata

The following is a standalone smoke query for known paper 1. The application must instead use the actual paper IDs returned by text retrieval:

```powershell
$metadataPayload = @{
    sql = "SELECT paper_id, authors, year, title, abstract FROM papers WHERE paper_id = 1;"
    max_rows = 2
    use_indexes = $true
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$P5Base/api/query" -ContentType "application/json" -Body $metadataPayload
```

The two-row bound lets the helper detect an unexpected duplicate rather than accepting an arbitrary first match. Exactly one row should resolve each selected paper ID. Metadata retrieval may legitimately scan the ten-row ordinary Heap; do not add an index merely to avoid that small scan.

**A3 completion criteria**

- [ ] Both text and relational routes work under `/parte5`.
- [ ] Responses come from the accepted academic tables.
- [ ] Actual index use, result bounds and correct column mapping are observed.

### A4. Implement the reusable application retrieval flow

#### A4.1 Keep the integration boundary explicit

Suggested new files are `api/academic_retrieval.py` and `scripts/check_academic_retrieval.py`. Reuse equivalent existing modules if the implementation branch already has them.

The application helper receives a configured Part 5 engine base URL and an asynchronous HTTP client, then returns validated sources. It must not call `Database.open`, `EngineService.text_query`, the SQL engine or index internals directly. The verification script calls this same helper; do not implement a second retrieval path in the script.

Use a server-controlled base such as `http://127.0.0.1:8000/parte5`. The question/request payload must not select the host or route. For this stage's local command, a `--base-url` argument is sufficient. Stage 4 can supply that same base through server configuration, including an explicitly changed port. Do not derive an outbound destination from an untrusted HTTP Host header.

Use finite HTTP timeouts, for example a documented ten-second per-request timeout, and close the client reliably. Keep the code asynchronous so the later mounted async handler can await same-server requests without blocking the event loop. No retry framework or connection service is needed.

#### A4.2 Implement this sequence

1. **Validate the question.** Require a string, trim it, reject empty text and cap it at 4,096 characters, matching the accepted contract. Perform validation before any HTTP request.
2. **Retrieve chunks.** POST the A3.2 request with the actual question, fixed academic table/column, BM25, descending scores, `limit=3` and `max_rows=3`.
3. **Validate the engine response.** Require a successful query response, expected columns, consistent row lengths and complete results for the requested top three. Reject malformed/error responses rather than treating them as no matches. The completeness check concerns the requested top three, not the entire matching corpus.
4. **Decode identifiers.** Map fields by column name. IDs must be positive exact integers within the accepted JavaScript-safe range; reject booleans, fractions and out-of-range values. The engine encodes int64 values as numbers or decimal strings, so handle that representation deliberately without float conversion. Stage 2's valid IDs normally arrive as JSON numbers.
5. **Preserve ranking.** Keep the engine's hit order, validate finite numeric scores and do not apply another ranking algorithm. Duplicate chunk IDs are an invalid response. Multiple different chunks from the same paper are allowed.
6. **Handle zero hits immediately.** Return `{"status":"no_context","sources":[]}` without metadata queries. This is a successful empty retrieval, not an engine failure and not a generated answer.
7. **Fetch metadata once per distinct paper.** Deduplicate paper IDs in first-occurrence order. Run the fixed A3.3 SELECT for each validated integer ID, with a bounded result. Interpolate only the validated integer into the fixed SQL template; never interpolate question text, table names or arbitrary response strings.
8. **Validate associations.** Require exactly one metadata row with the requested `paper_id`, nonempty title/authors/abstract and an integer year. Missing or duplicated metadata is an integrity failure; do not silently discard that passage or invent metadata.
9. **Assemble sources.** Attach the correct metadata to each original ranked chunk, then assign labels `S1`, `S2`, `S3` in that order. Return the actual stored text and scores.

With three results, this uses one text request and at most three metadata requests. Sequential metadata calls are sufficient. Do not add asynchronous fan-out, joins, caching or a bulk metadata API just for this bound.

An internal source record should preserve `label`, `chunk_id`, `paper_id`, `position`, `title`, `authors`, `year`, `abstract`, `content` and `score`. Fetch and validate the complete abstract now; Stage 4 can keep it internal when projecting the already-agreed public source fields in `CONTRACT_P5.md`.

For nonempty retrieval, a small internal result such as `{"status":"context","sources":[...]}` is sufficient. Document this as an **internal Stage 3 return shape**, not a replacement for the future public `rag/ask` contract. Do not put placeholder text in an `answer` field.

#### A4.3 Handle failures without claiming success

| Condition | Required Stage 3 behavior |
| --- | --- |
| Invalid question | Reject before HTTP; verification command exits nonzero. |
| Empty valid search result | Return `no_context` and an empty source list; no SQL lookup. |
| Connection failure, timeout or engine error | Return/raise an explicit retrieval failure; command exits nonzero. |
| Malformed response, invalid ID or missing metadata | Report a response/integrity failure; no partial successful context. |
| Successful retrieval | Return actual ordered sources; no LLM invocation. |

Use a small error representation that Stage 4 can map to the existing API envelope. Keep engine unavailability distinguishable from invalid questions and integrity errors. Stage 4 owns the public mappings specified in the contract, including 422 for invalid questions and 503 for engine unavailability; provider errors are not implemented here.

The HTTP application should not copy browser session tokens from another part into its internal requests. Use the existing supported read path, without an explicit cross-request transaction, and release request resources before returning context. Do not hold database locks while waiting for later generation.

#### A4.4 Provide an executable verification caller

Implement a thin CLI with this proposed interface:

```powershell
& $P5Python -X utf8 scripts/check_academic_retrieval.py --base-url http://127.0.0.1:8000/parte5 --question "How does HNSW use a hierarchy of proximity graphs?"
```

It should print readable JSON containing the internal status and actual assembled sources. Exit zero for `context` and `no_context`; exit nonzero for input, network or integrity failures with a clear diagnostic. This is a developer verification tool, not the final user interface.

**A4 completion criteria**

- [ ] Application retrieval consumes REST for both chunks and metadata.
- [ ] One reusable helper serves the CLI and future Stage 4 integration.
- [ ] Up to three sources retain ranking, correct associations and numbered labels.
- [ ] Bounds, identifiers, response validation and explicit failure handling are implemented.
- [ ] Empty retrieval does not fetch metadata or invoke a model.

### A5. Check real retrieval, restart and isolation

#### A5.1 Use a small content acceptance set

Start with four questions based on the accepted corpus. These are candidate questions, not promised rankings or predetermined passing results:

| Candidate question | Passage topic to inspect |
| --- | --- |
| How does HNSW use a hierarchy of proximity graphs? | Graph layers and navigation in the HNSW paper. |
| How does Dense Passage Retrieval encode questions and passages? | DPR's dual encoders and retrieval scoring. |
| How does retrieval-augmented generation combine a retriever with a generator? | RAG's retrieved documents and generation method. |
| How does ColBERTv2 reduce the storage cost of late interaction? | ColBERTv2's representation/compression approach. |

Use English questions initially because the accepted papers are in English. Translation or multilingual search is outside this stage. For each question, run the real helper against the live server, save the actual source IDs/scores and inspect the retrieved text. At least one top-three passage should contain information addressing the question; a title or bibliography mention alone is insufficient.

If a question fails, inspect the actual query, extraction and returned passages. Correct mapping/routing errors first. If a clearer in-domain question is needed, retain the failed attempt and explain the revision. Do not add query rewriting or silently select only favorable outputs. Unresolved failure for the agreed acceptance questions remains a finding for the owner.

Record a compact table: question, ordered chunk IDs, paper IDs, scores, supporting excerpt, expected-topic assessment and limitation. Exact chunk IDs should be measured, not hardcoded from this guide.

#### A5.2 Exercise empty results separately from relevance

Use a nonempty synthetic token and confirm through actual retrieval that it has no indexed matches. If it unexpectedly matches, choose another and record the final token. Verify `no_context` and zero metadata requests.

Also try one ordinary question outside the corpus topic and inspect what BM25 returns. **An unsupported question is not guaranteed to return zero rows:** shared words can retrieve irrelevant passages. A BM25 score is not a confidence probability. Record that limitation without inventing an arbitrary score threshold. Stage 4 must still handle insufficient evidence when passages exist.

#### A5.3 Prove restart without re-ingestion

1. Save one successful question's ordered sources, content, metadata and scores.
2. Stop the unified server cleanly.
3. Run offline `--verify-only` and compare the logical fingerprint and index generation with A1.
4. If practical, temporarily move the input PDF folder to a sibling path while preserving every file; restore it afterward. The goal is to demonstrate that serving does not depend on input PDFs, not to delete them.
5. Restart with the same unified root, without running a setup or publication command.
6. Run the same question through the same REST helper again.
7. Compare ordered IDs, text, metadata and scores, excluding timing/request IDs. Use appropriate numeric tolerance if comparing floating-point scores across environments.
8. Stop the server before any final offline verification, and restore any temporarily moved inputs.

The fingerprint and generation of this same prepared database must not change. Do not compare whole directory hashes: runtime control files may legitimately change.

#### A5.4 Check Part 5 remains isolated and read-only

Use disposable test data to verify write refusal for both `papers` and `chunks`, including a server opened with `--allow-writes`. Never use destructive write probes against accepted data merely to prove refusal.

Verify that Part 3 still serves its own collections and presets, Part 5 serves academic tables, and session tokens do not cross parts. Existing prepared Parts 1–4 should retain their behavior. Do not rebuild the 100k multimedia corpus or rerun unrelated benchmark campaigns for this integration.

**A5 completion criteria**

- [ ] Real questions return useful passages with verified metadata.
- [ ] Empty matches and unsupported-topic behavior are distinguished honestly.
- [ ] A separate server process reproduces retrieval without rebuilding data.
- [ ] Part 5 is read-only and isolated; existing parts remain functional.

### A6. Run focused automated checks

#### A6.1 Add tests for the actual boundaries

Suggested new test files: `tests/part5/test_retrieval.py` for the helper and `tests/part5/test_http.py` for mounted integration. Equivalent organization is acceptable.

| Area | Necessary coverage |
| --- | --- |
| Registration | Fifth part ready/missing; wrong academic directory rejected; owner released on failure. |
| Unified behavior | Existing parts/presets preserved; Part 5 has correct setup help and no Part 3 presets. |
| Read-only service | Both tables reject writes even with global writes enabled, using disposable data. |
| Real HTTP integration | Prepared academic tables are searchable under `/parte5`; SQL metadata resolves selected IDs. |
| Mapping | Reordered column descriptors still produce correct fields; malformed rows fail clearly. |
| Association/order | Two chunks from one paper cause one metadata lookup and retain hit order; labels follow that order. |
| Validation | Empty/oversized question, invalid identifiers, missing/duplicate metadata and failed responses. |
| No matches | Empty sources and no metadata call. |
| Resource/error behavior | Timeout/unavailable engine is not reported as no context; HTTP client closes. |
| Persistence | Close/reopen preserves academic retrieval without republishing. |

Use small prepared fixtures for automated tests. Controlled HTTP responses are appropriate for malformed-data and timeout cases. Include an integration check with real Heap/SPIMI data and actual routes, plus the live real-corpus run in A5. Mocked responses alone do not establish the application's REST boundary or same-server compatibility.

Update existing tests that assert exactly four parts, notably unified health/mode expectations. Retain their existing assertions for Parts 1–4; do not weaken them merely to make the new part pass.

#### A6.2 Run affected checks

After implementing the proposed tests, use:

```powershell
& $P5Python -X utf8 -m pytest -q -W error tests/part5 tests/api/test_unified.py tests/api/test_launcher.py tests/api/test_http.py tests/api/test_sessions.py tests/api/test_database.py tests/api/test_gui_tables.py tests/text/test_text_http_integration.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_4b_5_real_published_sql.py tests/text/test_registry_4b.py tests/text/test_sealing.py tests/test_architecture.py
& $P5Python -X utf8 -m pip check
git diff --check
```

Adjust only for actual file organization or newly affected behavior, and record the exact command. Use a fresh `--basetemp` and `-p no:cacheprovider` if a Windows temporary-directory/cache issue requires it; do not disable warnings or skip failing behavior to obtain a pass.

If frontend type/label code changes, run the existing frontend checks:

```powershell
Push-Location frontend
npm ci
npm run typecheck
npm test
npm run build
Pop-Location
```

Reuse installed dependencies when appropriate. Briefly inspect the automatically discovered Part 5 workspace if it is exposed, including the metadata-table origin label and unaffected Part 3 tab. A new chat UI is not an acceptance requirement here.

Diagnose environmental failures separately from implementation defects. Do not claim tests passed if they were skipped, blocked or never run. Once affected checks pass, broaden testing only for newly discovered risks or additional changes.

**A6 completion criteria**

- [ ] New behavior and affected regressions are covered by meaningful checks.
- [ ] Real HTTP/data evidence complements controlled-response tests.
- [ ] Actual commands, pass/fail/skip counts and environmental limitations are recorded.

### A7. Record evidence and hand off

#### A7.1 Create the results document

Write `PART_05/STAGE_03_RESULTS.md` with actual values. Use this outline:

```markdown
# Part 5 — Stage 3 results

- Overall status: PENDING_HUMAN / PASS / FAIL / BLOCKED
- Technical status:
- Human owner and review date:
- Baseline and reviewed implementation commit:
- Runtime and dependency versions:
- Unified root and Part 5 directory:
- Engine REST base:
- Logical fingerprint and index generation before/after:

## Implemented changes
## Registration, readiness and read-only checks
## REST retrieval and source assembly
## Real-question results and supporting excerpts
## Empty-result and unsupported-topic observations
## Restart and existing-part checks
## Automated checks and reproduction commands
## Human review and unresolved findings
## Stage 4 handoff
```

Provide enough recorded source text and IDs for the owner to review the relevance judgments without depending on temporary files available only on the agent's machine. Link tracked evidence relatively and use stable source links for original papers when useful. Keep generated databases, PDFs and bulky raw logs outside Git.

A technical PASS with outstanding required human review is `PENDING_HUMAN`, not overall PASS. Do not invent initials, dates or approvals. Record H2 as `NOT_NEEDED` when no access assistance was necessary.

#### A7.2 Update only durable instructions affected by this stage

- README: academic preparation reference, unified launch and the retrieval verification command.
- `PROJECT_CONTEXT.md`: Stage 3 implementation state and remaining generation/interface work.
- `PART_05/CONTRACT_P5.md`: clarify implemented routes and document the internal helper boundary where needed; preserve the public Stage 4 answer contract.
- Current-state wording in `AGENTS.md`, if needed, should reflect the actual authorized/completed stage rather than authorize later stages implicitly.

Check the diff and keep changes scoped. This guide does not require a PR comment, team notification, push, merge or deployment. Follow the owner's existing Git instructions for commits and publishing.

#### A7.3 Agent exit checklist

- [ ] Part 5 is correctly mounted with actionable readiness/setup behavior.
- [ ] Academic data and published index are reused, not rebuilt by serving.
- [ ] The helper uses REST for ranked text and relational metadata.
- [ ] Ordered, bounded sources and explicit empty/error behavior are implemented.
- [ ] Real relevance and restart checks are recorded.
- [ ] Read-only behavior and existing parts are preserved.
- [ ] Affected tests pass and actual evidence is available to the single owner.
- [ ] Remaining human actions are specific and no tasks are assigned to teammates.

The Stage 4 handoff must identify the helper entry point, client/base configuration, internal result shape, error behavior, actual sample questions, verified data location and known relevance limitations. Stage 4 connects these sources to the existing LLM integration and implements the final `rag/ask` endpoint.

Stop at this boundary. Do not begin model calls or the chat interface merely because retrieval is ready.

## Part II — Human guide

**Audience:** The one person responsible for Stage 3. All human tasks below belong to you. The coding agent performs implementation and technical verification; no other developer is required.

### H1. Start the stage and keep the scope clear

**Required once.** Assign the agent the implementation task. You can use:

> Implement Stage 3 following `PART_05/GUIDE_05_S03.md`. I am the only human responsible for this stage. Reuse the accepted Stage 2 corpus and published index. Register Part 5 in the unified server, implement reusable REST retrieval with relational metadata, run the affected tests and real-corpus restart checks, and prepare evidence for my review. Do not assign tasks to other developers. Do not implement LLM generation or the final chat UI in this stage. Continue independent work if a specific access issue blocks one step.

You do not need to write the retrieval code, download the papers again or obtain another API key. If your accepted data is stored somewhere other than the recorded path, tell the agent that path.

**Done when:** The agent has the execution task and any actual local constraints. Routine implementation does not require repeated authorization.

### H2. Resolve access gaps only when necessary

**Conditional.** Help only when the agent identifies a concrete gap, such as inaccessible local data, an unavailable Python installation or inability to start a server in the intended environment.

Provide the missing access or run the exact command the agent prepares. Share relevant output and errors. The agent remains responsible for diagnosis and interpretation. No OpenAI API key is needed for these checks.

If the accepted database is absent in the agent's checkout, it may reproduce it using the existing Stage 2 procedure and public pinned inputs. You do not have to perform that work simply because the original preparation happened on your machine.

**Done when:** The gap is resolved or specifically documented as blocked. Otherwise H2 is `NOT_NEEDED`.

### H3. Review the retrieved passages and metadata

**Required before closure.** This is your main content responsibility. Use the compact question/source table supplied by the agent.

For each of the four agreed questions:

1. Read the question and the returned passages in rank order.
2. Confirm that at least one top-three passage contains information useful for answering it, rather than only naming the topic or citing another paper.
3. Check that title, authors and year identify the paper from which the passage came.
4. Inspect the returned `paper_id`, `chunk_id` and source label when reporting a mismatch.
5. Record a short PASS or a concrete correction. If needed, consult the linked original PDF section.

Also review the zero-match example and the unsupported-topic observation. Understand that keyword overlap can return irrelevant passages for an unsupported question. A high score does not establish that the corpus can answer the question.

You are not reviewing generated answers yet: none should exist in Stage 3. You do not need to re-audit every PDF or repeat automated checks over all 393 chunks.

**Done when:** Your relevance and metadata assessment is recorded with your initials and date, and required corrections are resolved or explicit.

### H4. Review technical evidence; execute locally only if needed

**Evidence review is required. Manual execution is conditional.** Confirm that the report demonstrates:

- `/parte5` is served by the existing unified application and remains read-only.
- The application retrieves both text and metadata through REST.
- The helper uses the actual ranked chunks and attaches the correct paper fields.
- A restarted server reproduces retrieval without rebuilding the index.
- Part 3 and other existing parts retain their behavior.
- Automated checks passed, with any limitations stated explicitly.

If the agent already ran these checks in the stated environment, do not repeat them by default. If your workstation is the inaccessible environment that must be checked, use the agent's exact preparation and launch instructions. With the server running, a typical second-terminal check is:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 scripts/check_academic_retrieval.py --base-url http://127.0.0.1:8000/parte5 --question "How does Dense Passage Retrieval encode questions and passages?"
```

That command is available only after the agent implements it. Use the actual port and paths from the result document. Stop the server before running any offline database verification.

**Done when:** The evidence establishes the behavior in its stated environment, or you provide the missing local result for the agent to record.

### H5. Resolve findings and understand the handoff

**Required, but brief.** Review the agent's summary and request corrections for actual failures or mismatches with the accepted scope.

You should be able to explain:

- Where Part 5's prepared database lives and how `/parte5` differs from `/parte3`.
- Why text retrieval returns chunks and the SQL route supplies paper metadata.
- Why multiple passages can legitimately reference the same paper.
- Why a BM25 score expresses ranking rather than factual confidence.
- Why Stage 3 returns sources and Stage 4 will use them to generate an answer.
- Why the prepared data is reopened after restart instead of re-ingested.

The agent fixes implementation defects and reruns affected checks. You review corrected relevance samples where necessary. There is no team meeting, second reviewer or teammate reproduction requirement for this stage.

**Done when:** Blocking findings are resolved and the Stage 4 handoff is understood.

### H6. Close Stage 3

Use `PART_05/STAGE_03_RESULTS.md` and confirm:

- [ ] Part 5 is registered on the existing unified server.
- [ ] The accepted academic data and published index are reused.
- [ ] Text retrieval and metadata lookup run through the engine REST API.
- [ ] The source list is bounded, correctly associated and ordered.
- [ ] Empty results and failures are distinguished.
- [ ] The agreed real questions retrieve useful supporting passages.
- [ ] Restart preserves retrieval without rebuilding data.
- [ ] Read-only behavior and separation from other parts are verified.
- [ ] Affected tests pass and your content review is recorded.
- [ ] Remaining limitations and the Stage 4 handoff are explicit.

If these items pass, give a concise acceptance for the agent to record. If a required item remains unresolved, keep the overall status `PENDING_HUMAN`, `FAIL` or `BLOCKED`, with the next action specified. Only your acceptance is required.

### Reference sources

Repository links below are pinned to the inspected baseline. At implementation time, read the current checkout and reconcile later changes.

- [Assignment: Proyecto_Final.pdf](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/Proyecto_Final.pdf), §2.5 and Annex A, Option A. Stage 3 addresses Part 3 text indexing/retrieval and relational metadata through the engine API; it does not complete the entire RAG application.
- [Previous guide](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/PART_05/GUIDE_05_S02.md), [Stage 2 results](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/PART_05/STAGE_02_RESULTS.md), [ten-day plan](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/PART_05/PART_05_OPTION_A.md) and [accepted contract](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/PART_05/CONTRACT_P5.md).
- [Unified application](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/unified.py), [launcher](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/__main__.py) and [general setup](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/scripts/setup_all.py).
- [HTTP routes](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/app.py), [text response implementation](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/text_search.py), [request schemas](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/schemas.py) and [value serialization](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/api/serialization.py).
- [Academic setup/verification](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/scripts/setup_academic.py), [unified tests](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/tests/api/test_unified.py) and [real text HTTP acceptance tests](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/704ee9996faa97a9fc185822e6b2ebc00de5fb95/tests/text/test_4b_5_real_http_acceptance.py).

The top-three bound, example questions, timeout and verification CLI are implementation choices supporting the accepted plan. They are not additional requirements or numerical grading rules invented for the assignment.
