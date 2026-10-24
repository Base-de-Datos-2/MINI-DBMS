# Part 3 textual SQL contract — 1A.4

Frozen: 2026-10-24 for tasks 1A.1–1A.4. This document specifies the **future
phase 4B** extension to the handwritten parser/binder/planner. It does not
describe currently executable textual SQL. The current relational/spatial
baseline remains [sql-grammar.md](sql-grammar.md). Source requirements:
[REQUIREMENTS §16](../REQUIREMENTS.md) and
[Part 3 plan §§3.2–3.3](../PART_03/PLAN_PARTE_03.md).

## Syntax and binding

The following is the accepted textual subset. Parser diagnostics may also
recognize broader existing syntax in order to reject an unsupported combination
with a located error.

```ebnf
text_select = "SELECT", projection, "FROM", table_ref,
              "WHERE", match_condition, "USING", model,
              ["ORDER", "BY", text_order], ["LIMIT", nonnegative_integer] ;
match_condition = match | "(", match_condition, ")" ;
match = "MATCH", "(", column_ref, ",", string_literal, ")" ;
model = "TF_IDF" | "BM25" ;
score_expr = "SCORE", "(", ")" ;
```

Projection supports columns, `*`, qualified stars and `SCORE()`, including
`SELECT *, SCORE() AS relevancia`. Column and score expressions accept the
existing explicit/implicit aliases; a star cannot have an alias. A bare
`SCORE()` publishes a FLOAT column named `score`. All output names must be
unique after star expansion. Multiple projections of the same score are
allowed if they have distinct output names.

Resolve table/column/output aliases using existing case-sensitive identifier
rules and source locations. SQL keywords and model spellings are case
insensitive. MATCH/USING/SCORE/model names must preserve existing valid uses
as identifiers through contextual parsing; do not globally reserve names such
as an ordinary column named `score` merely to add this extension.

One complete statement, optional trailing semicolon and existing input/depth
limits apply. MATCH must be the complete WHERE condition (possibly wrapped in
parentheses), with one table and one registered VARCHAR field. The query is a
single-quoted string literal with doubled quotes for escaping. Parameters,
column-valued queries and arbitrary functions are outside this first contract.
USING is mandatory and must precede ORDER BY/LIMIT.

Recognize syntactically valid alternative model identifiers for a controlled
binding error; only TF_IDF and BM25 are executable. USING without MATCH and
SCORE outside a textual SELECT are semantic errors. There is no implicit
model or hidden MATCH expression.

Before execution, require a compatible published textual registration for
that table/field, with the tokenizer signature and collection association
validated. A missing/mismatched text index is a binding error even when
`use_indexes=False`: TextScan still needs the registered collection's global
statistics. A reader that becomes unavailable after preparation follows the
existing controlled stale-plan/runtime validation path; it must not silently
switch to an unrelated collection.

## Matching, projection and limits

Normalize the query with `engine.text.tokenize`. MATCH selects the union of
documents containing at least one query term (OR). Unknown terms contribute
no candidates; mixed known/unknown terms use the known vocabulary projection.
Empty, punctuation-only and wholly unknown queries return zero rows. Empty
and tokenless documents do not match. No error is raised just because the
query has no matches.

Scores use the formulas in the Part 3 plan. TF-IDF counts repeated query terms;
BM25 sums each distinct query term once. Exact worked scores/tolerances belong
to 1A.5. Output score values are finite FLOATs for matching documents.
Projection does not change candidate membership or corpus statistics.

Resolve ORDER BY aliases before selecting an access strategy. As in the
existing binder, an unqualified projected output name takes precedence over
a source name. An order key must then resolve to SCORE or the collection ID;
aliases of either are equivalent to their source. Qualified ID references
and an unprojected hidden ID are allowed. Resolving an alias to another
column does not make that column a supported textual order key.

| Resolved requested order | Effective total order | LIMIT strategy |
|---|---|---|
| None | score DESC, ID ASC | Top-k heap allowed |
| SCORE alias DESC | score DESC, ID ASC | Top-k heap allowed |
| SCORE alias DESC, ID ASC | score DESC, ID ASC | Top-k heap allowed |
| SCORE alias ASC or omitted direction | score ASC, ID ASC | All matches → ExternalSort → LIMIT |
| SCORE alias ASC, ID ASC | score ASC, ID ASC | All matches → ExternalSort → LIMIT |
| ID ASC or omitted direction | ID ASC | All matches → ExternalSort → LIMIT |
| ID DESC | ID DESC | All matches → ExternalSort → LIMIT |

Other order combinations and direct `ORDER BY SCORE()` are rejected in this
version. Without LIMIT, return every match in the effective total order;
without explicit ordering, that still means descending score then ascending
ID. With LIMIT k, return the first k rows in that order. LIMIT 0 returns an
empty result with the correct output schema; LIMIT larger than the match count
returns all matches. An HTTP preview may truncate presentation independently
and must report that fact.

## Accepted query matrix — future 4B acceptance

Assume published `documentos(id, contenido)` and `articulos(id, texto)` with
valid indexes/statistics. All examples are future acceptance cases, not
passing parser tests in this increment.

| ID | Query | Required behavior |
|---|---|---|
| A01 | `SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10;` | First literal assignment example; relevance-descending top 10 |
| A02 | `SELECT *, SCORE() as relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC;` | Second literal assignment example; all matches with score |
| A03 | `SELECT id, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY relevancia DESC, id ASC LIMIT 10;` | Explicit default total order |
| A04 | `SELECT id, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY relevancia LIMIT 1;` | ASC is implicit; lowest matching score, then ID |
| A05 | `SELECT id, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'base') USING TF_IDF ORDER BY relevancia ASC, id ASC LIMIT 1;` | Ascending-score order before limit |
| A06 | `SELECT contenido FROM documentos WHERE MATCH(contenido, 'base') USING TF_IDF ORDER BY id LIMIT 1;` | Lowest matching ID; ID stays hidden |
| A07 | `SELECT contenido FROM documentos WHERE MATCH(contenido, 'base') USING TF_IDF ORDER BY id DESC LIMIT 1;` | Highest matching ID |
| A08 | `SELECT id FROM documentos WHERE MATCH(contenido, '') USING BM25;` | No rows; normal ID schema |
| A09 | `SELECT id FROM documentos WHERE MATCH(contenido, '...') USING BM25 LIMIT 10;` | No rows |
| A10 | `SELECT id FROM documentos WHERE MATCH(contenido, 'unterminoausente') USING BM25;` | No rows if term is absent from the vocabulary |
| A11 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 0;` | Zero rows with correct schema |
| A12 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 1000;` | All matches if fewer than 1,000 |
| A13 | `SELECT d.id AS documento_id, SCORE() relevancia FROM documentos AS d WHERE (MATCH(d.contenido, 'BASE base ausente')) USING tf_idf ORDER BY relevancia DESC, documento_id ASC LIMIT 10;` | Qualified names, aliases, query repetitions and vocabulary projection |
| A14 | `SELECT SCORE() FROM documentos WHERE MATCH(contenido, 'base') USING BM25;` | Default FLOAT output name `score`; default ranking order |
| A15 | `EXPLAIN SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING TF_IDF LIMIT 10;` | Describe actual selected route/model without executing |
| A16 | `EXPLAIN ANALYZE SELECT id, SCORE() AS relevancia FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 10;` | Execute once, consume the plan and report actual measurements |
| A17 | `SELECT id FROM documentos WHERE MATCH(contenido, 'l''árbol') USING BM25;` | Decode SQL escape first, then tokenize query to `l`, `árbol` |

For the ordering counterexample, use three matches `(ID, score)`:
`(1, 0.2), (2, 0.9), (3, 0.5)`. LIMIT 1 yields ID 1 for A04/A05/A06,
ID 3 for A07, and ID 2 for score DESC. Test ties separately: equal scores
must use the lowest ID for either score direction. Repeat all applicable
cases using indexed access, TextScan and a fresh reopened collection.

## Rejected query matrix — future diagnostics

Use existing errors from `engine/query/errors.py`; retain their located source
information. These are the intended diagnostics after 4B implements the
extension. The current unextended parser may reject the same source earlier.

| ID | Query / condition | Expected category and reason |
|---|---|---|
| R01 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base');` | `SqlSyntaxError`: required USING/model missing |
| R02 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING otro_modelo;` | `SqlBindingError`: model is not TF_IDF/BM25 |
| R03 | `SELECT id FROM documentos WHERE MATCH(contenido, 123) USING BM25;` | `SqlSyntaxError`: query must be a string literal |
| R04 | `SELECT id FROM documentos WHERE MATCH(contenido) USING BM25;` | `SqlSyntaxError`: wrong argument structure |
| R05 | `SELECT id FROM documentos WHERE MATCH(id, 'base') USING BM25;` | `SqlBindingError`: MATCH field is not VARCHAR |
| R06 | `SELECT id FROM documentos WHERE MATCH(desconocido, 'base') USING BM25;` | `SqlUnknownColumnError`: unresolved field |
| R07 | `SELECT id FROM inexistente WHERE MATCH(contenido, 'base') USING BM25;` | `SqlUnknownTableError`: unresolved table |
| R08 | `SELECT SCORE() FROM documentos;` | `SqlBindingError`: no current MATCH |
| R09 | `SELECT id FROM documentos USING BM25;` | `SqlBindingError`: USING without MATCH |
| R10 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') AND id > 0 USING BM25;` | `SqlBindingError`: compound textual predicate outside scope |
| R11 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') OR MATCH(contenido, 'datos') USING BM25;` | `SqlBindingError`: multiple MATCH/compound predicate |
| R12 | `SELECT d.id FROM documentos d JOIN articulos a ON d.id = a.id WHERE MATCH(d.contenido, 'base') USING BM25;` | `SqlBindingError`: text JOIN outside scope |
| R13 | `SELECT COUNT(*) FROM documentos WHERE MATCH(contenido, 'base') USING BM25;` | `SqlBindingError`: textual aggregation outside scope |
| R14 | A textual SELECT combining MATCH with GROUP BY in a recognized clause position | `SqlBindingError`: textual grouping outside scope; malformed clause placement is still a syntax error |
| R15 | `SELECT SCORE() AS id, id FROM documentos WHERE MATCH(contenido, 'base') USING BM25;` | `SqlBindingError`: duplicate output name |
| R16 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY contenido;` | `SqlBindingError`: unsupported order field |
| R17 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY SCORE() DESC;` | `SqlBindingError`: use a projected SCORE alias |
| R18 | `SELECT id, SCORE() AS r FROM documentos WHERE MATCH(contenido, 'base') USING BM25 ORDER BY r DESC, id DESC;` | `SqlBindingError`: unsupported total order |
| R19 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT -1;` | `SqlSyntaxError`: nonnegative integer required |
| R20 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 1.5;` | `SqlSyntaxError`: integer required |
| R21 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 1 ORDER BY id;` | `SqlSyntaxError`: wrong clause order |
| R22 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25 LIMIT 1 OFFSET 1;` | `SqlUnsupportedError`: OFFSET remains outside SQL subset |
| R23 | Any otherwise valid textual query on a missing/incompatible textual registration | `SqlBindingError` before execution; no fabricated statistics or arbitrary index selection |
| R24 | `SELECT id FROM documentos WHERE MATCH(contenido, 'base') USING BM25; SELECT id FROM documentos;` | `SqlUnsupportedError`: multiple statements remain unsupported |
| R25 | Unterminated string in MATCH | `SqlLexicalError` under existing lexer rules |
| R26 | Input exceeding the existing SQL input/depth bounds | `SqlLimitError` under existing limits |

Also reject NOT around MATCH and combinations with spatial predicates as
`SqlBindingError`; reject malformed SCORE argument lists as `SqlSyntaxError`.
Do not introduce text support into INSERT/DELETE predicates in this delivery.
When a row mutation targets a sealed collection, 4A's write policy must reject
it before undo capture, regardless of whether the source contains text syntax.

Phase 4B must turn this matrix into executable parser/binder/engine acceptance
tests, including success, errors, alias collisions, ordering, index/scan
equivalence and no-mutation EXPLAIN. No skipped or expected-failure tests are
used to imply present support.
