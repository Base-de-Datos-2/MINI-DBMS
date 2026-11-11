# Part 5 — Stage 3 results

- Overall status: **PASS**, closed on 2026-11-10
- Technical status: **PASS**
- Human owner: JPCP. H3–H6 approved on 2026-11-10.
- Baseline: `704ee9996faa97a9fc185822e6b2ebc00de5fb95`, accepted Stage 2
- Reviewed implementation: `4ec98c5a000998f8005de67b487b6dd3eb4972ce` on `feat/part5-stage3`
- Runtime: Windows, CPython 3.12.4, Unicode 15.0.0, httpx2 2.13.0, FastAPI 0.141.1, Uvicorn 0.53.0
- Unified root: `data/generated/todas`. Academic database: `data/generated/todas/parte5`.
- Engine REST base: `http://127.0.0.1:8000/parte5`
- Logical row SHA-256 before, between and after the restart:
  `640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36`
- Index generation before, between and after the restart:
  `d74a9afd111c48cab531f4a3fcb43138`

## Registration and isolation

| Check | Observed result |
| --- | --- |
| Unified registry | `/api/parts` listed Part 5 fifth, ready at `/parte5` in read-only mode. |
| Academic collections | Scoped health reported `papers` and `chunks`. The text table endpoint exposed only `chunks.content` with `chunk_id` and 393 indexed chunks. |
| Missing or wrong data | Disposable tests covered absent data, ordinary Part 3 data, a wrong schema, a wrong index ID column and a malformed registry. Part 5 reported its status and the setup command for the selected root. The rejected directories could be reopened after the test. |
| General setup | `setup_all.py` preserves an existing Part 5 directory. A missing one gets the explicit academic preparation command with status `manual`. Other selected demos continue preparing. |
| Write policy | With global writes enabled in a disposable unified server, inserts into both academic tables were refused with `STATEMENT_DISABLED`. |
| Sessions and presets | Disposable tests rejected Part 3 and Part 5 session tokens in each other's routes. Part 3 kept its own presets and collections. Part 5 returned an empty preset list. |

## REST retrieval and source assembly

The live BM25 response reported **`TextIndexScan`** and **`TopKHeap`**,
with three complete rows in descending score order. The SQL smoke query
returned the single complete metadata row for paper 1. The application helper
read IDs from the ranked text response and used one bounded SQL request per
distinct paper ID. The acceptance run compared the returned metadata with
the accepted manifest. The HNSW request used one text request and
one SQL request for three hits from the same paper. The revised DPR request
used one text request and three SQL requests for three different papers.

The helper reads descriptors by name and position, validates complete
responses, and preserves BM25 order when assigning `S1` through `S3`.
It validates the question before HTTP and returns the stored text and complete
paper metadata. The verification CLI calls the same async helper.

## Review package for H3

Read each question's sources in rank order. Scores below are rounded to six
decimal places. The verification command below prints full passages, abstracts
and scores. PDF page numbers are one-based. The paper table links to the
pinned versions, and the accepted [corpus manifest](corpus.json) contains each
paper's full metadata.

| Paper ID | Metadata returned by REST |
| --- | --- |
| 1 | *Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs* · Yu. A. Malkov, D. A. Yashunin · 2018. [PDF](https://arxiv.org/pdf/1603.09320v4) |
| 3 | *Dense Passage Retrieval for Open-Domain Question Answering* · Vladimir Karpukhin, Barlas Oğuz, Sewon Min, Patrick Lewis, Ledell Wu, Sergey Edunov, Danqi Chen, Wen-tau Yih · 2020. [PDF](https://arxiv.org/pdf/2004.04906v2) |
| 6 | *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* · Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih, Tim Rocktäschel, Sebastian Riedel, Douwe Kiela · 2020. [PDF](https://arxiv.org/pdf/2005.11401v1) |
| 7 | *ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction* · Keshav Santhanam, Omar Khattab, Jon Saad-Falcon, Christopher Potts, Matei Zaharia · 2021. [PDF](https://arxiv.org/pdf/2112.01488v1) |
| 10 | *RocketQA: An Optimized Training Approach to Dense Passage Retrieval for Open-Domain Question Answering* · Yingqi Qu, Yuchen Ding, Jing Liu, Kai Liu, Ruiyang Ren, Xin Zhao, Daxiang Dong, Hua Wu, Haifeng Wang · 2020. [PDF](https://arxiv.org/pdf/2010.08191v1) |

### How does HNSW use a hierarchy of proximity graphs?

| Rank | Chunk · paper | BM25 | Excerpt from the stored chunk |
| --- | --- | ---: | --- |
| S1 | 1 · 1 | 17.626160 | “Hierarchical NSW incrementally builds a multi-layer structure consisting from hierarchical set of proximity graphs (layers) for nested subsets of the stored elements.” [PDF p. 1](https://arxiv.org/pdf/1603.09320v4#page=1) |
| S2 | 3 · 1 | 12.267421 | “explicit selection of the graph’s enter-point node, separation of links by different scales” [PDF p. 1](https://arxiv.org/pdf/1603.09320v4#page=1) |
| S3 | 5 · 1 | 10.361060 | “with logarithmic or polylogarithmic scaling of the number of hops during the greedy traversal” [PDF p. 2](https://arxiv.org/pdf/1603.09320v4#page=2) |

S1 describes graph layers over nested subsets and says the search starts
at the upper layer. S3 discusses the earlier NSW structure.

### In DPR, how do two independent BERT networks encode passages and questions?

| Rank | Chunk · paper | BM25 | Excerpt from the stored chunk |
| --- | --- | ---: | --- |
| S1 | 371 · 10 | 17.331453 | “At query time, another encoder Eq(·) is applied to embed the input question” [PDF p. 4](https://arxiv.org/pdf/2010.08191v1#page=4) |
| S2 | 98 · 3 | 14.554359 | “we use two independent BERT (Devlin et al., 2019) networks (base, un- cased) and take the representation at the [CLS] token” [PDF p. 3](https://arxiv.org/pdf/2004.04906v2#page=3) |
| S3 | 261 · 7 | 12.921297 | “invoking the BERT encoder and compress- ing the output embeddings” [PDF pp. 5–6](https://arxiv.org/pdf/2112.01488v1#page=5) |

The initial wording, “How does Dense Passage Retrieval encode questions and
passages?”, returned RocketQA chunks 371, 363 and 364, all from paper 10,
with BM25 scores 13.514734, 13.483412 and 12.985591. S1 described the
dual-encoder architecture, but the original DPR paper was absent. The revised
question names the specific architecture. Its S2 explains the DPR encoders and
the `[CLS]` representation. The highest-scoring hit still comes from RocketQA.

### How does retrieval-augmented generation combine a retriever with a generator?

| Rank | Chunk · paper | BM25 | Excerpt from the stored chunk |
| --- | --- | ---: | --- |
| S1 | 213 · 6 | 20.722557 | “Figure 1: An overview of retrieval-augmented generation (RAG).” [PDF pp. 1–2](https://arxiv.org/pdf/2005.11401v1#page=1) |
| S2 | 214 · 6 | 20.233797 | “then conditions on both these latent documents and the input to generate the output.” [PDF p. 2](https://arxiv.org/pdf/2005.11401v1#page=2) |
| S3 | 217 · 6 | 17.387655 | “To combine the inputx with the retrieved contentz when generating from BART, we simply concatenate them.” [PDF pp. 3–4](https://arxiv.org/pdf/2005.11401v1#page=3) |

S2 explains how the generator uses the retrieved documents and the input.
S3 identifies BART and describes how it receives the two inputs. The extracted
labels in S1 reflect the figure layout.

### How does ColBERTv2 reduce the storage cost of late interaction?

| Rank | Chunk · paper | BM25 | Excerpt from the stored chunk |
| --- | --- | ---: | --- |
| S1 | 251 · 7 | 19.035788 | “uses a residual compression mechanism (§4.3) to reduce the space footprint of late interaction by 5–8×” [PDF pp. 1–2](https://arxiv.org/pdf/2112.01488v1#page=1) |
| S2 | 250 · 7 | 16.736885 | “they must store billions of small vectors for a corpus with billions of to- kens” [PDF p. 1](https://arxiv.org/pdf/2112.01488v1#page=1) |
| S3 | 249 · 7 | 15.998970 | “a retriever that couples an aggressive residual compres- sion mechanism with a denoised supervision strategy” [PDF p. 1](https://arxiv.org/pdf/2112.01488v1#page=1) |

S1 and S3 identify residual compression. S2 explains why storing one
embedding per token increases storage.

## Empty result and unsupported topic

- `zqxacademicnonmatch2026` returned `{"status":"no_context","sources":[]}`.
  The HTTP trace recorded one text request and zero SQL metadata requests.
- “How do I change the oil in a 2015 Toyota Corolla?” returned chunks 143
  (Faiss, paper 4, 10.927899), 362 (ANCE, paper 9, 7.576596) and 325
  (BEIR, paper 8, 7.373409). The passages discussed quantizers or retrieval
  examples and provided no oil-change instructions. BM25 scores express
  lexical rank. Stage 4 must account for weak or irrelevant evidence even
  when retrieval returns passages.

## Restart and frontend checks

Two sequential unified server processes served the accepted corpus on port
8000. Both shut down gracefully. The HNSW CLI response was identical across
the two processes, including ordered IDs, labels, stored text, metadata and
scores. The second server started with the local PDF directory temporarily
moved out of its usual location. The PDFs were restored after shutdown.
Offline verification before serving, between server runs and after shutdown
returned the same fingerprint, index generation and 10-paper/393-chunk
counts. The startup path reused the published index.

The real-corpus root held only the prepared Part 5 database. The existing
unified fixtures exercised Parts 1–3. A disposable Part 4 fixture mounted
image and audio collections, exposed its existing presets and returned
results through `VectorIndexScan` with Part 5 absent. A browser check in
Edge 157.0.4341.42 used disposable Part 3 and Part 5 data and verified
both text workspace titles, the `papers` origin badge, disabled table
creation and the correct collections in each tab.

## Automated checks and reproduction

The Python suite reported **280 passed, 2 skipped in 96.38 seconds**.
The two skips are the existing POSIX-only launcher tests for socket reuse
and SIGINT. On Windows, the real server runs exercised graceful shutdown
via Ctrl+Break. `pip check` reported no broken requirements. The frontend
typecheck and production build passed, and Vitest reported **50 passed**.

From the repository root, with the unified server stopped:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -m pip install -e ".[test,api,academic]"
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
& $P5Python -X utf8 -m api --all --data-dir data/generated/todas --host 127.0.0.1 --port 8000
```

From another PowerShell terminal at the repository root, use the exact
questions above to display the full returned sources:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 scripts/check_academic_retrieval.py --base-url http://127.0.0.1:8000/parte5 --question "How does HNSW use a hierarchy of proximity graphs?"
```

For a manual restart check, stop the server, rerun `--verify-only`, and
restart it with the same root. Repeat the HNSW query and compare the ordered
sources and scores. The setup commands for reproducing missing data are in
the [Stage 2 results](STAGE_02_RESULTS.md).

```powershell
New-Item -ItemType Directory -Force tmp/p5_stage3 | Out-Null
& $P5Python -X utf8 -m pytest -q -rs -W error -p no:cacheprovider --basetemp tmp/p5_stage3/pytest_02 tests/part5 tests/api/test_unified.py tests/api/test_launcher.py tests/api/test_http.py tests/api/test_sessions.py tests/api/test_database.py tests/api/test_gui_tables.py tests/text/test_text_http_integration.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_4b_5_real_published_sql.py tests/text/test_registry_4b.py tests/text/test_sealing.py tests/test_architecture.py
& $P5Python -X utf8 -m pip check
git diff --check
Push-Location frontend
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
Pop-Location
```

The run reused installed frontend dependencies and used a fresh pytest
scratch path. Choose another scratch path for subsequent runs.

## Human review

| Task | Status | Evidence or remaining action |
| --- | --- | --- |
| H1 · Start | PASS | The stage owner authorized the scoped implementation. |
| H2 · Access | NOT_NEEDED | The accepted corpus and local runtime were available. |
| H3 · Relevance and metadata | PASS | H3 PASS — JPCP — 2026-11-10 |
| H4 · Technical evidence | PASS | H4 PASS — JPCP — 2026-11-10 |
| H5 · Handoff | PASS | H5 PASS — JPCP — 2026-11-10 |
| H6 · Closure | PASS | H6 PASS — JPCP — 2026-11-10 |

## Stage 4 handoff

Use `api.academic_retrieval.retrieve_academic(question, base_url=..., client=...)`
with a server-configured `/parte5` URL on the unified listener and a caller-owned
`httpx2.AsyncClient`. Each request has a ten-second HTTP timeout. The
helper returns `context` with up to three ordered sources, or `no_context`
with an empty source list. Each source contains its label, chunk and paper
IDs, position, title, authors, year, abstract, full stored content and score.
The exceptions are `InvalidQuestion`, `EngineUnavailable` and
`InvalidEngineResponse`. Stage 4 will map them to the public response
contract and use the retrieved content as generation evidence. The
[accepted contract](CONTRACT_P5.md) defines the future public response.
