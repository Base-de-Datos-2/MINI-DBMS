# Part 5 Stage 1 results

- Overall status: **PASS**
- Coding-agent technical checks: **PASS**
- Tested commit: `f8b6a568b89c15ae272c75cb3861d28541cce41a`
- Branch: `docs/part5-stage1`
- Execution date: 2026-11-09
- Agent reviewer: Codex
- Human corpus and answer reviewer: JPCP (2026-11-09)
- Runtime: Windows, CPython 3.12.4, Unicode 15.0.0, Node 22.23.4, npm 10.9.9
- Probe packages: pypdf 7.0.0 and OpenAI Python SDK 3.48.0. `pip check` passed.
- Baseline: `data/generated/p5_stage1_baseline_03`, Parts 1 and 3 on port 8000, read-only
- OpenAI Developers plugin installation: user reported
- Credential: existing user-authorized `OPENAI_API_KEY` available to the tested Python process via the user-identified local env file. It was loaded into that process for the probe.
- Requested and returned OpenAI model: `gpt-6-luna`

| Check | Status | Evidence |
| --- | --- | --- |
| Frontend install and build | PASS | `npm ci` installed 110 packages. `npm run build` passed TypeScript and Vite. |
| Unified launch and relational read | PASS | Parts 1 and 3 ready. `SELECT * FROM students LIMIT 3` returned three rows. |
| BM25 REST retrieval and SQL | PASS | Three scored results in descending order. The first hit, document 2, matched the content read by SQL. Both text routes reported `TextIndexScan`. |
| Reopen and repeat REST checks | PASS | Graceful stop and a new server process on the same prepared data. The probe passed again with the same summary. |
| Browser check | PASS | Edge 157.0.4341.42. Executed SELECT in Part 1 and the BM25 preset in Part 3. Both tabs showed rows and plans, used their respective API prefixes and preserved Part 1 results on return. CSS and JS loaded and no page errors occurred. |
| Focused repository tests | PASS | 64 passed in 54.76 s with warnings treated as errors. |
| Three PDFs and extracted evidence | PASS | 36 pages yielded text. The selected body passages were compared with the rendered page 2 of each PDF. |
| Metadata and chunk feasibility | PASS | All three complete metadata rows and 119 candidate chunks fit. See measurements below. |
| Agent contract | PASS | [Proposed schemas, APIs and lifecycle](CONTRACT_P5.md). |
| Single live OpenAI call and agent evidence review | PASS | Completed once in 2.96 s. 425 input and 40 output tokens. Both answer claims are supported by the reviewed passage. |
| Independent human corpus and answer review | PASS | JPCP signed off on 2026-11-09. |
| Team agreement and teammate reproduction | PASS | JPCP confirmed team agreement and reported that EPCR reproduced the baseline results. |
| Stage 1 closure | PASS | JPCP gave final sign-off after the technical checks, independent review and teammate reproduction were recorded. |

The first setup attempt hit a Windows console-encoding error. Using `-X utf8` resolved it. A second setup attempt hit a sandbox restriction while publishing the text registry, so the final run used a fresh directory and the required local filesystem access. The initial pytest command needed its scratch parent directory created before the successful rerun. The baseline browser logged a favicon 404. npm also reported five advisories for the locked dependencies, including two critical. The frontend build and functional check passed.

## Sample and measured feasibility

I selected English-language papers on dense retrieval and approximate nearest-neighbor search. The [manifest](corpus_sample.json) records exact arXiv versions, PDF hashes, full abstracts and authors. The year is the year of the pinned arXiv version. Abstracts normalize PDF line breaks, ligatures and visible extraction spacing. All 36 pages provided text. Raw whole-document extraction retains layout artifacts around some formulas and line breaks. The feasibility probe establishes the size bounds and the reviewed sections establish usable evidence.

| Paper and source | Pages | Candidate chunks | Words per chunk | Largest chunk row | Metadata row | Reviewed body question |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1, [HNSW v4](https://arxiv.org/abs/1603.09320v4) | 13 | 46 | 249–250 | 1,829 B | 1,625 B | PDF p. 2, §2.1. How does greedy traversal select the next base node? It chooses the adjacent node minimizing distance to the query. |
| 2, [GPU similarity search v1](https://arxiv.org/abs/1702.08734v1) | 12 | 44 | 250–251 | 2,395 B | 1,338 B | PDF p. 2, §2, compressed-domain search. How do the two IVFADC quantizers divide the work? The first is coarse and the second encodes the residual. |
| 3, [Dense Passage Retrieval v2](https://arxiv.org/abs/2004.04906v2) | 11 | 29 | 252–253 | 1,878 B | 900 B | PDF p. 2, end of §1. What framework and training pairs are used? See the real answer below. |

The codec was run on complete candidate records, including the final chunk of every paper. The maximum allowed row size was 4,079 bytes. These checks were performed on temporary candidate rows.

## Single live answer for independent review

Source [S1] was a 257-word passage from paper 3, PDF p. 2 at the end of §1. It starts with the paragraph introducing the authors’ focus and includes the following contributions paragraph through the end of the introduction. The tested passage is in [context.txt](../tmp/p5_stage1/context.txt) in this workspace.

**Question** — What framework do the authors use to learn dense representations of questions and passages, and what training examples do they fine-tune it on?

**Actual answer** — They use a simple dual-encoder framework to learn dense question and passage representations. They fine-tune the encoders on question–passage pairs from existing datasets [S1].

**Agent review** — PASS. The two paragraphs explicitly describe the dual encoder and fine-tuning on question–passage pairs. The sole source label points to the supplied passage. The probe used the Responses API with 45-second timeout, zero retries, reasoning effort `none`, 500 maximum output tokens and `store=False`.

## Reproduction

Use PowerShell from the repository root. The ignored probe files are present under `tmp/p5_stage1/` on this workstation. On a separate checkout, prepare Python 3.12 and install `.[test,api]` as in A1.2 of the [Stage 1 guide](GUIDE_P5_S01.md). Install `pypdf==7.0.0` to reproduce extraction. Recreate `check_baseline.py` and `inspect_pdfs.py` from A2.2 and A3.3. Download the three versioned PDFs into `data/generated/p5_stage1_inputs/` using the names and hashes in the manifest. Choose a fresh baseline directory when preparing from scratch.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -m pip check
Push-Location frontend
npm.cmd ci
npm.cmd run build
Pop-Location
& $P5Python -X utf8 scripts/setup_all.py --data-dir data/generated/p5_stage1_teammate --only parte1 parte3
& $P5Python -X utf8 -m api --all --data-dir data/generated/p5_stage1_teammate
```

Run the REST probe in a second terminal at the repository root. Stop and restart the server using the same path to repeat the reads. The tested local baseline can be reopened using the same launch command with `p5_stage1_baseline_03`.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 tmp/p5_stage1/check_baseline.py
& $P5Python -X utf8 tmp/p5_stage1/inspect_pdfs.py
& $P5Python -X utf8 -m pytest -q -W error -p no:cacheprovider --basetemp tmp/p5_stage1/pytest_repro tests/api/test_unified.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_tokenizer.py
```

Create `tmp/p5_stage1` before the focused pytest command. Reproducing the REST baseline requires no additional OpenAI call.

## Human handoff

| Guide item | Owner | State and remaining action |
| --- | --- | --- |
| H1 | JPCP (D3) | PASS. JPCP confirmed ownership of the existing key and identified BD2 as the OpenAI Platform project for Part 5. Reuse and the bounded call were authorized. |
| H2 | D3 | NOT_NEEDED. The existing key worked in the probe runtime. |
| H3 | D2 / D4 | NOT_NEEDED for this workstation. REST and browser checks completed. |
| H4 | JPCP | PASS. JPCP approved the three papers and signed off on the independent corpus and answer review on 2026-11-09. |
| H5 | All four | PASS. JPCP confirmed that the team agrees on the contract and that EPCR reproduced the baseline REST results on their setup. |
| H6 | Team | PASS. JPCP approved the Stage 1 closure. The record includes the technical checks, JPCP's independent review, team agreement and EPCR's baseline reproduction. |

The next planned work is production ingestion (D1), offline publication and retrieval (D2), the REST-to-OpenAI application flow (D3), and the scoped chat panel (D4), following the agreed contract.
