# ETAPA_02.md

> Context version: **1.2** — aligned with `AGENTS.md`, `PROJECT_CONTEXT.md`, `REQUIREMENTS.md`, `PLAN.md`, and the completed `ETAPA_01.md`.

## Stage 2 — Pages, Records, and Base Persistence

**Part:** Relational Database  
**Prerequisite:** Stage 1 complete  
**Previous stage:** Stage 1 — Architecture and Data Model  
**Next stage:** Stage 3 — Heap File and Paged Sequential File  
**Roadmap:** `PLAN.md`

## Implementation status (2026-08-31)

- Stage 2 is in progress by explicit user request, limited to tasks 2.2–2.6.
- Repository inspection (2.1) confirmed the existing model/contracts and no
  physical storage implementation. Baseline: 400 passing tests.
- Physical format v1 (2.2) is adopted in `PROJECT_CONTEXT.md`: 4096-byte
  slotted pages, 12-byte PageHeader, 5-byte slots, 20-byte file-header prefix,
  little-endian, signed int64, binary64 with canonical NaN, strict UTF-8,
  no NULL, reusable deleted RIDs, and an in-memory catalog during Stage 2.
- Completed with tests: binary constants and geometry checks (2.3), ValueCodec
  (2.4), RecordCodec (2.5), and immutable PageHeader (2.6).
- Validation: 296 new tests pass; the complete suite passes **696 tests** with
  `-W error` (Windows, Python 3.12.4, pytest 8.4.2). `compileall` and `pip check`
  also pass. Existing model/contract tests remain unchanged and pass.
- New tests live in `tests/storage/test_binary.py`, `test_value_codec.py`,
  `test_record_codec.py`, `test_page_header.py`, and
  `tests/test_codec_header_integration.py`. They cover fixed expected bytes,
  numeric/Unicode boundaries, NaN/infinities, malformed/truncated buffers,
  overlap/bounds checks, and integration with file-opening APIs blocked.
- SlotEntry, Page, FileHeader, PageManager and disk persistence remain pending.
  Stage 2 is not complete; do not infer persistence from byte round-trips.
- Next task: **2.7 — SlotEntry / slot directory**, outside this completed block.

---

# 1. Purpose

Stage 2 builds the physical persistence layer used by every file organization implemented later.

It answers:

> **How are relational records converted to bytes, placed inside fixed-size pages, written to disk, and recovered correctly after the process restarts?**

The goal is to establish a reliable path:

```text
Schema
  |
  v
Record
  |
  v
Record Codec
  |
  v
serialized bytes
  |
  v
Page
  |
  v
Page Manager
  |
  v
database file
  |
  v
Disk
```

and the reverse path:

```text
Disk
  |
  v
database file
  |
  v
Page Manager
  |
  v
Page
  |
  v
serialized bytes
  |
  v
Record Codec
  |
  v
Record
```

Stage 2 is complete only when data can be written, the process can close, the file can be reopened, and the original records can be recovered correctly.

---

# 2. Relationship with the project documents

The documentation authority remains:

```text
REQUIREMENTS.md
    |
    |  official academic requirements
    v
PROJECT_CONTEXT.md
    |
    |  stable architecture decisions
    v
PLAN.md
    |
    |  Part 1 roadmap
    v
ETAPA_02.md
    |
    |  detailed Stage 2 work
    v
CODE
```

`AGENTS.md` governs how Codex must work with these files.

This stage document must not override:

- official requirements in `REQUIREMENTS.md`;
- stable decisions already recorded in `PROJECT_CONTEXT.md`;
- Codex operating rules in `AGENTS.md`.

If implementation work resolves an open architectural decision, that decision must be promoted to `PROJECT_CONTEXT.md`.

---

# 3. Stage transition requirement

Stage 1 is assumed to be complete.

Before implementing Stage 2, verify that:

```text
[x] Stage 1 Definition of Done is satisfied
[x] Stage 1 tests pass
[x] DataType exists
[x] Column exists
[x] Schema exists
[x] Record exists
[x] RID exists
[x] TableMetadata exists
[x] Catalog exists
[x] storage/index/operator contracts are stable enough to continue
```

Because the project has moved to Stage 2, the `Current stage` sections of coordination documents should also point to:

```text
Stage 2 — Pages, Records, and Base Persistence
ETAPA_02.md
```

If `AGENTS.md` or `PROJECT_CONTEXT.md` still identify Stage 1 as the current stage, report that documentation mismatch before coding and update it consistently.

---

# 4. Scope of Stage 2

## Included

```text
physical storage design decisions
binary primitive encoding
Record serialization/deserialization
PageHeader
SlotEntry / slot directory
variable-length-record page layout
Page implementation
page insertion/read/delete primitives
page compaction if adopted
FileHeader / file metadata
PageManager / page I/O
page allocation
page read/write
flush/close/reopen
persistence validation
basic I/O instrumentation if adopted
Stage 2 unit tests
Stage 2 persistence tests
Stage 2 integration test
```

## Explicitly not included

```text
HeapFile
PagedSequentialFile
file-level free-space map
file-level free-list policy
B+ Tree
Extendible Hashing
TableScan
IndexScan
SQL parser
Planner
Executor
transactions
concurrency control
buffer replacement policy
full Buffer Pool Manager
WAL / crash recovery
FastAPI
React
benchmarks comparing Heap vs Sequential
```

Stage 2 provides primitives that Stage 3 will use. It must not secretly implement Stage 3.

---

# 5. Architectural objective

The preferred dependency direction is:

```text
Stage 1 abstractions
Schema / Record / RID
        |
        v
RecordCodec
        |
        v
serialized record bytes
        |
        v
Page
        |
        v
PageManager
        |
        v
database file
```

Important boundaries:

- `RecordCodec` understands `Schema` and `Record`;
- `Page` stores bytes and slot metadata;
- `Page` should not know about Heap File or SQL;
- `PageManager` performs physical page I/O;
- `PageManager` should not know about B+ or Extendible Hashing;
- higher-level file organizations should not calculate raw byte offsets themselves once `PageManager` exists.

---

# 6. Task 2.1 — Inspect the completed Stage 1 implementation

## Objective

Determine the exact Stage 1 APIs that Stage 2 must build on.

## Inspect

Codex should review:

- `DataType`;
- `Column`;
- `Schema`;
- `Record`;
- `RID`;
- storage contract;
- existing serialization helpers, if any;
- any code inherited from previous labs;
- current tests;
- current `PROJECT_CONTEXT.md` decisions.

Also search the repository for existing concepts such as:

```text
Page
PageHeader
Slot
SlottedPage
FileHeader
PageManager
DiskManager
Serializer
RecordSerializer
RecordCodec
```

## Expected output

Before modifying code, report:

```text
Existing reusable Stage 2 code:
- ...

Missing Stage 2 components:
- ...

Conflicts with the current architecture:
- ...

Stable Stage 1 APIs that Stage 2 will use:
- ...

Recommended implementation sequence:
- ...
```

## Restriction

Do not modify code during Task 2.1.

---

# 7. Task 2.2 — Resolve Stage 2 physical-storage decisions

**Completed:** the adopted v1 choices and their rationale are recorded in the
Page / Physical format v1 section of `PROJECT_CONTEXT.md`. The alternatives
below are planning context, not unresolved choices or official requirements.

## Objective

Close the architectural questions that were intentionally left unresolved at the end of Stage 1.

Do not begin implementing binary formats until these decisions are explicit.

---

## 7.1 Page size

The official project requires page-based storage but does not prescribe a specific page size.

Choose and document a value.

A reasonable educational default is:

```text
4096 bytes
```

but this value is a recommendation, not an official requirement.

Once adopted, record it in `PROJECT_CONTEXT.md`.

---

## 7.2 Page organization

Because the project already includes `VARCHAR` as a recommended type and later stages need variable-length records, the recommended baseline is a **slotted page**.

Conceptually:

```text
+----------------------------------------------------------+
| PageHeader                                               |
+----------------------------------------------------------+
| Slot 0 | Slot 1 | Slot 2 | ...                           |
+-----------------------------+----------------------------+
|         Free Space          |                            |
|                             |   Record Payloads          |
|                             |   growing backward         |
+-----------------------------+----------------------------+
```

Equivalent layouts are valid if they provide the same required behavior.

The adopted layout must be documented.

---

## 7.3 Slot representation

Each slot should contain enough information to locate a record.

Conceptually:

```text
offset
length
status
```

Possible statuses include:

```text
ACTIVE
DELETED / FREE
```

Do not add status fields that have no purpose.

---

## 7.4 RID stability

The Stage 1 conceptual RID is:

```text
RID(page_id, slot_id)
```

Therefore record movement **inside the same page** should preferably preserve `slot_id`.

If page compaction moves record bytes, update slot offsets rather than changing the RID.

Any policy that can invalidate a RID must be documented before adoption.

---

## 7.5 File metadata layout

Choose how the data file stores metadata such as:

```text
magic / file signature
format version
page size
number of allocated pages
```

Possible designs include:

```text
fixed FileHeader before all data pages
```

or:

```text
reserved metadata page
```

Choose one design and document it.

Do not implement both.

---

## 7.6 Binary byte order

Choose one deterministic encoding.

For example:

```text
little-endian
```

or:

```text
big-endian
```

The choice matters less than consistency and documentation.

---

## 7.7 NULL policy

`NULL` support is not an explicit Part 1 requirement in the current requirements file.

Therefore:

- do not silently invent a complex NULL encoding;
- if Stage 1 already supports nullable values, define their physical encoding;
- otherwise defer NULL support.

---

## 7.8 Catalog persistence

Decide whether catalog metadata becomes persistent now or remains in-memory temporarily.

Stage 2 must not automatically expand into a full persistent system catalog unless the architecture requires it.

---

## Required output of Task 2.2

A documented decision set similar to:

```text
PAGE_SIZE = ...
PAGE_LAYOUT = ...
SLOT_LAYOUT = ...
FILE_HEADER_STRATEGY = ...
BYTE_ORDER = ...
NULL_POLICY = ...
CATALOG_PERSISTENCE = ...
```

Promote stable values to `PROJECT_CONTEXT.md`.

---

# 8. Task 2.3 — Define binary-format constants and invariants

## Objective

Centralize physical-format definitions instead of scattering numeric offsets throughout the code.

Possible concepts:

```text
PAGE_SIZE
FILE_MAGIC
FORMAT_VERSION
PAGE_HEADER_FORMAT
SLOT_FORMAT
FILE_HEADER_FORMAT
```

If Python `struct` is used, format strings should live in a small number of clearly named places.

Avoid patterns such as:

```python
file.seek(17 + page_id * 4096)
```

appearing throughout the repository.

Prefer named helpers and constants.

---

## Required invariants

At minimum, define and test:

```text
serialized Page always occupies exactly PAGE_SIZE bytes
record payload never overlaps slot directory
slot offsets remain inside the page
slot lengths remain valid
free-space boundaries never cross
page_id values are valid
```

---

## Suggested tests

```text
test_page_size_constant_is_positive
test_binary_formats_have_expected_size
test_header_sizes_fit_inside_page
test_invalid_layout_is_rejected
```

---

## Definition of Done

The physical format has explicit constants and machine-checkable invariants.

---

# 9. Task 2.4 — Implement primitive value encoding

## Objective

Provide deterministic conversion between Stage 1 data values and bytes.

The codec should support the Stage 1 types that the project actually adopted.

Expected initial mappings may include:

```text
INTEGER
FLOAT
BOOLEAN
VARCHAR
```

---

## Requirements

Encoding must be deterministic.

Decoding must reconstruct the same logical value.

Examples:

```text
123
    -> bytes
    -> 123

3.5
    -> bytes
    -> 3.5

True
    -> bytes
    -> True

"Ana"
    -> bytes
    -> "Ana"
```

---

## VARCHAR

Variable-length strings require a framing rule.

A common design is:

```text
length prefix + encoded bytes
```

For example:

```text
[4-byte length][UTF-8 payload]
```

The exact width is a project decision.

Document it.

---

## Suggested tests

```text
test_integer_round_trip
test_negative_integer_round_trip
test_float_round_trip
test_boolean_round_trip
test_empty_string_round_trip
test_unicode_string_round_trip
test_long_string_round_trip
```

---

## Definition of Done

Every adopted primitive type has deterministic encode/decode round-trip behavior.

---

# 10. Task 2.5 — Implement `RecordCodec`

## Objective

Serialize and deserialize a Stage 1 `Record` according to its `Schema`.

Conceptually:

```text
Record + Schema
      |
      v
RecordCodec.serialize(...)
      |
      v
bytes
```

and:

```text
bytes + Schema
      |
      v
RecordCodec.deserialize(...)
      |
      v
Record
```

---

## Important design rule

`RecordCodec` owns logical row serialization.

`Page` should not contain type-specific code such as:

```text
if INTEGER ...
if VARCHAR ...
```

The Page layer should store record bytes without understanding every column type.

---

## Validation

The codec should reject:

- value count inconsistent with schema;
- unsupported data types;
- malformed/truncated serialized records;
- invalid string lengths;
- invalid boolean representation if a strict encoding is used.

---

## Suggested tests

```text
test_record_round_trip
test_record_with_multiple_types_round_trip
test_record_with_empty_varchar
test_record_with_unicode_varchar
test_two_records_have_independent_serialization
test_malformed_record_is_rejected
```

---

## Definition of Done

A `Record` can be converted to bytes and reconstructed using only the schema and serialized payload.

---

# 11. Task 2.6 — Implement `PageHeader`

## Objective

Represent page-level metadata required by the slotted-page implementation.

Possible fields include:

```text
page_id
slot_count
free_space_start
free_space_end
active_record_count
```

Only include fields that are actually needed.

Do not copy a header from an unrelated DBMS simply because it exists there.

---

## Required behavior

The header should allow the page to determine:

- number of slots;
- where slot metadata ends;
- where record payload begins;
- how much contiguous free space remains;
- page identity if the chosen format stores it.

---

## Suggested tests

```text
test_empty_page_header
test_header_round_trip
test_header_tracks_slot_count
test_header_tracks_free_space_boundaries
```

---

## Definition of Done

The page header contains enough information to reconstruct page state from disk.

---

# 12. Task 2.7 — Implement `SlotEntry`

## Objective

Represent one entry in the page slot directory.

Recommended conceptual fields:

```text
offset
length
status
```

An equivalent compact representation is acceptable.

---

## Required behavior

A slot must allow the page to:

- locate active record bytes;
- recognize an unused/deleted slot;
- preserve stable `slot_id` semantics;
- survive serialization/deserialization.

---

## Suggested tests

```text
test_active_slot_round_trip
test_deleted_slot_round_trip
test_slot_rejects_invalid_offset
test_slot_rejects_invalid_length
```

---

## Definition of Done

Slot metadata can be persisted and used to locate records safely.

---

# 13. Task 2.8 — Implement the empty `Page`

## Objective

Create a new valid page in memory.

An empty page should have:

```text
valid header
zero active records
zero or valid initial slot count
maximum available free space
exact PAGE_SIZE serialized size
```

---

## Core API

Names may vary, but the page should expose concepts similar to:

```text
page_id
free_space()
slot_count
active_record_count
serialize()
deserialize()
```

Do not add Heap File methods such as:

```text
find_page_for_record()
```

to `Page`.

---

## Suggested tests

```text
test_create_empty_page
test_empty_page_has_expected_free_space
test_empty_page_has_zero_active_records
test_empty_page_serializes_to_exact_page_size
test_empty_page_round_trip
```

---

## Definition of Done

A valid empty page can be created, serialized, and reconstructed.

---

# 14. Task 2.9 — Implement record insertion into a page

## Objective

Insert serialized record bytes into one page.

Conceptually:

```text
slot_id = page.insert(record_bytes)
```

The higher-level caller can later construct:

```text
RID(page_id, slot_id)
```

---

## Required behavior

Before insertion:

```text
required_space =
    record_payload_size
    + slot_entry_size if a new slot is required
```

Insertion must fail cleanly when insufficient space exists.

Do not silently grow the page beyond `PAGE_SIZE`.

---

## Slot reuse

If deleted/free slots exist, the design may reuse them.

If a reused slot does not require a new slot-directory entry, free-space accounting must reflect that correctly.

---

## Suggested tests

```text
test_insert_one_record
test_insert_multiple_records
test_insert_returns_slot_id
test_insert_preserves_previous_records
test_insert_updates_free_space
test_insert_reuses_free_slot_if_policy_allows
test_insert_fails_when_page_is_full
test_page_size_never_changes
```

---

## Definition of Done

Variable-sized record payloads can coexist safely inside one fixed-size page.

---

# 15. Task 2.10 — Implement record lookup by slot

## Objective

Retrieve serialized bytes using a slot identifier.

Conceptually:

```text
record_bytes = page.read(slot_id)
```

---

## Required behavior

The method must distinguish:

```text
valid active slot
deleted/free slot
slot outside valid range
corrupted slot metadata
```

Do not return arbitrary bytes for invalid slots.

---

## Suggested tests

```text
test_read_inserted_record
test_read_multiple_slots
test_invalid_slot_is_rejected
test_deleted_slot_is_not_returned_as_active_record
```

---

## Definition of Done

Any active record inside a page can be retrieved by stable `slot_id`.

---

# 16. Task 2.11 — Implement page-local deletion

## Objective

Provide the low-level delete primitive needed by Stage 3 file organizations.

This task is **not** the Paged Sequential File lazy-deletion policy.

Stage 2 only defines what happens to one page slot.

---

## Possible behavior

A page-local delete may:

```text
mark slot FREE/DELETED
decrease active record count
make its payload reclaimable
```

The adopted semantics must be explicit.

---

## RID consideration

If slot reuse is allowed later, a previously deleted RID could eventually refer to a newly inserted record occupying the same slot.

This is acceptable only if the project consciously adopts that model.

Do not introduce generation counters unless needed.

---

## Suggested tests

```text
test_delete_active_slot
test_deleted_slot_is_not_readable
test_delete_updates_active_count
test_double_delete_is_handled
test_deleted_space_can_be_reclaimed_according_to_policy
```

---

## Definition of Done

The Page layer can remove a record without depending on Heap File or Sequential File logic.

---

# 17. Task 2.12 — Implement page compaction if required by the adopted layout

## Objective

Reclaim fragmented payload space while keeping slot identifiers stable.

Recommended conceptual behavior:

```text
before:

slots               payload area
0 -> record A        [A][hole][B][hole][C]
1 -> deleted
2 -> record B
3 -> deleted
4 -> record C

after compaction:

slots               payload area
0 -> updated offset  [A][B][C]
1 -> deleted
2 -> updated offset
3 -> deleted
4 -> updated offset
```

The record bytes may move.

The `slot_id` should not change.

---

## When compaction is needed

Depending on the chosen page layout, insertion may trigger compaction when:

```text
total reclaimable space >= required space
```

but contiguous free space is insufficient.

---

## Suggested tests

```text
test_compaction_preserves_active_records
test_compaction_preserves_slot_ids
test_compaction_updates_offsets
test_compaction_recovers_contiguous_space
test_page_round_trip_after_compaction
```

---

## Definition of Done

If the page design permits internal fragmentation, the adopted strategy can safely recover that space.

If the chosen page design does not require an explicit compaction operation, document why and mark this task not applicable.

---

# 18. Task 2.13 — Implement complete Page serialization/deserialization

## Objective

Persist every piece of information required to reconstruct a Page.

The serialized representation must include:

```text
PageHeader
slot directory
record payloads
unused/free bytes
```

and must always occupy exactly:

```text
PAGE_SIZE
```

---

## Deserialization validation

Reject malformed pages where possible, for example:

```text
invalid header
slot outside page boundaries
negative/invalid lengths
free-space pointers crossed
record payload outside page
unexpected page size
```

---

## Suggested tests

```text
test_page_round_trip_with_records
test_page_round_trip_with_deleted_slots
test_page_round_trip_after_compaction
test_page_serialization_is_exactly_page_size
test_corrupted_slot_is_rejected
test_corrupted_header_is_rejected
```

---

## Definition of Done

A complete in-memory Page survives a byte-level round trip without losing logical state.

---

# 19. Task 2.14 — Implement `FileHeader`

## Objective

Persist file-level metadata required to locate and validate data pages.

Minimum recommended concepts:

```text
magic / signature
format version
page size
number of allocated data pages
```

The exact fields depend on the design selected in Task 2.2.

---

## File signature

A signature allows the program to distinguish its database file from arbitrary bytes.

Example concept:

```text
MINIDB
```

Do not use a particular value unless adopted by the project.

---

## Format version

A version number makes future format changes detectable.

This can remain very simple.

---

## Suggested tests

```text
test_file_header_round_trip
test_file_header_rejects_wrong_magic
test_file_header_rejects_unsupported_version
test_file_header_tracks_page_count
test_file_header_tracks_page_size
```

---

## Definition of Done

A database file can identify its format and core physical parameters after reopen.

---

# 20. Task 2.15 — Implement `PageManager`

## Objective

Centralize physical page allocation and I/O.

Higher layers should not perform raw `seek()` calculations themselves.

---

## Minimum conceptual API

```text
create(...)
open(...)
allocate_page() -> page_id
read_page(page_id) -> Page
write_page(page)
flush()
close()
```

The exact class name may be:

```text
PageManager
DiskManager
PagedFile
```

Reuse an existing compatible abstraction if present.

---

## Offset calculation

Raw page offsets must be defined in one place according to the chosen file-header strategy.

Conceptually:

```text
physical_offset(page_id)
```

should be a helper owned by the physical I/O layer.

---

## Allocation

Allocating a page must:

- produce a valid new `page_id`;
- initialize a valid empty page;
- update file metadata;
- extend the file correctly.

Do not implement Heap File free-page selection here.

---

## Suggested tests

```text
test_create_database_file
test_open_existing_database_file
test_allocate_first_page
test_allocate_multiple_pages
test_read_written_page
test_write_updates_existing_page
test_invalid_page_id_is_rejected
test_close_and_reopen
```

---

## Definition of Done

Pages can be allocated, persisted, read, rewritten, flushed, closed, and reopened through one physical I/O abstraction.

---

# 21. Task 2.16 — Add basic physical I/O counters

## Objective

Prepare low-cost instrumentation that later benchmarks and execution plans can reuse.

This task is recommended because `PROJECT_CONTEXT.md` already anticipates metrics such as:

```text
pages_read
pages_written
```

Possible counters:

```text
pages_read
pages_written
pages_allocated
```

---

## Important rule

Counters must reflect actual I/O operations.

Do not fabricate values.

Do not build the complete Stage 10 benchmark system now.

---

## Suggested tests

```text
test_read_counter_increments
test_write_counter_increments
test_allocate_counter_increments
test_counter_reset_if_supported
```

---

## Definition of Done

If adopted, basic page-I/O statistics are accurate and isolated from business logic.

This task may be deferred only if the project explicitly chooses to instrument I/O later.

---

# 22. Task 2.17 — Add persistence and restart tests

## Objective

Prove that Stage 2 provides real persistence rather than only in-memory correctness.

A required test pattern is:

```text
1. create database file
2. allocate page
3. insert serialized records
4. write page
5. flush
6. close
7. create a new PageManager instance
8. reopen same file
9. read page
10. recover record bytes
11. deserialize Record
12. compare with original values
```

The test should instantiate fresh objects after reopen.

Do not reuse the same in-memory Page instance and call that persistence.

---

## Multi-page persistence

Also test:

```text
page 0
page 1
page 2
...
```

according to the adopted page-id strategy.

---

## Suggested tests

```text
test_record_survives_close_and_reopen
test_multiple_pages_survive_restart
test_deleted_slot_state_survives_restart
test_file_header_survives_restart
```

---

## Definition of Done

Persisted state is recoverable from disk by a fresh process-equivalent object graph.

---

# 23. Task 2.18 — Add malformed-file and boundary tests

## Objective

Fail predictably when physical data is invalid.

At minimum consider:

```text
file too short
invalid file signature
unsupported version
wrong page size
read beyond allocated page count
truncated page
record too large to fit in an empty page
invalid slot id
corrupted slot metadata
```

---

## Oversized records

Stage 2 must define behavior when:

```text
serialized_record_size > maximum record space in one page
```

For Part 1, a valid simple policy is to reject that record with a clear error.

Do not implement overflow pages unless the project explicitly adopts them.

---

## Suggested tests

```text
test_reject_record_larger_than_page_capacity
test_reject_truncated_file
test_reject_invalid_file_magic
test_reject_read_past_last_page
test_reject_truncated_page
```

---

## Definition of Done

Physical-storage failures produce controlled domain errors instead of silent corruption.

---

# 24. Task 2.19 — Add the Stage 2 end-to-end integration test

## Objective

Connect Stage 1 abstractions to Stage 2 persistence.

The integration path should be:

```text
Schema
  |
  v
Record
  |
  v
RecordCodec.serialize
  |
  v
Page.insert
  |
  v
PageManager.write
  |
  v
close
  |
  v
reopen
  |
  v
PageManager.read
  |
  v
Page.read
  |
  v
RecordCodec.deserialize
  |
  v
Record
```

---

## Example scenario

Conceptually:

```python
schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
])

original = Record(
    schema=schema,
    values=[1, "Ana"],
)

payload = record_codec.serialize(original)

page_id = page_manager.allocate_page()
page = page_manager.read_page(page_id)
slot_id = page.insert(payload)
page_manager.write_page(page)

page_manager.close()

page_manager = PageManager.open(path)
page = page_manager.read_page(page_id)

payload = page.read(slot_id)
recovered = record_codec.deserialize(schema, payload)

assert recovered == original
```

Exact APIs may differ.

---

## Definition of Done

One integration test proves the full Stage 1 → Stage 2 persistence pipeline.

---

# 25. Task 2.20 — Update architecture documentation

## Objective

Promote stable Stage 2 decisions to `PROJECT_CONTEXT.md`.

At minimum document the decisions that were resolved:

```text
PAGE_SIZE
page layout
slot layout
RID stability policy
record binary encoding
VARCHAR encoding
file-header strategy
byte order
NULL policy
catalog persistence policy
PageManager responsibility
page-local deletion semantics
compaction policy
I/O counters if adopted
```

Do not record temporary implementation experiments as stable architecture.

---

# 26. Recommended implementation order

```text
2.1  Inspect Stage 1 / repository
          |
          v
2.2  Resolve physical-storage decisions
          |
          v
2.3  Binary constants / invariants
          |
          v
2.4  Primitive value encoding
          |
          v
2.5  RecordCodec
          |
          +-------------------+
          |                   |
          v                   v
2.6  PageHeader          2.7 SlotEntry
          |                   |
          +---------+---------+
                    |
                    v
             2.8 Empty Page
                    |
                    v
             2.9 Page insert
                    |
                    v
             2.10 Page read
                    |
                    v
             2.11 Page delete
                    |
                    v
             2.12 Compaction
                    |
                    v
             2.13 Page round-trip
                    |
                    v
             2.14 FileHeader
                    |
                    v
             2.15 PageManager
                    |
                    v
             2.16 I/O counters
                    |
                    v
             2.17 Restart tests
                    |
                    v
             2.18 Boundary/corruption tests
                    |
                    v
             2.19 Integration test
                    |
                    v
             2.20 Documentation
```

Some adjacent tasks may be implemented together when that produces a smaller, clearer design.

Do not collapse all Stage 2 work into one large unreviewable change.

---

# 27. Recommended test organization

A possible layout is:

```text
tests/
├── storage/
│   ├── test_value_codec.py
│   ├── test_record_codec.py
│   ├── test_page_header.py
│   ├── test_slot_entry.py
│   ├── test_page.py
│   ├── test_file_header.py
│   ├── test_page_manager.py
│   └── test_persistence.py
│
└── integration/
    └── test_stage2_persistence_pipeline.py
```

This is illustrative.

Follow the existing repository test layout if it is already coherent.

---

# 28. Recommended commit strategy

Possible incremental commits:

```text
docs: start stage 2 persistence plan

feat(storage): add deterministic primitive codecs

feat(storage): add schema-based record codec

feat(storage): define page header and slot metadata

feat(storage): implement slotted page insertion and lookup

feat(storage): add page-local deletion and compaction

feat(storage): add page serialization validation

feat(storage): add persistent file header

feat(storage): implement page manager

test(storage): add restart and malformed-file tests

test(stage2): add persistence pipeline integration test

docs: record stage 2 physical-format decisions
```

Exact commit boundaries may differ.

---

# 29. Recommended validation commands

If the project uses pytest:

```bash
pytest tests/storage -q
```

Then:

```bash
pytest tests/integration -q
```

At the end of the stage:

```bash
pytest -q
```

Optional syntax/import check:

```bash
python -m compileall engine
```

Also verify persistence with tests that use temporary files/directories rather than writing test artifacts into the repository.

---

# 30. Stage 2 Definition of Done

Stage 2 is complete only when all applicable items are satisfied.

## Architecture decisions

```text
[x] page size is explicitly adopted
[x] page layout is documented
[x] slot layout is documented
[x] record encoding is documented
[x] file-header strategy is documented
[x] byte order is documented
[x] RID stability policy is documented
[x] NULL policy is explicit
[x] catalog persistence policy is explicit
```

## Serialization

```text
[x] adopted primitive types round-trip correctly
[x] VARCHAR framing is deterministic
[x] RecordCodec serializes Stage 1 Records
[x] RecordCodec reconstructs Records correctly
[x] malformed records are rejected
```

## Page

```text
[x] PageHeader
[ ] SlotEntry / slot directory
[ ] empty Page
[ ] variable-length record insertion
[ ] read by slot_id
[ ] page-local deletion
[ ] free-space accounting
[ ] compaction if required by adopted design
[ ] exact PAGE_SIZE serialization
[ ] Page deserialization
[ ] page invariant validation
```

## File persistence

```text
[ ] FileHeader
[ ] create database file
[ ] open database file
[ ] allocate page
[ ] write page
[ ] read page
[ ] rewrite page
[ ] flush
[ ] close
[ ] reopen
[ ] multiple-page persistence
```

## Reliability

```text
[ ] invalid page ids are rejected
[ ] oversized records are rejected cleanly
[ ] malformed/truncated files are handled
[ ] corrupted slot/header data is detected where practical
```

## Integration

```text
[ ] Stage 1 Record -> bytes -> Page -> disk works
[ ] disk -> Page -> bytes -> Stage 1 Record works
[ ] a fresh PageManager can reopen and recover data
[ ] all relevant tests pass
```

## Documentation

```text
[x] stable Stage 2 decisions are recorded in PROJECT_CONTEXT.md
[x] coordination documents identify Stage 2 correctly
[x] no Stage 3 algorithm was implemented unnecessarily
```

Only after this checklist is satisfied should the project move to Stage 3.

Partial verification note (tasks 2.2–2.6): all 696 currently implemented tests
pass. Full Page invariants, slot validation, allocated-page checks, oversized
insertion rejection and the disk round-trip remain unchecked because those
components do not exist yet. The initial in-memory integration test does not
satisfy task 2.19 or the complete-stage integration checklist.

---

# 31. What is NOT required to complete Stage 2

Do not require any of the following before declaring Stage 2 complete:

```text
[ ] HeapFile
[ ] PagedSequentialFile
[ ] file-level free-space selection
[ ] B+ Tree
[ ] Extendible Hashing
[ ] TableScan
[ ] SQL execution
[ ] transaction locks
[ ] buffer replacement algorithm
[ ] WAL
[ ] crash recovery
[ ] frontend
[ ] benchmark comparison graphs
```

Those belong to later stages unless the project explicitly changes its roadmap.

---

# 32. Risks to watch during Stage 2

## 32.1 Mixing logical and physical responsibilities

Bad direction:

```text
Page knows about SQL columns and query predicates
```

Preferred:

```text
RecordCodec knows Schema
Page stores bytes
```

---

## 32.2 Scattered offset arithmetic

Bad direction:

```text
raw seek formulas repeated across HeapFile, indexes, tests, and API
```

Preferred:

```text
PageManager owns physical page addressing
```

---

## 32.3 Fake persistence tests

Bad:

```text
write Page
read same in-memory Page object
```

Good:

```text
write
close
new manager instance
reopen
read from disk
```

---

## 32.4 Treating 4096 bytes as an official requirement

It is only a recommended default unless the team adopts it.

Once adopted, put it in `PROJECT_CONTEXT.md`.

---

## 32.5 Implementing Stage 3 too early

Stage 2 should not contain:

```text
HeapFile.find_free_page()
SequentialFile.insert_sorted()
```

Those algorithms consume Stage 2 primitives later.

---

## 32.6 Unstable RID semantics

Before indexes exist, decide whether page compaction and slot reuse can alter the meaning of a RID.

Document the policy now to avoid breaking B+ and Hash later.

---

# 33. Recommended prompt to start Stage 2 with Codex

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_01.md, and ETAPA_02.md.

Stage 1 is complete.

First inspect the repository and verify the completed Stage 1 APIs.
Then inspect any existing storage/page/serialization code.

Do not modify files yet.

Report:
1. which Stage 2 components already exist;
2. which existing code should be reused;
3. the current Record, Schema, RID, and storage-contract APIs;
4. unresolved Stage 2 architecture decisions;
5. any conflicts between code and the project documents;
6. the smallest safe implementation sequence for Stage 2.

Do not implement HeapFile, PagedSequentialFile, indexes, SQL,
transactions, API, or frontend functionality.
```

---

# 34. Recommended prompt for Task 2.2

After the repository inspection:

```text
Work only on Task 2.2 from ETAPA_02.md.

Based on the existing repository and Stage 1 abstractions,
propose the smallest coherent physical-storage design for:

- PAGE_SIZE
- slotted-page layout
- PageHeader fields
- SlotEntry fields
- RID stability
- FileHeader strategy
- byte order
- VARCHAR encoding
- NULL policy
- catalog persistence policy

Do not implement code yet.

Clearly separate:
1. official requirements;
2. existing architectural decisions;
3. your recommended new decisions.

The final adopted decisions will be recorded in PROJECT_CONTEXT.md.
```

---

# 35. Recommended prompt for the first coding task

After Task 2.2 decisions are approved and documented:

```text
Implement only the next incomplete task from ETAPA_02.md.

Reuse the completed Stage 1 abstractions.
Do not implement Stage 3 or later functionality.

Add or update only the relevant tests.
Run the relevant tests and report the results.

If implementation reveals a new stable architectural decision,
state it explicitly so PROJECT_CONTEXT.md can be updated.
```

---

# 36. Condition for moving to Stage 3

Move to Stage 3 only when:

```text
Stage 1 abstractions
      +
deterministic Record serialization
      +
valid fixed-size Pages
      +
stable slot-based addressing
      +
FileHeader
      +
PageManager
      +
close/reopen persistence
      +
boundary/error handling
      +
Stage 2 tests
      +
documented physical format
      =
READY FOR STAGE 3
```

Stage 3 should build Heap File and Paged Sequential File **on top of** these primitives rather than replacing them.
