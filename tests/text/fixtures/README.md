# Text contract fixtures v1

Fixture ID: `text-contract-v1`; authored 2026-10-24. All text was written for
this project. These are deterministic functional examples, not an experimental
corpus or relevance judgments for evaluating Precision@10/Recall@10.

| File | Purpose |
|---|---|
| [collections.v1.json](collections.v1.json) | 16 short Spanish documents and six `articulos` documents, each with original text and manually specified normalized tokens |
| [queries.v1.json](queries.v1.json) | 20 cases: both literal assignment queries, 1/3/5+ token queries, repeated/unknown terms, accents, empty queries, order and LIMIT variations |
| [expected.v1.json](expected.v1.json) | Whole-collection frequencies, lengths, df, IDF, norms and ordered IDs/scores for every query and the worked example |
| [worked_example.v1.json](worked_example.v1.json) | Four-document collection used in the independent mathematical derivations |
| [invalid_documents.v1.json](invalid_documents.v1.json) | Separate duplicate-ID rejection inputs, including cross-block and tokenless duplicates |
| [manifest.v1.json](manifest.v1.json) | Version, model parameters, assertion tolerances and SHA-256 hashes of the five JSON inputs/results |

IDs arrive shuffled. Spanish IDs 3/45 and article IDs 4/14 have identical
content to force exact ties. Empty/tokenless Spanish IDs 90/88 and article
ID 8 count toward N/average length but never match. Spanish ID 2 preserves
the decomposed accent in its original text (`cafe\u0301 y café`) while its
tokens use composed `café`. No text is truncated or pre-normalized in storage.

The `tokenizer` field in collections records the authoring algorithm and
Unicode version (15.0.0). It is source-fixture provenance, not a persisted
index signature: all document/query tokens are checked explicitly on the
running interpreter. Future indexes built from these sources must record the
actual runtime signature; the index open-time mismatch policy remains binding.

The Spanish fixture has N=16, 61 tokens and avgdl=3.8125. `articulos` has N=6,
23 tokens and avgdl=23/6, with its own df and norms. Do not mix statistics
between collections. Scores are decimal strings to retain the archived
17-significant-digit values; convert only for assertion/display.

The Decimal reference and independent float/closed-form checks are described
in [the ranking contract](../../../docs/text-ranking-contract.md).
Fresh-process Heap tests check all 22 originals, per-document UTF-8 hashes,
row counts, physical arrival order and exact ID/RID associations. These tests
use a temporary mapping snapshot; production mapping/index persistence is
still phase 2/4B work. Duplicate cases currently validate the independent
reference; forcing SPIMI blocks and verifying failed publication belongs to
phase 2 and is not claimed here.

Regenerate snapshots only after review:

```text
python -m tests.text.freeze_expected
```

Tests never regenerate their own expected results. Original fixture bytes
use LF endings, enforced by `.gitattributes`. Any changed input/results must
be accompanied by reviewed manifest hashes and, when appropriate, a new
fixture version. Corpus acceptance remains pending in Part 3 block 1B.
