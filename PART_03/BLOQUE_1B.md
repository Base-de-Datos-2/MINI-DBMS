# Part 3 — Block 1B: real corpus acceptance

Date: 2026-10-24. Sources: [Part 3 plan](PLAN_PARTE_03.md), §3.1.1,
[Block 1A contracts](BLOQUE_1A.md), and [REQUIREMENTS §16](../REQUIREMENTS.md).
The current request authorizes **1B.1–1B.4 only**. Block 1A remains closed;
Block 1B and overall corpus acceptance remain **PENDING** until 1B.5–1B.8.

| Task | Deliverable | State |
|---|---|---|
| 1B.1 | Version/split-compatible source manifests, verified access/bytes/hashes and usage conditions | Complete for the chosen ESCI replacement; initial MS MARCO candidate rejected by the query gate |
| 1B.2 | Original-query token lengths, independent judgments, deterministic shortlist and early failure | PASS for ESCI US/test; FAIL for MS MARCO v1 dev/train |
| 1B.3 | Streaming validation using actual engine types, UTF-8, declared and complete-record size checks | PASS: 100,000 valid pool documents plus all candidate positives |
| 1B.4 | Thirty original queries and all their positives, deterministic replacement/cap rules | PASS: 10 per group, union of 439 known positive documents |
| 1B.5 | Exact seeded nested 1k/10k/100k subsets | Pending; not authorized by this request |
| 1B.6 | All final selected rows inserted into Heap and verified after fresh-process reopening | Pending; codec validation does not substitute for this |
| 1B.7 | Complete corpus acceptance manifest with measured PASS/FAIL for every criterion | Pending |
| 1B.8 | Full block tests, documentation and closure | Pending |

## Implementation and methodology

[docs/text-corpus-preparation.md](../docs/text-corpus-preparation.md) records
source URLs/terms, exact CLI commands, dataset decisions, input formats,
original-field preservation, label mapping, reversible ID mapping and output
contracts. Preparation is in `benchmarks/text/` and the standalone script;
no production engine algorithm or API/frontend flow changes.

The initial candidate's complete original query files were checked:

- MS MARCO dev: 101,093 queries; 59,273 unique judged pairs; distinct eligible
  counts 2 / 5,427 / 38,593 for groups 1 / 3 / 5+.
- MS MARCO train: 808,731 queries; 532,751 unique judged pairs from 532,761 raw
  qrels rows; ten identical duplicate judgments consolidated. Distinct eligible
  counts 4 / 47,713 / 356,328.

Both fail the minimum ten one-token queries; queries/judgments were not edited
to force success. The plan's replacement-corpus path is therefore used.

Amazon ESCI source revision `7916cdf6ab75a462e77f20ab40428a10923998d5`,
large_version/test/us, supplies 22,458 original queries and 425,762 judged
pairs. Its eligible distinct query counts are **1,036 / 6,174 / 5,454**;
raw eligible query-ID counts are 1,036 / 6,177 / 5,455. The text field is the
entire product title, with original text preserved. ASIN-to-INTEGER mapping
is a fixed-width base36 bijection, and I/C/S/E map to grades 0/1/2/3 before
selection. These are explicit experimental decisions, not academic mandates.

The real validator scans all **1,215,854 US product IDs** for uniqueness. It
codec-checks **285,225 records**, covering the 100,000-document pool and every
candidate positive; **930,629 unselected distractor texts are not claimed as
codec-validated**. All 197,500 candidate-positive IDs resolve to valid original
titles; no positive is rejected or missing. No validation rejection was
observed in that scope. Accepted encoded rows range from **13 to 412 bytes**,
with mean **120.30571303356999 bytes**, below the actual 4,079-byte record limit.

Selection examines groups 1,3,5plus and ascending numeric query IDs. It keeps
ten per group whose complete known positives fit and whose normalized queries
are distinct, with a union cap of 1,000 documents. The measured run selects
30 queries with a positive union of **439 documents**, requiring no exclusions
among the examined first eligible candidates. No ranking model is consulted.

## Verification boundary

The code tests malformed encodings/IDs, logical versus physical overflow,
source identity/hash checks, missing/conflicting judgments, duplicate query
variants, missing positives, replacement rules, union limits and deterministic
results. A synthetic 100,000-row stream tests that the actual target is
processed rather than inferred from a small sample; it is not presented as
the real-corpus evidence above. Network unit tests use bounded fake responses.

The real source run uses PyArrow only to decode selected Parquet columns in
4,096-row batches. Original product titles stream to disk; IDs and
query/judgment metadata are retained in memory. A global ID set is explicitly
not a constant-memory guarantee. Stored query lengths use the same versioned
tokenizer as 1A; every accepted row uses the existing engine validation.

Full original sources/exports remain under ignored generated data. Versioned
sanitized evidence summaries identify the source hashes, counts and selected
IDs without publishing local profile paths or copying the complete corpus.
This work does not generate a corpus-approval PASS, SPIMI, production ranking,
seeded experimental subsets or the required real Heap acceptance run.

## Recorded evidence and validation

Implementation commit: `801ff72`. On 2026-10-24, the focused warnings-as-errors
regression passed **448 tests in 41.32 seconds**, including **58 new preparation
tests** and all 88 existing text-contract tests. Python 3.12.4, Unicode 15.0.0,
pytest 8.4.2 and PyArrow 26.0.0 were used on Windows. The independent real-data
rerun reproduced the same 30 original queries, 439 positive IDs and byte hash
of the complete selected-positive export; it preserves 443 judged query/product
pairs (some products are positive for more than one query).

Run from the repository root, using a fresh temporary directory:

```text
python -m pytest -W error -p no:cacheprovider --basetemp tmp/part03_1b_regression_20261024_a tests/text tests/test_architecture.py tests/storage/test_record_codec.py tests/storage/test_value_codec.py tests/storage/test_heap_file.py tests/storage/test_heap_persistence.py tests/query/test_parser_contract.py tests/query/test_binder.py tests/api/test_database.py
```

Versioned artifacts:

- [Chosen source manifest](../docs/implementacion/evidencias/text_1b_1_4/source_manifest_esci.json): pinned URLs, license, actual byte sizes, timestamps and complete verified source hashes.
- [Initial candidate failures](../docs/implementacion/evidencias/text_1b_1_4/candidate_rejections.json): original MS MARCO dev/train counts and exact source identities, including duplicate-judgment accounting.
- [Real preparation summary](../docs/implementacion/evidencias/text_1b_1_4/preparation_summary.json): stage results, scope/counts, byte distribution, selected query IDs, runtime, implementation commit and full local report hashes.

Full local reports/exports are in the ignored relative directory documented
in those artifacts. Evidence is sanitized with `scripts/sanitize_evidence.py`;
Archived JSON uses LF; the original source-manifest byte hash and all metadata
values/timestamps are preserved, alongside the archive checksum. No local account paths
or complete raw corpus are committed. This is preparation evidence and a
focused regression, not a final corpus-acceptance report or benchmark result.
