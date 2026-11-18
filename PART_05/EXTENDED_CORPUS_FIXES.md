# Extended academic corpus corrections

Technical verification: **PASS — 2026-11-18**. Baseline: `cdd55f3`.
Branch: `codex/fix-extended-academic-corpus`.

## Corrections

1. The original pypdf extraction split words in the legacy Okapi and
   PageRank PDFs, preventing their own names from matching their chunks.
   `corpus_extra.json` now explicitly selects Poppler `pdftotext` for
   papers 12 and 13. Other papers retain pypdf. PDF bytes, URLs, pinned
   revisions and SHA-256 values are unchanged. This is an offline ingestion
   option; the tokenizer, ranking algorithms and runtime SQL are unchanged.
2. The three short authored descriptions have been replaced with complete
   source abstracts: 147 words for TW-IDF, 148 for Okapi and 94 for PageRank.
   TW-IDF and PageRank were checked against their rendered PDF first pages.
   Okapi's full abstract comes from the
   [official NIST TREC-3 proceedings catalog](https://pages.nist.gov/trec-browser/trec3/proceedings/#okapi-at-trec-3),
   recorded in `abstract_source_url`. Its PDF starts with an introduction.
   PageRank's year is now 1998, matching January 29, 1998 on the pinned
   draft's title page. The commonly cataloged 1999 report date describes
   a different publication date.

The selected extractor must succeed: missing Poppler, failed execution,
timeout or a page-count discrepancy rejects preparation. SHA-256 checks
still precede extraction. Page order, whitespace normalization, complete
text reconstruction and encoded-record bounds retain their existing checks.
Minor legacy ligature and mathematical-symbol artifacts remain in extracted
text; this correction restores continuous search terms and readable main
prose, without claiming a perfect reconstruction of every PDF glyph.

## Real preparation and persistence

Environment: CPython 3.12.4, Unicode 15.0.0, pypdf 7.0.0 and Poppler
`pdftotext` 24.03.0. The production extended-profile preparation entry point
was run using the 13 previously downloaded, SHA-256-verified PDF files as
its download cache. This run did not re-download the PDFs from the network.
The existing complete-row comparison passed after insertion and reopening.

| Measurement | Result |
| --- | --- |
| Papers | 13 |
| Chunks before correction | 522 |
| Corrected chunks | 496 |
| TW-IDF / Okapi / PageRank chunks | 34 / 41 / 28 |
| Corrected chunk IDs for papers 11 / 12 / 13 | 394–427 / 428–468 / 469–496 |
| Words per corrected chunk, across all 13 papers | 248–254 |
| Largest complete encoded chunk row | 2,395 bytes |
| Largest complete encoded paper row | 1,908 bytes |
| Engine's complete-record limit | 4,079 bytes |
| Empty extracted pages | 0 |
| Input hashes and reopened rows match inputs | PASS |
| Fresh-process verification and index/storage validation | PASS |
| Original 10 metadata rows and 393 chunk rows match rebuilt prefix exactly | PASS |

The corrected database is `data/generated/extended_corrected/parte5`.
Its logical SHA-256 is
`ebb749fd5eddf9ee856ac776f921397aee009ccac540fa59563910774ea8761b`;
published generation: `76edd8db30194cea9314108b8e45637b`.

The accepted base database at `data/generated/todas/parte5` was independently
reopened and verified: 10 papers, 393 chunks, logical SHA-256
`640e6f06612e1d005de3cbd43fad81828c3ffbd1b99ead854e69688ef8842d36`,
generation `d74a9afd111c48cab531f4a3fcb43138`.
The base manifest is unchanged. Index generation UUIDs need not match
across rebuilds; compare logical rows with the same extractor versions.

Preparation reports now include a per-source `text_extractor` and the
set `text_extractors`. The existing `extractor` field identifies the pypdf
reader version; refer to the per-source fields for the actual text method.

## Retrieval and regression evidence

`scripts/check_extended_demo.py` now requires both TF-IDF and BM25 to
retrieve paper 12 for `Okapi` and paper 13 for `PageRank` in their top ten
results. This stronger check **failed against the original extended corpus**
with `Okapi did not retrieve paper 12` and **passed against the correction**.

The real five-part server also passed its text, media-search, media-file
and metadata checks. Parts 1–4 in the corrected demo root were copied from
the previously prepared extended demo. The academic REST retrieval helper
returned these ordered sources over actual loopback HTTP:

| Question | Chunk IDs | Paper IDs |
| --- | --- | --- |
| `Okapi` | 460, 428, 462 | 12, 12, 12 |
| `How does PageRank use links between web pages?` | 473, 477, 491 | 13, 13, 13 |

The returned sources include stored content and full relational metadata.
The PageRank passages discuss backlinks, rank computation and usage.
For the single-term Okapi query the highest-ranked passage is a reference
section; this is the measured lexical ranking, not a generation-quality
claim. No OpenAI request was made.

Focused strict regression: **206 passed in 40.67 seconds, no skips**:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pytest -q -rs -W error -p no:cacheprovider --basetemp tmp/fix_extended_20261118/pytest_01 tests/part5 tests/api/test_unified.py tests/text/test_tokenizer.py tests/text/test_4b_5_real_published_sql.py tests/test_architecture.py --tb=short
```

Coverage includes real Poppler Unicode/page-order extraction, invalid
selector, missing executable, command failure, timeout, page-count mismatch,
hash rejection before extraction, complete abstract metadata, ingestion,
retrieval, answer tests with test doubles, unified-server integration,
Part 3 SQL/tokenizer compatibility and architectural boundaries.

## Reproduction and local review

Use CPython 3.12 with the project's `academic` extra. For a new extended
build, install Poppler and ensure `pdftotext` is on `PATH`. Docker now
installs `poppler-utils`. Compose configuration validation passed; an image
build was not run because the local Docker daemon was unavailable.

From the repository root, prepare a **fresh destination**:

```powershell
pdftotext -v
.\.venv\Scripts\python.exe -X utf8 -m scripts.setup_academic_image --corpus extended --data-dir data/generated/extended_rebuild/parte5
.\.venv\Scripts\python.exe -X utf8 scripts/setup_academic.py --verify-only --data-dir data/generated/extended_rebuild/parte5
```

Use the already corrected, complete five-part root for local review:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m api --all --data-dir data/generated/extended_corrected --allow-writes
```

Then run the strengthened check in another terminal:

```powershell
.\.venv\Scripts\python.exe scripts/check_extended_demo.py --base-url http://127.0.0.1:8000
```

In Part 5, inspect the two retrieval examples and the full abstracts for
papers 11–13. These corrections do not record a new human acceptance or
supersede earlier stage sign-offs. Commits and pushes remain subject to
the repository's explicit approval rule.
