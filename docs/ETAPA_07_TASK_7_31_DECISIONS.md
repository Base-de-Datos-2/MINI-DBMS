# Stage 7 Task 7.31 — extension contract and inspected baseline

**Decision date:** 2026-09-19  
**Inspected commit:** `87f442a` (`DOCS: Nueva versión de ETAPA_07.md`)  
**Scope:** design and coordination only; Tasks 7.32–7.40 remain unimplemented

> **Subsequent status:** Task 7.32 implemented the syntax boundary later on
> 2026-09-19. This note preserves the decisions and baseline as inspected; see
> `docs/ETAPA_07_TASK_7_32.md` for the implementation evidence.

## Authority and status

Tasks 7.1–7.30 remain the closed, verified Stage 7 baseline recorded in
`docs/ETAPA_07_AUDIT.md`. Tasks 7.31–7.40 are a team-approved extension for
limited `CREATE TABLE`, persistent database registration, constraints,
`EXPLAIN SELECT`, and `EXPLAIN ANALYZE SELECT`. These additions are not
requirements from `REQUIREMENTS.md`.

The implementation at the inspected commit still accepts only the original
`SELECT`, `INSERT`, and `DELETE` statement families. `CREATE` and `EXPLAIN` are
recognized as unsupported keywords; no extension feature is described here as
implemented.

## Frozen ownership boundary

The persistent database owner belongs below the API and above the in-memory
Catalog/runtime registries. A new engine-level database package will own:

- the configured database directory;
- the versioned database manifest;
- the in-memory `Catalog` and `QueryEnvironment`;
- every permanent storage and index handle;
- database open/close and DDL creation orchestration;
- the `SqlEngine` configured with a narrow DDL service.

`Catalog` remains an in-memory, immutable-metadata registry. It does not open,
close, create, or delete files. `QueryEnvironment` continues to pair Catalog
metadata with borrowed live objects and does not become a persistence layer.
The query package will depend only on a narrow DDL protocol injected into
`SqlEngine`; it must not import `api` or own the database directory.

The existing `api.database.Database` currently owns these resources for the
demo. Tasks 7.34 and the later Stage 9 integration will move or delegate that
ownership to the engine-level database owner rather than creating a second
competing owner. The API remains an adapter over the engine.

## Persistent database manifest

Manifest-backed databases use one canonical UTF-8 JSON file named
`database.catalog.json` under the configured database root. The first format
is identified by:

```text
magic   = MINIDB_CATALOG
version = 1
```

The manifest stores the database identity and an ordered table list. Each
table entry stores:

- its exact logical name and opaque table identity;
- `HEAP` as the organization for SQL-created tables;
- the relative storage-file identity;
- ordered column names and physical `DataType` values;
- optional declared `VARCHAR` character limits;
- the optional single-column primary key;
- every index's logical name, opaque identity, table/column reference, type,
  uniqueness, clustering flag, relative file identity, and ready state.

Only exact documented fields are accepted. Duplicate JSON keys, unknown
versions, unknown fields, absolute paths, parent traversal, separators inside
file identities, duplicate logical/physical identities, and references that
escape the configured root are rejected before handles are exposed. The
manifest is the discovery source of truth; per-file headers remain the source
of truth for each physical structure and are cross-checked on open.

The generic page/file format and `OrganizationMetadata` v1 remain unchanged.
Declared lengths and primary-key constraints are logical table metadata, not a
record-layout change. They will live in backward-compatible immutable
`TableMetadata` extensions and the manifest. Existing `Column(name,
data_type)`, `Schema`, record codecs, organization schema pairs, and physical
index schema signatures therefore retain their current meaning.

Manifest replacement uses a same-directory uniquely named temporary file,
flush plus `fsync`, and `os.replace`. No code edits the committed manifest in
place. Directory `fsync` may be used where the platform supports it, but this
stage does not claim crash-atomic multi-file DDL.

## Managed file identities and names

SQL identifiers are logical names only and are never concatenated into file
paths. Each created table/index receives an opaque UUID4 identity encoded as
32 lowercase hexadecimal characters. Managed filenames are:

```text
t_<32 hex>.heap
i_<32 hex>.bpt
```

This avoids Windows reserved names, case-folding collisions, separators, and
Unicode filesystem normalization differences. Paths are resolved under the
database root and containment is checked before use. Existing files are never
replaced; an identity collision is retried before any Catalog publication.

Catalog identifiers remain exact and case-sensitive because that is the
existing Stage 1–7 policy. SQL keywords remain case-insensitive. Consequently,
`Alumnos` and `alumnos` are different logical names even on a case-insensitive
filesystem; opaque file identities keep their files distinct.

The automatically created primary-key index has logical name
`__pk__<exact-table-name>`. The `__pk__` prefix is reserved for engine-created
indexes. A conflicting existing index is a predictable CREATE error checked
before physical mutation; no numeric or registration-order suffix is invented.

## CREATE physical route and publication boundary

SQL-created tables use an existing `HeapFile`. An optional primary key uses an
existing unique, unclustered B+ index. A primary key does not imply clustered
storage or output ordering.

CREATE follows this ordinary-failure sequence:

1. Parse, bind, and prepare the whole submission without side effects.
2. Revalidate table/index-name availability and the current manifest at
   execution time.
3. Allocate opaque identities and create the base file and optional index
   without registering them in the live environment.
4. Flush and validate the new structures.
5. Publish table metadata, index metadata, and runtime handles through
   all-or-nothing Catalog/environment bundle operations.
6. Atomically replace the manifest.
7. Return success only after the manifest replacement and resource flushes
   complete.

Predictable validation happens before step 3. An ordinary failure before
manifest replacement removes only files allocated by that CREATE. A manifest
failure rolls back the newly published live bundle, closes its handles, and
removes its files. Existing tables, files, and the previous manifest are never
replaced. If unexpected cleanup cannot restore a trustworthy live state, the
database owner becomes unavailable until reopen rather than advertising a
partial table.

This is deterministic compensation for ordinary exceptions. It is not WAL,
transaction rollback, concurrent DDL, or crash-atomic commit across the
manifest, table, and index files; those guarantees remain outside Stage 7.

## Type and constraint contract

SQL `CREATE TABLE` accepts exactly `INT`, `INTEGER`, and `VARCHAR(n)`.
`INT` and `INTEGER` both map to the existing signed 64-bit
`DataType.INTEGER`. Programmatically declared legacy schemas may continue to
use `FLOAT`, `BOOLEAN`, and unrestricted `VARCHAR`; this does not add those
spellings to CREATE grammar.

The shared constant for a declared `VARCHAR` is:

```text
MAX_DECLARED_VARCHAR_CODEPOINTS = MAX_RECORD_SIZE - VARCHAR_LENGTH_STRUCT.size
                                = 4079 - 4
                                = 4075
```

Thus `VARCHAR(n)` requires `1 <= n <= 4075`. The limit counts Python Unicode
code points in the decoded value. Values are not normalized, case-folded, or
silently truncated. Strict UTF-8 encoding and the complete record's 4,079-byte
physical limit remain independent checks, so a value within its character
limit can still be too large in bytes or in combination with other columns.

An inline primary key may use either accepted logical type. The existing B+
codec imposes its additional 255-byte UTF-8 limit on a `VARCHAR` primary-key
value. This limit is validated before the base write. Integers retain the
existing signed 64-bit range. The no-NULL, no-default, full-row INSERT policy
remains in force.

Constraint validation will consume immutable table metadata through one
shared validator used by SQL writes and the engine-level database write path.
Raw storage methods remain low-level primitives and do not claim universal SQL
constraint enforcement.

## Legacy compatibility

There are two explicit open modes:

1. A manifest-backed database opens from `database.catalog.json` without a
   caller-supplied schema and supports SQL DDL.
2. A legacy database continues to open from its existing
   `DatabaseDefinition`, with the same filenames and physical formats used by
   the Stage 9 demo.

No manifest is inferred from filenames or partial headers, and no legacy
directory is migrated silently. Legacy mode remains queryable and writable
through its existing APIs but rejects SQL CREATE with a controlled
DDL-registry-unavailable error. A future explicit import operation may write a
manifest only after cross-checking every supplied table, index, and file; that
operation is not required by Tasks 7.31–7.40.

## Public engine result contract

The extension adds explicit statement identities for `CREATE`, `EXPLAIN`, and
`EXPLAIN_ANALYZE`; consumers must not infer them from SQL text. Existing
`SELECT`, `INSERT`, and `DELETE` identities remain stable.

- SELECT continues to return a streaming row result.
- INSERT and DELETE continue to return completed mutation command results.
- CREATE returns a completed definition result containing the created table
  identity and no invented affected-row count.
- EXPLAIN returns a structured explanation with `executed=false`,
  `complete=true`, a prepared plan, no runtime tree, and no fabricated
  measurements.
- EXPLAIN ANALYZE returns a structured explanation with `executed=true` and
  `complete=true` only after one execution reaches EOF and cleanup succeeds.
  It reports final output cardinality and actual available metrics but does
  not retain ordinary result rows.

The result-kind model therefore distinguishes rows, mutation commands,
definitions, and explanations. Explanation payloads keep prepared facts and
runtime measurements separate. All non-streaming results release operation
resources before return. The existing one-active-stream rule remains.

## Stage 9 API safety contract

Stage 9 must use explicit allowlists and exhaustive result dispatch. It must
never use `frozenset(StatementKind)`, because adding an enum member would grant
it permission automatically.

```text
read-only mode:
    SELECT, EXPLAIN, EXPLAIN_ANALYZE

serialized-writes mode:
    SELECT, INSERT, DELETE, CREATE, EXPLAIN, EXPLAIN_ANALYZE
```

EXPLAIN ANALYZE is read-only because its child is restricted to SELECT. CREATE
requires write-enabled mode. Unknown future statement/result kinds fail closed.
The API will dispatch SELECT, mutation commands, definitions, and explanations
through separate explicit branches. Dynamic table listings will read the
engine-owned Catalog rather than an immutable Python `DatabaseDefinition`.

Tasks 7.31–7.40 define the engine contract; HTTP serialization and frontend
rendering remain a separately reviewed Stage 9 integration. Until that work is
implemented, the API continues to reject CREATE/EXPLAIN under its current
baseline behavior.

## Newline/comment compatibility finding

The verified baseline handles LF, CRLF through the LF terminator, and EOF line
comments. A CR-only line is currently consumed as one comment and its source
map does not advance a line. Task 7.32 must treat LF, CRLF, CR, and EOF as line
comment boundaries and apply the same newline model to source spans.

## Affected-component map

| Extension | Primary modules | Existing contract to preserve |
|---|---|---|
| Tokens, AST, parsing | `engine/query/lexer.py`, `tokens.py`, `ast.py`, `parser.py`, `source.py` | bounded handwritten parsing, complete-input rejection, located diagnostics |
| Logical definitions | `engine/catalog/metadata.py`, binder/resolved statement modules | immutable exact-name metadata; existing constructors remain valid |
| Constraint checks | binder plus one shared engine validator and `engine/maintenance` | pre-write validation, no NULL, signed-int64 and physical-row limits |
| Durable ownership/DDL | new engine database/registry service; Catalog/environment bundle registration | Catalog has no I/O; runtime handles have one owner |
| Physical creation | `HeapFile`, Catalog B+ factories | existing formats and validation; unique unclustered B+ primary route |
| Preparation/execution | `engine/query/planner.py`, `executor.py` | prepare is side-effect free; fresh executions; one active stream |
| Explanation | prepared descriptors and Stage 6 `PlanReport` | planned and measured facts remain distinct |
| API compatibility | `api/database.py`, `engine_service.py`, schemas/serialization | explicit permissions, bounded responses, exclusive admission |
| Evidence | query/API tests, `docs/sql*.md`, audit documents | historical closure stays immutable; new evidence is separate |

## Verification baseline

The focused baseline command is:

```powershell
.venv\Scripts\python.exe -m pytest `
  tests\query\test_lexer.py `
  tests\query\test_parser_contract.py `
  tests\api\test_engine_service.py `
  -q -W error -p no:cacheprovider
```

On 2026-09-19 one run produced 114 passes and one timing/serialized-size
sensitive API failure in
`test_a_row_that_cannot_fit_is_an_error_not_an_empty_success`; its immediate
isolated rerun passed. The test derived a second response limit from a first
response containing run-specific metrics. Task 7.31 replaced that unstable
comparison with a deterministic encoded-size boundary; production response
logic was not changed.

The final post-change gates were:

```powershell
.venv\Scripts\python.exe -m pytest tests\api `
  -q -W error -p no:cacheprovider
# 97 passed in 51.38s

.venv\Scripts\python.exe -m pytest `
  tests\query\test_lexer.py `
  tests\query\test_parser_contract.py `
  tests\test_architecture.py `
  -q -W error -p no:cacheprovider
# 97 passed in 13.10s

git diff --check
# no whitespace errors
```

The API gate includes a new regression proving that read-only and write-enabled
statement allowlists enumerate only result kinds the adapter currently knows
how to dispatch. The historical 2,556-test count belongs to the 2026-09-18
baseline audit; no new complete-suite count is claimed for this documentation
and API-policy task.

Tasks 7.32–7.40 must add their own positive, negative, restart, failure, and
end-to-end evidence. Historical counts from the 2026-09-18 closure are not
presented as results of the new extension.
