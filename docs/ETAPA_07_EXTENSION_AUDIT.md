# Stage 7 CREATE/EXPLAIN extension closure audit

**Closure date:** 2026-09-20  
**Scope:** Tasks 7.31–7.40 of the separately authorized Stage 7 extension  
**Preserved baseline:** Tasks 7.1–7.30 remain closed under
`docs/ETAPA_07_AUDIT.md`  
**Checked-out revision:** `49b575470f612191cd1b8e7fe5fb8d6e89cbca02`
(`main`), plus the reviewed extension working-tree changes  
**Environment:** Windows, Python 3.12.4, pytest 8.4.2

## Result

Tasks 7.31–7.40 are implemented and verified. The extension adds:

- a handwritten, fully located CREATE/EXPLAIN syntax boundary with required
  `--` comment handling and complete-input validation;
- immutable VARCHAR-length and optional primary-key metadata;
- an engine-owned version-1 database manifest and clean-close discovery;
- synchronous compensated CREATE over existing Heap and unique unclustered B+
  implementations;
- shared VARCHAR, physical-row, index-key, and primary-key validation for SQL
  and managed programmatic inserts;
- non-executing EXPLAIN over the real SELECT plan specification;
- one-run EXPLAIN ANALYZE over the real Stage 6 operators and metrics;
- explicit statement and result variants for rows, mutations, definitions,
  and explanations.

The official academic requirements in `REQUIREMENTS.md` were reviewed and did
not change. CREATE/EXPLAIN remain team-selected additions to the limited SQL
dialect, not newly claimed assignment requirements.

## Exact Section 12.M acceptance

`tests/query/test_stage7_extension_acceptance.py` submits every required block
separately, preserving comments, commas, semicolons, accents, and
`'Pérez, Juan'` exactly.

| Phase | Verified outcome |
|---|---|
| A — empty | SQL CREATE produces the ordered four-column schema and primary index; queries 1–3 return successful empty four-column results; EXPLAIN has no runtime evidence; ANALYZE reports zero rows |
| B — populated | Three separate INSERT calls produce the prescribed fixture; query 1 returns id 3; query 2 returns id 1 then id 3; query 3 is empty; EXPLAIN remains non-executing; ANALYZE reports two rows |
| C — reopen | A fresh `Database.open(path)` reconstructs definitions and handles solely from the manifest; the same queries and explanations agree; index and forced-scan results match; duplicate-key rejection leaves base/index state unchanged |
| Constraints | Exactly 100 Unicode code points succeed, 101 fail before a write, DELETE permits primary-key reuse, and the reused key survives reopen |
| D — boundary | CREATE+SELECT, SELECT+SELECT, and INSERT+SELECT fail before effects; a final semicolon plus line comment succeeds; semicolon/comment text inside a string remains data |

The prepared and measured grade-query shapes contain Projection,
ExternalSort, Filter, and TableScan. No index on `id` is mislabeled as an
access path for the predicate on `nota`.

## Negative and failure evidence

| Boundary | Evidence |
|---|---|
| Malformed suffixes, nested/unsupported EXPLAIN children, unsupported DDL, comments, spans | `tests/query/test_parser_extension.py`, `tests/query/test_stage7_extension_acceptance.py` |
| Duplicate definitions, invalid lengths/types, manifest corruption, missing/incomplete files, metadata/header mismatch | `tests/database/test_managed_database.py`, `tests/database/test_manifest_validation.py` |
| Heap/index/registry/manifest CREATE failures and later recovery | `tests/database/test_managed_database.py` |
| Duplicate primary keys, Unicode boundaries, DELETE/reinsert, scan/index agreement, reopen | `tests/database/test_managed_database.py`, `tests/query/test_stage7_extension_acceptance.py`, `tests/query/test_mutation_maintenance.py` |
| EXPLAIN non-execution and failed ANALYZE partial report/cleanup | `tests/query/test_explain.py` |
| Temporary-write failure, forced external paths, cleanup, fresh managers | `tests/query/test_stage7_resources.py` |
| Previous SQL families and optimized/baseline agreement | `tests/query/test_stage7_acceptance.py` and the complete regression suite |

All full-input syntax errors occur before binding or execution. Predictable
definition/value failures occur before the first write. Ordinary later failures
retain the existing compensated or explicit incomplete-state contracts; this
does not claim transaction rollback or crash-atomic multi-file DDL.

## Reproducible verification

Exact scenario alone:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/query/test_stage7_extension_acceptance.py -q -W error
```

Result: **8 passed in 1.25 seconds**.

Restart and injected-failure gate:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/query/test_stage7_extension_acceptance.py `
  tests/database/test_managed_database.py `
  tests/database/test_manifest_validation.py `
  tests/query/test_explain.py `
  tests/query/test_mutation_maintenance.py `
  tests/query/test_stage7_resources.py `
  -q -W error
```

Result: **54 passed in 54.55 seconds**.

SQL/database/API compatibility gate:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests/query tests/database tests/api `
  -q -W error -p no:cacheprovider
```

Result: **436 passed in 239.74 seconds**.

Complete repository gate:

```powershell
.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider
```

Result: **2,742 passed in 1,283.57 seconds (21:23)**.

Additional checks:

```powershell
.venv\Scripts\python.exe -m compileall -q engine api tests
.venv\Scripts\python.exe -m pip check
git diff --check
```

Result: compilation succeeded, dependency validation reported no broken
requirements, and the diff has no whitespace errors. Git emitted only the
repository's existing LF-to-CRLF checkout warnings.

## Documentation reconciliation

Current capability and status were reconciled in:

- `ETAPA_07.md`;
- `PROJECT_CONTEXT.md`;
- `PLAN.md`;
- `AGENTS.md`;
- `README.md`;
- `docs/sql.md` and `docs/sql-grammar.md`;
- the incremental Task 7.31–7.38 evidence notes;
- `docs/demo.md` and the historical Stage 9 progress note.

The original Stage 7 audit and earlier stage documents remain historical
records. `REQUIREMENTS.md` and ETAPA_01–ETAPA_06 were intentionally unchanged.

## Handoff and declared limits

The Stage 7 extension is closed. Stage 8 transactions, locking, concurrency,
WAL, and crash recovery remain unimplemented and are the next roadmap work.

The Stage 9 emergency demo still uses its explicit legacy database owner and
allowlists: read-only mode permits SELECT, and optional write mode additionally
permits INSERT/DELETE. It does not yet expose manifest CREATE or serialize
definition/explanation results. A later Stage 9 integration must move to the
manifest owner and add exhaustive handling for `DEFINITION` and `EXPLANATION`;
the extension closure makes no claim that the existing editor already supports
those variants.
