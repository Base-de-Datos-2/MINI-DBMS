# Part 5 — Stage 2 results

- Overall status: **PASS**, closed on 2026-11-10
- Technical checks: **PASS**
- Human review: JPCP approved **H3–H6** on 2026-11-10.
- Execution date: 2026-11-09
- Baseline: `afbd63e31707b31b0bc3b5dcce3a45663410a669` on branch `feat/part5-stage2`
- Reviewed implementation: working-tree changes to `api/database.py` and `pyproject.toml`, plus `scripts/academic_corpus.py`, `scripts/setup_academic.py`, `tests/part5/test_ingestion.py` and the final manifest
- Runtime: Windows, CPython 3.12.4, Unicode 15.0.0, pypdf 7.0.0
- Inputs: [10-paper manifest](corpus.json) and local PDFs in `data/generated/p5_inputs/`
- Prepared database: `data/generated/todas/parte5`, definition `text`

## Implementation

- `scripts/setup_academic.py` validates all local inputs before creating a database. The manifest retains the three [accepted Stage 1 entries](corpus_sample.json) unchanged and adds seven pinned arXiv papers on dense retrieval and approximate nearest-neighbor search. The pinned source dates supply the years. The PDF title pages resolve the Aleksandra Piktus spelling in paper 6 and the merged Yingqi Qu and Yuchen Ding author entry in paper 10.
- The extractor reads pages in order, separates them with whitespace and collapses whitespace across the full text. The splitter rounds the target chunk count (word count divided by 250) half up, balances the chunk lengths and retries with shorter balanced chunks if required by the codec. Paper order follows ascending IDs. Chunk IDs are global and positions start at one per paper. Both complete row types must fit `MAX_RECORD_SIZE`.
- `Database.prepare_text` loads `papers` as a companion Heap alongside `chunks`. After the loading owner closes, the existing publication flow builds SPIMI, seals the indexed Heap and publishes only `chunks.content`. The original Part 3 call still works without companions.

## Measured checks

| Check | Status | Evidence |
| --- | --- | --- |
| Manifest and source hashes | PASS | 10 unique IDs and 10 distinct pinned PDFs. All actual SHA-256 values matched. Entries 1–3 are identical to the accepted sample. |
| Real PDF extraction | PASS | 147 pages across 10 PDFs. Every page returned some text. Representative body prose was checked against the source pages. Layout artifacts are recorded below. |
| Complete metadata | PASS | 10 metadata rows with complete abstracts and required fields. Largest serialized metadata row was 1,908 bytes (paper 6). |
| Word and byte bounds | PASS | 393 chunks at 249–254 words. Largest complete chunk row was 2,395 bytes (chunk 78). The Heap record limit was 4,079 bytes. |
| IDs, order, positions and associations | PASS | Paper IDs 1–10 and chunk IDs 1–393. Every paper has chunks, each association resolves and each paper's positions are consecutive. |
| Lossless chunk boundaries | PASS | For every paper, concatenating chunks with single spaces exactly reconstructed the whitespace-normalized extraction. |
| Full rows after owner reopen | PASS | Ordered SQL scans compared all 10 metadata rows and all 393 chunk rows against the validated inputs, field by field. |
| Separate process without input PDFs | PASS | `--verify-only` ran with `data/generated/p5_inputs/` temporarily absent. Counts, logical fingerprint and index generation matched preparation. The inputs were restored afterward. |
| Index publication and integrity | PASS | Only `chunks.content` is registered. It resolves by `chunk_id` against sealed storage and passes index and Heap consistency checks. `papers` opens as an ordinary Heap. |
| Existing destination refusal | PASS | A second preparation attempt returned exit code 1 before loading input. The subsequent fresh process verified the same database. |
| Focused and affected regression tests | PASS | 217 tests passed in 85.84 seconds with warnings treated as errors, including offline ingestion and the existing Part 3 SQL and HTTP checks. `pip check` reported no broken requirements. |
| Human corpus and extraction review | PASS | JPCP approved H3 on 2026-11-10. |

Both process invocations reported the logical row SHA-256
`640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36`
and index generation `d74a9afd111c48cab531f4a3fcb43138`. The fingerprint
covers the ordered full metadata and chunk rows. A fresh rebuild from the
same inputs should reproduce the fingerprint. Its index generation can differ.

## Corpus measurements

Page numbers in the notes and review samples are one-based PDF page numbers.

| Paper | Pages | Chunks (IDs) | Words/chunk | Max chunk bytes | Metadata bytes | Body checked and extraction notes |
| --- | ---: | --- | --- | ---: | ---: | --- |
| 1 · HNSW | 13 | 46 (1–46) | 249–250 | 1,829 | 1,625 | Page 2, proximity graphs and navigable small worlds. Some words split at hyphens or within glyph runs. |
| 2 · GPU similarity search | 12 | 44 (47–90) | 250–251 | 2,395 | 1,338 | Pages 2–3, problem statement and GPU architecture. Page 9 combines mathematical glyphs and plot labels with prose. |
| 3 · DPR | 11 | 29 (91–119) | 252–253 | 1,878 | 900 | Pages 2–3, dense representations and the dual encoder. Ligatures, line-end hyphens and adjacent math symbols are visible in extracted text. |
| 4 · The Faiss library | 21 | 66 (120–185) | 251–252 | 1,775 | 868 | Pages 2–3, index behavior and benchmark datasets. Some line breaks leave separated words, and some accents use PDF glyph sequences. |
| 5 · MIPS loss functions | 13 | 26 (186–211) | 251–252 | 1,950 | 1,103 | Pages 2–3, quantization loss motivation and derivation. Mathematical symbols and nearby text can run together. |
| 6 · RAG | 18 | 37 (212–248) | 252–253 | 2,243 | 1,908 | Pages 2–3, retrieval and generation methods. Figure 1 labels precede the main prose on page 2. The final appendix prose is readable. |
| 7 · ColBERTv2 | 11 | 27 (249–275) | 253–254 | 2,129 | 1,144 | Pages 2–3, LoTTE and retrieval background. Column prose remained coherent in the sample. Ligatures and printed hyphens remain. |
| 8 · BEIR | 21 | 53 (276–328) | 251–252 | 2,169 | 1,451 | Pages 2–3, benchmark coverage and neural retrieval. Figure 1 emits adjacent dataset labels before the prose. |
| 9 · ANCE | 15 | 34 (329–362) | 253–254 | 2,064 | 1,334 | Pages 2–3, negative sampling and dense retrieval loss. Labels and formula notation appear inline. |
| 10 · RocketQA | 12 | 31 (363–393) | 250–251 | 1,855 | 1,202 | Pages 2–3, false negatives and retriever training. Extracted text retains line-end hyphens and ligatures. |

The original ColBERT paper produced malformed words in its core prose in both
versions examined. The corpus uses the distinct ColBERTv2 paper, whose
representative prose survived extraction. The final corpus keeps extractable
headers, captions, tables, equations and references. Glyphs, inline labels
and column layout are subject to the PDF text layer. There is no OCR, formula
reconstruction or layout cleanup beyond whitespace normalization. The splitter
tries balanced partitions, so another input may be rejected even if a valid
unequal partition exists.

## Reproduction

Run from the repository root with CPython 3.12. Download any missing inputs
using the manifest. The preparation command verifies the bytes against its
pinned hashes before extraction.

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -m pip install -e ".[test,api,academic]"
$pdfDir = "data/generated/p5_inputs"
New-Item -ItemType Directory -Force $pdfDir | Out-Null
foreach ($paper in (Get-Content PART_05/corpus.json -Raw -Encoding UTF8 | ConvertFrom-Json)) {
    $file = Join-Path $pdfDir $paper.pdf
    if (-not (Test-Path -LiteralPath $file)) {
        Invoke-WebRequest -UseBasicParsing -Uri $paper.source_url -OutFile $file
    }
}

& $P5Python -X utf8 scripts/setup_academic.py --manifest PART_05/corpus.json --pdf-dir $pdfDir --data-dir data/generated/todas/parte5
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
```

The preparation invocation requires a fresh directory. Use another fresh
path for a rebuild and pass that same path to verification. If publication
fails after the database directory is created, the attempt may leave files
for inspection. The CLI reports the failure and a retry uses a fresh path.
The Windows run allowed the existing registry hard-link operation and local
HTTP test sockets.

The recorded test run used `tmp/p5_stage2/pytest_run_02` as its base temp
directory. Use a new scratch path for your own run.

```powershell
New-Item -ItemType Directory -Force tmp/p5_stage2 | Out-Null
& $P5Python -X utf8 -m pytest -q -W error -p no:cacheprovider --basetemp tmp/p5_stage2/pytest_review tests/part5/test_ingestion.py tests/api/test_database.py tests/api/test_gui_tables.py tests/text/test_4b_5_real_published_sql.py tests/text/test_registry_4b.py tests/text/test_sealing.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_tokenizer.py tests/api/test_unified.py tests/test_architecture.py
& $P5Python -X utf8 -m pip check
git diff --check
```

## Owner review package

Review the relevance and new metadata for papers 4–10 using each manifest
entry's source version. The unchanged metadata for papers 1–3 was reviewed
in [Stage 1](STAGE_01_RESULTS.md). The excerpts below are short anchors from
the persisted rows. Use them to locate the corresponding original passages.

| Sample | Stored chunk | Extracted anchor | Source PDF and passage |
| --- | ---: | --- | --- |
| Original paper | 5 | “only distances between the stored elements” | [HNSW, page 2](https://arxiv.org/pdf/1603.09320v4#page=2), §2.1, approximation using distances between stored elements. |
| New paper | 252 | “LoTTE focuses on long-tail topics in its passages” | [ColBERTv2, page 2](https://arxiv.org/pdf/2112.01488v1#page=2), Introduction, LoTTE paragraph. |
| Largest serialized chunk | 78 | “We use a PQ encoding of” | [GPU similarity search, page 9](https://arxiv.org/pdf/1702.08734v1#page=9), §6.4 DEEP1B through §6.5, around Figures 4–5. Inspect math and label placement. |
| Figure layout | 213–214 | “Query Encoder + Document Index” | [RAG, page 2](https://arxiv.org/pdf/2005.11401v1#page=2), Figure 1 labels and caption before the introduction continues. |
| Figure layout | 279 | “9 Retrieval Tasks 17 Datasets” | [BEIR, page 2](https://arxiv.org/pdf/2104.08663v1#page=2), Figure 1 labels followed by the introduction. |
| Final chunk | 248 | “F Retrieval Collapse In preliminary experiments” | [RAG, page 18](https://arxiv.org/pdf/2005.11401v1#page=18), appendix E–F. Read through the final paragraph and page number. |

To display the full stored samples, run this from the repository root
with `$P5Python` defined as above. Use the actual prepared directory if it
differs. Other IDs can be substituted for closer inspection.

```powershell
@'
from pathlib import Path
from api.database import Database, DatabaseDefinition

with Database.open(DatabaseDefinition("text"), Path("data/generated/todas/parte5")) as database:
    for chunk_id in (5, 252, 78, 213, 214, 279, 248):
        with database.engine.execute(
            f"SELECT chunk_id, paper_id, position, content FROM chunks WHERE chunk_id = {chunk_id};"
        ) as result:
            for row in result:
                chunk, paper, position, content = row.values
                print(f"\nPaper {paper}, chunk {chunk}, position {position}\n{content}")
'@ | & $P5Python -X utf8 -
```

| Human task | Status | Remaining action |
| --- | --- | --- |
| H1 · Start | PASS | JPCP authorized Stage 2 offline work. |
| H2 · Access | NOT_NEEDED | Public sources and the intended environment were accessible. |
| H3 · Corpus and extraction | PASS | H3 PASS — JPCP — 2026-11-10 |
| H4 · Persistence | PASS | H4 PASS — JPCP — 2026-11-10 |
| H5 · Handoff | PASS | H5 PASS — JPCP — 2026-11-10 |
| H6 · Closure | PASS | H6 PASS — JPCP — 2026-11-10 |

## Stage 3 handoff

The verified `text` database is at `data/generated/todas/parte5`. The
[accepted contract](CONTRACT_P5.md) defines `papers(paper_id, authors, year,
title, abstract)` and `chunks(chunk_id, paper_id, position, content)`.
The two Heap tables contain 10 and 393 rows, respectively. The published
SPIMI index covers `chunks.content` and uses `chunk_id` for identity.
Stage 3 covers Part 5 registration, REST retrieval and metadata assembly.
