# Stage 7 review — Tasks 7.5-7.7

**Date:** 2026-09-17  
**Scope:** Block 3 of the revised `ETAPA_07.md`  
**Technique:** bounded handwritten recursive descent

## Result

Tasks 7.5-7.7 are implemented and verified against the grammar and policies
frozen in `docs/sql-grammar.md`. The parser constructs syntax only: it performs
no Catalog lookup, planning, operator creation, or storage/index mutation.
Stage 7 remains open because Tasks 7.8-7.30 are not implemented.

## Critical findings and corrections

| Finding | Consequence | Correction |
|---|---|---|
| PLUS/MINUS tokens were never consumed by the parser | The adopted signed-number syntax always failed | Added one optional sign to integer/decimal literal parsing; signs cannot prefix strings, booleans, references, or another sign |
| Nested NOT/parentheses had no explicit bound | Pathological input exposed raw `RecursionError` | Enforced the frozen 128-level Boolean nesting limit with `SqlLimitError`; repeated AND/OR use loops |
| INSERT reused `value_expr` | Column references such as `VALUES (other_column)` were incorrectly accepted without a row scope | Added shared literal parsing and restricted INSERT values to numeric, string, and Boolean literals |
| Aggregate arguments reused general value parsing | `COUNT(1)` was accepted, and `SUM(*)` was accepted as if it were valid | Restricted ordinary aggregate arguments to column references and reserved `*` exclusively for `COUNT(*)` |
| Unsupported functions were parsed as column names followed by unexplained trailing punctuation | Diagnostics hid the real subset boundary | Calls outside COUNT/SUM/AVG/MIN/MAX now raise `SqlUnsupportedError` |
| Unsupported reserved words were ordinary identifiers | `LEFT JOIN` could be accepted as an inner JOIN with `LEFT` silently used as the table alias; `DISTINCT` could also be misinterpreted | Tokenize recognized SQL reserved words and classify reliable unsupported forms explicitly |
| Parser errors carried only a starting offset | Callers could not show consistent line/column, expected input, or source context | Added the shared `SqlQueryError` hierarchy with spans, line/column, offending lexeme/EOF, expected category, and bounded excerpts |
| List parsing was duplicated and had no explicit progress guard | Comma-list regressions could diverge or stall | Added a shared non-empty comma-list routine that verifies token progress |
| Direct token indexing encoded the EOF assumption | Future grammar changes could create index errors | Added safe lookahead that remains on the single EOF token |

## Implemented parser contract

- exactly one SELECT, INSERT, or DELETE statement;
- at most one final semicolon and mandatory EOF;
- fresh parser state for every call, including after a failed parse;
- explicit precedence: comparison, NOT, AND, OR;
- parentheses and repeated NOT within the 128-level limit;
- unqualified and qualified references without Catalog access;
- SELECT star, qualified star, approved aggregate calls, explicit/implicit
  aliases, one inner JOIN, WHERE, GROUP BY, and ORDER BY;
- one-row INSERT with an optional column list and literal-only values;
- filtered DELETE and the Task 7.2 adopted whole-table DELETE form;
- eager lexical failure anywhere in the submission;
- explicit rejection of chained comparisons, subqueries, unsupported join
  families, DISTINCT, NULL predicates/literals, transactions, DDL, UPDATE,
  INSERT SELECT, multi-row VALUES, and RETURNING.

The recognized reserved-word policy means names such as `LEFT`, `DISTINCT`,
`NULL`, `RETURNING`, and transaction/DDL verbs cannot be used as unquoted
identifiers. Quoted identifiers are outside the adopted grammar.

## Diagnostic hierarchy

```text
ValidationError
└── SqlQueryError
    └── SqlSyntaxError
        ├── SqlLexicalError
        ├── SqlUnsupportedError
        └── SqlLimitError
```

`SqlLexicalError` remains a `SqlSyntaxError` subtype for compatibility with the
original public lexer tests. The more specific subtype lets API work in later
tasks distinguish lexical, malformed, unsupported, and limit failures without
parsing exception strings.

## Verification evidence

```text
.venv/Scripts/python.exe -m pytest tests/query/test_ast.py tests/query/test_lexer.py tests/query/test_parser.py tests/query/test_parser_contract.py -q -W error -p no:cacheprovider
104 passed in 0.30s

.venv/Scripts/python.exe -m pytest tests/test_architecture.py -q -W error -p no:cacheprovider
19 passed in 7.54s

.venv/Scripts/python.exe -m pytest --ignore=tests/query/test_executor_writes.py --ignore=tests/query/test_index_pushdown.py --ignore=tests/query/test_planner_select.py -q -W error -p no:cacheprovider
2399 passed in 539.19s
```

The 2,399-test run consists of the 2,295 strict Stage 1-6 baseline plus 104
implemented Stage 7 AST/lexer/parser tests. No tests were skipped in that run.

At the time of this Block 3 review, running `tests/query` without exclusions
stopped at three collection errors:

- missing `engine.maintenance` for `test_executor_writes.py`;
- missing `engine.query.environment` for `test_index_pushdown.py`;
- missing `engine.query.environment` for `test_planner_select.py`.

Block 4 has since implemented `engine.query.environment`. The current three
future-boundary imports are `engine.query.planner`, `engine.query.executor`, and
`engine.maintenance`, as recorded in `docs/ETAPA_07_REVIEW_7_8_7_12.md`. No
placeholder implementations were added to conceal their absence.

## Handoff to the next block

Tasks 7.8-7.12 can now consume a stable syntax model. They must resolve exact
Catalog names, aliases, ambiguity, types, aggregate signatures, grouping
validity, and mutation schemas without changing parser precedence or accepting
new grammar implicitly. Target `DataType` range checks for signed numeric
literals belong to that semantic layer.
