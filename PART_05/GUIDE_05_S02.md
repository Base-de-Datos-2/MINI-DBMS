# GUIDE_05_S02 — Stage 2: Ingest and Persist Academic Papers

This guide follows the same two-part structure as the Stage 1 guide:

- **Part I — Coding agent execution guide:** implementation steps, commands, validation, tests and evidence.
- **Part II — Human guide:** responsibilities of the **single person responsible for Stage 2**, including access that the agent lacks, content review and acceptance.

The coding agent starts. The stage owner does not need to collect the PDFs, write the ingestion code or repeat every technical check. Human review is required for closure; access assistance is conditional. No task in this guide requires another developer, a team meeting or a second person's sign-off.

**Starting point:** Stage 1 is recorded as PASS in `PART_05/STAGE_01_RESULTS.md`. Its three sample papers, data contract and existing OpenAI connection are established inputs. Stage 2 is offline ingestion: it needs neither an API key nor an OpenAI request. The installed OpenAI Developers plugin does not add work to this stage.

**Filename:** `GUIDE_05_S02.md`  
**Suggested repository location:** `PART_05/GUIDE_05_S02.md`  
**Planning window:** Days 2–3 of the existing ten-day plan, implemented by one stage owner with a coding agent. This is a planning estimate, dependent on usable PDFs and a working Stage 1 environment.

The guide is based on repository commit **`afbd63e31707b31b0bc3b5dcce3a45663410a669`**. It describes work to execute; it is not evidence that Stage 2 has run. Existing interfaces and proposed additions are distinguished below.

## Part I — Coding agent execution guide

**Audience:** The coding agent assigned to implement Stage 2. Execute the technical work, resolve ordinary implementation details within the accepted contract, and involve the single stage owner only for the tasks in Part II. Preserve existing work and keep errors and measured results explicit.

### A0. Objective and completion boundary

**Objective:** Provide one reproducible offline command that turns the selected academic PDFs and metadata manifest into persisted `papers` and `chunks` tables in a fresh Part 5 database directory.

Stage 2 is technically complete when:

1. The preparation command accepts a local PDF directory and a manifest.
2. Each selected paper has complete relational metadata stored in MINI-DBMS.
3. PDF text is extracted and normalized without changing its intended meaning.
4. Every stored chunk contains 200–500 whitespace-separated words and fits the complete serialized-record limit.
5. Paper IDs, global chunk IDs, positions and paper associations are valid and reproducible for the same inputs and configuration.
6. The preparation owner creates ordinary metadata and indexed text in one database without breaking existing Part 3 callers.
7. A fresh process can reopen the database and read the persisted data without PDFs, network access or extraction.
8. Focused automated checks pass and actual evidence is recorded.

Human closure additionally requires the stage owner's content review and acceptance in H3–H6.

#### A0.1 What carries over from Stage 1

| Established input | Use in Stage 2 |
| --- | --- |
| Unified application baseline and CPython 3.12 | Reuse the environment and owner/API conventions. |
| `PART_05/corpus_sample.json` | Preserve the three original paper IDs, versions, URLs and metadata as the starting sample. |
| `PART_05/CONTRACT_P5.md` | Preserve table fields, ID rules, word bounds and the storage/publication lifecycle. |
| Three successful extraction/size probes | Use them as development inputs; do not confuse temporary candidate rows with persisted Stage 2 data. |
| Working OpenAI connection | No action required in Stage 2. |

The Stage 1 report measured metadata rows of 1,625, 1,338 and 900 bytes and 119 candidate chunks. Those are historical probe results, not constants to force into the production implementation. If production normalization changes chunk counts, explain the difference and demonstrate text preservation.

#### A0.2 Resolve the Stage 2/Stage 3 boundary using the existing lifecycle

At the inspected commit, `Database.prepare_text()` already performs all of these operations together:

1. Creates and loads tables through the database owner.
2. Closes that owner.
3. Builds SPIMI, seals each indexed collection and publishes the text registry.
4. Reopens and validates the published collection.

Reuse that sequence. Add a small compatible way to create the ordinary `papers` table during preparation. **Do not split the existing method into new unfinished states merely to postpone its existing index work.**

Consequently, the Stage 2 preparation command may already produce a sealed, published `chunks.content` index as part of the reused method. Record this explicitly. Stage 3 still owns registration under `/parte5`, engine REST integration, metadata association in the application and retrieval relevance checks. Do not mark Stage 3 complete because offline publication already ran.

Direct owner/SQL reads are appropriate for offline preparation and persistence verification. The later runtime application must still consume the engine's REST API.

#### A0.3 Responsibilities and scope

| Task | Coding agent | Single stage owner |
| --- | --- | --- |
| Repository and environment | Inspect, prepare and record the baseline. | Resolve access only if necessary. |
| Corpus | Obtain public PDFs, verify sources, extend the manifest and inspect extraction. | Review the final corpus and representative excerpts. |
| Implementation | Write extraction, chunking, validation, owner extension and offline command. | No duplicate coding assignment. |
| Testing | Run meaningful automated tests and real corpus preparation/reopen checks. | Review evidence; run a prepared command only if the agent cannot reach the intended machine. |
| Closure | Document results, limitations and the Stage 3 handoff. | Accept or identify a concrete correction. |

Do not add OCR, embeddings, a vector database, automatic web crawling, model calls, an upload endpoint, frontend work, persistent chat, incremental corpus updates, new SQL constraints or storage-format changes. Do not require a new benchmark campaign. PDF downloading during execution is a finite corpus-selection task, not a new application feature.

### A1. Establish the implementation baseline

#### A1.1 Inspect the checkout before changing it

Run from the existing repository root:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

Read the current versions of:

- `AGENTS.md`, `REQUIREMENTS.md` and relevant sections of `PROJECT_CONTEXT.md`.
- `PART_05/PART_05_OPTION_A.md`, especially Stages 2 and 3.
- `PART_05/CONTRACT_P5.md`, `PART_05/STAGE_01_RESULTS.md` and `PART_05/corpus_sample.json`.
- `scripts/setup_text.py`, `api/database.py`, `engine/storage/record_codec.py` and `engine/storage/binary.py`.
- Existing owner, GUI-table, text-publication and sealing tests.

Preserve uncommitted work. Do not reset files or overwrite an existing database to follow this guide. If the current branch already contains the accepted Stage 1 work, create a dedicated branch from that baseline when needed:

```bash
git switch -c feat/part5-stage2
```

If the branch exists, inspect it and reuse it where appropriate. Record the actual starting commit. If the checkout has advanced beyond the inspected commit, reconcile relevant changes before applying the proposed interface below.

The previous review identified a local-only Stage 1 passage link and stale current-state wording. Those are documentation follow-ups, not reasons to rerun the OpenAI test or fabricate missing historical evidence. When recording Stage 2, link the accepted contract and update current-state documentation within the authorized scope.

#### A1.2 Reuse the tested Python environment

Use **CPython 3.12** and the existing environment where available. The Stage 1 run used Python 3.12.4 and Unicode 15.0.0. Preserve the frozen text-normalization baseline.

PowerShell:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 -c "import sys, unicodedata; print(sys.version); print(unicodedata.unidata_version)"
& $P5Python -X utf8 -m pip check
New-Item -ItemType Directory -Force tmp/p5_stage2 | Out-Null
```

If the environment is absent, follow Stage 1's Python setup. Do not overwrite a working environment unnecessarily. The `-X utf8` flag retains the Windows console-encoding workaround already demonstrated in Stage 1.

Declare `pypdf` as an application/preparation dependency, outside the engine's core dependencies. A small optional extra is sufficient. For example, add this entry under the existing `[project.optional-dependencies]` table, preserving all other entries:

```toml
academic = ["pypdf==7.0.0"]
```

This pins the version recorded in Stage 1. Then install the declared extras:

```powershell
& $P5Python -X utf8 -m pip install -e ".[test,api,academic]"
& $P5Python -X utf8 -m pip check
```

The `academic` extra is a **proposed addition**, not an existing baseline feature. If the repository has since added an equivalent extra, reuse it and update the recorded command.

Bash equivalent after declaring the extra:

```bash
P5_PYTHON="$PWD/.venv/bin/python"
mkdir -p tmp/p5_stage2
"$P5_PYTHON" -X utf8 -m pip install -e '.[test,api,academic]'
"$P5_PYTHON" -X utf8 -m pip check
```

For later commands, replace PowerShell's `& $P5Python` with `"$P5_PYTHON"` in Bash. Run commands from the repository root. Node/npm work is unnecessary unless an actual frontend change is introduced, which this stage does not require.

#### A1.3 Keep the change small and reviewable

Suggested files to create or modify:

| Path | Purpose |
| --- | --- |
| `scripts/setup_academic.py` | New offline CLI and orchestration. |
| `scripts/academic_corpus.py` | Small extraction/chunking/validation helper, if separating it makes tests clearer. A single script is acceptable if it stays readable. |
| `api/database.py` | Compatible companion-table argument for `prepare_text`. |
| `pyproject.toml` | Declare the PDF extraction dependency. |
| `PART_05/corpus.json` | Complete corpus manifest using the existing sample format. |
| `tests/part5/test_ingestion.py` | Focused new ingestion and preparation checks. |
| `PART_05/STAGE_02_RESULTS.md` | Actual execution evidence and single-owner acceptance. |
| `PROJECT_CONTEXT.md` and a short setup section in `README.md` | Implemented decisions and reproducible commands. |

These are suggested new paths, not claims that the files already exist. Keep the old sample manifest as historical Stage 1 evidence. Reuse equivalent existing files if the checkout already provides them.

**A1 completion criteria**

- [ ] Actual baseline commit and interpreter recorded.
- [ ] Stage 1 inputs and current owner lifecycle inspected.
- [ ] PDF dependency declared without importing it into `engine/`.
- [ ] Existing work and data directories preserved.

### A2. Prepare the real corpus and manifest

#### A2.1 Extend the accepted sample

The ten-day plan targets **10 papers on one coherent topic**. Ten is a project planning choice, not an academic minimum and not a hardcoded CLI requirement. Use the existing theme: dense retrieval and approximate nearest-neighbor search.

1. Start from the three versioned papers in `corpus_sample.json`.
2. Select seven additional public academic PDFs with selectable text and complete metadata.
3. Keep existing IDs 1–3; assign unique positive IDs to the additions.
4. Record a versioned source where available, the exact PDF filename and its SHA-256 hash.
5. Save PDFs under `data/generated/p5_inputs/`, which belongs with generated inputs, not tracked source code.
6. Read each abstract and inspect representative body text before committing to the paper.

The agent handles public searches and downloads. Ask the owner only for a concrete restricted-access problem or a course-specific constraint not available in the supplied materials. If a paper is unusable, choose another suitable public paper. Do not implement OCR or a crawler to rescue unsuitable inputs.

Do not silently reduce the accepted corpus to three papers and call the full Stage 2 corpus complete. If the owner explicitly changes the planning target, record the revised decision without presenting ten as an assignment requirement.

#### A2.2 Preserve the manifest shape

Create `PART_05/corpus.json` as a UTF-8 JSON array. Each entry follows the existing fields:

```json
{
  "paper_id": 4,
  "pdf": "paper_04.pdf",
  "source_url": "REPLACE_WITH_VERIFIED_PDF_URL",
  "version": "REPLACE_WITH_VERIFIED_SOURCE_VERSION",
  "sha256": "REPLACE_WITH_ACTUAL_64_CHARACTER_SHA256",
  "authors": "REPLACE_WITH_VERIFIED_AUTHORS",
  "year": 2020,
  "title": "REPLACE_WITH_VERIFIED_TITLE",
  "abstract": "REPLACE_WITH_COMPLETE_ABSTRACT"
}
```

The object above is a shape example, not a selected paper. Do not leave placeholders in the final manifest.

Maintain the Stage 1 convention: `year` is the year of the pinned source version. Verify it against that source rather than deriving it blindly from a filename or the first-submission identifier.

The source/version/hash fields remain in the manifest; they do not require extra database columns. Store all authors in one text field. Normalize metadata spacing as needed, but do not summarize or truncate the abstract to make a record fit.

#### A2.3 Validate inputs before preparing a database

Validate all manifest entries and PDFs before creating the destination database:

- Manifest is a nonempty array of objects with the required fields.
- `paper_id` and `year` are actual integers, not strings or JSON booleans.
- Paper IDs are positive, unique and at most `2**53 - 1`.
- Authors, title and abstract are nonempty strings after trimming.
- Source and version identify the selected document; hashes contain 64 hexadecimal characters.
- `pdf` names resolve to regular files inside the supplied PDF directory. Reject absolute paths or traversal outside that directory.
- Reused entries do not accidentally point to the same file/content as separate papers; report duplicate PDF paths or hashes.
- Actual PDF hashes match the manifest before extraction. A mismatch requires investigating the download/version, not silently replacing the expected hash.
- Metadata rows pass the actual codec and record-size checks in A3.3.

Use clear errors identifying the paper ID, filename and invalid field or bound. No online metadata service is needed during the ingestion command: the downloaded corpus and verified manifest are its inputs.

**A2 completion criteria**

- [ ] Final corpus manifest contains the agreed corpus, with existing sample IDs preserved.
- [ ] Every source, version, hash and metadata entry is verified.
- [ ] Downloaded inputs remain outside tracked code.
- [ ] Missing, duplicate or mismatched input fails explicitly before database preparation.

### A3. Implement extraction, chunking and complete-row validation

#### A3.1 Extract readable text

Use `pypdf.PdfReader` and each page's `extract_text()` as in the Stage 1 probe. Keep this logic in preparation code outside `engine/`.

For each paper:

1. Read pages in document order.
2. Collect each page's extracted text; join pages with whitespace so adjacent page words are not concatenated.
3. Normalize runs of whitespace into single spaces and trim ends.
4. Keep the original capitalization, punctuation and accents. Do not stem, remove stopwords or lowercase the stored content.
5. Reject an unreadable, encrypted-without-access, or effectively textless PDF with a source-specific error. A figure-only page is not by itself a failure when the document has usable body text.
6. Compare extracted body passages with the PDF. If columns or formulas corrupt the relevant prose, select a suitable input or make a narrow, documented extraction correction. Do not silently generate missing text with an LLM.

The default includes all extractable document text. Do not add a references classifier, header-removal engine or full document-layout reconstruction. Basic whitespace normalization is the planned scope. If an essential paragraph is garbled, a passing byte count does not make the extraction acceptable.

#### A3.2 Use deterministic chunk boundaries

Word count means **`len(content.split())`**, as agreed in Stage 1; it is different from the text index's token count.

A small deterministic balanced splitter is sufficient for this corpus:

1. Split normalized text into words. Reject fewer than 200 words.
2. For `N` words, permissible chunk counts are from `ceil(N / 500)` to `floor(N / 200)`.
3. Choose a count near `N / 250`, clamped to that interval, using a documented deterministic rounding rule.
4. Divide the words among that many chunks using quotient and remainder: lengths differ by at most one word, with the extra words assigned to the earliest chunks.
5. Join each chunk's words with single spaces.
6. Validate the full serialized row of every candidate. If byte bounds fail, try higher permissible chunk counts with the same balancing rule, producing shorter chunks.
7. If no candidate fits, report that this splitter cannot produce valid rows for the paper. Inspect the input or select a compatible paper; do not truncate words, increase the storage limit, or fall below 200 words.

This is a bounded practical algorithm, not a claim that it finds every mathematically possible unequal partition. For the small selected corpus it avoids a new optimization subsystem. Record that limitation if a rejection occurs.

Examples of valid behavior:

| Input word count | Expected property |
| --- | --- |
| 199 | Reject: cannot produce a valid chunk. |
| 200 | One 200-word chunk. |
| 251 | One 251-word chunk; no one-word tail. |
| 501 | Two balanced chunks of 251 and 250 words. |
| 1,001 | Four chunks near 250 words, preserving every word. |

A particular chunk count is less important than the contract invariants. Validate these for each paper:

- Every chunk contains 200–500 words.
- Joining the chunks with one space reconstructs the normalized document text exactly.
- No overlap, missing tail, duplicated words or empty chunk is introduced.
- Positions are consecutive, starting at one.

Do not chunk each page independently: that can leave many fragments below 200 words.

#### A3.3 Validate the actual complete records

Use the exact storage order from the contract:

| Table | Ordered fields |
| --- | --- |
| `papers` | `paper_id INTEGER`, `authors VARCHAR`, `year INTEGER`, `title VARCHAR`, `abstract VARCHAR` |
| `chunks` | `chunk_id INTEGER`, `paper_id INTEGER`, `position INTEGER`, `content VARCHAR` |

Construct `Schema`, `Record` and `RecordCodec.serialize()` values using the existing engine classes. Compare the result with the imported `MAX_RECORD_SIZE`; do not enforce a separate handwritten character limit.

```python
from engine.storage.binary import MAX_RECORD_SIZE
from engine.storage.record import Record
from engine.storage.record_codec import RecordCodec


def require_row_fits(schema, values, label):
    size = len(RecordCodec.serialize(Record(schema, values)))
    if size > MAX_RECORD_SIZE:
        raise ValueError(
            f"{label}: serialized row is {size} bytes; "
            f"maximum is {MAX_RECORD_SIZE}"
        )
    return size
```

`RecordCodec.serialize()` validates encoding and types but does not itself enforce the page-capacity limit. The explicit comparison is necessary. Validate metadata as well as chunks.

At the inspected baseline, each of these schemas has 28 bytes of fixed integer/string-length overhead. UTF-8 bytes, rather than characters, determine the remaining size. Use the codec as the authority so tests also cover accents and multibyte characters.

#### A3.4 Assign final IDs before persistence

Process papers in ascending `paper_id`, regardless of JSON array order. Assign chunk IDs globally from one upward, and positions from one within each paper. Validate all IDs within the agreed JavaScript-safe range and every chunk's paper association.

For the same manifest, PDF bytes, extractor version and normalization/chunking rules, logical rows must be reproducible. Do not promise identical index directory names or generation UUIDs across rebuilds. A changed corpus or changed extraction can change downstream chunk IDs; incremental updates are outside this stage.

For ten papers, holding validated metadata and chunk rows in memory before calling preparation is acceptable. Do not add a streaming framework or duplicate database to avoid this small amount of memory. Once final IDs are assigned, validate final records again or reuse validation only where the fixed-width ID assumptions are explicit.

**A3 completion criteria**

- [ ] Extracted text is readable and normalized consistently.
- [ ] No text is silently omitted to satisfy length or byte bounds.
- [ ] IDs and positions are deterministic and valid.
- [ ] Both tables' complete serialized rows fit the imported limit.
- [ ] Invalid inputs identify the affected paper or chunk.

### A4. Extend preparation without changing the engine algorithms

#### A4.1 Add ordinary companion tables to the existing method

The current method accepts indexed collections shaped as `(NewTable, rows, id_column, text_column)` and indexes every supplied collection. Do not pass `papers` as another indexed collection.

A minimal proposed extension is:

```python
@classmethod
def prepare_text(
    cls,
    directory,
    collections,
    *,
    companion_tables=(),
    memory_budget_bytes=8 * 1024 * 1024,
):
    ...
```

Each companion entry is `(NewTable, rows)`. The keyword name is a proposed interface; use an existing equivalent if one has been added. Preserve positional arguments, the current default memory budget and the return value of published text registrations.

Implementation sequence:

1. Validate duplicate table names across indexed collections and companion tables. Avoid consuming one-shot row iterables during this name check.
2. Preserve the existing refusal to use a destination that already exists.
3. Within the single preparation owner, create/load `papers` through `create_gui_table()` with a Heap `NewTable` and no additional indexes.
4. Create/load `chunks` using the existing indexed-collection path.
5. Collect publication snapshots **only for indexed collections**.
6. Close the owner before the existing SPIMI/sealing work.
7. Preserve enumeration of every declared secondary index when sealing, even though this application requests none.
8. Publish only `chunks.content` to the text registry.
9. Reopen through `Database.open(DatabaseDefinition("text"), directory)` and preserve existing index validation.

Do not directly manufacture `gui_tables.json`, write Heap pages from the ingestion script, bypass ownership, or implement a second SPIMI path. The current owner already persists and reopens ordinary registered tables alongside indexed tables.

#### A4.2 Keep compatibility and failure behavior explicit

- Calls without `companion_tables` must retain their previous behavior.
- The existing text demo command must still prepare and reopen its collections.
- Companion `papers` is ordinary relational storage, not a sealed text collection. Its absence from the text registry is intentional.
- Later read-only API configuration protects runtime access; this stage does not invent a storage seal for the unindexed metadata table.
- Never modify or unseal an existing published chunks collection to add papers.
- If validation fails before preparation, no destination database should be created.
- If storage or publication fails after preparation starts, exit nonzero and do not report success. Leave the new failed directory clearly identified and use a different directory for retry.
- Do not promise crash-atomic multi-table preparation. Preserve existing cleanup/ownership behavior and avoid adding a recovery framework.

**A4 completion criteria**

- [ ] `papers` and `chunks` are created in the same new owner directory.
- [ ] Only `chunks.content` is indexed and published.
- [ ] Publication runs after the preparation owner closes.
- [ ] Existing callers remain compatible.
- [ ] A failed preparation cannot be mistaken for a successful Stage 2 run.

### A5. Provide and execute the offline command

#### A5.1 Implement the command contract

Create the CLI in `scripts/setup_academic.py`, following the import/entry-point style of `scripts/setup_text.py`. Keep extraction/validation functions importable for tests.

Proposed command:

```powershell
& $P5Python -X utf8 scripts/setup_academic.py --manifest PART_05/corpus.json --pdf-dir data/generated/p5_inputs --data-dir data/generated/todas/parte5
```

**This command does not exist in the inspected baseline. Implement it before running it.** It should:

1. Parse and validate arguments; require the manifest and PDF directory in preparation mode.
2. Refuse an existing destination, including an empty directory, consistently with `prepare_text`.
3. Validate the manifest, hashes, extraction, chunks and complete records.
4. Build ordinary metadata rows and indexed chunk rows from those validated values.
5. Call the extended `Database.prepare_text` once.
6. Reopen and compare the persisted rows with the validated input rows.
7. Print a concise success summary only after all required checks succeed.

One offline preparation command is enough. Downloads occur beforehand using the recorded source URLs; do not make ingestion depend on network availability. Do not add `--force`, an overwrite mode or automatic directory deletion.

For development, prepare into disposable paths such as `data/generated/p5_stage2_trial_01`. Use `data/generated/todas/parte5` for the accepted output only if absent. If already occupied, select a fresh path and record it for Stage 3; do not destroy data just to match the example.

#### A5.2 Verify persisted data through the owner

After preparation closes its resources, open a fresh owner and read the tables through its SQL engine. Follow the existing result context-manager pattern:

```python
from api.database import Database, DatabaseDefinition


def read_persisted_rows(directory):
    with Database.open(DatabaseDefinition("text"), directory) as database:
        with database.engine.execute(
            "SELECT paper_id, authors, year, title, abstract "
            "FROM papers ORDER BY paper_id;"
        ) as result:
            papers = [tuple(row.values) for row in result]
        with database.engine.execute(
            "SELECT chunk_id, paper_id, position, content "
            "FROM chunks ORDER BY chunk_id;"
        ) as result:
            chunks = [tuple(row.values) for row in result]
    return papers, chunks
```

Iterating results avoids relying on a UI preview cap. Do not retain open cursors across owner closure.

Compare these rows with the in-memory validated preparation rows, including full metadata and full chunk text, not just counts. Also verify:

- Exactly the expected table schemas and row counts exist.
- Every persisted paper has at least one chunk.
- Chunk IDs are globally unique and positions consecutive per paper.
- All paper associations are valid.
- All persisted word/byte bounds hold.
- The text registry contains `chunks.content`, not `papers`.
- The reopened owner validates the published index, with no rebuild.

#### A5.3 Demonstrate restart without re-ingestion

Add a small `--verify-only` mode to the same CLI so another process can inspect the prepared data:

```powershell
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
```

In this mode, only `--data-dir` is required. It must use `Database.open`, validate schemas, stored rows, IDs, associations, size bounds and the expected text registration, and print measured counts. It must not read input PDFs, download anything, call `prepare_text`, repair files or rebuild an index.

Require the relevant tables and registration explicitly: opening an empty `DatabaseDefinition("text")` by itself does not establish that an academic corpus exists.

Run preparation and verification as separate process invocations. Compare their counts and checks. The preparation-time row comparison establishes fidelity to inputs; `--verify-only` independently establishes the stored invariants and reopening behavior. Do not imply that verification without inputs can re-prove the original PDF text extraction.

Run preparation again against the same directory once to verify an expected refusal. Confirm the accepted database remains readable afterward. Do not count this intentional nonzero exit as a regression.

#### A5.4 Record useful output

Print or capture a compact summary containing:

- PDF and stored-paper counts.
- Stored chunk count and per-paper chunk counts.
- Minimum/maximum chunk words and maximum serialized chunk bytes.
- Maximum metadata bytes.
- Input hash checks and extractor version.
- Successful fresh-owner comparison and fresh-process verification.
- Actual destination and the published text collection name.

Place large temporary outputs under `tmp/p5_stage2/`. Put durable conclusions and exact commands in `STAGE_02_RESULTS.md`. If you link a small review excerpt from that report, commit the excerpt or include it directly; do not make the report depend on an ignored local file.

**A5 completion criteria**

- [ ] One documented command prepares the full corpus from local inputs.
- [ ] Full rows survive close/reopen without alteration.
- [ ] A separate process verifies persisted data without PDFs or network access.
- [ ] Existing-destination refusal preserves accepted data.
- [ ] Output distinguishes real success, expected refusal and actual failure.

### A6. Run focused tests and the real corpus check

#### A6.1 Test the behavior that can fail

Use small synthetic inputs for deterministic edge cases and the selected real PDFs for acceptance. Synthetic tests do not replace the actual PDF run.

| Area | Meaningful checks |
| --- | --- |
| Manifest | Missing fields; duplicate IDs; boolean/string IDs; invalid year type; missing PDF; bad/mismatched hash; escaping input path; accidental duplicate document. |
| Extraction | Page text joined in order with separating whitespace; textless/unreadable input rejected; meaningful Unicode preserved. Include a small PDF extraction integration fixture using an existing fixture technique or a tiny checked-in fixture. |
| Chunking | 199, 200, 251, 501 and 1,001-word cases; consecutive positions; no lost/duplicated words; repeated runs and manifest reordering produce the same logical rows. |
| Row bounds | Multibyte text where character and byte sizes differ; exact-boundary and oversized rows; oversized metadata rejected without truncation. |
| Owner extension | Ordinary `papers` plus indexed `chunks`; companion-only entries excluded from the text registry; duplicate names rejected; existing call without companions still works. |
| Persistence | Exact row comparison after reopening; separate-process verification; input PDFs not required for verification; existing destination is not overwritten. |
| Failure | Input validation leaves destination absent; a controlled preparation/publication failure is reported, releases resources and does not produce a successful summary. Reuse existing failure-test patterns. |

Use at least one real owner/index integration test for the extension. Do not mock away the persistence behavior the stage is meant to prove. Keep network downloads and paid calls out of automated tests.

#### A6.2 Run the affected checks

After creating the proposed new tests:

```powershell
& $P5Python -X utf8 -m pytest -q -W error tests/part5/test_ingestion.py tests/api/test_database.py tests/api/test_gui_tables.py tests/text/test_4b_5_real_published_sql.py tests/text/test_registry_4b.py tests/text/test_sealing.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_tokenizer.py tests/api/test_unified.py tests/test_architecture.py
& $P5Python -X utf8 -m pip check
git diff --check
```

Adapt only the proposed test filename if the implementation places tests differently; keep the relevant existing coverage. These existing test paths were confirmed in the inspected repository. Record the actual results, not the historical Stage 1 total.

If Windows temporary-directory restrictions recur, use the already-demonstrated approach with a new scratch path:

```powershell
New-Item -ItemType Directory -Force tmp/p5_stage2 | Out-Null
& $P5Python -X utf8 -m pytest -q -W error -p no:cacheprovider --basetemp tmp/p5_stage2/pytest_run_01 tests/part5/test_ingestion.py tests/api/test_database.py tests/api/test_gui_tables.py tests/text/test_4b_5_real_published_sql.py tests/text/test_registry_4b.py tests/text/test_sealing.py tests/text/test_4b_5_real_http_acceptance.py tests/text/test_tokenizer.py tests/api/test_unified.py tests/test_architecture.py
```

Use the fallback only when needed, rather than running the same full command twice. Broaden testing when shared-code changes, failures or current repository instructions justify it. Do not regenerate frozen tokenizer fixtures to conceal an interpreter mismatch.

Finally, run the real corpus preparation and fresh-process verification in A5. Automated small fixtures cannot prove that the selected academic PDFs are usable.

#### A6.3 Diagnose failures without expanding scope

| Failure | Action |
| --- | --- |
| PDF cannot be read or has unusable extraction | Confirm source/version; replace unsuitable input or report restricted access. |
| Fewer than 200 usable words | Reject the document; do not pad content. |
| Oversized row | Try valid shorter balanced chunks; reject incompatible metadata or paper without truncation. |
| Missing metadata | Correct from the source; do not invent values or use empty placeholders. |
| Existing output directory | Choose a fresh destination; preserve the existing database. |
| Owner/publication failure | Inspect the lifecycle error, release resources and retry in a new directory after fixing the cause. |
| Reopened rows differ | Treat as a blocking implementation issue; compare expected and persisted rows before moving on. |
| Old Part 3 test fails | Investigate compatibility of the preparation extension; do not disable the regression test. |

**A6 completion criteria**

- [ ] Boundary, failure, compatibility and persistence tests pass.
- [ ] Full selected corpus prepares successfully.
- [ ] Fresh-process checks pass and real measurements are captured.
- [ ] Any remaining blocker has an explicit status and owner.

### A7. Record evidence and hand off to the single owner

#### A7.1 Write the results document

Create `PART_05/STAGE_02_RESULTS.md`. A sufficient template is:

```markdown
# Part 5 — Stage 2 results

- Overall status: PENDING
- Coding-agent technical checks: PENDING
- Human review: PENDING
- Stage owner:
- Starting commit:
- Reviewed implementation commit or exact working-tree state:
- Execution date:
- Python / Unicode / pypdf versions:
- Corpus manifest:
- Actual prepared directory:
- Corpus target and actual paper count:

## Implemented changes
- Offline command:
- Companion-table preparation extension:
- Chunking and normalization rules:
- Offline index publication performed through the reused lifecycle:
- Stage 3 routing/retrieval integration remains pending.

## Measured checks
| Check | Result | Evidence |
| --- | --- | --- |
| Manifest/source/hash checks | PENDING | |
| Real PDF extraction | PENDING | |
| Complete metadata persisted | PENDING | |
| All chunks satisfy 200–500 words | PENDING | |
| All complete rows fit MAX_RECORD_SIZE | PENDING | |
| Valid unique IDs, positions and associations | PENDING | |
| No missing or duplicated normalized text | PENDING | |
| Reopened rows equal validated preparation rows | PENDING | |
| Fresh-process verification without input PDFs | PENDING | |
| Only chunks.content is registered for text search | PENDING | |
| Existing destination refused without data loss | PENDING | |
| New and affected regression tests | PENDING | |
| Human corpus/extraction review | PENDING | |

## Corpus measurements
| Paper ID | Pages | Stored chunks | Min/max words | Max chunk bytes | Metadata bytes | Extraction note |
| --- | --- | --- | --- | --- | --- | --- |

## Reproduction
Exact dependency, preparation and verify-only commands; source URLs and hashes
are in the tracked manifest. Temporary files are not required for reproduction.

## Human review
- Reviewer/date:
- Metadata reviewed:
- Representative source passages and stored chunk IDs reviewed:
- Result and any specific correction:

## Stage 3 handoff
- Actual directory and definition name:
- Table schemas and row counts:
- Text registration:
- Known limitations:
- Next work: Part 5 registration and REST retrieval/metadata flow.
```

Use `PASS`, `FAIL`, `BLOCKED` and `PENDING_HUMAN` truthfully. Overall PASS requires the technical work and the single owner's review. Do not copy Stage 1's sign-off or claim human review on the person's behalf.

#### A7.2 Update the minimum durable documentation

- Document installation, manifest/input locations and preparation/verification commands in a short README section.
- Record the implemented companion-table contract and persisted academic tables in `PROJECT_CONTEXT.md`.
- Update current-state notes so Stage 1/2 progress is clear without claiming later-stage work is authorized or complete.
- Preserve `CONTRACT_P5.md` unless an implemented decision needs clarification. Record the single owner's decision for a genuine scope/schema change; do not seek team approval for routine compatible choices.
- Keep secrets, PDFs, prepared database files, virtual environments and large logs out of the commit.

Run the repository's evidence sanitizer and inspect the resulting diff:

```powershell
& $P5Python -X utf8 scripts/sanitize_evidence.py PART_05/STAGE_02_RESULTS.md
git diff --check
git status --short
git diff --stat
```

Stage only intended files when staging is part of the assigned execution task. Follow existing commit/push instructions; writing this guide alone does not execute or publish Stage 2. No GitHub issue, PR comment or team notification is required by this guide.

#### A7.3 Agent exit checklist

- [ ] Offline CLI and declared dependency implemented.
- [ ] Final manifest and source records complete.
- [ ] Extraction, chunking, IDs and serialized-row bounds validated.
- [ ] Minimal owner extension preserves existing callers and publication rules.
- [ ] Actual corpus is stored and exact rows survive reopen.
- [ ] Separate process verifies without re-ingestion or original PDFs.
- [ ] New and affected tests pass; evidence contains actual results.
- [ ] Owner has a compact review package with source locations and stored excerpts.
- [ ] Remaining human items are specific; no tasks assigned to other developers.

Stop at this stage boundary after reporting the outcome. Do not implement the Part 5 API routes or UI simply because the offline data is ready.

## Part II — Human guide

**Audience:** The one person responsible for Stage 2. Every human task below belongs to you. You may use the coding agent for implementation and verification; this guide does not require participation from the rest of the team.

### H1. Start the stage and keep the scope clear

**Required once.** Give the coding agent the guide and assign execution. For example:

> Implement Stage 2 following `PART_05/GUIDE_05_S02.md`. I am the only human responsible for this stage. Reuse the accepted Stage 1 contract and sample papers, complete the offline ingestion and persistence work, run the relevant checks, and prepare evidence for my review. Do not assign work to other developers. Stage 2 does not require an OpenAI call or API key setup. Continue independent tasks if an access issue blocks one step.

You do not need to pre-download the corpus or create the scripts. If you already have a course-specific restriction on papers, tell the agent before corpus expansion. Otherwise, let it use the topic and planning target established above.

**Done when:** The agent has the execution task and any actual constraints. Do not repeat authorization for routine work already assigned.

### H2. Resolve access gaps only when they occur

**Conditional.** Intervene only when the agent identifies a specific limitation, such as:

- A required local installation or filesystem operation is unavailable in its environment.
- A PDF or repository is accessible only through your account.
- The accepted corpus exists only on your machine and cannot be reached by the agent.

Provide the missing file/access or run the exact prepared local command. Share the relevant output or error, not a credential. Do not enter an API key merely because the OpenAI plugin is installed: this stage uses no provider API.

The agent remains responsible for diagnosing the issue, preparing the command and incorporating the result. Mark H2 `NOT_NEEDED` when it encounters no access gap.

**Done when:** The specific access issue is resolved or clearly recorded as blocked.

### H3. Review the corpus and representative extraction

**Required before closure.** This is a content check, not a request to redo all automated validation.

Use the review package supplied by the agent:

1. Review the final list of papers for relevance to the selected topic.
2. Check title, authors, year and complete abstract against the listed sources. Reuse the recorded Stage 1 review for unchanged original metadata; focus new metadata review on the additions.
3. Read representative original PDF passages and the corresponding stored chunks. A practical minimum is three samples: one original paper, one newly added paper and the input with the most concerning layout or largest row. Inspect every extraction warning, even if that requires more samples.
4. Confirm that word order and meaning survived extraction; look for mixed columns, joined page words and missing essential prose.
5. Check the final chunk of at least one paper is readable and is not an artificial fragment or padded text.
6. Report a concrete issue using paper ID, PDF page/section and chunk ID if something is wrong.

The agent validates **all** chunk counts, sizes and associations. Your sample review evaluates meaning and suitability; it does not certify that every PDF formula was reconstructed perfectly.

**Done when:** You record PASS or a specific correction, with your initials and date. This review is required; it is not an optional replacement for implementation tests.

### H4. Review persistence evidence; run locally only if necessary

**Evidence review is required. Manual execution is conditional.** Confirm that the report shows:

- The actual directory, paper/chunk counts and measured bounds.
- Full row equality after preparation closes and a new owner opens.
- A later separate-process `--verify-only` invocation that does not read PDFs or rebuild data.
- Passing affected tests and preservation of the previous Part 3 preparation behavior.

If the coding agent already ran those checks in the intended environment, you do not need to repeat them. If it could not access your workstation and your local result is needed, use its recorded setup and run:

```powershell
$P5Python = ".\.venv\Scripts\python.exe"
& $P5Python -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/todas/parte5
```

Replace the path with the actual prepared directory. If the data has not been prepared on your machine, first obtain the recorded PDFs and run the documented preparation command into a fresh directory. Do not copy a success label from a different environment.

There is no requirement for a teammate to reproduce this stage. A fresh process run by the agent plus your review is sufficient when it establishes the intended evidence.

**Done when:** The evidence demonstrates persistence in the stated environment, or you provide the missing local result for the agent to record.

### H5. Resolve findings and understand the handoff

**Required, but brief.** Review the agent's final summary and request corrections only for observed defects, unresolved constraints or mismatches with the accepted contract.

You should be able to explain:

- Where the original PDFs, tracked manifest and prepared database live.
- What belongs in `papers` and `chunks`.
- Why both word counts and serialized byte sizes are checked.
- Why a rebuild uses a fresh directory and never edits a sealed text collection.
- That the existing preparation lifecycle may already publish the offline index, while Part 5 routes and retrieval integration remain Stage 3 work.

No team alignment meeting, second reviewer or four-person sign-off is required. If a correction changes extraction or stored data, the agent rebuilds into a fresh directory and reruns the affected checks; you review the corrected excerpts.

**Done when:** You understand the resulting dataset and any stated limitations, and blocking findings are resolved.

### H6. Close Stage 2

Use `PART_05/STAGE_02_RESULTS.md` and confirm:

- [ ] The offline command prepares the agreed corpus reproducibly.
- [ ] Metadata and all text chunks are persisted in the project's own storage.
- [ ] ID, association, word-count and complete-row size checks pass.
- [ ] Preparation and reopen use the existing owner/publication lifecycle.
- [ ] A fresh process reads the stored data without extraction or rebuilding.
- [ ] Relevant automated tests pass.
- [ ] Your corpus and extraction review is recorded.
- [ ] Access gaps are resolved or explicitly marked; no required item is hidden.
- [ ] The actual directory and Stage 3 handoff are documented.
- [ ] No API key, generated database or unintended large input is proposed for commit.

If all applicable items pass, give a concise acceptance for the agent to record. If one required item remains, leave the overall result `PENDING_HUMAN`, `FAIL` or `BLOCKED` with the concrete next action. Do not require additional participants to close the stage.

### Reference sources

Repository references are pinned to the inspected commit. The stage owner should use current checkout versions at execution time and reconcile any newer changes.

- [Stage 1 guide](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PART_05/GUIDE_P5_S01.md)
- [Part 5 plan](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PART_05/PART_05_OPTION_A.md), [accepted contract and planned routes](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PART_05/CONTRACT_P5.md), [Stage 1 results and sign-off](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PART_05/STAGE_01_RESULTS.md)
- [Sample corpus manifest](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PART_05/corpus_sample.json)
- [Repository instructions](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/AGENTS.md), [requirements transcription](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/REQUIREMENTS.md), [project context](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/PROJECT_CONTEXT.md)
- [Existing text preparation command](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/scripts/setup_text.py), [database owner and prepare_text](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/api/database.py)
- [Record codec](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/engine/storage/record_codec.py), [storage constants](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/engine/storage/binary.py), [declared dependencies](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/pyproject.toml)
- [Owner persistence tests](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/tests/api/test_database.py), [published text/ordinary table reopening tests](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/tests/text/test_4b_5_real_published_sql.py), [text registry tests](https://github.com/Base-de-Datos-2/MINI-DBMS/blob/afbd63e31707b31b0bc3b5dcce3a45663410a669/tests/text/test_registry_4b.py)
