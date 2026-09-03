# ETAPA_03.md

> Context version: **1.3** - aligned with `AGENTS.md`, `PROJECT_CONTEXT.md`, `REQUIREMENTS.md`, `PLAN.md`, and active Stage 3 tasks 3.1-3.11.

## Stage 3 - Heap File and Paged Sequential File

**Part:** Relational Database  
**Prerequisite:** Stage 2 complete  
**Previous stage:** Stage 2 - Pages, Records, and Base Persistence  
**Next stage:** Stage 4 - B+ Tree  
**Roadmap:** `PLAN.md`
**Status:** Active as of 2026-09-02; Tasks 3.1-3.11 complete; Task 3.12 pending.

---

# 1. Purpose

Stage 3 implements the two disk file organizations required for Part 1:

```text
HeapFile
PagedSequentialFile
```

It answers two different storage questions:

> **How can records be stored quickly in arrival order while reusing available page space?**

and:

> **How can records be kept ordered by a chosen key while supporting ordered insertion, lazy deletion, and periodic reorganization?**

Both organizations must use the Stage 2 physical layer:

```text
Schema / Record / RID
          |
          v
      RecordCodec
          |
          v
        Page
          |
          v
     PageManager
          |
          v
         Disk
```

Stage 3 must not replace `Page`, duplicate raw file-offset logic, or bypass `PageManager`.

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
ETAPA_03.md
    |
    |  detailed Stage 3 work
    v
CODE
```

`AGENTS.md` governs how Codex must work with these documents.

This stage document must not override:

- official requirements in `REQUIREMENTS.md`;
- stable decisions in `PROJECT_CONTEXT.md`;
- operating rules in `AGENTS.md`;
- the binary format adopted and tested during Stage 2.

When Stage 3 resolves a new architectural decision, promote it to `PROJECT_CONTEXT.md` after it becomes stable.

---

# 3. Stage transition requirement

Stage 2 is assumed to be complete.

Before implementing Stage 3, verify:

```text
[x] Stage 2 Definition of Done is satisfied
[x] all Stage 1 and Stage 2 tests pass
[x] RecordCodec is deterministic
[x] Page supports variable-length records
[x] slot-based lookup and deletion work
[x] page free-space accounting is correct
[x] Page serialization occupies exactly PAGE_SIZE bytes
[x] FileHeader is stable
[x] PageManager can create, open, allocate, read, write, flush, and close
[x] close/reopen persistence tests use fresh objects
[x] malformed pages/files fail predictably
[x] physical-format decisions are recorded in PROJECT_CONTEXT.md
```

Because the project has moved to Stage 3, the `Current stage` sections of the coordination documents should point to:

```text
Stage 3 - Heap File and Paged Sequential File
ETAPA_03.md
```

If `AGENTS.md` or `PROJECT_CONTEXT.md` still identifies Stage 2 as current, report and correct that documentation mismatch before coding.

---

# 4. Official Stage 3 obligations

Stage 3 must preserve the distinction between requirements and project decisions.

## 4.1 Heap File

The official project requires:

```text
records stored in disk pages
records stored in arrival order
a strategy for reusing free space
```

## 4.2 Paged Sequential File

The official project requires:

```text
records ordered by a chosen key
insertion that maintains order
lazy deletion
a reorganization strategy
```

The assignment mentions more than 30% wasted space as an example reorganization trigger. The exact threshold is a project decision unless it has already been adopted in `PROJECT_CONTEXT.md`.

## 4.3 Later experimental use

Stage 10 must compare Heap File and Paged Sequential File using:

```text
insertion time for 1,000 / 10,000 / 100,000 records
primary-key search time
disk space used
reorganization time
```

Stage 3 does not run the final experiments, but its APIs and instrumentation must not prevent fair measurement later.

---

# 5. Scope of Stage 3

## Included

```text
HeapFile lifecycle
HeapFile insertion
HeapFile read by RID
HeapFile deletion
HeapFile active-record scan
file-level free-space tracking
free-space reuse
PagedSequentialFile lifecycle
ordered-key definition
ordered insertion
exact-key search
ordered active-record scan
lazy deletion
wasted-space measurement
reorganization trigger policy
physical reorganization
RID behavior during reorganization
organization-specific metadata
close/reopen persistence
I/O-counter compatibility
unit, functional, persistence, and integration tests
architecture documentation updates
```

## Explicitly not included

```text
B+ Tree nodes or traversal
clustered B+ implementation
unclustered B+ implementation
Extendible Hashing
TableScan operator
IndexScan operator
SQL parser
Planner
Executor
transactions
concurrency control
buffer replacement policy
WAL / crash recovery
REST API
frontend
final 1K / 10K / 100K benchmark report
benchmark charts
```

Stage 3 must expose storage behavior that later stages can consume. It must not implement later stages under different names.

---

# 6. Architectural boundaries

The preferred dependency direction is:

```text
HeapFile ----------------------+
                               |
PagedSequentialFile -----------+--> PageManager --> Page --> Disk
                               |
RecordCodec -------------------+
```

Important rules:

- file organizations decide **which page** should receive or provide a record;
- `Page` decides whether and how serialized bytes fit inside one page;
- `PageManager` owns page allocation and physical I/O;
- `RecordCodec` owns conversion between `Record` and bytes;
- neither file organization should repeat raw `seek()` arithmetic;
- neither file organization should parse SQL;
- neither file organization should pretend that a linear page directory is a B+ Tree;
- shared behavior may be factored into small helpers, but the two organizations must retain distinct policies.

---

# 7. Task 3.1 - Inspect the completed Stage 2 implementation

**Status: complete (2026-09-02).** The inspection found no required Stage 2
format change; Stage 3 can compose the existing codecs, pages and manager.

## Objective

Determine the exact APIs and persisted formats that Stage 3 must reuse.

## Inspect

Codex should review:

- `Schema`, `Record`, and `RID`;
- `RecordCodec`;
- `PageHeader` and `SlotEntry`;
- page insertion, lookup, deletion, and compaction semantics;
- `FileHeader`;
- `PageManager` create/open/allocation/read/write/flush/close behavior;
- page-I/O counters;
- storage contracts from Stage 1;
- all Stage 2 tests;
- physical-format decisions in `PROJECT_CONTEXT.md`;
- existing code named similarly to `HeapFile`, `SequentialFile`, or `PagedSequentialFile`.

## Questions that must be answered

```text
What does Page.insert(...) accept and return?
How is a deleted slot represented?
Can deleted space be reused immediately?
Does page compaction preserve slot_id?
How are pages allocated and enumerated?
Can FileHeader store organization-specific metadata?
Are I/O counters already available?
What does the Stage 1 Storage.scan() contract yield?
```

## Expected output

Before modifying code, report:

```text
Reusable Stage 2 APIs:
- ...

Missing Stage 3 components:
- ...

Required minimal Stage 2 extensions:
- ...

Potential conflicts:
- ...

Recommended implementation sequence:
- ...
```

## Restriction

Do not modify code during Task 3.1.

---

# 8. Task 3.2 - Resolve Stage 3 architectural decisions

**Status: complete (2026-09-02).** The adopted decision set is recorded in
`PROJECT_CONTEXT.md` under "Stage 3 file-organization decisions".

## Objective

Choose the smallest coherent design for both organizations before implementing their algorithms.

The following decisions must be explicit.

## 8.1 Physical file ownership

Decide whether each table/organization uses:

```text
one independent paged file
```

or another already-adopted layout.

Do not introduce multiple competing storage layouts.

## 8.2 Organization identification

Persist enough metadata to reject opening a Heap File as a Paged Sequential File or vice versa.

Possible metadata:

```text
organization type
format version
table/schema identity if adopted
organization-specific counters
```

## 8.3 Heap insertion-order interpretation

The project requires arrival-order storage and free-space reuse. These can conflict when a new record is placed into a hole on an earlier page.

Choose and document the exact rule. A reasonable interpretation is:

```text
append when no reusable page fits;
reuse eligible free space when available;
physical scan order is not guaranteed to remain chronological after reuse.
```

Do not claim strict chronological scan order if hole reuse can violate it.

## 8.4 Heap free-space strategy

Choose one file-level strategy:

```text
free-page list
free-space directory
simplified free-space map
rebuildable in-memory directory derived from pages
```

Specify whether it is persisted or rebuilt on open.

## 8.5 Sequential physical organization

Choose one coherent strategy for maintaining key order across pages. Examples include:

```text
ordered primary pages with an auxiliary/overflow area and periodic merge
```

or:

```text
direct ordered placement with page redistribution/splitting and controlled record movement
```

Do not implement both. Do not introduce a tree index in this stage.

## 8.6 Sequential key definition

Define:

```text
which column is the ordering key
how the key is extracted from a Record
which key types are supported
how values are compared
whether duplicate keys are allowed
what search(key) returns when duplicates exist
```

Do not assume uniqueness unless table metadata explicitly provides it.

## 8.7 Lazy-deletion semantics

Define exactly what remains on disk after deletion and what operations must ignore tombstones.

Lazy deletion should not silently become immediate physical reorganization.

## 8.8 Wasted-space formula

Adopt a deterministic formula. Distinguish between:

```text
space occupied by logically deleted records
internal page fragmentation
ordinary unused capacity in the last page
auxiliary/overflow area if the adopted design uses one
```

Only include categories that the project intentionally defines as waste.

## 8.9 Reorganization trigger

Choose whether reorganization is:

```text
explicit only
automatically evaluated after deletion/insertion
both explicit and policy-driven
```

If a default threshold such as `0.30` is adopted, make it configurable and record it in `PROJECT_CONTEXT.md`.

## 8.10 RID behavior

Heap page compaction should follow the Stage 2 RID-stability policy.

Sequential insertion or reorganization may move records across pages. Decide whether:

```text
old RIDs are invalidated and indexes must be rebuilt
```

or:

```text
reorganization returns an old-RID -> new-RID mapping
```

This decision must be stable before Stage 4 and Stage 5 store RIDs in indexes.

## Required output of Task 3.2

Produce a documented decision set similar to:

```text
FILE_OWNERSHIP = ...
ORGANIZATION_METADATA = ...
HEAP_INSERTION_ORDER_POLICY = ...
HEAP_FREE_SPACE_STRATEGY = ...
HEAP_FREE_SPACE_PERSISTENCE = ...
SEQUENTIAL_PHYSICAL_STRATEGY = ...
SEQUENTIAL_KEY_POLICY = ...
DUPLICATE_KEY_POLICY = ...
LAZY_DELETE_POLICY = ...
WASTED_SPACE_FORMULA = ...
REORGANIZATION_TRIGGER = ...
REORGANIZATION_RID_POLICY = ...
```

Promote the adopted decisions to `PROJECT_CONTEXT.md`.

---

# 9. Task 3.3 - Define organization metadata and invariants

**Status: complete (2026-09-02).** `OrganizationType` and canonical,
versioned `OrganizationMetadata` are implemented in
`engine/storage/organization.py`, with strict round-trip/invariant tests.

## Objective

Persist the metadata required to reopen each organization without guessing.

## Possible common metadata

```text
organization type
format version
active record count
deleted record count
allocated page count
```

## Possible Heap metadata

```text
last append page
free-space-directory location or rebuild policy
```

## Possible Paged Sequential metadata

```text
key column identifier
key type
duplicate-key policy
primary/auxiliary page counts
reorganization threshold
```

Only persist fields needed by the adopted design.

## Required invariants

At minimum:

```text
metadata record counts match observable records
referenced page ids exist
organization type matches the class opening the file
sequential key metadata matches the schema
free-space entries do not reference invalid pages
reorganization threshold, if stored, is within a valid range
```

## Suggested tests

```text
test_heap_metadata_round_trip
test_sequential_metadata_round_trip
test_reject_wrong_organization_type
test_reject_invalid_record_counts
test_reject_invalid_key_metadata
```

---

# 10. Task 3.4 - Define the common file lifecycle

**Status: complete (2026-09-02).** `OrganizationFile` centralizes validated
create/open, metadata persistence, flush/close and context management while
leaving all raw file I/O in `PageManager`.

## Objective

Make creation, opening, flushing, closing, and context management consistent without hiding organization-specific behavior.

## Minimum lifecycle

Conceptually:

```text
create(path, schema, ...)
open(path, schema, ...)
flush()
close()
```

Optional Python convenience:

```python
with HeapFile.open(path, schema) as heap:
    ...
```

## Requirements

- opening must validate file and organization metadata;
- closing must flush modified metadata and pages according to the Stage 2 policy;
- operations on a closed file must fail predictably;
- repeated close should follow one documented behavior;
- tests must use temporary paths;
- do not add a buffer pool or WAL.

## Suggested tests

```text
test_create_and_close_heap_file
test_open_existing_heap_file
test_create_and_close_sequential_file
test_open_existing_sequential_file
test_context_manager_closes_file_if_supported
test_operation_after_close_is_rejected
```

---

# 11. Task 3.5 - Implement the `HeapFile` skeleton

**Status: complete (2026-09-02).** Empty create/open/count/scan and lifecycle
behavior established the `Storage` boundary; populated operations were then
completed in Tasks 3.7-3.10 below.

## Objective

Connect the Stage 1 storage contract to the Stage 2 persistence primitives.

## Minimum conceptual API

```text
insert(record) -> RID
read(rid) -> Record
delete(rid)
scan() -> iterator
flush()
close()
```

The exact scan item may be:

```text
Record
```

or:

```text
(RID, Record)
```

according to the existing storage contract. Later indexes need a reliable way to associate records with RIDs, so expose that capability without breaking the adopted interface.

## Initial behavior

At this task, creation/opening and empty-file behavior should work. Full insertion and deletion follow in later tasks.

## Suggested tests

```text
test_create_empty_heap_file
test_empty_heap_scan
test_empty_heap_record_count
test_heap_conforms_to_storage_contract
```

---

# 12. Task 3.6 - Implement Heap free-space tracking

**Status: complete (2026-09-02).** `HeapFreeSpaceTracker` selects the lowest
eligible page from an in-memory capacity directory and `HeapFile.open`
reconstructs it from validated data pages. `Page` remains the fit authority.

## Objective

Identify candidate pages without scanning every page for every insertion.

## Required capabilities

The chosen tracker must support concepts equivalent to:

```text
register newly allocated page
record page free-space change
find candidate page for required bytes
remove or update stale candidate
rebuild or reload after reopen
```

The tracker provides candidates. `Page` remains the final authority on whether the record fits.

## Correctness rule

If a tracker entry is stale:

```text
verify page
update tracker
continue safely
```

Do not overwrite a page or allocate endlessly because metadata was stale.

## Suggested tests

```text
test_register_page_in_free_space_tracker
test_tracker_selects_page_with_enough_space
test_tracker_skips_page_without_enough_space
test_tracker_updates_after_insert
test_tracker_updates_after_delete
test_tracker_handles_stale_entry
test_tracker_rebuilds_or_reloads_after_reopen
```

---

# 13. Task 3.7 - Implement Heap insertion

**Status: complete (2026-09-02).** Heap insertion serializes through
`RecordCodec`, safely refreshes stale candidates, reuses/compacts eligible
pages, allocates only when required and returns the exact physical RID.

## Objective

Insert a `Record` into an eligible page and return its physical RID.

## Conceptual path

```text
Record
  |
  v
RecordCodec.serialize
  |
  v
required byte count
  |
  v
free-space tracker
  |
  v
candidate Page
  |
  v
Page.insert
  |
  v
RID(page_id, slot_id)
```

## Required behavior

- reject a record that cannot fit in an empty page;
- reuse eligible free space according to the adopted policy;
- allocate a new page when no current page can fit the record;
- update record counts and free-space metadata;
- preserve all earlier records;
- route writes through `PageManager`;
- return the exact RID created by the successful page insertion.

## Suggested tests

```text
test_heap_insert_returns_rid
test_heap_insert_and_read_one_record
test_heap_insert_variable_length_records
test_heap_insert_fills_one_page
test_heap_insert_allocates_multiple_pages
test_heap_insert_reuses_eligible_free_space
test_heap_does_not_allocate_page_when_reusable_space_exists
test_heap_rejects_oversized_record
```

---

# 14. Task 3.8 - Implement Heap read by RID

**Status: complete (2026-09-02).** Heap reads validate the RID page range,
delegate slot state to `Page`, and reconstruct or reject payloads through the
persisted schema and `RecordCodec`.

## Objective

Recover a logical `Record` using `RID(page_id, slot_id)`.

## Conceptual path

```text
RID
 |
 v
PageManager.read_page
 |
 v
Page.read(slot_id)
 |
 v
serialized bytes
 |
 v
RecordCodec.deserialize
 |
 v
Record
```

## Required behavior

Distinguish:

```text
invalid page id
invalid slot id
deleted slot
corrupted payload
valid active record
```

## Suggested tests

```text
test_heap_read_by_rid
test_heap_read_from_multiple_pages
test_heap_rejects_invalid_page_id
test_heap_rejects_invalid_slot_id
test_heap_does_not_read_deleted_record
```

---

# 15. Task 3.9 - Implement Heap deletion and reuse

**Status: complete (2026-09-02).** Deletion persists the FREE slot, updates
active/deleted counts and capacity exactly once, rejects double deletion and
allows the stale RID value to name a later replacement when its slot is reused.

## Objective

Delete a record through its RID and make the resulting capacity reusable according to the adopted page policy.

## Required behavior

- validate the RID;
- use the Stage 2 page-local deletion primitive;
- decrement the active-record count exactly once;
- update free-space tracking;
- persist the modified page and metadata;
- handle double deletion predictably;
- allow a later insertion to reuse eligible capacity.

## RID note

If deleted slots may be reused, document whether a stale RID can later identify a different record. Do not add RID generation counters unless the architecture explicitly adopts them.

## Suggested tests

```text
test_heap_delete_active_record
test_heap_delete_updates_count
test_heap_double_delete_is_handled
test_heap_deleted_rid_is_not_readable
test_heap_reuses_space_after_delete
test_heap_reuse_survives_reopen
```

---

# 16. Task 3.10 - Implement Heap scan

**Status: complete (2026-09-02).** Scan lazily reads one page at a time and
yields each active `(RID, Record)` once in physical order without owning or
closing the shared storage handle.

## Objective

Iterate every active Heap record exactly once.

## Required behavior

- empty heap returns no records;
- all allocated data pages are considered;
- deleted slots are skipped;
- variable-length records are decoded correctly;
- scan does not load the entire file into memory unnecessarily;
- scan order is documented and not presented as key order;
- RIDs can be exposed where required by later index construction.

Heap scan is the correctness path later used for an unindexed primary-key search. Do not add an invisible index to accelerate it.

## Suggested tests

```text
test_scan_empty_heap
test_scan_one_page_heap
test_scan_multi_page_heap
test_scan_skips_deleted_records
test_scan_yields_each_active_record_once
test_scan_can_expose_rids_if_contract_requires
```

---

# 17. Task 3.11 - Validate Heap persistence and restart behavior

**Status: complete (2026-09-02).** Fresh-instance tests cover multipage data,
deletions, exact slot reuse, rebuilt capacity, reads/scans, continued writes and
a second reopen.

## Objective

Prove that Heap behavior survives a real close/reopen cycle.

## Required scenario

```text
create HeapFile
insert records across multiple pages
delete selected records
insert replacement records
flush and close
discard all in-memory objects
open with a new HeapFile/PageManager instance
read retained RIDs
verify deleted RIDs fail
scan all active records
insert again using recovered free-space state
close and reopen once more
verify final state
```

## Suggested tests

```text
test_heap_records_survive_restart
test_heap_deletions_survive_restart
test_heap_metadata_survives_restart
test_heap_free_space_state_survives_or_rebuilds
test_heap_can_continue_inserting_after_restart
```

---

# 18. Task 3.12 - Define the sequential ordering contract

## Objective

Create one deterministic comparison contract before implementing the sequential algorithms.

## Required decisions

```text
key column selection
key extraction
supported key data types
ascending order definition
duplicate-key behavior
tie-breaking policy if needed
comparison of invalid or unsupported values
```

## Rules

- use `Schema`/`Column` metadata rather than hard-coded column positions when possible;
- use one comparator consistently for insertion, search, scan validation, and reorganization;
- do not rely on string conversion to compare unrelated types;
- do not silently treat duplicate keys as unique;
- keep SQL collation and advanced locale rules out of this stage unless already adopted.

## Suggested tests

```text
test_extract_integer_key
test_extract_varchar_key_if_supported
test_reject_unknown_key_column
test_reject_unsupported_key_type
test_duplicate_key_policy
test_comparator_is_consistent
```

---

# 19. Task 3.13 - Implement the `PagedSequentialFile` skeleton

## Objective

Create/open an ordered file with persisted key metadata.

## Minimum conceptual API

```text
insert(record) -> RID
search(key)
delete(key or rid)
scan() -> iterator
wasted_space_ratio()
reorganize()
flush()
close()
```

Exact signatures must follow the existing repository style and the adopted duplicate/RID policies.

## Initial behavior

At this task:

- empty creation/opening works;
- key metadata is validated;
- empty search and scan work;
- incompatible schema or organization metadata is rejected.

## Suggested tests

```text
test_create_empty_sequential_file
test_empty_sequential_scan
test_empty_sequential_search
test_sequential_key_metadata_round_trip
test_open_with_incompatible_schema_is_rejected
```

---

# 20. Task 3.14 - Implement ordered active-record scan

## Objective

Yield all active records in nondecreasing key order according to the adopted physical strategy.

## Required behavior

- skip lazily deleted records;
- merge primary and auxiliary areas correctly if both exist;
- never return the same record twice;
- preserve duplicate-key semantics;
- stream records instead of materializing the entire file when the design permits;
- expose RIDs when required by the storage/index integration contract.

## Ordering invariant

For consecutive active records:

```text
key(previous) <= key(current)
```

according to the adopted comparator.

## Suggested tests

```text
test_sequential_scan_empty
test_sequential_scan_is_ordered
test_sequential_scan_handles_multiple_pages
test_sequential_scan_skips_lazy_deleted_records
test_sequential_scan_handles_duplicate_keys
test_sequential_scan_yields_each_active_record_once
```

---

# 21. Task 3.15 - Implement exact-key search

## Objective

Use the ordered organization to find active records with a requested key.

## Required behavior

- search an empty file safely;
- return no match for an absent key;
- return the correct result for first, middle, and last keys;
- ignore lazy-deleted matches;
- follow the duplicate-key policy;
- consider auxiliary/overflow records if the adopted design uses them;
- return or expose the corresponding RID where required.

## Search strategy

The implementation may use page boundaries, binary search, a sparse page directory, or another documented method consistent with the chosen organization.

Do not implement a B+ Tree or Extendible Hashing to satisfy this task.

## Suggested tests

```text
test_search_empty_sequential_file
test_search_first_key
test_search_middle_key
test_search_last_key
test_search_missing_key
test_search_ignores_deleted_match
test_search_duplicate_key_behavior
test_search_after_reopen
```

---

# 22. Task 3.16 - Implement ordered insertion

## Objective

Insert records supplied in arbitrary order while preserving the file's ordered-view invariant.

## Required cases

```text
insert into empty file
insert before the current minimum
insert after the current maximum
insert between existing keys
insert duplicate key according to policy
insert when target page has space
insert when target page has insufficient space
insert across a page boundary
```

## Required behavior

- serialize through `RecordCodec`;
- route page allocation and I/O through `PageManager`;
- keep organization metadata consistent;
- return the resulting RID if the storage contract requires it;
- preserve every existing active record;
- maintain the adopted ordering semantics;
- never silently exceed `PAGE_SIZE`;
- reject oversized records cleanly.

## Suggested tests

```text
test_insert_into_empty_sequential_file
test_insert_unsorted_input_produces_ordered_scan
test_insert_new_minimum
test_insert_new_maximum
test_insert_middle_key
test_insert_across_page_boundary
test_insert_duplicate_key_behavior
test_insert_variable_length_records
test_insert_rejects_oversized_record
```

---

# 23. Task 3.17 - Implement lazy deletion

## Objective

Make a record logically absent without immediately rebuilding the sequential file.

## Required behavior

- locate the target according to the adopted key/RID API;
- mark the record as logically deleted;
- keep enough information to measure its wasted space;
- exclude it from `search()` and normal `scan()`;
- update active/deleted counters;
- handle repeated deletion predictably;
- preserve the tombstone across reopen;
- avoid an implicit full-file reorganization.

## Stage 2 interaction

If the Stage 2 page delete operation immediately reclaims or compacts payload bytes, determine the smallest compatible extension needed for a durable tombstone.

Do not fork a second incompatible `Page` implementation solely for the sequential file.

## Suggested tests

```text
test_lazy_delete_by_adopted_identifier
test_lazy_deleted_record_is_not_searchable
test_lazy_deleted_record_is_not_scanned
test_lazy_delete_updates_counts
test_double_lazy_delete_is_handled
test_lazy_delete_survives_reopen
test_lazy_delete_does_not_trigger_unrequested_rebuild
```

---

# 24. Task 3.18 - Implement wasted-space measurement

## Objective

Calculate the metric used by the reorganization policy.

## Requirements

The formula must be:

- deterministic;
- documented;
- based on observable physical state;
- meaningful for variable-length records;
- consistent before and after restart;
- separate from final Stage 10 disk-space reporting.

Conceptual example only:

```text
wasted_space_ratio =
    bytes retained by lazy-deleted entries
    / usable bytes allocated to sequential data pages
```

The adopted formula may differ, but tests must make its numerator and denominator explicit.

## Suggested tests

```text
test_empty_sequential_waste_ratio
test_waste_ratio_before_delete
test_waste_ratio_after_one_delete
test_waste_ratio_uses_record_byte_lengths
test_waste_ratio_survives_reopen
test_waste_ratio_rejects_invalid_metadata
```

---

# 25. Task 3.19 - Implement the reorganization policy

## Objective

Decide when reorganization is needed without mixing the decision with the physical rewrite algorithm.

## Possible API

```text
should_reorganize() -> bool
```

with a separate:

```text
reorganize()
```

## Requirements

- use the documented wasted-space formula;
- use the configured threshold;
- define strict `>` versus inclusive `>=` behavior;
- allow explicit reorganization even when automatic triggering is disabled;
- do not run a full rewrite during a read-only search;
- do not disguise every insertion as reorganization.

## Suggested tests

```text
test_should_not_reorganize_below_threshold
test_threshold_boundary_behavior
test_should_reorganize_above_threshold
test_custom_reorganization_threshold
test_invalid_threshold_is_rejected
```

---

# 26. Task 3.20 - Implement physical reorganization

## Objective

Rewrite the Paged Sequential File so active records remain ordered and logically deleted space is removed.

## Conceptual flow

```text
current sequential file
        |
        v
ordered stream of active records
        |
        v
new compact temporary paged file
        |
        v
flush + validate
        |
        v
replace old organization state
        |
        v
reopen compact ordered file
```

## Required behavior

- preserve all active records exactly once;
- exclude lazy-deleted records;
- preserve nondecreasing key order;
- remove or reduce the measured wasted space according to the documented formula;
- update all organization metadata;
- work across multiple pages;
- follow the adopted RID invalidation/remapping policy;
- leave the original file usable if building the replacement fails before commit where practical;
- report actual elapsed/I/O information only through real instrumentation if exposed.

## Important boundary

This is a file rewrite, not WAL/crash recovery. Do not expand Stage 3 into a complete recovery subsystem.

## Suggested tests

```text
test_reorganize_empty_file
test_reorganize_without_deletions
test_reorganize_removes_tombstones
test_reorganize_preserves_all_active_records
test_reorganize_preserves_order
test_reorganize_updates_record_counts
test_reorganize_reduces_wasted_space
test_reorganize_multi_page_file
test_reorganize_follows_rid_policy
test_reorganized_file_survives_reopen
```

---

# 27. Task 3.21 - Validate sequential persistence and restart behavior

## Objective

Prove that the complete ordered-file lifecycle works after fresh reopen operations.

## Required scenario

```text
create PagedSequentialFile with key metadata
insert unsorted variable-length records
verify ordered scan
delete selected records lazily
flush and close
discard in-memory objects
open with a new instance
verify ordered scan and exact-key search
verify tombstones and waste metric
insert more records
trigger or call reorganization
close and reopen again
verify compact ordered active set
```

## Suggested tests

```text
test_sequential_records_survive_restart
test_sequential_order_survives_restart
test_sequential_key_metadata_survives_restart
test_sequential_tombstones_survive_restart
test_sequential_waste_metric_survives_restart
test_sequential_can_continue_inserting_after_restart
test_sequential_reorganization_survives_restart
```

---

# 28. Task 3.22 - Add operation-level error and boundary tests

## Objective

Ensure both organizations fail predictably instead of corrupting persisted data.

## Cases to cover

```text
wrong organization type
incompatible schema/key metadata
invalid RID
deleted RID
record larger than page capacity
stale free-space entry
corrupted organization metadata
empty-file operations
closed-file operations
unsupported key type
duplicate key conflict if duplicates are rejected
failed or interrupted reorganization before replacement
```

Reuse Stage 1/2 domain errors where appropriate. Add only a small, meaningful extension such as:

```text
StorageOrganizationError
InvalidRIDError
DuplicateKeyError
ReorganizationError
```

Do not create a large exception hierarchy without demonstrated value.

---

# 29. Task 3.23 - Preserve measurement readiness

## Objective

Make later comparison possible without implementing the final benchmark suite now.

## Required compatibility

Both file organizations should allow later code to measure:

```text
elapsed insertion time
elapsed primary-key search time
actual file size on disk
actual page reads/writes
sequential reorganization time
```

## Rules

- preserve Stage 2 physical I/O counters if they exist;
- do not fabricate operation costs;
- do not add a hidden index to Heap File;
- use the same `Schema`, `RecordCodec`, page size, and dataset for fair later comparison;
- do not run the final 1K/10K/100K experiment in Stage 3;
- do not hard-code performance assertions that depend on one machine.

## Suggested smoke tests

```text
test_heap_operations_update_real_io_counters_if_enabled
test_sequential_operations_update_real_io_counters_if_enabled
test_reorganization_reports_or_exposes_actual_io_if_enabled
test_file_size_can_be_observed_after_flush
```

---

# 30. Task 3.24 - Add Stage 3 end-to-end integration tests

## Objective

Connect the Stage 1/2 foundations to both Stage 3 file organizations.

## 30.1 Heap integration scenario

```text
Schema
  -> Records
  -> HeapFile.insert
  -> RIDs across pages
  -> delete selected RIDs
  -> reuse free space
  -> close/reopen
  -> read by RID + active scan
```

## 30.2 Sequential integration scenario

```text
Schema + ordering key
  -> unsorted Records
  -> PagedSequentialFile.insert
  -> ordered scan/search
  -> lazy delete
  -> waste threshold
  -> reorganize
  -> close/reopen
  -> compact ordered active set
```

## 30.3 Cross-organization equivalence

Insert the same logical dataset into both organizations and verify:

```text
same active logical records
different documented physical/access behavior
no shared mutable file state
real disk persistence
```

This is a correctness comparison, not the final performance experiment.

## Suggested tests

```text
test_stage3_heap_end_to_end
test_stage3_sequential_end_to_end
test_stage3_same_dataset_logical_equivalence
```

---

# 31. Task 3.25 - Update architecture and stage documentation

## Objective

Promote stable Stage 3 decisions and prepare the repository for Stage 4.

## Update `PROJECT_CONTEXT.md`

At minimum record:

```text
storage-file ownership model
organization metadata/versioning
Heap insertion-order interpretation
Heap free-space strategy
free-space tracker persistence/rebuild behavior
Heap scan contract
sequential physical strategy
sequential ordering-key representation
duplicate-key policy
lazy-delete representation
wasted-space formula
reorganization threshold and trigger behavior
reorganization replacement strategy
RID invalidation/remapping behavior
I/O instrumentation behavior
```

## Update current-stage references

While Stage 3 is active:

```text
Stage 3 - Heap File and Paged Sequential File
ETAPA_03.md
```

After its Definition of Done is satisfied and Stage 4 begins:

```text
Stage 4 - B+ Tree
ETAPA_04.md
```

Do not update the project to Stage 4 before Stage 3 is actually complete.

---

# 32. Recommended implementation order

```text
3.1  Inspect completed Stage 2
          |
          v
3.2  Resolve Stage 3 decisions
          |
          v
3.3  Organization metadata/invariants
          |
          v
3.4  Common file lifecycle
          |
          +-----------------------------+
          |                             |
          v                             v
3.5  Heap skeleton              3.12 Ordering contract
          |                             |
          v                             v
3.6  Free-space tracker         3.13 Sequential skeleton
          |                             |
          v                             v
3.7  Heap insert                3.14 Ordered scan
          |                             |
          v                             v
3.8  Heap read                  3.15 Exact-key search
          |                             |
          v                             v
3.9  Heap delete/reuse          3.16 Ordered insertion
          |                             |
          v                             v
3.10 Heap scan                  3.17 Lazy deletion
          |                             |
          v                             v
3.11 Heap restart tests         3.18 Wasted-space metric
                                        |
                                        v
                                3.19 Trigger policy
                                        |
                                        v
                                3.20 Reorganization
                                        |
                                        v
                                3.21 Sequential restart tests
          |                             |
          +---------------+-------------+
                          |
                          v
                 3.22 Boundary/error tests
                          |
                          v
                 3.23 Measurement readiness
                          |
                          v
                 3.24 Integration tests
                          |
                          v
                 3.25 Documentation
```

The Heap and Paged Sequential branches may proceed separately after Tasks 3.1-3.4, but shared Stage 2 primitives must not diverge into incompatible copies.

Do not collapse all Stage 3 work into one large unreviewable change.

---

# 33. Recommended test organization

A possible layout is:

```text
tests/
├── storage/
│   ├── test_heap_file.py
│   ├── test_heap_free_space.py
│   ├── test_heap_persistence.py
│   ├── test_sequential_ordering.py
│   ├── test_paged_sequential_file.py
│   ├── test_sequential_lazy_delete.py
│   ├── test_sequential_reorganization.py
│   └── test_sequential_persistence.py
│
└── integration/
    ├── test_stage3_heap_pipeline.py
    ├── test_stage3_sequential_pipeline.py
    └── test_stage3_storage_equivalence.py
```

This layout is illustrative.

Follow the existing repository structure if it is already coherent.

Use temporary directories/files so tests do not leave database artifacts in the repository.

---

# 34. Recommended commit strategy

Possible incremental commits:

```text
docs: start stage 3 file organization plan

feat(storage): add organization metadata and lifecycle

feat(storage): add heap free-space tracking

feat(storage): implement heap insert and read

feat(storage): implement heap deletion and scan

test(storage): add heap restart and reuse coverage

feat(storage): define sequential key ordering

feat(storage): implement sequential scan and search

feat(storage): implement ordered sequential insertion

feat(storage): add sequential lazy deletion and waste metrics

feat(storage): implement sequential reorganization

test(storage): add sequential restart and reorganization coverage

test(stage3): add file-organization integration tests

docs: record stage 3 architecture decisions
```

Exact commit boundaries may differ according to the repository state.

---

# 35. Recommended validation commands

If the project uses pytest:

```bash
pytest tests/storage/test_heap_file.py -q
```

Then:

```bash
pytest tests/storage/test_paged_sequential_file.py -q
```

Run the broader storage suite:

```bash
pytest tests/storage -q
```

Run Stage 3 integration tests:

```bash
pytest tests/integration -q
```

At the end:

```bash
pytest -q
```

Optional syntax/import check:

```bash
python -m compileall engine
```

Adapt paths to the actual repository. Do not create placeholder test files solely to make these exact commands valid.

---

# 36. Stage 3 Definition of Done

Stage 3 is complete only when all applicable items below are satisfied.

## Stage transition

```text
[x] Stage 2 Definition of Done was verified
[x] Stage 1 and Stage 2 tests still pass
[x] coordination documents identify Stage 3 correctly
```

## Shared organization layer

```text
[x] organization type is persisted and validated
[x] lifecycle create/open/flush/close behavior is defined
[x] organization metadata survives reopen
[x] schema/key compatibility is validated
[x] raw page offsets remain encapsulated by PageManager
```

## Heap File

```text
[x] insert(record) returns a valid RID
[x] read(rid) reconstructs the correct Record
[x] delete(rid) removes one active record
[x] scan visits every active record exactly once
[x] deleted records are skipped
[x] multiple pages are supported
[x] variable-length records are supported
[x] free space is actually reused
[x] unnecessary page allocation is avoided according to the chosen tracker
[x] insertion-order/reuse semantics are documented honestly
[x] free-space tracking survives or rebuilds correctly after reopen
[x] Heap state persists across fresh reopen operations
```

## Paged Sequential File

```text
[ ] ordering key is persisted and validated
[ ] comparator and duplicate-key policy are explicit
[ ] arbitrary insertion order produces an ordered active scan
[ ] insertion before, after, and between existing keys works
[ ] insertion across pages works
[ ] exact-key search works
[ ] lazy deletion works
[ ] deleted records are excluded from normal search and scan
[ ] wasted-space formula is documented and tested
[ ] reorganization threshold behavior is explicit
[ ] reorganize() preserves every active record exactly once
[ ] reorganize() removes logically deleted records
[ ] ordering remains valid after reorganization
[ ] RID remapping/invalidation behavior is implemented and documented
[ ] sequential state persists across fresh reopen operations
```

## Reliability

```text
[x] invalid RIDs fail predictably
[x] wrong organization type is rejected
[x] incompatible key/schema metadata is rejected
[x] oversized records are rejected cleanly
[x] stale free-space information cannot corrupt pages
[ ] reorganization failures are handled according to the adopted strategy
[x] all record/page/file counts remain consistent
```

## Integration and future readiness

```text
[ ] both organizations use the same Stage 2 Page/PageManager layer
[ ] both organizations use RecordCodec
[ ] both expose records/RIDs needed by later indexes
[x] Stage 2 I/O counters remain accurate if adopted
[ ] the same logical dataset can be stored in both organizations
[ ] all relevant unit, functional, persistence, and integration tests pass
[x] stable Stage 3 decisions are recorded in PROJECT_CONTEXT.md
[x] no Stage 4 or later algorithm was implemented unnecessarily
```

Only after this checklist is satisfied should the project move to Stage 4.

---

# 37. What is NOT required to complete Stage 3

Do not require any of the following before declaring Stage 3 complete:

```text
[ ] B+ Tree
[ ] clustered B+ integration
[ ] unclustered B+ integration
[ ] Extendible Hashing
[ ] SQL execution
[ ] relational operators
[ ] transaction locks
[ ] buffer pool replacement
[ ] WAL or crash recovery
[ ] REST API
[ ] frontend
[ ] final benchmark graphs
[ ] 100,000-record performance target
```

These belong to later stages unless the project explicitly changes its roadmap.

---

# 38. Risks to watch during Stage 3

## 38.1 Duplicating Stage 2 persistence logic

Bad:

```text
HeapFile calculates raw byte offsets and writes arbitrary bytes directly
```

Preferred:

```text
HeapFile chooses a page
PageManager performs page I/O
Page manages slots and payload bytes
```

## 38.2 Calling a page scan a free-space strategy

Scanning every page can be a temporary correctness baseline, but the final Heap design must contain the adopted free-space reuse strategy.

## 38.3 Claiming incompatible Heap guarantees

Strict arrival-order scan and arbitrary hole reuse may conflict.

Document the actual semantics rather than claiming both without qualification.

## 38.4 Hiding an index inside the sequential file

A small page-boundary directory may support the file organization, but Stage 3 must not pre-implement the B+ Tree or Extendible Hashing.

## 38.5 Treating Page compaction as sequential reorganization

Page compaction affects one page.

Sequential reorganization rebuilds the file organization and removes lazy-deletion waste across pages.

They are not the same operation.

## 38.6 Losing records during ordered insertion

When a target page is full, every displaced or overflow record must remain reachable exactly once.

Test page-boundary cases heavily.

## 38.7 Breaking RIDs without a policy

Stage 4 and Stage 5 indexes will store RIDs.

Record movement across pages must either produce a remapping or explicitly invalidate/rebuild dependent indexes.

## 38.8 Measuring waste ambiguously

Do not count ordinary unused capacity, tombstones, fragmentation, and overflow as the same concept unless the adopted formula deliberately does so.

## 38.9 Fake persistence or fake instrumentation

Restart tests must use fresh objects.

I/O metrics must come from actual PageManager operations.

## 38.10 Premature benchmarking

Stage 3 should be correct and measurable. Final experiment orchestration, plots, and conclusions belong to Stage 10.

---

# 39. Recommended prompt to start Stage 3 with Codex

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_01.md, ETAPA_02.md, and ETAPA_03.md.

Stages 1 and 2 are complete.

First inspect the repository and verify the completed Stage 2 APIs and tests.
Inspect any existing HeapFile, SequentialFile, free-space, or
organization-metadata code.

Do not modify files yet.

Report:
1. which Stage 3 components already exist;
2. which Stage 2 components and APIs must be reused;
3. how Page deletion, compaction, and slot reuse currently behave;
4. whether organization-specific metadata can be persisted cleanly;
5. all unresolved decisions listed in Task 3.2;
6. conflicts between code and project documents;
7. the smallest safe implementation sequence for Stage 3.

Do not implement B+ Tree, Extendible Hashing, relational operators,
SQL, transactions, API, frontend, or final benchmarks.
```

---

# 40. Recommended prompt for Task 3.2

After repository inspection:

```text
Work only on Task 3.2 from ETAPA_03.md.

Based on the existing Stage 2 implementation, propose the smallest
coherent architecture for:

- organization metadata and file ownership;
- Heap insertion-order semantics;
- Heap free-space tracking and persistence/rebuild behavior;
- Paged Sequential physical organization;
- ordering key and duplicate-key semantics;
- lazy deletion;
- wasted-space calculation;
- reorganization trigger;
- RID behavior during sequential insertion/reorganization.

Do not implement code yet.

Clearly separate:
1. official requirements;
2. stable existing decisions;
3. recommended new decisions;
4. alternatives rejected and why.

The adopted decisions must be recorded in PROJECT_CONTEXT.md before
dependent implementation becomes stable.
```

---

# 41. Recommended prompt for the first coding task

After Task 3.2 decisions are approved and documented:

```text
Implement only the next incomplete task from ETAPA_03.md.

Reuse the completed Stage 1 and Stage 2 abstractions.
Do not duplicate Page, PageManager, RecordCodec, or raw offset logic.

Add or update only the relevant tests.
Run the relevant tests and report the results.

If implementation reveals a new stable architectural decision,
state it explicitly so PROJECT_CONTEXT.md can be updated.

Do not implement Stage 4 or later functionality.
```

---

# 42. Condition for moving to Stage 4

Move to Stage 4 only when:

```text
completed Stage 1 abstractions
      +
stable Stage 2 physical persistence
      +
persistent multi-page HeapFile
      +
working free-space reuse
      +
persistent ordered PagedSequentialFile
      +
ordered insertion and exact-key search
      +
lazy deletion and measured waste
      +
tested reorganization
      +
explicit RID movement policy
      +
Stage 3 tests
      +
documented file-organization decisions
      =
READY FOR STAGE 4
```

Stage 4 should build B+ access on top of these storage organizations rather than replacing them.
