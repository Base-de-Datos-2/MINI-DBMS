# Stage 7 Task 7.32 — AST, lexer, parser, spans, and diagnostics

**Implemented:** 2026-09-19  
**Starting commit:** `b0e7533` (`Tarea 7.31 completada`)  
**Scope:** syntax and public pre-execution boundary only; Tasks 7.33–7.38 still
own CREATE semantics and CREATE/EXPLAIN execution.

> **Subsequent status (2026-09-20):** Tasks 7.33–7.40 implemented and closed
> CREATE/EXPLAIN execution and acceptance. Statements below about unsupported
> execution describe the Task 7.32 checkpoint; current evidence is in
> `ETAPA_07_EXTENSION_AUDIT.md`.

## Outcome

The handwritten SQL front end now parses the adopted limited `CREATE TABLE`,
`EXPLAIN SELECT`, and `EXPLAIN ANALYZE SELECT` forms. It retains the existing
one-statement contract, creates immutable parser-independent ASTs, and assigns
non-empty source spans to every new syntax node. Parsing remains free of
Catalog, storage, index, planner, and mutation side effects.

The six exact `alumnos` submissions in `ETAPA_07.md` all parse as one complete
statement. This task does not claim that CREATE or EXPLAIN can execute yet.
`SqlEngine.prepare()` and string `SqlEngine.execute()` reject those newly parsed
families with a located `SqlUnsupportedError` until their later extension tasks
provide the semantic and execution routes.

## Implementation map

| Area | Implemented behavior |
|---|---|
| AST | Added immutable `TypeSpecification`, `ColumnDefinition`, `CreateTableStatement`, and SELECT-only `ExplainStatement` nodes |
| Lexer | Recognizes `ANALYZE`, `INT`, `INTEGER`, `KEY`, `PRIMARY`, and `VARCHAR`; existing `CREATE`, `TABLE`, and `EXPLAIN` tokens are reused |
| CREATE parser | Accepts a non-empty ordered column list, `INT`/`INTEGER`, `VARCHAR(positive integer)`, and optional inline `PRIMARY KEY` |
| EXPLAIN parser | Reuses the existing SELECT parser, records the analyze flag, rejects nesting and non-SELECT children, and leaves final-semicolon ownership to the public statement boundary |
| Submission boundary | Requires complete EOF after one optional final semicolon and rejects a second CREATE, EXPLAIN, or baseline statement |
| Comments and locations | Supports `--` comments through LF, CRLF, CR, or EOF and reports correct line, column, span, and single-line context for every newline form |
| Engine boundary | Rejects parsed but not yet executable extensions before binder/planner dispatch, avoiding internal type errors and all side effects |

## Critical compatibility and diagnostic corrections

Adding type grammar words to the keyword set could have invalidated existing
legal identifiers, including the established join test column `key`. The new
words therefore remain contextual identifiers outside grammar positions. Their
original source spelling is preserved for exact, case-sensitive Catalog
resolution. Keyword recognition itself remains case-insensitive and whole-word,
so names such as `integer_value` and `primary_key` are not split.

The previous source map counted only LF as a newline, and the diagnostic
excerpt helper also searched only for LF. The lexer and error context now agree
on LF, CRLF, and CR. A CRLF pair advances the logical line once. Comment markers
inside a string remain string data, doubled quotes remain decoded by the
existing lexer, and an EOF comment produces only the final EOF token.

Malformed supported syntax produces a located `SqlSyntaxError`. Recognized
syntax outside the adopted subset, such as `CREATE INDEX`, unsupported CREATE
types, table-level primary keys, nested EXPLAIN, and EXPLAIN over writes or DDL,
produces a located `SqlUnsupportedError`. Block comments remain a controlled
lexical error. Empty and comment-only submissions retain the established
empty-input diagnostic.

## Scope boundary retained

Task 7.32 validates the grammatical shape of `VARCHAR(n)` and requires a
positive integer. The frozen maximum of 4,075 code points, duplicate names,
multiple primary keys, declared constraints, and type mapping into Catalog
metadata belong to Task 7.33. Physical creation, durable registration, results,
and EXPLAIN execution remain in Tasks 7.34–7.38. No statement kind or public
result kind was added prematurely.

## Verification

All commands ran from the repository root with warnings treated as errors and
without pytest cache writes.

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\query\test_parser_extension.py `
  tests\query\test_lexer.py `
  tests\query\test_ast.py `
  tests\query\test_parser.py `
  tests\query\test_parser_contract.py `
  tests\api\test_engine_service.py `
  -q -W error -p no:cacheprovider
# 181 passed in 17.98s

.venv\Scripts\python.exe -m pytest tests\query `
  -q -W error -p no:cacheprovider
# 300 passed in 179.11s

.venv\Scripts\python.exe -m pytest tests\api tests\test_architecture.py `
  -q -W error -p no:cacheprovider
# 116 passed in 63.91s
```

The gates overlap and are reported separately rather than summed. The
historical 2,556-test Stage 7 closure belongs to the 2026-09-18 audit and is not
presented as a current full-suite result.
