# Text corpus preparation and acceptance — Block 1B

This is offline preparation for [Part 3](../PART_03/PLAN_PARTE_03.md), using
the existing engine's row validation, shared tokenizer and persistent Heap.
It builds the final nested subsets and measures their storage acceptance.
SPIMI and production ranking belong to later blocks.
The engine has no network/Parquet dependency. The CLI and source adapters live
in `scripts/prepare_text_corpus.py` and `benchmarks/text/`.

## Sources and the initial candidate decision

The official [MS MARCO dataset page](https://microsoft.github.io/msmarco/Datasets.html)
identifies the matching passage-v1 collection, query archive and split-specific
TREC qrels. Files were checked against HTTP Content-Length/ETag and downloaded
query/qrels hashes. The official terms specify non-commercial research use,
as-is provision and citation of Bajaj et al. (2016). Metadata preserves the
published size labels separately from measured HTTP byte sizes.

The initial candidate fails the required query gate:

| MS MARCO v1 split | Original queries | Unique judged pairs | Eligible distinct queries: 1 / 3 / 5+ tokens | Result |
|---|---|---|---|---|
| dev | 101,093 | 59,273 | 2 / 5,427 / 38,593 | FAIL: fewer than ten one-token queries |
| train | 808,731 | 532,751 | 4 / 47,713 / 356,328 | FAIL: fewer than ten one-token queries |

The train qrels have 532,761 raw rows, including ten identical duplicate pairs.
Identical repeats are counted and consolidated; conflicting grades fail.
Queries are not shortened, and unjudged queries are not assigned fabricated
positives. The large MS MARCO passage transfer was stopped after this failure;
partial bytes are not treated as a complete verified source. An exploratory
check of DBpedia-Entity v2's 467 original queries also found only five usable
one-token queries, so it was not adopted.

## Replacement candidate: Amazon ESCI

The official [Amazon Shopping Queries Dataset repository](https://github.com/amazon-science/esci-data)
provides original shopping queries, product fields and independent E/S/C/I
judgments. The source adapter pins repository revision
`7916cdf6ab75a462e77f20ab40428a10923998d5`, uses **large_version**, **test** split
and **us** locale, and records the repository's Apache-2.0 license/citation.
Its two Parquet source files have verified sizes of **51,286,808 bytes**
(examples) and **1,108,857,465 bytes** (products). Complete downloaded hashes
must match their upstream Git LFS SHA-256 identities before use.

This corpus choice indexes **the entire original `product_title` field** as
the document text. Other product fields are not part of that declared text
field. Titles are neither truncated nor normalized in storage. The original
title and query text, including punctuation, whitespace and case, are retained.
This is a title-retrieval experiment against supplied product-level judgments;
it must not be presented as indexing the complete product description.

Source product identity is `(product_locale, product_id)`. Since locale is
fixed to us, a canonical ten-character uppercase base36 ASIN maps bijectively
to an INTEGER via `int(asin, 36)`; its maximum is `36**10 - 1`, safely inside
signed 64-bit range. Leading zeros are preserved through the retained
`source_id` and the fixed width. This is not Python hashing. Invalid ASINs and
conflicting query/judgment identities are rejected.

Freeze the label mapping before ranking experiments: **I=0, C=1, S=2, E=3**.
Known positives are all supplied grades greater than zero. The mapping is a
project evaluation decision, not an extra assignment requirement. Original
labels remain in the source and are recoverable from the stored grade map.
Each query has only a limited judged result set; unjudged catalog products
may also be relevant. Future Precision@10/Recall@10 must be described as
relative to these supplied judgments, not exhaustive semantic truth.

## Deterministic preparation rules

1. Decode only source columns needed by each stage, in Parquet batches of
   4,096 rows. PyArrow is solely an auxiliary input decoder; no required DBMS
   operator, index or ranking uses it. TSV/TREC input uses the standard library.
2. Count query lengths with the shared tokenizer. Only groups 1, 3 and 5+ are
   eligible. Count distinct normalized token sequences; retain original texts
   and IDs, including alternatives with different judgments for the same
   normalized query. Require ten distinct queries per group before scanning
   documents. Missing qrels/query references or conflicting labels fail early.
3. Scan document IDs throughout the chosen source locale. Keep a global ID set
   to detect duplicates; corpus **texts** stream to JSONL. The ID set and
   query/judgment metadata grow with the source and are not an RSS memory bound.
4. Codec-validate the first 100,000 valid documents and **every candidate
   positive**, even when that positive occurs after the pool is full. Do not
   claim skipped distractor text has been codec-validated. Reject invalid
   UTF-8/types, logical character overflow and physical record overflow
   separately. A duplicate anywhere invalidates the provisional pool.
5. Use `TableMetadata`, `RecordCodec`, `validate_record` and imported
   `MAX_RECORD_SIZE`; do not approximate the page limit as 4 KiB. Every accepted
   record fits the actual complete-row format. Export original text and source
   ID unchanged; rejected documents never contribute to the 100,000 count.
6. Choose groups in order 1, 3, 5plus and query IDs numerically ascending. Skip
   a query if any known positive is missing/rejected, its normalized query
   duplicates an already selected query, or adding its complete positive set
   exceeds a union of 1,000 documents. Continue under the same rule until ten
   per group are selected. This does not use a ranker or select model winners.
7. Check source revision/split and hashes across stages. Bind validation to the
   exact preflight file. Check the positive spool hash, then verify every
   selected original exists before publishing a selection PASS report.

The selected positive union can overlap the first 100k pool. Block 1B.5 forms
exact nested 1k/10k/100k sets from this pool plus separately validated positive
originals. It checks duplicate IDs within each input and requires identical
original text/source identity wherever the two inputs overlap.

## Commands

From the repository root, install optional source decoding support:

```text
python -m pip install -e ".[test,corpus]"
```

Initial candidate checks, using separate source/preparation destinations for
each split:

```text
python scripts/prepare_text_corpus.py download --source-dir data/generated/text_corpus/msmarco_v1_dev/sources --split dev --metadata-only
python scripts/prepare_text_corpus.py preflight --source-dir data/generated/text_corpus/msmarco_v1_dev/sources --output-dir data/generated/text_corpus/msmarco_v1_dev/preparation_final
python scripts/prepare_text_corpus.py download --source-dir data/generated/text_corpus/msmarco_v1_train/sources --split train --metadata-only
python scripts/prepare_text_corpus.py preflight --source-dir data/generated/text_corpus/msmarco_v1_train/sources --output-dir data/generated/text_corpus/msmarco_v1_train/preparation_final
```

Both preflight commands correctly exit with status 1 for these sources.
Use a fresh preparation directory when repeating a stage; do not overwrite
its earlier evidence. Download caches are reusable only after rechecking
remote metadata and local hashes.

Replacement candidate preparation:

```text
python scripts/prepare_text_corpus.py download-esci --source-dir data/generated/text_corpus/esci_us_test/sources --metadata-only
python scripts/prepare_text_corpus.py preflight --source-dir data/generated/text_corpus/esci_us_test/sources --output-dir data/generated/text_corpus/esci_us_test/preparation_final
python scripts/prepare_text_corpus.py download-esci --source-dir data/generated/text_corpus/esci_us_test/sources
python scripts/prepare_text_corpus.py validate --source-dir data/generated/text_corpus/esci_us_test/sources --output-dir data/generated/text_corpus/esci_us_test/preparation_final
python scripts/prepare_text_corpus.py select --source-dir data/generated/text_corpus/esci_us_test/sources --output-dir data/generated/text_corpus/esci_us_test/preparation_final
```

Sources and full exports remain under ignored `data/generated/`. Downloading
uses checked byte ranges with at most sixteen 8 MiB blocks in flight, and
three attempts for transient I/O errors. No TLS verification is disabled.
Only Git LFS sources with an upstream full-content SHA-256 can resume partial
downloads; the complete result must still match that identity. Unverified
partials are preserved rather than silently adopted or overwritten.

## Outputs and acceptance boundary

| Output | Meaning |
|---|---|
| `sources/source_manifest.json` and download receipts | URLs, pinned revision, locale/split, terms, byte sizes, ETags and verified SHA-256 identities |
| `query_preflight.json` | Length counts, original candidate queries, positive judgments, deterministic shortlist and PASS/FAIL |
| `accepted_pool.jsonl` | First 100,000 codec-valid original documents; a preparation pool, not a frozen experimental subset |
| `candidate_positives.jsonl` | All accepted known positives for candidate queries, with original source IDs/text |
| `document_validation.json` | Full ID scan, accepted/rejected counts, byte distribution, source/preflight bindings and output hashes |
| `selected_queries.json` | Thirty original queries, complete positive associations, label grades, exclusions and PASS/FAIL |
| `selected_positives.jsonl` | Every selected positive original, checked against the positive spool |

PASS in one of these preparation reports applies only to its task. They keep
`corpus_acceptance = PENDING`; source/selection manifests also keep
`candidate_approved = false` as a historical preparation snapshot. The final
`corpus_feasibility.json` is the authoritative approval gate. No indexing/query
speed or relevance measurements are claimed by corpus acceptance.

## Nested exports and deterministic selection (1B.5)

The frozen seed is **20261024**. Algorithm `nested-v1` places all selected
positive IDs first, in numeric order, then orders the remaining validated pool
IDs by `SHA256(ASCII("nested-v1:" + seed + ":" + id))`, breaking any hash tie
by numeric ID. It takes prefixes of exactly 1,000, 10,000 and 100,000 IDs.
This specifies the seed's meaning without relying on Python RNG versions or
source arrival order. Required positives outside the original pool displace
the last distractors; the largest export still has exactly 100,000 documents.

Every row is canonical UTF-8 JSONL with LF, sorted keys, compact separators,
original `text`, numeric `id` and retained `source_id`. No title normalization,
truncation or chunking occurs. Text is streamed through file offsets; memory
holds IDs, offsets and digests, rather than the entire corpus text.
The three document files are byte-identical prefixes as well as nested sets.

Each size directory exports `documents.jsonl`, identical `queries.json`,
`qrels.tsv` and `manifest.json`. Qrels use `query_id 0 document_id grade`, with
tabs, and retain **all** supplied judgments for selected queries/documents,
including grade zero. Every known positive is included in every size; an
unjudged distractor is not assigned grade zero. The top-level
`subsets_manifest.json` records seed, algorithm, tokenizer, exact preparation
input hashes and each export's byte size/hash. Outputs require a fresh directory.

## Actual Heap verification and final gate (1B.6–1B.7)

The final schema is `documentos(id INTEGER PRIMARY KEY, contenido VARCHAR)`;
the declared text-character limit is 4,067 and the complete encoded-row limit
is 4,079 bytes, imported from the existing engine contract. Each of the
100,000 exported rows is validated again and inserted into `HeapFile`.
The writer records `id → RID` and a SHA-256 digest of canonical UTF-8 JSON
`{"id":id,"text":original_text}` followed by LF, then closes every handle.

A separate Python interpreter, launched with `-I -B`, opens the saved Heap
without a supplied schema. It checks the restored schema, record count,
unique ID set, every text digest and every RID association. Heap scans may
return a different order from insertion; aggregate content digests therefore
concatenate the binary row digests in numeric ID order. Writer and reader
process IDs, counts, before/after digests, encoded-size statistics, Heap/RID
file hashes and elapsed preparation time are saved in `heap_verification.json`.
Exceptions and nonzero child exits produce a FAIL receipt. This verifies a
clean close/reopen, not crash recovery or concurrent mutation.

The `accept` command rehashes both complete pinned sources; verifies the
preparation bindings; rereads every subset and its original validated spool;
recalculates the seeded order; rereads original selected query/judgment rows;
and checks all filtered qrels, positives and persistence artifacts. Six gates
receive measured PASS/FAIL evidence in `corpus_feasibility.json`. Missing
evidence fails the gate. Official acceptance always requires 100k rows and
ten original queries in each length group; small test fixtures cannot pass it.

Continue after the five preparation commands above, with the repository's
Python 3 virtual environment active (on Windows, `.venv/Scripts/python.exe`):

```text
python scripts/prepare_text_corpus.py subsets --source-dir data/generated/text_corpus/esci_us_test/sources --preparation-dir data/generated/text_corpus/esci_us_test/preparation_final --output-dir data/generated/text_corpus/esci_us_test/accepted_v1 --seed 20261024
python scripts/prepare_text_corpus.py verify-heap --output-dir data/generated/text_corpus/esci_us_test/accepted_v1
python scripts/prepare_text_corpus.py accept --source-dir data/generated/text_corpus/esci_us_test/sources --preparation-dir data/generated/text_corpus/esci_us_test/preparation_final --output-dir data/generated/text_corpus/esci_us_test/accepted_v1
```

To reproduce, reuse hash-verified pinned sources and run into fresh
preparation/export directories. Repeat `subsets` into a second destination
with the same seed and compare all 13 files: top-level subset manifest plus
the four files under each size. Bytes must match. Repeat Heap verification
against the new destination; timestamps, process IDs and elapsed times are
run-specific, while ID/text digests and document/query/qrels hashes must match.
The original source/preparation reports are preserved, not rewritten as final
approval. Full datasets and Heap artifacts remain under ignored generated data.
The versioned closure evidence and measured result are linked from
[Block 1B](../PART_03/BLOQUE_1B.md).

The corpus remains a selected English-US product-title collection, with a
positive-enriched smallest subset and finite product-level judgments. It is
not the complete official ESCI benchmark. Metrics in later blocks must use
these frozen exports and acknowledge incomplete relevance judgments.
