# Part 5 — Option A: Academic-document RAG

## Goal and planning basis

Build a chatbot that answers questions from academic PDFs using MINI-DBMS for relational metadata and text retrieval, followed by one LLM call. Deliver the implementation in **10 working days with four developers**, assuming the existing relational and Part 3 components are operational.

The scope follows **Proyecto_Final.pdf, §2.5 and Annex A, Option A**. Delivery documentation follows §3. The PDF provides no numerical grading rubric; this plan maps acceptance criteria to its explicit requirements rather than inventing scoring rules.

Repository baseline inspected: [Base-de-Datos-2/MINI-DBMS](https://github.com/Base-de-Datos-2/MINI-DBMS/tree/65067796b167c2c8b89a3abb416d631d56ffcd7d), commit **65067796b167c2c8b89a3abb416d631d56ffcd7d** (7 November 2026). The repository documents Parts 3 and 4 as complete and already has a unified server. This plan is based on source inspection; running the application and verifying the baseline are Day 1 tasks.

## Required scope

| Assignment requirement | Implementation and completion evidence |
| --- | --- |
| Extract text from academic PDFs | An offline ingestion command processes the selected PDFs into persisted chunks. |
| Chunks of 200–500 words | Every stored chunk passes word-count and serialized-record-size checks. |
| Relational author, year, title and abstract | A papers table stores these fields; retrieval reads metadata from the engine. |
| Index chunks with Part 3 | Publish and query the existing inverted text index. |
| Question → relevant chunks → LLM answer | A real question retrieves stored chunks and sends them with the question to one configured LLM. |
| Consume the engine REST/GraphQL API | Use the existing REST text-search and SQL-query endpoints in the application workflow. REST is sufficient. |
| Integrate at least two data types | Text chunks and relational paper metadata participate in each successful answer. |
| Demonstrate through a user interface | Add a Part 5 chat panel to the existing tabbed frontend. |
| Project deliverables | Extend the repository documentation, incremental report, overall demo and presentation. |

Optional embeddings and Part 4 vector search are excluded. No model training, OCR, automated paper crawling, account system, cloud deployment, persistent conversation memory, streaming responses, or additional benchmark campaign is needed for this scope. The chatbot can display successive independent questions and answers without implementing conversational query rewriting.

## Reuse the repository

| Existing component | Planned use or minimal extension |
| --- | --- |
| `api/unified.py`: `PartSpec`, `PARTS`, mounted applications | Register `parte5` on the existing server, with its own prepared directory and read-only service. |
| `api/database.py`: `Database`, `NewTable`, `prepare_text` | Reuse the owner and offline text-publication lifecycle; extend preparation to include an ordinary metadata table alongside the indexed chunks. |
| `scripts/setup_text.py` | Follow its preparation pattern in a small academic-corpus setup script. Its existing demo collections are not the academic dataset. |
| `api/app.py`, `api/engine_service.py`, `api/text_search.py` | Reuse text retrieval and relational reads. Keep engine access behind the current service boundary. |
| `frontend/src/App.tsx`, `frontend/src/components/Workspace.tsx`, `frontend/src/workspaceScope.ts` | Add the RAG panel and preserve the per-tab API prefix and session isolation. |
| `scripts/setup_all.py` and existing documentation | Integrate or document preparation of the fifth directory and the existing unified launch command. |

The current `prepare_text` implementation creates and indexes every supplied collection. It does **not** already offer an argument for unindexed companion tables. Make the smallest compatible preparation extension so the papers table is created before the chunks are sealed; preserve existing Part 3 callers and publication checks.

Use `python -m api --all` and the existing port, with proposed data location `data/generated/todas/parte5`. Reuse the text database kind where sufficient; identify the new application panel by its part identity. Do not open a second owner on an already-owned directory or write into a sealed text collection. A corpus rebuild prepares a fresh directory while the affected application is stopped.

PDF extraction and LLM access belong in scripts/application code, outside `engine/`. Reuse the existing engine algorithms and frontend stack.

## Dataset and minimal data flow

Use a small collection of **10 academic papers on one coherent topic**, selected from the PDF's suggested sources, such as arXiv or conference papers. This is a planning target, not an assignment minimum. Begin with three papers on Day 1. Select PDFs with extractable text and use questions in the corpus language. Record the exact paper sources so the corpus can be reproduced.

A short manually checked manifest may supply author(s), year, title and abstract; the assignment does not require automatic metadata inference. Extract the document text from the PDFs themselves.

| Table | Minimal fields |
| --- | --- |
| `papers` | `paper_id`, `authors`, `year`, `title`, `abstract` |
| `chunks` | `chunk_id`, `paper_id`, `position`, `content` |

Store authors in one text field. Keep stable integer identifiers and validate each chunk's paper association during preparation. No additional author-management schema is needed.

Aim for approximately **250 words per chunk**, without overlap initially. Rebalance short final fragments so stored chunks remain within 200–500 words. The repository documents a **4,079-byte maximum complete serialized record**: validate the full row, including identifiers and encoding overhead, rather than counting characters. Adapt chunk boundaries within the permitted word range. Report incompatible documents or metadata instead of truncating content silently. Select a suitable small corpus rather than expanding the storage format for this application.

The proposed runtime flow is:

1. The Part 5 frontend submits a question to an application endpoint, proposed as `POST /parte5/api/rag/ask`.
2. The application retrieves chunks through `POST /parte5/api/text/query`, using existing BM25 with an initial top three results.
3. It obtains the corresponding papers through `POST /parte5/api/query`, using the integer paper IDs returned by retrieval.
4. It sends the question, retrieved chunks and source labels to one LLM.
5. It returns the answer and the retrieved sources for display.

The RAG orchestration can use a small HTTP client to those existing engine routes on the same server. Configure the internal engine address on the server; do not accept arbitrary target URLs from the user. Release database requests before waiting for the LLM. The new application route must not implement its own search engine or read database files directly.

The initial chunk size, corpus count and retrieval limit are implementation choices that may be adjusted during validation; they are not extra academic requirements.

## Ten-day schedule and team allocation

| Stage | Days | Main responsibility | Parallel contribution |
| --- | --- | --- | --- |
| 1. Confirm baseline and contracts | 1 | All four | D1 checks corpus; D2 checks engine/API; D3 tests LLM; D4 checks frontend integration. |
| 2. Ingest and persist academic papers | 2–3 | D1 + D2 | D3 prepares application orchestration; D4 builds the panel using the agreed response shape. |
| 3. Publish and expose retrieval | 4–5 | D2, supported by D1 | D3 connects REST retrieval; D4 connects question submission and source rendering. |
| 4. Complete grounded generation | 6 | D3 | D1 checks source fidelity; D2 checks API behavior; D4 integrates answer states. |
| 5. Complete the application interface | 7–8 | D4, supported by D3 | D1 prepares demonstration questions; D2 checks integration and restart behavior. |
| 6. Validate and fix | 9 | All four | Each developer fixes their area; another developer checks the result. |
| 7. Document and deliver | 10 | All four | D1 corpus/report; D2 setup/architecture; D3 RAG configuration; D4 demo/presentation. |

These are elapsed working days, with overlapping tasks across the team. Integration happens during the schedule. The ten-day estimate assumes a working baseline, shared daily availability, and an accessible LLM by the end of Day 1; it does not include rebuilding earlier project parts.

## Stage 1 — Confirm baseline and contracts

**Day:** 1  
**Objective:** Verify that the existing system, sample PDFs and chosen LLM support the intended application before committing to the full ingestion work.

**Completion criteria**

- [ ] Launch the unified application using the repository's documented environment and confirm that existing Part 3 text retrieval and relational queries work.
- [ ] Use the repository's required Python environment, including its documented CPython 3.12 text-normalization baseline.
- [ ] Select three initial academic PDFs and verify extraction quality, required metadata and storage-size feasibility.
- [ ] Agree on the two table schemas, integer IDs, request/response format, and Part 5 API prefix.
- [ ] Make one real LLM request with a sample question and extracted passage. Choose one provider/model; OpenRouter is a candidate, not a required dependency.
- [ ] Keep provider configuration and credentials on the server. Verify access and any applicable usage limits before depending on a free offering.
- [ ] Record the few setup decisions needed by the other developers.

**Exit result:** A verified baseline, sample corpus and working LLM connection. Full RAG integration comes later, but provider access is not postponed until the final day.

## Stage 2 — Ingest and persist academic papers

**Days:** 2–3  
**Objective:** Convert the selected corpus into valid relational metadata and searchable text rows.

**Completion criteria**

- [ ] Provide one offline command that accepts the corpus and metadata manifest and prepares a new Part 5 data directory.
- [ ] Store author(s), year, title and abstract for every paper in `papers`.
- [ ] Extract PDF text and normalize basic whitespace without adding OCR or elaborate layout reconstruction.
- [ ] Generate stable chunk identifiers, paper associations and document positions.
- [ ] Ensure every stored chunk contains 200–500 words, including the final chunk.
- [ ] Validate complete serialized rows against the engine's limits, including metadata rows; report the source of invalid input clearly.
- [ ] Extend preparation only as needed to create the unindexed metadata table and indexed chunk collection in the same database.
- [ ] Reopen the prepared database and verify that metadata and chunk content remain available.

**Exit result:** A reproducible, persisted academic corpus suitable for Part 3 indexing.

## Stage 3 — Publish and expose retrieval

**Days:** 4–5  
**Objective:** Retrieve relevant academic chunks and their relational metadata through the engine's REST API.

**Completion criteria**

- [ ] Build and publish the existing SPIMI text index over `chunks.content`, preserving the current sealing and fresh-owner validation lifecycle.
- [ ] Register Part 5 in the unified server with its own owner, directory and scoped API.
- [ ] Retrieve ranked chunks through the existing text-query route using BM25; do not introduce a new ranking implementation.
- [ ] Fetch each selected paper's metadata through the SQL-query route and associate it with its chunks.
- [ ] Implement the application retrieval flow with a small bounded result set and an explicit empty-result response.
- [ ] Verify that relevant passages are retrieved for a small set of questions drawn from the selected papers.
- [ ] Restart the server and repeat a retrieval without rebuilding the corpus or modifying Parts 1–4.

**Exit result:** Question → persisted text retrieval → relational source metadata, operating through REST.

## Stage 4 — Complete grounded generation

**Day:** 6  
**Objective:** Produce an answer using the question and the passages actually retrieved.

**Completion criteria**

- [ ] Complete the application endpoint connecting REST retrieval to the single LLM client tested on Day 1.
- [ ] Construct a bounded prompt containing the question, numbered source labels and retrieved passages.
- [ ] Instruct the model to answer from the supplied evidence and acknowledge when that evidence is insufficient.
- [ ] Return the generated answer with the actual source records used as context; do not invent bibliographic metadata.
- [ ] Keep API keys outside frontend bundles and tracked files.
- [ ] Handle an empty question, empty retrieval, provider timeout and provider rejection with clear responses. An unavailable LLM must not be presented as a successful generated answer.
- [ ] Verify at least one complete request against the real provider. Simulated provider responses may support automated checks but cannot be the sole integration evidence.

**Exit result:** A complete academic RAG request works before final UI validation.

## Stage 5 — Complete the application interface

**Days:** 7–8  
**Objective:** Make the required workflow usable and demonstrable in the existing frontend.

**Completion criteria**

- [ ] Show a Part 5 tab and a chat panel with a question field, submit control and readable answer.
- [ ] Use the tab's existing API scope so requests reach the Part 5 database.
- [ ] Show pending, successful, insufficient-evidence and failed-request states; prevent accidental duplicate submission while a request is pending.
- [ ] Display retrieved passages with paper title, author(s) and year so the answer's grounding can be inspected.
- [ ] Demonstrate several successive questions. Persistent chat storage and follow-up interpretation are not required.
- [ ] Complete the real PDF → MINI-DBMS → REST → LLM → interface flow without fixture answers.
- [ ] Confirm that switching tabs preserves the existing separation between project parts.

**Exit result:** The selected application is usable from the unified interface.

## Stage 6 — Validate and fix

**Day:** 9  
**Objective:** Demonstrate required behavior and resolve defects that would prevent a reliable submission.

**Completion criteria**

- [ ] Check ingestion boundaries: chunk word counts, final-fragment handling, row-size validation and correct paper associations.
- [ ] Check persistence and text-search/API integration using the project's existing testing conventions.
- [ ] Review a small acceptance set, for example four supported questions and two questions not supported by the corpus. Inspect retrieved passages and answer claims manually.
- [ ] Confirm that unsupported questions do not receive confidently invented corpus facts; adjust retrieval or prompting when failures occur, without claiming that prompting guarantees factuality.
- [ ] Exercise unavailable-provider handling and confirm that credentials never appear in responses.
- [ ] Verify the fifth tab, engine/API boundaries, and unchanged operation of Parts 1–4.
- [ ] Run the affected automated tests, repository-required checks and frontend build; record actual outcomes and fix blocking failures.

**Exit result:** A working application with concrete acceptance evidence and documented limitations. This small validation set is not an additional large-scale benchmark or a claim of measured general LLM accuracy.

## Stage 7 — Document and deliver

**Day:** 10  
**Objective:** Make the implementation reproducible and integrate Option A into the required project deliverables.

**Completion criteria**

- [ ] Commit the implementation and tests to the project repository through the team's normal review workflow.
- [ ] Update README instructions for dependencies, corpus preparation, LLM configuration and unified launch.
- [ ] Document the two-table design, text-retrieval reuse, REST flow, source selection and relevant limitations in the incremental report.
- [ ] Update `PROJECT_CONTEXT.md` with the implemented application decisions, without changing official requirements.
- [ ] Have a teammate reproduce preparation and one real question from the instructions.
- [ ] Include Option A in the overall **5–10-minute project demo**, showing retrieval, relational metadata and an LLM answer.
- [ ] Include the application's design and demonstration in the overall **15-minute presentation plus 5 minutes of questions**.
- [ ] Preserve the earlier parts' required experimental evidence; do not invent new Part 5 dataset scales or repeat completed experiments without a reason.

**Exit result:** Reproducible code, documentation and demonstration ready for the final project submission.

## Definition of done

Part 5 Option A is complete when a user can ask a question in the fifth tab, the application retrieves 200–500-word chunks through the engine's text API, obtains their relational metadata through the engine's query API, and displays an actual LLM answer based on those passages. The corpus survives restart, setup is documented, and the required project deliverables include the application.

The main implementation effort is corpus preparation and integration with the existing owner/API lifecycle. The LLM connection is essential to Option A, but it is a small integration whose availability should be proven early.

## Sources

- **Proyecto_Final.pdf** supplied with the request: §2.5, §3 and Annex A, Option A.
- Repository instructions and architecture at the inspected commit: [AGENTS.md](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/AGENTS.md), [REQUIREMENTS.md](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/REQUIREMENTS.md), [PROJECT_CONTEXT.md](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/PROJECT_CONTEXT.md).
- Backend integration points: [api/unified.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/api/unified.py), [api/database.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/api/database.py), [api/app.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/api/app.py), [api/engine_service.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/api/engine_service.py), [api/text_search.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/api/text_search.py), [scripts/setup_text.py](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/scripts/setup_text.py).
- Frontend integration points: [App.tsx](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/frontend/src/App.tsx), [Workspace.tsx](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/65067796b167c2c8b89a3abb416d631d56ffcd7d/frontend/src/components/Workspace.tsx).

