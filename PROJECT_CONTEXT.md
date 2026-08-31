# PROJECT_CONTEXT.md

> Context version: **1.2** — aligned with `PLAN.md` and `ETAPA_02.md`.

## Project identity

**Project:** Minigestor de Base de Datos Multimodal  
**Course:** Base de Datos 2  
**Academic term:** 2026-2

The project consists of building a small multimodal database-management system progressively.

The current implementation focus is:

> **Part 1 — Relational Database (Tables and SQL)**

The project must remain modular because later parts build on structures created earlier.

---

## Project coordination documents

The repository uses the following documentation structure:

| File | Responsibility |
|---|---|
| `REQUIREMENTS.md` | Official academic requirements |
| `PROJECT_CONTEXT.md` | Stable architectural and technical decisions |
| `PLAN.md` | Part 1 implementation roadmap |
| `ETAPA_XX.md` | Detailed implementation plan for the current stage |
| `AGENTS.md` | Operating instructions for Codex |

These documents have different responsibilities and should not be collapsed into one source.

Implementation details discovered while working on a stage should only be promoted to `PROJECT_CONTEXT.md` after they become stable architectural decisions.

`PLAN.md` and `ETAPA_XX.md` organize implementation work; they do not override the official requirements in `REQUIREMENTS.md`.

---

## Main architectural objective

The system should expose, as clearly as possible, how a SQL query becomes physical operations over storage.

Conceptual flow:

```text
SQL
 |
 v
Parser
 |
 v
AST
 |
 v
Planner
 |
 v
Physical Execution Plan
 |
 v
Executor
 |
 v
Relational Operators
 |
 +-------------------+
 |                   |
 v                   v
Indexes            Storage
 |                   |
 +---------+---------+
           |
           v
          Pages
           |
           v
           Disk
```

The project is not intended to be a thin wrapper around PostgreSQL, SQLite or another complete DBMS.

---

## Current development scope

The current goal is to complete Part 1 before expanding the engine with spatial, text or multimedia capabilities.

Part 1 must provide:

- storage in disk pages;
- Heap File;
- Paged Sequential File;
- clustered B+ index;
- unclustered B+ index;
- Extendible Hashing;
- external sorting;
- grouping and join strategies;
- a limited SQL parser;
- planning/execution;
- transactions and concurrency control;
- a frontend with execution-plan visualization;
- experimental comparisons.

---

## Current recommended stack

These are project decisions, not official assignment requirements.

### Engine
Python 3

The initial Python package requires Python 3.11 or newer. The engine currently
uses only the standard library; pytest is an optional test dependency and
setuptools is the build backend, declared in `pyproject.toml`.

### Parser
Lark

### HTTP API
FastAPI

### Frontend
React + TypeScript + Vite

### SQL editor
Monaco Editor is recommended but optional.

### Tests
pytest

### Benchmarks / plots
`time.perf_counter` + matplotlib

If the repository already contains a working alternative stack that satisfies the assignment, preserve it unless there is a clear reason to migrate.

---

## Proposed repository organization

```text
mini-dbms/
|
├── AGENTS.md
├── REQUIREMENTS.md
├── PROJECT_CONTEXT.md
├── PLAN.md
├── ETAPA_01.md
├── README.md
|
├── engine/
│   ├── storage/
│   ├── indexes/
│   ├── operators/
│   ├── query/
│   ├── transactions/
│   └── catalog/
|
├── api/
├── frontend/
├── tests/
├── benchmarks/
├── data/
└── docs/
```

This is a target organization, not an instruction to rewrite an existing repository that already has a coherent structure.

---

## Layer responsibilities

### `engine/storage`

Owns physical storage concepts such as:
- pages;
- page headers;
- records;
- serialization;
- file headers;
- page I/O;
- Heap File;
- Paged Sequential File;
- free-space tracking.

### `engine/indexes`

Owns:
- generic B+ implementation;
- clustered B+ behavior;
- unclustered B+ behavior;
- Extendible Hashing.

### `engine/operators`

Owns physical relational operators such as:
- Table Scan;
- Index Scan;
- Filter;
- Projection;
- Sort;
- Group;
- Join.

### `engine/query`

Owns:
- SQL grammar;
- parser;
- AST;
- planner;
- execution-plan representation;
- executor coordination.

### `engine/transactions`

Owns:
- transaction state;
- lock management;
- concurrency control.

### `engine/catalog`

Owns metadata such as:
- tables;
- schemas;
- columns;
- indexes;
- table storage organization.

### `api`

Exposes engine functionality through HTTP.

### `frontend`

Provides the required graphical interface.

### `benchmarks`

Contains reproducible experimental scripts. Benchmark logic should not contaminate core engine logic.

---

## Fundamental data concepts

### RID

A record should have a stable location reference when required by an access structure.

Current conceptual design:

```text
RID(page_id, slot_id)
```

This is especially useful for unclustered indexes.

If the existing implementation already has an equivalent physical identifier, preserve it.

Implemented in `engine/storage/rid.py`: `RID` is an immutable, hashable value
object, ordered lexicographically by `(page_id, slot_id)`. Components must be
non-negative built-in `int` values; booleans and coercions are rejected. No
binary upper bound is imposed by this logical value object. Physical bounds
are validated by storage components. A RID is relative to a storage file, not
globally unique across tables, and does not access disk or validate allocation.

---

## Schema

A table schema should describe:
- column name;
- type;
- order;
- optional constraints needed by the supported SQL subset.

Start with a small set of types sufficient for the project.

Recommended initial types:

```text
INTEGER
FLOAT
BOOLEAN
VARCHAR
```

Do not expand the type system until required.

---

## Implemented Stage 1 schema decisions

The initial model lives in `engine/catalog/types.py` and
`engine/catalog/schema.py`, with public imports from `engine.catalog`.

- `DataType` is an `Enum` with explicit textual values `INTEGER`, `FLOAT`,
  `BOOLEAN`, and `VARCHAR`. These identifiers do not prescribe a binary encoding.
- `Column(name, data_type)` is immutable and requires a string name and a
  `DataType` member. No implicit type conversion is performed.
- Empty and whitespace-only names are rejected. Otherwise names are preserved
  exactly, including case and surrounding whitespace. Lookup and duplicate
  detection are case-sensitive; there is no SQL identifier normalization yet.
- `Schema(columns)` accepts a sequence of `Column` objects and snapshots it as
  an immutable tuple in declaration order. Empty schemas are allowed. Duplicate
  names and non-column entries are rejected.
- `schema.column(name_or_position)` supports exact names and zero-based,
  non-negative integer positions. Booleans, slices, and other selector types
  are rejected. `schema.index_of(name)` returns a column's position.
- `schema.columns`, `len(schema)`, and iteration expose ordered metadata.
  Equality of columns and schemas compares their definitions, including order.
- Explicit validation uses domain errors from `engine.errors`, preserving
  compatibility with `TypeError`, `ValueError`, `KeyError`, and `IndexError`
  and the existing descriptive messages. See the error policy below.

These classes are independent from storage, SQL parsing, API, and frontend code.
Record-value validation is implemented separately by `Record`, as described
below. Physical encoding belongs to the storage codecs, not these classes.

---

## Record

A Record represents one relational row according to a Schema.

The Record abstraction should remain independent from React, FastAPI and parser-specific objects.

Implemented in `engine/storage/record.py`, with public imports of `Record` and
`RID` from `engine.storage`:

- `Record(schema, values)` requires an existing `Schema` and a sequence whose
  length exactly matches the number of columns. Empty schemas accept empty rows.
- Values are copied into an immutable tuple. The record and its schema reference
  cannot be reassigned through the public API.
- Validation accepts exact built-in Python types: `INTEGER -> int`,
  `FLOAT -> float`, `BOOLEAN -> bool`, and `VARCHAR -> str`. In particular,
  booleans are not integers, integers are not automatically promoted to floats,
  and custom scalar subclasses are not accepted.
- No implicit conversions are performed, including parsing numeric strings.
  `None`/SQL `NULL` is not supported by the current model.
- Logical integers remain unbounded. FLOAT accepts Python float values,
  including NaN and infinities. The physical codec rules below do not change
  Record validation; future SQL operators must define their own semantics.
- `record["column_name"]` is the single named-value access API. Names use
  `Schema.index_of` and its exact-name validation. Position/slice access is not
  added; the ordered `values` tuple remains available.
- Wrong argument/value types raise `InvalidTypeError` (a `TypeError`); wrong
  value counts raise `ValidationError` (a `ValueError`). There is no page, RID,
  file, or index ownership inside a record.

---

## Implemented table/index metadata and catalog decisions

`engine/catalog/metadata.py` defines immutable `TableMetadata(name, schema)`
and `IndexMetadata(name, table_name, column_name, index_type, clustered=False)`.
They follow the exact, nonblank name policy of `Column`, and carry no paths,
records, nodes, buckets, or physical storage configuration.

- `IndexType` is a separate enum (`BPLUS`, `EXTENDIBLE_HASH`). `index_type`
  requires an enum member, not a string; `clustered` requires a built-in bool.
- Only BPLUS metadata may be marked clustered. This declares a future physical
  organization; it does not implement clustering or an index.
- Standalone index metadata validates its own fields. Table/column existence is
  checked by the catalog at registration time.

`engine/catalog/catalog.py` implements an in-memory `Catalog`:

- Table operations: `register_table`, `get_table`, `has_table`, `list_tables`.
- Index operations: `register_index`, `get_index`, `get_indexes(table_name)`.
- Table names are unique within a catalog. Index names are also catalog-wide
  unique, even across tables. Table and index namespaces are independent.
- At most one clustered B+ definition is registered per table. Differently
  named unclustered/hash definitions may coexist, including on the same column.
- Registration checks all invariants before changing state. Failed operations
  neither overwrite existing definitions nor reserve names.
- Listing methods return tuple snapshots in registration order; returned
  metadata is immutable. Callers cannot mutate the internal dictionaries via
  query results. Catalog instances own independent state.
- An existing table without indexes returns `()`. Unknown tables, indexes, and
  referenced columns raise domain subclasses of `KeyError`; duplicates and
  conflicting clustered definitions raise `DuplicateError` (a `ValueError`);
  wrong argument types raise `InvalidTypeError` (a `TypeError`).
- Persistence, row storage, removal of metadata, and concurrency protection
  are not implemented.

The catalog depends only on metadata/schema/types, never on storage. These
objects are exported from `engine.catalog`. An integration test covers schema,
record, RID, metadata, and catalog operations while file-opening APIs are blocked.

---

## Implemented Stage 1 domain errors

`engine/errors.py` is dependency-free. All explicit validation errors in the
model and catalog derive from `DatabaseError` and retain the previous built-in
exception category and message. There is no wrapper that hides the original
table/column reference failure.

| Domain error | Built-in compatibility | Current use |
|---|---|---|
| `InvalidTypeError` | `TypeError` | Wrong argument or row-value types |
| `ValidationError` | `ValueError` | Blank metadata names, negative RID components, wrong row length, clustered hash metadata |
| `SchemaError` | `ValueError` | Blank column names and duplicate schema columns |
| `DuplicateError` | `ValueError` | Duplicate table/index names or a second clustered definition |
| `InvalidReferenceError` | `KeyError` | Unknown index names; base for named reference failures |
| `UnknownTableError` | `KeyError` | Unknown table lookups and index table references |
| `UnknownColumnError` | `KeyError` | Schema/record lookups and index column references |
| `ColumnPositionError` | `IndexError` | Numeric column positions outside a schema |

`SchemaError` and `DuplicateError` specialize `ValidationError`.
`UnknownTableError` and `UnknownColumnError` specialize `InvalidReferenceError`.
Contracts also use `InvalidReferenceError` for missing RIDs/key-RID pairs,
without adding an exception class for each future storage/index structure.
Wrongly typed schema inputs use `InvalidTypeError`, not `SchemaError`.

Native Enum construction, frozen-dataclass assignment, tuple mutation, and
Python comparison errors retain their native exceptions. They are not wrapped
as engine errors. Operator lifecycle misuse is specified as `RuntimeError`;
no additional operator error hierarchy exists before concrete operators.

---

## Page

A Page is the fundamental fixed-size storage unit.

Important note:

> The assignment requires page-based storage but does not prescribe a page size in the project statement.

Therefore the page size must be a configurable or explicitly documented project decision.

The project adopts the following version-1 design on 2026-08-31, under the
user's request for tasks 2.2–2.6. These are project decisions, not additional
academic requirements. **4096 bytes is now adopted**, not merely proposed:
it gives a small fixed unit for educational tests and enough space for several
variable-length rows. Alternative page sizes are not supported by format v1.

### Physical format v1

All multibyte fields use little-endian, standard sizes, and no native padding
(`struct` prefix `<`). Formats and derived sizes live in
`engine/storage/binary.py`; no other module owns binary layout constants.

| Structure | Format / size | Fields in byte order |
|---|---|---|
| Page | 4096 bytes | header, slot directory, contiguous free area, payload area |
| PageHeader | `<IHHHH` / 12 bytes | page_id, slot_count, free_space_start, free_space_end, active_record_count |
| Slot (planned) | `<HHB` / 5 bytes | offset, length, status (0 free, 1 active) |
| File header (planned) | `<8sIII` / 20 bytes | magic, version, page_size, allocated_page_count |

The directory grows from byte 12 toward higher offsets; record bytes grow
backward from byte 4096. Page offsets are relative to the page, not the file.
`slot_count` includes free entries, and slot ids are zero-based directory
positions. `active_record_count` counts only live entries.

Required numeric and geometric invariants:

- page_id fits uint32; counts, offsets, and lengths fit uint16;
- `0 <= active_record_count <= slot_count <= 816`;
- `free_space_start == 12 + slot_count * 5`;
- `free_space_start <= free_space_end <= 4096`;
- zero slots implies `free_space_end == 4096`;
- live payload ranges lie in `[free_space_end, 4096]`, never overlap the
  header/directory/free area or each other; adjacent ranges and holes are valid;
- zero-byte records (empty schema) are valid; their planned canonical slot
  offset is 4096 and they occupy no payload bytes;
- a serialized complete page must have exactly 4096 bytes.

An empty page has 4084 contiguous free bytes. A new slot costs 5 bytes, so a
record in an otherwise empty page can occupy at most 4079 bytes. Future Page
insertion must reject oversized payloads; overflow pages are not adopted.
Codecs enforce value framing limits, not page capacity. Header free space is
only `free_space_end - free_space_start`, not total reclaimable fragmented
space. Checking geometry is not proof that a page id has been allocated.

`PageHeader` is an immutable validated snapshot with an empty-page default.
It serializes/deserializes exactly its 12 bytes, not a complete page. Shared
validators check buffer size and geometry; optional active payload ranges
allow overlap checks without knowing records or slot objects. Full page/slot
validation remains the responsibility of their later implementations.

### RID lifetime and space reuse (policy for the upcoming Page)

Live `RID(page_id, slot_id)` values survive page-local compaction. Compaction
moves bytes and updates offsets, never renumbers slots or moves rows across
pages. Deletion will mark the entry free (offset and length reset to zero),
decrement the active count, and leave a reclaimable hole until compaction.
Slot entries are retained. Insertion may reuse the first free slot before
appending one; it still needs payload capacity. Compaction may reclaim holes
without changing the identity of live slots.

An eliminated RID is invalidated, but its pair can subsequently identify a
new row when its slot is reused. No generation counter or historical identity
guarantee is provided. Future storage/index integration must remove old index
references before making a deleted slot reusable. This policy does not modify
the existing logical RID class or implement allocation/deletion yet.

### Primitive and record encoding

| Type | Physical representation | Boundary behavior |
|---|---|---|
| INTEGER | `<q`, signed 64-bit | accepts -2**63 through 2**63-1; rejects larger logical ints |
| FLOAT | `<d`, IEEE-754 binary64 | preserves finite values, signed zero and infinities |
| BOOLEAN | `<B`, one byte | only 0 and 1 are valid encodings |
| VARCHAR | `<I` byte-length prefix + strict UTF-8 bytes | at most 2**32-1 encoded bytes; no terminator |

NaN is allowed as a row value. Every NaN is encoded as the canonical quiet NaN
`00 00 00 00 00 00 f8 7f`; decoding accepts all binary64 NaN patterns. NaN
payload/sign is not preserved, and tests use `isnan`, not equality. Existing
index contracts still reject NaN keys. No scalar coercions are introduced.
UTF-8 preserves Unicode and embedded NUL; lone surrogates and malformed UTF-8
are rejected. Lengths count bytes, not characters.

`ValueCodec.encode/decode` handles a single value, with exact consumption on
decode. `decode_from` returns the value and absolute next offset within a byte
buffer. `RecordCodec.serialize` concatenates values in schema order;
`deserialize(schema, payload)` reconstructs a Record and rejects missing or
trailing bytes. Empty records encode to empty bytes. Neither codec owns pages
or accesses disk. Binary input APIs require immutable `bytes`.

Rows contain no schema, type tags, column count, checksum, or NULL bitmap.
The caller must supply the matching schema; an incorrect schema with an
otherwise compatible encoding cannot always be detected. Validation catches
structural corruption, not arbitrary bit changes to valid values. `None` /
SQL NULL remains unsupported. Wrong argument/scalar types raise
`InvalidTypeError`; range, framing, UTF-8, boolean and header/layout failures
raise `ValidationError`, retaining TypeError/ValueError compatibility.

### File and catalog strategy (not file I/O yet)

Use a 20-byte file-header prefix before the first data page, not a reserved
metadata page. Its magic is `b"MINIDB\x00\x00"` (8 bytes), format version is 1,
and page size must equal 4096. The future manager maps a zero-based page id to
`20 + page_id * 4096`, verifies `page_id < allocated_page_count`, and checks
file length against the count. File counts fit uint32; therefore the maximum
allocated id is below the maximum count, even though PageHeader can represent
any uint32 id. No FileHeader class, allocation, flushing, or recovery is
implemented in tasks 2.2–2.6.

The catalog remains in memory throughout Stage 2. Schema/catalog persistence
is deferred to a later integration task; reopen tests will explicitly supply
the same schema. Reopening page bytes will not imply automatic table discovery.
The versioned format is a baseline, not a crash-recovery or migration protocol.

---

## Storage abstractions

A general storage manager should conceptually support operations such as:

```text
insert(record)
read(rid)
delete(rid)
scan()
```

Concrete organizations may expose additional operations.

The implemented boundary is the `Storage` ABC in `engine/storage/base.py`,
exported from `engine.storage`. It has exactly four abstract operations:

- `insert(record: Record) -> RID`: duplicate row values are allowed. A concrete
  storage has a fixed schema; a different ordered schema raises `SchemaError`.
- `read(rid: RID) -> Record`: absent/deleted locations raise
  `InvalidReferenceError`, never a `None` row.
- `delete(rid: RID) -> None`: absent/deleted locations also raise
  `InvalidReferenceError`; no silent deletion of missing rows.
- `scan() -> Generator[tuple[RID, Record], None, None]`: stream each live row
  together with its physical reference once. Empty scans yield nothing; no
  common ordering is imposed on different storage organizations.

Non-Record/non-RID inputs raise `InvalidTypeError`; validation failures do not
mutate storage. Each scan is fresh and closable. Scan-owned resources must be
released on exhaustion, failure, and `close()`, without closing the borrowed
storage manager. Callers use `contextlib.closing` or `try/finally` when they
may stop early. Concurrency, allocation, capacity, file lifetime, and physical
I/O error details are deferred. No physical implementation is included.

---

## Implemented index contracts

`engine/indexes/base.py` defines `Index[Key]` and its `OrderedIndex[Key]`
specialization, exported from `engine.indexes`.

- `Index.insert(key, rid) -> None` adds an association. Multiple RIDs per key
  are allowed; repeating the same pair is a no-op.
- `Index.search(key) -> Generator[RID, None, None]` streams matching RIDs once
  each, with unspecified order. No match is an empty generator.
- `Index.delete(key, rid) -> None` removes only that pair. An absent pair raises
  `InvalidReferenceError`. These operations do not create/delete storage rows
  or resolve RIDs through a storage manager.
- Only `OrderedIndex` requires `range_search(lower=None, upper=None, *,
  include_lower=True, include_upper=True) -> Generator[RID, None, None]`.
  `None` is an unbounded endpoint, not a NULL key. Results follow ascending
  native Python key order; ties have no prescribed RID order. Both endpoints
  are inclusive by default. Equal bounds with an excluded endpoint yield
  nothing; an inverted interval raises `ValidationError`.

Concrete indexes configure one exact built-in key type (`int`, `float`, `bool`,
or `str`); coercion and bool/int mixing are rejected with `InvalidTypeError`.
Range inclusion flags require exact bools. NaN is rejected as an index key/bound
with `ValidationError`, because it lacks reflexive equality; infinity is valid.
This is an index-contract decision, not a new restriction on `Record` values
or a definition of future SQL NULL/NaN semantics.

Search generators have the same cleanup obligations as storage scans. Argument
errors may appear during the first iteration, so callers must also protect
consumption. Mutations during iteration are not specified. No B+ nodes, hash
buckets, physical indexes, or range requirement for Extendible Hashing exist.

---

## Heap File model

Required behavior:

- records are stored in arrival order;
- records are distributed across disk pages;
- free space must be reused;
- a full scan must be possible;
- records should be addressable using the project's chosen physical identifier.

A Heap File must not be implemented by inserting rows into SQLite/PostgreSQL.

---

## Paged Sequential File model

Required behavior:

- records remain ordered by a chosen key;
- insertion preserves the ordering;
- deletion is lazy;
- wasted space must be measurable;
- a reorganization mechanism must exist.

The assignment gives **more than 30% wasted space** as an example trigger for reorganization.

The implementation may use that threshold as the default unless the team explicitly documents another valid strategy.

The file organization must remain page-based.

---

## B+ index model

One reusable B+ implementation is preferred over two unrelated trees.

Core B+ behavior should support:
- equality lookup;
- range lookup;
- insertion;
- splitting;
- deletion;
- the balancing operations required by the chosen deletion algorithm;
- linked leaves where useful for range traversal.

### Unclustered B+

Conceptually:

```text
key -> RID
```

The physical row order is independent from index order.

### Clustered B+

The physical organization of records must reflect the index key ordering sufficiently to behave as a clustered organization.

Do not label an ordinary unclustered index as "clustered" only in metadata.

The exact physical design should be documented once implemented.

---

## Extendible Hashing model

The required dynamic-hashing strategy is Extendible Hashing.

Expected concepts:
- directory;
- global depth;
- buckets;
- local depth;
- equality search;
- bucket split;
- directory expansion when necessary.

This structure is intended primarily for equality access.

It is not a replacement for B+ range access.

---

## Relational operators

The engine should expose physical operators independent from SQL syntax.

Recommended operator set:

```text
TableScan
IndexScan
Filter
Projection
ExternalSort
Group
Join
```

This keeps parsing separate from execution.

`engine/operators/base.py` now supplies the `Operator` ABC, exported from
`engine.operators`. It is a contract only, with no concrete TableScan or other
operator:

- `open() -> None` starts from the beginning. Instances start closed; opening
  an already open/exhausted run raises `RuntimeError`. Reopening after close
  starts a new run. A failed open must release partially acquired resources.
- `next() -> Record | None` yields rows with one output schema per run.
  Exhaustion returns `None` repeatedly, not `StopIteration`; empty-schema rows
  remain valid results. Calling while closed raises `RuntimeError`.
- `close() -> None` is idempotent, including before open or after failures. It
  releases owned children, scan/search generators, and temporary resources,
  not borrowed storage/index managers. Cleanup must attempt all releases even
  if one fails.

Consumers must use `try/finally` around the full run, including `open`, and
close on exhaustion, early exit, or failure. An execution error requires
closing before another run. The ABCs enforce required methods, not lifecycle,
validation, or resource semantics: later implementations need conformance
tests for those documented rules. There is no common stateful executor here.

---

## Stage 1 verification boundary

`tests/doubles.py` contains minimal `StorageDouble`, `EqualityIndexDouble`,
`OrderedIndexDouble`, and `OperatorDouble` examples. They reuse production
models/contracts but remain exclusively in the test package; only `engine`
packages are selected for distribution. Their dictionaries, small ordered
lists, synthetic RIDs, and resource probes do not implement academic physical
algorithms or prescribe future storage layouts.

Behavioral tests exercise contract validation, equality/ranges, exhaustion,
reopening, and cleanup on normal/early/error exits. The integration scenarios
compose catalog, records and the doubles with file-opening APIs blocked during
operations. Architecture tests separately inspect source dependencies and use
fresh isolated interpreters to validate public imports without pytest preload.

The contracts' semantics remain unchanged. Tests of these examples are not a
substitute for conformance tests on future physical implementations, nor evidence
of persistence, concurrency, or relational query execution.

---

## External sorting

`ORDER BY` must be supported using External Sorting with k-way merge.

Conceptual algorithm:

1. Read chunks that fit in the allowed in-memory working area.
2. Sort each chunk.
3. Persist sorted runs.
4. Merge the runs using a k-way merge.

The implementation should not simply call an in-memory sort on the entire required dataset and call it external sorting.

Using Python's `heapq` inside the merge is acceptable because it does not replace the external-sort algorithm.

---

## GROUP BY

The assignment requires optimized `GROUP BY` using External Hashing and/or strategic index usage.

A valid design may begin with in-memory hash aggregation and extend to partitioned/external hashing when data exceeds the configured memory budget.

The final implementation must be able to justify how the required external/index strategy is satisfied.

---

## JOIN

The assignment requires optimized joins using External Hashing and/or strategic index usage.

Recommended implementations:

- Nested Loop Join as a baseline;
- Hash Join;
- index-assisted join when an appropriate index exists.

At least one required optimization path must clearly satisfy the assignment.

---

## SQL subset

The SQL parser only needs to support the subset required by the project.

Required families:

```sql
SELECT ...
FROM ...
WHERE ...

SELECT ...
FROM ...
ORDER BY ...

SELECT ...
FROM ...
GROUP BY ...

INSERT INTO ...
VALUES (...)

DELETE FROM ...
WHERE ...
```

The project does not require a complete SQL standard implementation.

Do not add advanced SQL syntax at the cost of required features.

---

## Query planning

The planner should choose an access path based on available structures.

Examples:

```text
Equality predicate on indexed key
    -> Hash lookup or B+ lookup

Range predicate
    -> B+ range scan when available

No useful index
    -> Table scan
```

The planner can begin simple and rule-based.

A cost-based optimizer is not an explicit Part 1 requirement.

---

## Execution plans

The physical execution plan should be an actual representation of what the executor runs.

Example:

```text
Projection(name)
  |
IndexScan(table=students, index=idx_students_id, condition=id=100)
```

The frontend's execution-plan panel should visualize this real plan.

---

## Transactions and concurrency

The project requires transaction grouping and concurrency control.

Current recommended strategy:

- a Transaction Manager;
- a Lock Manager;
- shared locks for compatible reads;
- exclusive locks for writes;
- a simple locking protocol sufficient to demonstrate safe concurrent execution.

A simplified strict two-phase-locking design is acceptable as a project decision if implemented consistently.

Do not implement MVCC unless explicitly chosen later.

---

## Required thread demonstration

The project must include a simulation where multiple transactions execute concurrently.

The demonstration should show:

1. concurrent transactions;
2. a race condition / conflicting access;
3. how the concurrency-control mechanism prevents or resolves the incorrect result.

This demonstration should be reproducible.

---

## Frontend

The graphical interface requires four primary panels:

### Files panel
Shows loaded tables and their structure.

### Query panel
Allows the user to write SQL.

### Results panel
Shows result rows in tabular form.

### Execution Plan panel
Shows how the query was executed, including relevant indexes and operation order.

The frontend should consume the engine through a clean API rather than importing storage internals.

---

## API

FastAPI is the current recommended transport layer.

Potential conceptual endpoints:

```text
GET  /tables
GET  /tables/{table_name}
POST /query
```

The exact API may evolve.

The DBMS engine must be callable independently from the web layer.

---

## Metrics and instrumentation

Because the project requires experiments, core execution should expose enough information to measure behavior.

Useful metrics may include:

```text
elapsed_ms
pages_read
pages_written
records_scanned
index_name
operator_name
```

Only metrics that are actually measured should be reported.

Do not fabricate instrumentation values.

---

## Experimental datasets

Part 1 requires comparisons using:

```text
1,000 records
10,000 records
100,000 records
```

Use the same logical datasets across compared techniques whenever possible.

Dataset generation should be reproducible.

---

## Part 1 experimental comparisons

### File organization comparison

Compare:
- Heap File;
- Paged Sequential File.

Measure:
- insertion time;
- primary-key search time;
- disk space used;
- reorganization time.

### Index comparison

Compare:
- clustered B+;
- unclustered B+;
- Extendible Hashing.

Evaluate:
- exact equality search;
- range search;
- sorting.

Measure:
- index construction time;
- query time;
- extra disk space;
- behavior under frequent insertions/deletions.

The report must include comparative charts, a summary table and conclusions about when each technique is preferable.

---

## 10-stage implementation roadmap

### 1. Architecture and data model
Foundation classes/interfaces only.

### 2. Pages, records and persistence
Reliable disk/page layer.

### 3. Heap + Paged Sequential
Both required file organizations.

### 4. B+
Generic B+ plus clustered/unclustered use.

### 5. Extendible Hashing
Dynamic hash index.

### 6. Operators and external algorithms
Physical relational execution.

### 7. SQL engine
Parser, AST, planner and executor.

### 8. Transactions and concurrency
Safe concurrent execution.

### 9. API and frontend
Required user interface.

### 10. Experiments and integration
Benchmarks, graphs, conclusions and delivery cleanup.

---

## Current stage

Latest completed stage:

> **Stage 1 — Architecture and data model**

Overall Part 1 roadmap:

> `PLAN.md`

Detailed current-stage specification:

> `ETAPA_02.md`

Implemented so far:

- planned directories and Python package initialization;
- minimal packaging/test configuration, Git exclusions, and introductory README;
- `DataType`, `Column`, `Schema`, `RID`, and `Record`;
- `TableMetadata`, minimal `IndexMetadata`/`IndexType`, and in-memory `Catalog`;
- abstract `Storage`, `Index`/`OrderedIndex`, and `Operator` contracts;
- minimal domain errors integrated without changing existing validation rules;
- passing unit/interface tests, test-only behavioral examples, expanded
  model/catalog/contract integration without file access during operations,
  and architecture/import regression checks.
- Stage 2 tasks 2.2–2.6: documented physical format v1, centralized binary
  constants/geometry checks, ValueCodec, RecordCodec, and immutable PageHeader;
- 296 additional tests for golden bytes, boundaries, malformed data, header
  geometry, and integration with the catalog without file access. All 696
  current tests pass with warnings treated as errors; compileall and pip check
  also pass (Windows, Python 3.12.4, pytest 8.4.2).

**Stage 1 is formally complete**, audited on 2026-08-31 against the entire
Definition of Done in `ETAPA_01.md`, with 400 passing tests. Evidence and the
limits of verification are recorded in [the audit](docs/ETAPA_01_AUDIT.md).

**Stage 2 is in progress**, explicitly authorized on 2026-08-31 for tasks
2.2–2.6 only: physical design, binary constants/invariants, primitive and record
codecs, and PageHeader. See `ETAPA_02.md` for verified progress. SlotEntry, Page,
FileHeader and PageManager are not part of this implementation block. There is
no disk persistence yet, and Stage 2 is not complete.

If the repository already contains code from later stages, do not delete it. First inspect the repository, determine its actual implementation status, and preserve compatible working functionality.

When the project advances to a new stage, update this section and point it to the corresponding `ETAPA_XX.md`.

---

## Important unresolved design decisions

The following should not be guessed silently:

- eventual catalog/schema persistence format and integration timing (deferred
  beyond Stage 2; the current catalog remains in memory);
- exact clustered B+ physical layout;
- supported comparison operators in `WHERE`;
- aggregation functions beyond those required by tests/use cases;
- exact transaction syntax details beyond the assignment's `BEGIN TRANSACTION` / `END TRANSACTION`;
- deadlock handling strategy;
- memory budget used by external algorithms.

When one of these decisions is made, document it here.

---

## Project philosophy

Prefer:
- simple;
- testable;
- educational;
- modular;
- observable implementations.

Avoid:
- unnecessary frameworks;
- hidden magic;
- premature optimization;
- building features from future parts before Part 1 is stable.

The engine should make database-internals concepts visible rather than obscure them.
