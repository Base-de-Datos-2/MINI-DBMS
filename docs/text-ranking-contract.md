# Text ranking mathematics and worked examples — 1A.5

Frozen on 2026-10-24. This contract confirms the variants selected in
[the Part 3 plan](../PART_03/PLAN_PARTE_03.md), §§4.2–4.3. It defines expected
behavior for the phase 3 production rankers. Since 2026-10-28 the standalone
rankers are implemented in `engine/text/ranking.py`; evidence and limits are
in [Block 3](../PART_03/BLOQUE_3.md). The calculations in this contract remain
independent, exhaustive **test references**. Statistics/tokenization are defined in
[Block 1A](../PART_03/BLOQUE_1A.md).

## 1. Exact formulas

Use natural logarithms throughout. `N` includes empty/tokenless documents;
`df(t)` counts documents containing the term, and document length counts all
normalized tokens with repetitions. Statistics belong to one collection.

```text
log_tf(tf) = 1 + ln(tf) if tf > 0, otherwise 0
idf(t) = 1 + ln((N + 1) / (df(t) + 1))
w(t,d) = log_tf(tf(t,d)) × idf(t)
w(t,q) = log_tf(tf(t,q)) × idf(t)
norm(d) = sqrt(sum over ALL document terms of w(t,d)^2)
norm(q) = sqrt(sum over known query terms of w(t,q)^2)
TF_IDF(d,q) = dot(w(d), w(q)) / (norm(d) × norm(q))

k1 = 1.2
b = 0.75
idf_BM25(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
BM25(d,q) = sum over DISTINCT known query terms of:
            idf_BM25(t) × tf(t,d) × (k1 + 1)
            / (tf(t,d) + k1 × (1 - b + b × len(d)/avgdl))
```

Project the query to the collection vocabulary **before** computing its
weights and norm. Unknown terms neither generate candidates nor enlarge the
query norm. Repetitions affect TF-IDF query weights. BM25 ignores repetitions
of the same query term; it has no query-frequency factor and no parameter
search. Both models rank the OR union of matching documents.

Zero query norm means no matches. Tokenless documents have zero norm and
never match. For an empty collection, or a collection containing only tokenless
documents, return no matches before any division by N, norm or avgdl. Do not
add a small epsilon to a denominator or generate zero-score result rows for
documents without a matching term.

## 2. Worked collection

The independent small example in
[worked_example.v1.json](../tests/text/fixtures/worked_example.v1.json) contains:

| ID | Text | tf(base) | tf(datos) | tf(índice) | Length |
|---|---|---|---|---|---|
| 30 | base base datos | 2 | 1 | 0 | 3 |
| 7 | base | 1 | 0 | 0 | 1 |
| 11 | datos índice | 0 | 1 | 1 | 2 |
| 90 | Empty | 0 | 0 | 0 | 0 |

Thus `N = 4`, `total_tokens = 6`, `avgdl = 6/4 = 1.5`;
`df(base) = df(datos) = 2`, `df(índice) = 1`.

Define these three intermediate values:

```text
a = 1 + ln(5/3) = 1.5108256237659907
z = 1 + ln(5/2) = 1.9162907318741551
r = 1 + ln(2)   = 1.6931471805599453
```

The complete document vectors, in dimensions `(base, datos, índice)`, are
`D30 = (r×a, a, 0)`, `D7 = (a, 0, 0)`, `D11 = (0, a, z)`, and `D90 = (0,0,0)`.
Their norms are:

| ID | Norm expression | Approximate norm |
|---|---|---|
| 30 | `a × sqrt(r² + 1)` | 2.9708945808915602 |
| 7 | `a` | 1.5108256237659907 |
| 11 | `sqrt(a² + z²)` | 2.4402385609801923 |
| 90 | 0 | 0 |

### TF-IDF/cosine: query `base datos`

The query vector is `(a, a, 0)`, with norm
`a×sqrt(2) = 2.1366300875106554`.

| ID | Reduced score expression | Score |
|---|---|---|
| 30 | `(r+1) / sqrt(2×(r²+1))` | 0.96843882194433620 |
| 7 | `1/sqrt(2)` | 0.70710678118654752 |
| 11 | `a / sqrt(2×(a²+z²))` | 0.43779123108611478 |

Expected ranking: **30, 7, 11**. ID 90 is absent. The `índice` weight remains
inside D11's norm despite not appearing in the query; using only query-term
components for that norm would give the wrong result.

### Repeated query `base base datos`

The query vector becomes `(r×a, a, 0)`, identical to D30's vector, with norm
`2.9708945808915602`:

| ID | Reduced cosine expression | Score |
|---|---|---|
| 30 | 1 | 1.0000000000000000 |
| 7 | `r/sqrt(r²+1)` | 0.86103699594397641 |
| 11 | `a / (sqrt(a²+z²)×sqrt(r²+1))` | 0.31485395759354463 |

The ranking remains **30, 7, 11**, but its scores change. The larger Spanish
fixture also demonstrates an actual ranking change from query repetition.

### BM25: either query above

Both queried terms have `idf_BM25 = ln(2)`. Substituting lengths and fixed
parameters reduces the calculations to the following rational multipliers:

| ID | Length-normalization denominator(s) | Reduced score | Score |
|---|---|---|---|
| 30 | base: `2+2.1=4.1`; datos: `1+2.1=3.1` | `ln(2)×(44/41 + 22/31)` | 1.2357761692752447 |
| 7 | base: `1+0.9=1.9` | `ln(2)×22/19` | 0.80259147222730510 |
| 11 | datos: `1+1.5=2.5` | `ln(2)×22/25` | 0.60996951889275187 |

Expected ranking: **30, 7, 11** for both `base datos` and `base base datos`.
The repeated query term adds no second contribution. Appending an unknown
term to the balanced query preserves every score in both models.

## 3. Numerical assertions and deterministic order

Production scores use float64-compatible arithmetic. Freeze assertion
tolerances to **relative `1e-10` and absolute `1e-12`**:

```text
abs(actual - expected) <= max(1e-12, 1e-10 × abs(expected))
```

Use these values explicitly in pytest assertions; do not rely on pytest's
default tolerances. Reject NaN/infinite scores. Integer frequencies, document
IDs, candidate membership and returned ordering require **exact** assertions.
Do not use score tolerance to group results into ties or to excuse a wrong
top-k. Sort using unrounded scores; round only for presentation or archived
reference decimals. Exact score ties use ID ascending for both score ASC and
score DESC. Accumulate terms in stable vocabulary order for deterministic
repeated executions. No random/arrival-order tie breaking is allowed.

The two identical documents with IDs 3 and 45 in the Spanish fixture must
always return 3 before 45 on a score tie; `articulos` similarly uses 4 and 14.
LIMIT applies after the resolved total order in
[the textual SQL contract](text-sql-contract.md). Those cases are evaluated
as reference inputs; production top-k/ExternalSort tests are now in Block 3,
while SQL acceptance belongs to 4B.

## 4. Independence and reproducibility

[tests/text/reference.py](../tests/text/reference.py) computes exhaustive scores
with 60-digit Decimal `ln`/`sqrt` from manually frozen token sequences. It
imports no tokenizer, engine ranker or index. Frozen statistics, norms and
scores are archived to 17 significant decimal digits in
[expected.v1.json](../tests/text/fixtures/expected.v1.json).

These archives are cross-checked by a second implementation using dense float
vectors and scalar BM25 sums. The small example is additionally checked
against the closed-form cosine expressions and simplified rational BM25
coefficients above. This anchors the calculations independently of the
generic reference loops. Tokenization is checked separately against every
manually specified document/query token list. Thus archived values are
reference calculations, not fabricated experimental measurements.

The explicit maintenance command `python -m tests.text.freeze_expected`
regenerates snapshots/manifests after intentional fixture edits. It is never
run by tests and must not be used just to make a failing ranker pass. Review
input changes, analytic anchors, reference results and expected rankings
together; change the fixture version for a changed frozen contract. The
manifest hashes provide provenance only; the independent checks provide
numerical validation. LF line endings are fixed for fixture JSON so hashes
survive Git checkout on Windows and Unix.
