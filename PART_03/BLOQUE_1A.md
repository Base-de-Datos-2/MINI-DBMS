# Part 3 — Block 1A: contracts and fixture

Date: 2026-10-24. Source: [Part 3 plan](PLAN_PARTE_03.md), §§2–5, and
[REQUIREMENTS](../REQUIREMENTS.md), §16. These contracts are project decisions,
not additional academic requirements.

The initial request authorized tasks 1A.1–1A.4; the follow-up explicitly
authorizes **1A.5–1A.7 and closure of Block 1A**. Corpus acceptance, SPIMI,
production ranking, storage sealing, SQL execution and API/frontend integration
belong to subsequent blocks. Corpus acceptance remains **PENDING** in 1B.

**Status: Block 1A CLOSED on 2026-10-24**, after all seven criteria and the
390-test focused regression below passed. This closes contracts/fixtures only.

| Task | Deliverable | Status |
|---|---|---|
| 1A.1 | Integration map below | Complete |
| 1A.2 | Document/statistics contract and storage checks below | Complete |
| 1A.3 | Shared versioned tokenizer and exact-output tests | Complete |
| 1A.4 | [Textual SQL contract](../docs/text-sql-contract.md) | Complete as a specification; parser implementation belongs to 4B |
| 1A.5 | [Ranking mathematics and worked examples](../docs/text-ranking-contract.md), Decimal/float/analytic checks | Complete |
| 1A.6 | [Versioned fixtures](../tests/text/fixtures/README.md), 20 queries and frozen results; all 22 texts verified through a fresh-process Heap reopen | Complete |
| 1A.7 | Final block validation and closure | Complete; 390 focused regression tests passed |

## 1A.1 — Integration map

Inspection baseline: commit `206af83`, before this increment. Part 1 Stage 10
is closed; the current work starts the explicitly authorized Part 3 contracts.

| Existing abstraction | Reuse | Later change / relevant tests |
|---|---|---|
| `Schema`, `Record`, `TableMetadata`, `ColumnConstraint` in `engine/catalog/` and `engine/storage/record.py` | Ordered columns, exact Python types, declared character limits | Text publication must validate ID uniqueness across the whole collection. Schema/type checks alone do not enforce it. `tests/storage/test_record_codec.py`, `tests/query/test_executor_writes.py` |
| `RecordCodec`, `ValueCodec`, `binary.MAX_RECORD_SIZE` | Signed 64-bit INTEGER; strict UTF-8 VARCHAR with a four-byte byte-length prefix | Use `engine.maintenance.validation.validate_record` for existing logical and physical row checks. The codec alone does not enforce page capacity. `tests/storage/test_value_codec.py`, `tests/storage/test_record_codec.py` |
| `HeapFile.create/open/insert/read/scan`, `RID` | Store original text; scan `(RID, Record)` pairs and retrieve winners by RID | Persist the collection-specific ID/RID map during SPIMI preparation. Add the persistent seal in 4A. `tests/storage/test_heap_file.py`, `test_heap_persistence.py`, `test_heap_arrival_order.py` |
| `api.database.Database`, `NewTable`, `create_gui_table`, `gui_tables.json` | The owner already used by the UI opens permanent files and owns sessions/cleanup | Build the text preparation flow and registry here in 4B. `create_gui_table` accepts a Sequence and materializes rows; create an empty table first and load through an offline streaming preparation path rather than passing a corpus generator to this API. `tests/api/test_database.py`, `test_gui_tables.py` |
| `engine.database.Database` | Preserve the independent manifest-backed relational owner | No second text lifecycle or UI migration in this delivery. Explicitly reject unsupported textual collections when applicable. `tests/database/` |
| `QueryEnvironment` | Borrow open storage/index handles; preserve registration identities and runtime generations | Add a separate textual registration in 4B. Current `IndexType`/`Index` contracts serve B+/hash scalar keys and must not masquerade as a text index. The environment never owns or closes permanent readers. `tests/query/test_binder.py`, `test_planner_select.py` |
| Handwritten lexer/parser, AST, binder and planner | Located errors, case-sensitive names, alias binding, hidden sort fields, immutable prepared plans | Add MATCH/USING/SCORE syntax and text specifications in 4B using the frozen contract. Current parser does not execute these cases. `tests/query/test_lexer.py`, `test_parser_contract.py`, `test_parser_extension.py`, `test_binder.py` |
| `ExternalSort`, operator lifecycle, `ExecutionContext`, `QueryResult` | Actual plans, bounded buffers, cancellation, streaming results and resource cleanup | Add text access operators; apply LIMIT after the resolved order. Use a top-k heap only for the approved score-descending route. `tests/operators/test_sorting.py`, `tests/query/test_limit.py`, `test_executor_results.py` |
| `MutationService`, `TransactionCompletion.prepare_write`, `SqlSession`, `TableRuntime` | Shared mutation/lock/undo lifecycle | In 4A, check the persistent seal before undo capture, plus maintenance/storage guards. Preserve rollback on other mutable tables. `tests/query/test_mutation_maintenance.py`, `tests/transactions/test_undo_completion.py`, `test_sql_integration.py` |
| `PageManager` physical latch pattern | Protect seek plus exact read as one physical operation | Text reader implements its own bounded offset reads in phase 2; each iterator owns its logical offset. Do not share an unprotected cursor across sessions. `tests/transactions/test_physical_concurrency.py` |
| `EngineService`, `/api/query`, existing four panels | Result/plan serialization, preview limits and sessions | Add textual examples and metadata in phases 4B/5. A preview limit is distinct from SQL LIMIT. `tests/api/`, later real-browser checks |

The first executable Part 3 module is `engine/text/tokenizer.py`; it depends
only on the standard library and shared domain errors. No existing runtime
API or binary format changes in this increment.

## 1A.2 — Documents and collections

### Identity, schema and original content

- One published collection identifies one table, its physical Heap, its ID
  column and one VARCHAR text column. The initial schemas are
  `documentos(id INTEGER, contenido VARCHAR(...))` and
  `articulos(id INTEGER, texto VARCHAR(...))`.
- A document ID is a built-in Python `int` representable by the existing
  signed 64-bit codec (`INTEGER_MIN` through `INTEGER_MAX`, inclusive).
  Boolean values and implicit string/numeric conversions are rejected.
  Negative IDs are representable; IDs need not be contiguous or arrive sorted.
- IDs are unique **within the collection**, including empty/tokenless documents.
  The builder must reject a duplicate anywhere in the input before publication;
  it must not overwrite a mapping or combine two documents silently. This
  collection check is pending phase 2. Heap and row codecs do not implement it.
- Preserve original corpus IDs when representable. Otherwise preparation must
  persist a bijective source-ID-to-internal-ID mapping, including source ID
  type/encoding, and translate qrels accordingly. Do not use Python's hash as
  a persisted identifier.
- The text is a Python string, including the empty string, with a strict UTF-8
  encoding. NULL, bytes, invalid UTF-8 encodings such as lone surrogates, and
  automatic conversion from other types are rejected at the storage boundary.
- Store the original text unchanged. Normalization only produces index/query
  tokens; it must not rewrite stored content or invalidate source hashes.

### Physical size and the ID/RID association

For this two-column schema, derive the available text bytes from the engine:

```text
encoded_row_bytes = INTEGER_STRUCT.size + VARCHAR_LENGTH_STRUCT.size
                    + len(original_text.encode("utf-8", errors="strict"))
maximum_text_bytes = MAX_RECORD_SIZE - INTEGER_STRUCT.size
                     - VARCHAR_LENGTH_STRUCT.size
```

The current format has a 4,096-byte page, a 12-byte page header and a 5-byte
slot. `MAX_RECORD_SIZE` is therefore 4,079 bytes. After the eight-byte ID and
four-byte VARCHAR prefix, text may occupy at most **4,067 UTF-8 bytes**.
These are derived current values, not hard-coded limits for future formats.
The page/slot overhead is already included in `MAX_RECORD_SIZE`; do not
subtract it twice. Recalculate if the schema gains columns.

Use a declared VARCHAR character bound of `maximum_text_bytes` for the initial
two-column table, alongside the mandatory complete-row byte validation.
Multi-byte characters can exceed physical capacity before reaching the
character limit. `validate_record(table_metadata, record)` validates declared
limits, codec representability and complete-row capacity; final Heap insertion
remains authoritative. Reject oversized documents without truncation or
automatic chunking, and record their rejection during corpus preparation.

Persist one `doc_id → RID(page_id, slot_id)` entry for **every** accepted
document, including tokenless ones. A RID is scoped to that exact Heap and
collection generation, not a globally unique logical ID. At publication,
verify unique IDs and RIDs, `len(mapping) == N`, and that each mapped record
contains the expected ID. Do not assume an ID is a zero-based array offset.
Reopening uses the same association; rebuilding creates a new collection
generation and a new mapping. Never reuse an old RID map against a new Heap.
Generation binding and mapping persistence belong to phases 2/4B.

### Statistics

All following definitions use tokens from the same tokenizer signature:

| Symbol | Exact definition |
|---|---|
| `N` | Number of accepted, uniquely identified documents, including empty strings and nonempty text with zero tokens |
| `tf(t,d)` | Number of occurrences of normalized term `t` in document `d`; positive integer for persisted postings, zero if absent |
| `len(d)` | Number of tokens in `d`, including repetitions; `sum_t tf(t,d)` |
| `V` | Union of terms appearing in accepted documents; empty documents add no terms |
| `df(t)` | Number of distinct accepted documents containing `t`, not its total occurrence count; `1 <= df(t) <= N` for indexed terms |
| `total_tokens` | `sum_d len(d)` |
| `avgdl` | `total_tokens / N` when `N > 0`, otherwise the explicit stored value `0.0` |
| TF-IDF document norm | Euclidean norm over **all** weighted terms in `d`, using the collection's final `N` and `df`; zero for a tokenless document |

The empty collection has `N = 0`, empty vocabulary/postings/map, zero total
tokens and `avgdl = 0.0`. A collection of only tokenless documents has `N > 0`
but the same empty vocabulary and zero lengths/norms. Both yield zero MATCH
results without evaluating an invalid division. Each experimental subset
computes its own statistics; do not reuse the 100k collection's `df` or norms
for its smaller subsets.

Assign dimensions by the final vocabulary's Unicode code-point order. The
mapping is stable for one published collection and shared by documents and
queries. A rebuild or different subset may assign different dimensions.

### Contract samples and evidence

These four rows establish storage and statistics expectations. They are a
small contract sample, not the full 1A.6 ranking/demo fixture:

| Input ID | Original text | Expected tokens | Length |
|---|---|---|---|
| 30 | `¡ÁRBOL, árbol! 2026` | `árbol, árbol, 2026` | 3 |
| 7 | `cafe\u0301 y café` (the first accent is decomposed) | `café, y, café` | 3 |
| 90 | Empty string | None | 0 |
| 12 | `... ¿?!` | None | 0 |

Expected `N = 4`, `total_tokens = 6`, `avgdl = 1.5`;
`df(árbol) = df(2026) = df(café) = df(y) = 1`.
`tests/text/test_document_contract.py` checks these values, original text/RID
preservation through Heap reopen, exact byte capacity, multi-byte overflow,
ID range and non-coercing field types. No production statistics calculator or
textual index is claimed by these tests.

## 1A.3 — Tokenizer contract v1

Public API: `engine.text.tokenize(text) -> tuple[str, ...]` and
`engine.text.tokenizer_signature() -> dict[str, str]`.

The exact pipeline is:

1. Require a string; reject non-string inputs with `InvalidTypeError`.
2. Apply Unicode **NFC** normalization.
3. Apply Python `str.lower()`, using its Unicode rules without locale settings.
4. Apply NFC again to normalize sequences produced by lowercasing.
5. Emit maximal nonempty runs of characters for which `str.isalnum()` is true.
   Every other character is a delimiter. Preserve token order and repetitions.

No stemming, stopword removal, accent folding, casefolding, NFKC compatibility
normalization, synonym expansion or numeric parsing occurs. Thus `á` and `a`
remain distinct, `Straße` becomes `straße`, full-width digits remain full-width,
and `3.14` becomes two tokens. Unicode numerals accepted by `isalnum`, such as
`²`, are tokens. Underscores, apostrophes, emoji, NUL and residual combining
marks delimit runs. For example, `İSTANBUL` lowercases to `i` plus a combining
dot followed by `stanbul`, giving `("i", "stanbul")`; this behavior is deliberate
and tested. Canonically composed/decomposed accents such as `café` and
`cafe\u0301` produce the same token.

The signature contains `algorithm = "nfc-lower-nfc-alnum-v1"` and the running
`unicodedata.unidata_version`. Each call returns a fresh JSON-compatible dict.
Persist the entire signature with a future index, not merely the algorithm
ID. Before using an index with query tokens, compare both fields; a mismatch
must produce a controlled incompatibility error and require reconstruction.
That persistence/open-time guard belongs to phase 2. Changing tokenization
rules requires a new algorithm version. The function is pure and performs no
file I/O; indexing, exhaustive evaluation and SQL must all call it.

`tests/text/test_tokenizer.py` freezes exact outputs for Spanish accents,
canonical equivalence, punctuation, Unicode letters/numerals, repetitions,
stopwords, whitespace/empty input and invalid types. Architecture checks keep
this first text module independent of storage, SQL, API and frontend.

## 1A.4 — Textual SQL contract

The complete accepted/rejected query matrix and diagnostic categories are in
[docs/text-sql-contract.md](../docs/text-sql-contract.md). This is a target for
phase 4B, not a claim that the current parser supports text search. Keep
[the existing SQL grammar](../docs/sql-grammar.md) as the implemented baseline.

## 1A.5 — Ranking mathematics

[The ranking contract](../docs/text-ranking-contract.md) confirms log-TF,
smoothed IDF and complete-vector cosine norms, and BM25 with k1=1.2/b=0.75.
It freezes query repetition, vocabulary projection, zero-norm/avgdl behavior
and exact score/ID ordering. Score assertions use relative tolerance 1e-10
and absolute tolerance 1e-12; IDs and result order must match exactly.

The four-document worked example records tf, df, lengths, N, avgdl, complete
weights/norms and scores for balanced/repeated queries. An exhaustive 60-digit
Decimal test reference supplies frozen snapshots; independently simplified
cosine expressions and rational BM25 coefficients anchor it. A second dense
float calculation checks every larger fixture query. Test helpers import no
production text ranker/index; no production ranker is introduced here.

## 1A.6 — Deterministic fixtures

The [fixture directory](../tests/text/fixtures/README.md) contains 16 original
Spanish documents and six `articulos` documents. IDs arrive shuffled; content
includes different lengths, repeated terms, identical-document score ties,
an empty string, tokenless punctuation and a decomposed accent preserved in
storage. The article collection supports the literal `machine learning`
assignment example. Both collections have unique IDs; duplicate-ID cases
are separate invalid inputs, including cross-block/tokenless duplicates.

Twenty query cases cover the assignment examples, 1/3/5+ token inputs,
repetitions, unknown terms, accents, empty queries, all admitted resolved
orders, LIMIT 0 and LIMIT above the match count. JSON files archive tokens,
statistics, norms, ordered IDs and 17-significant-digit scores. A versioned
manifest freezes parameters/tolerances and hashes the input/result files.
Test runs read these expected values and never regenerate them automatically.

`tests/text/test_fixtures.py` validates every original row with the real
logical/physical codec checks, inserts it into Heap, closes the writer, and
reopens in an isolated Python process. That process verifies exact text,
UTF-8 hashes, counts, physical arrival order and every original RID; the parent
then reopens again. Temporary RID snapshots are test evidence only, not the
future production text registry. Duplicate inputs are checked by the reference;
SPIMI block/publication rejection remains phase 2 work.

## 1A.7 — Validation and closure

### Historical validation of 1A.1–1A.4

Run with the repository's configured Python environment from the repository
root, with warnings treated as errors:

```text
python -m pytest -W error -p no:cacheprovider --basetemp tmp/part03_1a_regression_20261024_a tests/text tests/test_architecture.py tests/storage/test_record_codec.py tests/storage/test_value_codec.py tests/storage/test_heap_file.py tests/storage/test_heap_persistence.py tests/query/test_parser_contract.py tests/query/test_binder.py tests/api/test_database.py
```

Measured on 2026-10-24: **345 passed in 49.60 seconds**, Python 3.12.4,
Unicode 15.0.0, pytest 8.4.2 on Windows. This includes 43 new text tests and
architecture, codec, Heap, parser, binder and owner regression checks. The
initial default-temp run encountered Windows access errors in pre-existing
temporary/cache directories. The command above uses a fresh workspace
temporary directory and disables pytest's cache plugin; warning/error policies
and test assertions are unchanged. Use a fresh temporary destination for an
independent rerun. No existing cache or temporary directory was deleted.

That initial increment implemented shared tokenization and storage contract
checks. Its tokenizer/contract commits are `fdbb8ef` and `cfeb4ee`; the later
1A.5–1A.7 evidence below supersedes its previously pending block status.

### Final closure checklist

Final verification on 2026-10-24, Python 3.12.4 / Unicode 15.0.0 / pytest
8.4.2 on Windows: **390 passed in 37.06 seconds**, with warnings treated as
errors. This includes all **88 text tests** (45 added for 1A.5–1A.7), isolated
imports/architecture checks and the existing owner, binder, parser, codec and
Heap regressions. It is a focused regression, not a new full-project audit.

Ranking/fixture source and frozen results are recorded in commit `8e30e62`.
Thirty local documentation links, Python compilation, staged fixture hashes
and `git diff --check` also pass. The evidence documents were checked with
`scripts/sanitize_evidence.py`; no local account paths are published.

Reproducible command from the repository root (use a fresh temporary directory):

```text
python -m pytest -W error -p no:cacheprovider --basetemp tmp/part03_1a_final_regression_20261024_a tests/text tests/test_architecture.py tests/storage/test_record_codec.py tests/storage/test_value_codec.py tests/storage/test_heap_file.py tests/storage/test_heap_persistence.py tests/query/test_parser_contract.py tests/query/test_binder.py tests/api/test_database.py
```

| Criterion | Evidence |
|---|---|
| Integration boundaries match existing code | 1A.1 map and regression of owner, binder, parser, codec, Heap and architecture |
| Statistics and identity semantics are unambiguous | 1A.2 definitions, four contract samples and whole-fixture statistics |
| Tokenization is shared, versioned and deterministic | 32 exact/signature/type/canonical-equivalence tests |
| SQL scope and errors are frozen | 17 accepted and 26 rejection cases in the specification; execution remains 4B |
| Ranking variants and edge cases are fixed | 1A.5 derivations; Decimal, dense-float and analytic anchor checks |
| Fixtures and expected results are reproducible | Versioned JSON, SHA-256 manifest, fixed LF endings and 20 query cases |
| Original documents survive real persistence | 22 rows checked through fresh-process Heap reopening and UTF-8 hashes |
| Corpus acceptance is not claimed | 1B PENDING; no MS MARCO feasibility report or experimental measurement |

The only production text implementation in Block 1A is the shared tokenizer.
Reference rankings and frozen query results are functional test data, not
engine execution or an experimental comparison. Remaining work is 1B corpus
acceptance; phases 2/3 index and production ranking; 4A/4B seal/SQL integration;
5 UI/API demo; 6 experiments; and 7 Part 3 closure. Completing 1A does not
authorize those subsequent blocks or close Part 3.
