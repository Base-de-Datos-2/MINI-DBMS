# ETAPA_05.md

> Context version: **1.1** — aligned with AGENTS.md, PROJECT_CONTEXT.md, REQUIREMENTS.md, PLAN.md, and the completed ETAPA_01.md through ETAPA_04.md.

## Stage 5 — Extendible Hashing

**Part:** Relational Database  
**Prerequisite:** Stage 4 complete  
**Previous stage:** Stage 4 — B+ Tree  
**Next stage:** Stage 6 — Relational Operators and External Algorithms  
**Roadmap:** PLAN.md

---

# 1. Purpose

Stage 5 implements a persistent Extendible Hash index and integrates it with the storage, index, and catalog infrastructure completed in earlier stages.

It answers:

> **How can the DBMS locate exact keys through a disk-oriented hash structure that grows dynamically without rebuilding the complete index?**

The required lookup path is:

~~~text
typed key
  -> canonical key bytes
  -> stable hash value
  -> D selected bits
  -> directory entry
  -> bucket page
  -> complete key comparison
  -> matching RID or RID collection
~~~

When a bucket fills, only that bucket is split. The directory doubles only when the bucket local depth equals the global depth.

Extendible Hashing is an equality access path. It does not replace the B+ Tree for range predicates or ordered traversal.

---

# 2. Relationship with the project documents

The documentation authority remains:

~~~text
REQUIREMENTS.md
  -> official academic requirements

PROJECT_CONTEXT.md
  -> stable architecture decisions

PLAN.md
  -> Part 1 implementation order

ETAPA_05.md
  -> detailed current-stage work

AGENTS.md
  -> rules governing how Codex works
~~~

This document must not override:

- official requirements in REQUIREMENTS.md;
- stable decisions in PROJECT_CONTEXT.md;
- operating rules in AGENTS.md;
- the persisted page and record formats from Stage 2;
- HeapFile, PagedSequentialFile, and RID semantics from Stage 3;
- shared index contracts, key encoding, uniqueness, and maintenance policies from Stage 4.

Promote every stable Stage 5 decision to PROJECT_CONTEXT.md.

---

# 3. Stage transition requirement

Before implementation, verify:

~~~text
[ ] Stage 4 Definition of Done is satisfied
[ ] all Stage 1–4 tests pass
[ ] B+ exact and range lookup work after restart
[ ] clustered and unclustered B+ behavior is explicit
[ ] the shared Index contract is stable
[ ] canonical key and RID codecs are stable
[ ] duplicate and unique-index semantics are explicit
[ ] HeapFile can expose active records with their RIDs
[ ] record deletion and RID validation work
[ ] the RID movement/remapping policy is explicit
[ ] PageManager supports allocation, read, write, flush, close, and reopen
[ ] persistent header/version conventions exist
[ ] Catalog and IndexMetadata identify physical index implementations
[ ] actual page I/O counters remain available
[ ] Stage 4 decisions are recorded in PROJECT_CONTEXT.md
~~~

Current-stage references must identify:

~~~text
Stage 5 — Extendible Hashing
ETAPA_05.md
~~~

If coordination documents still identify Stage 4, update their current-stage references without rewriting completed-stage history.

---

# 4. Official obligations and minimum API

The official project requires an implementation of Extendible Hashing.

The minimum public behavior is:

~~~python
insert(key, rid)
search(key)
delete(key, rid)
~~~

The implementation must visibly include:

~~~text
Directory
Global Depth
Bucket
Local Depth
Bucket Split
Directory Doubling
Persistent Storage
~~~

The implementation must remain academically visible. Do not replace it with a Python dictionary, a third-party hash table, SQLite, PostgreSQL, or another database engine.

Stage 10 will compare Extendible Hashing with clustered and unclustered B+ indexes. Stage 5 must expose trustworthy metrics for that later work, but it must not perform the final experiments yet.

---

# 5. Structural invariants

Let:

~~~text
D = directory global depth
d = local depth of a bucket
~~~

The implementation must preserve:

~~~text
directory entry count = 2^D
0 <= d <= D
every directory entry references one valid bucket
every live bucket is referenced by at least one directory entry
references to a bucket = 2^(D - d)
all associations in a bucket match its directory-bit pattern
directory aliases are intentional and consistent
all persisted live buckets are reachable from the directory
~~~

If least-significant bits are selected:

~~~text
directory_index = hash_value & ((1 << D) - 1)
~~~

If most-significant bits are selected, the fixed hash width and extraction formula must be equally explicit. Select one convention and use it in search, insertion, split, validation, serialization, and tests.

After splitting a bucket of local depth d:

~~~text
old bucket local depth = d + 1
new bucket local depth = d + 1
old associations are redistributed using d + 1 bits
only the matching directory aliases are redirected
~~~

If d equals D before the split:

~~~text
global depth becomes D + 1
directory size doubles
old aliases are duplicated
the affected alias subset is redirected during the split
~~~

A hash match is never sufficient for key equality. Store and compare the complete encoded key.

---

# 6. Scope

## Included

- versioned persistent hash-index metadata;
- deterministic hashing and canonical typed-key bytes;
- a paged directory that may grow beyond one page;
- persistent bucket pages and local depth;
- exact-key search;
- insertion with and without structural growth;
- bucket splitting and directory doubling;
- repeated splits under skewed distributions;
- duplicate and unique-index policies;
- bounded full-hash collision behavior;
- deletion of exact key/RID associations;
- physical page allocation and safe reuse;
- an independent structural validator;
- restart and malformed-file tests;
- building an index from existing HeapFile records;
- Catalog and IndexMetadata integration;
- maintenance after table insert, delete, update, or RID movement;
- real I/O and structural counters;
- optional buddy merge and directory shrinking;
- unit, property, persistence, and integration tests;
- architecture documentation updates.

## Explicitly excluded

- ordered or range lookup through hashing;
- Stage 6 relational operators and external algorithms;
- SQL parsing, planning, or execution;
- transactions, locking, and concurrent mutation;
- WAL and crash recovery;
- API and frontend work;
- final benchmark graphs and conclusions;
- linear or distributed hashing;
- production-grade online index construction.

Buddy merging and directory shrinking are optional. They must not block the required API, split, doubling, persistence, and integration behavior.

---

# 7. Recommended module boundary

Adapt names to the actual repository. Do not create parallel abstractions when an existing one can be extended safely.

~~~text
engine/
  indexes/
    extendible_hash.py
    hash_directory.py
    hash_bucket.py
    hash_codec.py
    hash_validator.py
  storage/
    page_manager.py
  catalog/
    index_metadata.py

tests/
  unit/indexes/
  property/indexes/
  persistence/indexes/
  integration/indexes/
~~~

Prefer one public ExtendibleHashIndex facade. Directory and bucket mutation should remain internal.

---

# 8. Task 5.1 — Inspect the completed Stage 4 implementation

## Objective

Map Stage 5 concepts to the real repository before selecting formats or interfaces.

## Actions

- Read all five coordination documents and this stage document.
- Inspect the Stage 1–4 code and tests.
- Locate the Index contract and B+ public API.
- Record how typed keys, RIDs, page IDs, and index metadata are encoded.
- Confirm duplicate, unique, and repeated-association behavior.
- Inspect page allocation, deallocation, free-page reuse, flush, and reopen.
- Confirm how table mutation and RID movement maintain Stage 4 indexes.
- Locate physical I/O and index-structure counters.
- Run the complete suite and save a baseline.

## Deliverable

A short implementation note containing:

- reused components;
- components requiring extension;
- missing prerequisites;
- detected documentation/code conflicts;
- baseline test results.

## Acceptance criteria

No duplicate key, RID, page, error, metrics, or Catalog abstraction is introduced.

---

# 9. Task 5.2 — Resolve physical and algorithmic decisions

## Objective

Freeze every choice that affects persisted bytes or observable index behavior.

| Decision | Required definition |
|---|---|
| Hash algorithm | Stable named algorithm and version |
| Hash width | Fixed unsigned 32-bit or 64-bit representation |
| Key bytes | Canonical encoding for every supported DataType |
| Selected bits | Least-significant suffix or most-significant prefix |
| Initial depth | Initial D and initial bucket topology |
| Maximum depth | Bound and behavior when reached |
| Bucket capacity | Serialized byte rule, not an accidental object count |
| Directory layout | Persistent paged representation and growth |
| Bucket layout | Page type, header, entries, and free-space layout |
| Value representation | One key/RID association or key with RID collection |
| Duplicate policy | Same public behavior as Stage 4 |
| Collision policy | Bounded behavior for unsplittable hashes |
| Deletion policy | Exact association deletion |
| Merge/shrink policy | Implemented now or explicitly deferred |
| Update ordering | Safe order for bucket, directory, and header writes |
| Corruption policy | Validation and domain-error behavior |

## Mandatory constraints

- Never use the language runtime's built-in hash for persisted keys.
- Reuse the Stage 4 key codec if it is canonical and deterministic.
- Do not assume the directory fits in one physical page.
- Do not ignore variable-length key bytes when calculating capacity.
- Do not silently change shared duplicate or unique semantics.
- Do not allow maximum-depth collisions to loop indefinitely.

## Deliverable

An accepted decision table, with stable choices added to PROJECT_CONTEXT.md.

## Acceptance criteria

A fresh process can reproduce the same hash and reopen the same structure using disk metadata alone.

---

# 10. Task 5.3 — Define the persistent index header

## Objective

Persist everything required to identify, reopen, and validate the index.

## Minimum fields

~~~text
magic number
format version
index identifier
table identifier
key-schema or indexed-column reference
unique/non-unique flag
hash algorithm and version
hash width
bit-selection convention
global depth
directory root/first page id
directory entry count
bucket layout/capacity version
maximum global depth
logical association count
optional free/allocated-page metadata
~~~

## Tests

- valid round trip;
- invalid magic or version;
- impossible depth or entry count;
- invalid page identifier;
- truncated header;
- mismatched key/hash metadata.

## Acceptance criteria

Opening the index never relies on constructor defaults that were not persisted.

---

# 11. Task 5.4 — Implement deterministic hashing and bit extraction

## Objective

Convert a typed key into stable bytes, a stable unsigned hash, and a directory index.

## Suggested internal API

~~~python
encode_key(key, key_schema) -> bytes
hash_bytes(encoded_key) -> int
directory_index(hash_value, global_depth) -> int
~~~

## Requirements

- Equal typed keys produce identical bytes and hashes across restarts.
- Different types do not become equal merely because their display strings match.
- String, numeric, Boolean, null, and floating-point policies follow the existing schema contract.
- Unsupported/null keys fail explicitly when not indexable.
- Depth is validated before bit extraction.
- Test injection may replace the hash function to force collisions.

## Tests

- golden hash vectors;
- process-independent repeatability;
- all supported key types and numeric boundaries;
- Unicode and empty strings;
- directory indexes at several depths;
- invalid depths;
- deliberately colliding unequal keys.

## Acceptance criteria

Results are independent of runtime hash randomization and remain compatible after reopen.

---

# 12. Task 5.5 — Implement the paged directory

## Objective

Represent the 2^D mapping from bit patterns to bucket page IDs.

## Required operations

~~~python
lookup_bucket(hash_value) -> page_id
get_entry(index) -> page_id
set_entry(index, page_id) -> None
double() -> None
iter_entries()
validate_shape() -> None
~~~

## Requirements

- Logical size always equals 2^D.
- Multiple entries may intentionally reference one bucket.
- Doubling preserves every old lookup before the affected bucket is split.
- Logical entry order remains stable on disk.
- Growth works beyond one directory page.
- Directory pages use existing allocation, typing, and validation mechanisms.

## Tests

- initial directory;
- every bit pattern at small depths;
- aliases;
- one and multiple doublings;
- crossing directory-page boundaries;
- malformed counts, links, and bucket references.

## Acceptance criteria

The directory is a real persistent paged structure, not an unbounded in-memory list with an undefined disk representation.

---

# 13. Task 5.6 — Implement the bucket model

## Objective

Store key/RID associations in page-sized buckets carrying local depth.

## Minimum metadata

~~~text
page type and format version
local depth
entry count
free-space or slot metadata
optional overflow reference if that policy is selected
~~~

## Required operations

~~~python
find(key) -> list[RID]
contains(key, rid) -> bool
can_fit(key, rid) -> bool
insert(key, rid) -> None
delete(key, rid) -> bool
iter_entries()
replace_entries(entries)
~~~

## Requirements

- Capacity is based on serialized bytes unless entries are truly fixed-size.
- Complete keys are compared after hash routing.
- Mutation cannot expose partially encoded entries.
- All contents can be enumerated for deterministic redistribution.
- Every accepted bucket serializes to exactly one page, excluding explicit overflow pages.

## Tests

- empty, partial, and full buckets;
- existing and missing keys;
- duplicate key with distinct RIDs;
- repeated key/RID policy;
- variable-length keys;
- deletion;
- malformed local depth, offsets, and counts.

## Acceptance criteria

Bucket bytes round-trip without changing entries, RIDs, or local depth.

---

# 14. Task 5.7 — Implement strict directory and bucket codecs

## Objective

Separate binary persistence from algorithms and reject malformed storage.

## Actions

- Define widths and byte order for every field.
- Encode directory entries and page-chain metadata.
- Encode bucket headers, keys, RIDs, and slots/offsets.
- Reuse existing checksums only if they are already part of the storage contract.
- Validate offsets, counts, overlap, page types, links, and truncation.
- Add stable golden fixtures for fields that define the disk format.

## Tests

- exact page-length assertions;
- directory round trip across multiple pages;
- bucket round trip for every supported key type;
- randomized codec round trips;
- truncated and corrupted pages;
- impossible offsets, counts, and links.

## Acceptance criteria

Valid pages round-trip exactly; invalid pages raise controlled domain errors.

---

# 15. Task 5.8 — Implement create, open, flush, and close

## Objective

Establish the lifecycle of an empty persistent hash index.

## Required behavior

~~~python
ExtendibleHashIndex.create(...)
ExtendibleHashIndex.open(...)
index.flush()
index.close()
~~~

Creation must allocate and persist a compatible header, directory, and initial bucket topology. Opening must reconstruct behavior solely from persisted metadata.

## Tests

- create and reopen an empty index;
- reject a non-hash or incompatible file;
- operations after close;
- repeated close according to project policy;
- failed creation cleanup;
- restart with entirely new PageManager and index objects.

## Acceptance criteria

The empty structure passes the validator before and after a real restart.

---

# 16. Task 5.9 — Implement exact-key search

## Objective

Use exactly one directory route and the selected bucket/overflow path.

~~~text
encode -> hash -> extract D bits -> directory -> bucket -> full-key comparison
~~~

## Requirements

- Return the result type defined by the shared Index contract.
- Return all and only matching RIDs.
- Preserve deterministic RID ordering if the project requires it.
- Validate bucket page type and local depth.
- Include actual directory and bucket reads in metrics.
- Never scan unrelated buckets.

## Tests

- empty index;
- existing and missing keys;
- duplicate keys;
- unique index;
- unequal keys with the same hash;
- before/after directory growth;
- after restart.

## Acceptance criteria

Hash equality never substitutes for complete key equality.

---

# 17. Task 5.10 — Implement insertion without structural growth

## Objective

Insert an association when the target bucket has enough serialized space.

## Requirements

- Validate key type and RID first.
- Route using current global depth.
- Enforce duplicate and unique constraints.
- Persist only the intended bucket and logical metadata.
- Leave global depth, local depth, and directory aliases unchanged.
- Define rollback/unchanged-state behavior for validation failures.

## Tests

- first and subsequent insertions;
- keys routed to the same/different buckets;
- duplicate key with distinct RIDs;
- repeated association;
- unique violation;
- invalid key and RID;
- reopen after insertion.

## Acceptance criteria

A non-overflowing insertion does not mutate directory topology.

---

# 18. Task 5.11 — Split a bucket when local depth is less than global depth

## Objective

Split a full aliased bucket without growing the directory.

## Required sequence

~~~text
read full bucket at local depth d
allocate a new bucket
set both local depths to d + 1
identify every directory alias of the old bucket
redirect the half selected by the new distinguishing bit
redistribute old associations plus the pending association
persist both buckets and affected directory entries
~~~

## Critical rules

- Pointer changes depend on the chosen bit convention.
- Unrelated directory entries remain unchanged.
- Redistribution includes every old association exactly once.
- Every result must route back to its final bucket.
- A failed split must not expose an uninitialized bucket.

## Tests

- split with d less than D;
- expected alias counts;
- redistribution to both sides;
- one side empty after redistribution;
- variable-sized keys;
- search every key and restart immediately after split.

## Acceptance criteria

Directory size is unchanged, both buckets have depth d+1, and no association is lost or duplicated.

---

# 19. Task 5.12 — Implement directory doubling

## Objective

Grow the directory when a full bucket has local depth equal to global depth.

## Required sequence

~~~text
verify D < MAX_GLOBAL_DEPTH
build logical directory of size 2^(D + 1)
duplicate old aliases using the chosen bit convention
persist the enlarged directory
update global depth to D + 1
split the full bucket
~~~

## Requirements

- All lookups remain equivalent immediately after alias duplication.
- Growth can cross one or many directory pages.
- Header and directory writes follow a documented order.
- Allocation or depth-limit failures are controlled.

## Tests

- first and multiple doublings;
- aliases for affected and unaffected buckets;
- growth across page boundaries;
- maximum-depth rejection;
- injected allocation/write failure when supported;
- restart after doubling.

## Acceptance criteria

The new directory contains exactly 2^(D+1) entries and every old association remains reachable.

---

# 20. Task 5.13 — Complete repeated-split insertion

## Objective

Continue splitting until the pending association fits or the declared collision/depth limit is reached.

## Requirements

- Recalculate the directory index after every depth change.
- Support skewed distributions requiring consecutive splits.
- Use an explicit loop or otherwise prove termination.
- Stop through the documented maximum-depth/collision policy.
- Preserve prior logical contents on failure.

## Tests

- one split;
- split plus doubling;
- several consecutive splits;
- keys sharing long selected-bit prefixes/suffixes;
- deterministic final contents;
- controlled termination at maximum depth.

## Acceptance criteria

No insertion is routed with stale depth, and pathological input cannot create an infinite split loop.

---

# 21. Task 5.14 — Enforce duplicate and unique semantics

## Objective

Match Stage 4 behavior wherever B+ and hash capabilities overlap.

## Required case matrix

~~~text
non-unique key + new RID
non-unique key + existing RID
unique key + first RID
unique key + different RID
delete one RID while others remain
delete final RID for the key
~~~

## Requirements

- Reuse shared uniqueness errors.
- Define whether identical reinsertion is idempotent or an error.
- Search aggregates all matching RIDs if associations are stored separately.
- Unique violations leave logical and physical contents unchanged.

## Tests

Cover the full matrix before/after splits and after restart.

## Acceptance criteria

Callers observe one consistent key/RID policy across index implementations.

---

# 22. Task 5.15 — Handle unsplittable full-hash collisions

## Objective

Prevent endless growth when distinct associations cannot be separated by additional hash bits.

## Select one bounded policy

- controlled persistent overflow pages/chains;
- an explicit capacity/depth error with unchanged prior contents;
- another persistent bounded strategy approved in PROJECT_CONTEXT.md.

## Requirements

- Equal hashes still require full key comparison.
- Splitting stops when remaining bits cannot separate contents.
- Existing associations survive a rejected insertion.
- If overflow is selected, search, deletion, validation, persistence, and metrics must traverse it.

## Tests

- injectable constant-hash function;
- distinct colliding keys;
- one key with many RIDs;
- maximum-depth boundary;
- restart with collision state;
- failed insertion preserves the prior index.

## Acceptance criteria

Adversarial collisions terminate predictably without unbounded directory growth.

---

# 23. Task 5.16 — Implement deletion

## Objective

Remove only the requested key/RID association.

## Required behavior

~~~python
delete(key, rid) -> bool
~~~

- Route using current global depth.
- Compare complete key and exact RID.
- Remove one association under the shared contract.
- Update counts and persist the bucket.
- Keep an empty bucket valid when merge is deferred.
- Do not change depths unless optional merge logic is invoked.

## Tests

- existing association;
- missing key;
- incorrect RID;
- one of several RIDs;
- final RID;
- split bucket;
- after restart;
- repeated deletion.

## Acceptance criteria

Deletion never makes another association unreachable and does not depend on directory shrinking.

---

# 24. Task 5.17 — Integrate allocation, deallocation, and page reuse

## Objective

Use Stage 2 physical-page ownership rules for directory and bucket pages.

## Requirements

- Allocate through PageManager.
- Use registered page types and existing validation.
- Free a bucket only when no directory entry references it.
- Distinguish directory-extension and bucket pages.
- Flush dirty pages through the established lifecycle.
- Count physical allocation, free, read, and write events.

## Tests

- enough buckets and directory entries for many pages;
- continue allocating after restart;
- safe reuse after cleanup or optional merge;
- no double-free of aliased buckets;
- no referenced page is freed;
- wrong page types are rejected.

## Acceptance criteria

No private, volatile allocator controls persistent hash pages.

---

# 25. Task 5.18 — Optionally merge buddy buckets

## Objective

Reclaim underused buckets after deletion without blocking the mandatory implementation.

Two buckets may merge only when:

~~~text
they differ only in the distinguishing bit at their local depth
they have the same local depth
their combined serialized associations fit in one bucket
~~~

If implemented:

- identify the buddy using the chosen bit convention;
- combine associations deterministically;
- decrease survivor local depth by one;
- redirect all relevant aliases;
- free the removed bucket only when no alias remains;
- validate after every merge.

## Tests

- eligible merge;
- unequal depths;
- combined data does not fit;
- pointer redirection;
- repeated merge;
- restart after merge.

## Acceptance criteria

Either the feature is fully validated or it is explicitly documented as deferred.

---

# 26. Task 5.19 — Optionally shrink the directory

## Objective

Reduce global depth when the highest directory bit is no longer required.

A common necessary condition is:

~~~text
maximum live bucket local depth < global depth
~~~

If implemented:

- verify the two logical directory halves are redundant under the selected convention;
- reduce entries from 2^D to 2^(D-1);
- decrement global depth;
- reclaim unused directory-extension pages;
- preserve the minimum/initial depth;
- persist header and directory safely.

## Tests

- one and multiple shrinks;
- rejected shrink while a bucket requires depth D;
- page-boundary reclamation;
- lookup and restart afterward.

## Acceptance criteria

Shrinking is optional and never delays required Stage 5 completion.

---

# 27. Task 5.20 — Implement an independent structural validator

## Objective

Detect invariant violations without relying on successful point lookups.

## Suggested API

~~~python
validate_structure(deep: bool = True) -> ValidationReport
~~~

## Required checks

- directory size equals 2^D;
- directory page links are valid and acyclic;
- all entries reference valid bucket pages;
- every bucket local depth is between zero and D;
- each bucket reference count equals 2^(D-d);
- aliases agree with the bucket's selected-bit pattern;
- each association hashes to its referenced bucket;
- bucket counts and free-space metadata are valid;
- unique-index constraints hold;
- required pages are not unexpectedly orphaned or multiply owned;
- persisted totals match recomputed totals when applicable.

## Tests

Corrupt each invariant independently: depths, aliases, references, placement, page chains, counts, and uniqueness.

## Acceptance criteria

Validation reports the violated invariant and relevant page/entry without mutating the index.

---

# 28. Task 5.21 — Add real restart tests

## Objective

Prove that correctness comes from disk state rather than surviving objects.

## Mandatory lifecycle

~~~text
create
insert enough associations to split and double
flush
close
destroy all in-memory objects
create a new PageManager
open from persisted metadata
search all keys
delete selected associations
insert additional associations
close and reopen again
validate structure and contents
~~~

## Scenarios

- empty and populated indexes;
- split without doubling;
- one and multiple doublings;
- duplicate and unique keys;
- delete after reopen;
- continue growth after reopen;
- multipage directory;
- full-hash collision policy;
- optional merge/shrink if implemented.

## Acceptance criteria

No restart test reuses the original index, directory, bucket, or PageManager object.

---

# 29. Task 5.22 — Build an index from existing HeapFile storage

## Objective

Create an Extendible Hash index for a table that already contains records.

## Required workflow

~~~text
scan active records with their RIDs
extract and validate the indexed key
insert key -> RID into a new physical index
enforce uniqueness when requested
flush and validate the completed index
publish Catalog metadata only after success
~~~

## Requirements

- Initial integration targets unclustered HeapFile records.
- Logically deleted records are excluded.
- Partial builds are not visible through Catalog.
- Failure cleans up or marks incomplete pages according to established policy.
- Collect build metrics without making final performance claims.

## Tests

- empty and populated tables;
- non-unique duplicate keys;
- uniqueness failure;
- variable-length keys;
- source spanning many pages;
- restart after build;
- failed-build cleanup.

## Acceptance criteria

Every active source RID is discoverable through its key after reopening the new index.

---

# 30. Task 5.23 — Maintain table/index consistency

## Objective

Keep hash associations synchronized with table mutation and RID movement.

## Actions

- Reuse Stage 4 maintenance services or hooks.
- Insert the new key/RID association after table insertion.
- Remove the exact association after table deletion.
- On indexed-key update, replace old with new under the established failure policy.
- Consume RID remaps or rebuild when storage reorganization moves records.
- Detect stale RIDs during validation/integration checks.

## Tests

- table insert, delete, and indexed-key update;
- multiple indexes when supported;
- reorganization with RID remap or rebuild;
- reopen after maintenance;
- stale RID detection.

## Acceptance criteria

Hash search never silently returns a RID that now identifies a different live record.

---

# 31. Task 5.24 — Integrate Catalog and IndexMetadata

## Objective

Identify, persist, open, and drop the hash index through shared metadata.

## Minimum metadata

~~~text
index id/name
table id/name
indexed columns or key schema
index type = EXTENDIBLE_HASH
unique flag
physical header/root location
hash algorithm/version
format version
creation/build state
~~~

## Requirements

- Validate table, columns, key type, and duplicate index names.
- Dispatch index opening by physical type.
- Persist enough information for restart.
- Drop physical pages and metadata safely.
- Advertise equality capability, not range/ordering capability.

## Tests

- create, register, open, restart, and drop;
- invalid table/column/type;
- duplicate name;
- correct B+ versus hash dispatch;
- interrupted/failed build state.

## Acceptance criteria

Callers need no hidden constructor values to reopen the index through Catalog.

---

# 32. Task 5.25 — Add metrics and domain errors

## Objective

Make the algorithm measurable and failures diagnosable.

## Suggested metrics

~~~text
directory page reads/writes
bucket page reads/writes
bucket allocations/frees
bucket splits
directory doublings
optional merges/shrinks
associations inspected
current global depth
current live bucket count
allocated index pages/bytes
~~~

## Suggested errors

~~~text
HashIndexFormatError
HashIndexCorruptionError
HashDepthLimitError
HashBucketOverflowError
UnsupportedHashKeyError
UniqueConstraintViolation
InvalidRIDError
ClosedIndexError
~~~

Reuse existing general errors when they already express the same contract.

## Requirements

- Count actual physical I/O where it occurs.
- Do not count a cache hit as a disk read.
- Define lifetime versus per-operation snapshots.
- Document counter behavior for failed operations.

## Acceptance criteria

Stage 10 can compare B+ and hash behavior using metrics with consistent meanings.

---

# 33. Task 5.26 — Add integration, property, and differential tests

## Objective

Verify the complete persistent workflow against storage and a simple test oracle.

## Integration workflow

~~~text
create table
insert HeapFile records
build hash index
search every key
insert more records through maintenance hooks
force splits and doublings
delete selected records/associations
close every component
reopen through Catalog
repeat searches
validate structure
compare with source storage and oracle
~~~

## Differential strategy

- Maintain a test-only map from key to RID set.
- Generate deterministic insert/search/delete sequences.
- Compare index results after every operation.
- Periodically close and reopen the real index.
- Validate structure after every mutation in small randomized tests.
- Inject small bucket capacity and controlled hashes to force edge cases.

## Scale checks

- multiple buckets and global-depth changes;
- duplicate and variable-sized keys;
- directory spanning several pages;
- repeated reopen cycles;
- skew and full-hash collisions.

These are correctness/stress checks, not final Stage 10 benchmarks.

## Acceptance criteria

Oracle contents, source-table RIDs, persisted results, and structural validation agree throughout.

---

# 34. Task 5.27 — Update architecture and stage documentation

## Objective

Promote stable decisions and prepare the Stage 6 handoff.

Update PROJECT_CONTEXT.md with:

- hash algorithm/version and width;
- canonical key bytes;
- selected directory-bit convention;
- initial and maximum depth;
- directory and bucket layouts;
- bucket-capacity rule;
- duplicate and uniqueness behavior;
- unsplittable-collision strategy;
- deletion and optional merge/shrink policy;
- persistence update ordering;
- Catalog representation;
- RID maintenance policy;
- metrics definitions;
- known limitations.

Only after this document's Definition of Done is satisfied, update current-stage references to:

~~~text
Stage 6 — Relational Operators and External Algorithms
ETAPA_06.md
~~~

## Acceptance criteria

A new contributor can reopen, validate, maintain, and later benchmark the index without reconstructing decisions from source code.

---

# 35. Recommended implementation order

## Increment A — Decisions and formats

~~~text
5.1 inspection
5.2 decision checkpoint
5.3 persistent header
5.4 stable hashing
5.5 paged directory
5.6 bucket model
5.7 strict codecs
~~~

Exit condition: all persistent formats are approved and isolated round-trip tests pass.

## Increment B — Basic persistent index

~~~text
5.8 lifecycle
5.9 exact search
5.10 insertion without growth
~~~

Exit condition: a fixed-topology index works across real restart.

## Increment C — Dynamic growth

~~~text
5.11 split without doubling
5.12 directory doubling
5.13 repeated splits
5.14 duplicate/unique semantics
5.15 unsplittable collisions
~~~

Exit condition: growth terminates correctly under normal, skewed, and adversarial input.

## Increment D — Deletion and structural safety

~~~text
5.16 deletion
5.17 physical-page lifecycle
5.18 optional merge
5.19 optional shrink
5.20 validator
~~~

Exit condition: mandatory deletion works; optional compaction is tested or explicitly deferred.

## Increment E — Persistence and integration

~~~text
5.21 restart tests
5.22 build from HeapFile
5.23 mutation/RID maintenance
5.24 Catalog integration
5.25 metrics and errors
5.26 integration/differential tests
5.27 documentation
~~~

Exit condition: the complete Stage 5 Definition of Done is satisfied.

---

# 36. Suggested test layout

~~~text
tests/
  unit/indexes/
    test_hash_codec.py
    test_hash_directory.py
    test_hash_bucket.py
    test_extendible_hash_search.py
    test_extendible_hash_insert.py
    test_extendible_hash_split.py
    test_extendible_hash_delete.py
    test_hash_validator.py
  property/indexes/
    test_extendible_hash_model.py
  persistence/indexes/
    test_extendible_hash_restart.py
    test_extendible_hash_corruption.py
  integration/indexes/
    test_hash_heapfile.py
    test_hash_catalog.py
    test_hash_index_maintenance.py
    test_bplus_hash_contract.py
~~~

Use repository conventions instead of creating duplicate test trees solely to match this example.

---

# 37. Suggested commit sequence

~~~text
1. document Stage 5 format decisions
2. add deterministic hashing and golden vectors
3. add directory/bucket models and codecs
4. add lifecycle and exact search
5. add insertion without split
6. add split without directory growth
7. add directory doubling and repeated splits
8. add duplicate and collision behavior
9. add deletion and page lifecycle
10. add validator and restart tests
11. add HeapFile build and maintenance
12. add Catalog integration, metrics, and errors
13. complete integration tests and documentation
~~~

Keep optional merge/shrink work isolated from required functionality.

---

# 38. Validation commands

Adapt these to the repository's configured tooling:

~~~bash
pytest
pytest tests/unit/indexes
pytest tests/persistence/indexes
pytest tests/integration/indexes
~~~

If already configured:

~~~bash
pytest -q
pytest --maxfail=1
ruff check .
mypy engine
~~~

Do not introduce a new tool merely because it appears in this example.

---

# 39. Definition of Done

Stage 5 is complete only when every required item below is true.

## Decisions and format

~~~text
[ ] deterministic hash algorithm/version is documented
[ ] canonical key encoding is documented and tested
[ ] hash width and bit convention are fixed
[ ] initial and maximum depths are fixed
[ ] directory and bucket layouts are versioned
[ ] duplicate, unique, deletion, and collision policies are explicit
[ ] optional merge/shrink status is explicit
[ ] stable decisions are in PROJECT_CONTEXT.md
~~~

## Persistence

~~~text
[ ] header stores everything needed to reopen
[ ] directory size always equals 2^D
[ ] the directory can span multiple pages
[ ] bucket local depth persists correctly
[ ] bucket capacity respects serialized page size
[ ] malformed/truncated pages are rejected
[ ] create, open, flush, close, and reopen work
~~~

## API and algorithms

~~~text
[ ] insert(key, rid) works with available space
[ ] search(key) returns all and only matching RIDs
[ ] delete(key, rid) removes only that association
[ ] split with d < D works
[ ] doubling with d == D works
[ ] repeated splits terminate correctly
[ ] duplicate/unique behavior matches Stage 4
[ ] maximum-depth/full-hash collisions are bounded
[ ] full key comparison follows hash routing
~~~

## Structural integrity

~~~text
[ ] every directory entry references a valid bucket
[ ] every bucket has local_depth <= global_depth
[ ] bucket alias counts equal 2^(D-d)
[ ] every association resides in a compatible bucket
[ ] no split loses or duplicates associations
[ ] no referenced page is freed
[ ] the validator passes after every tested mutation
~~~

## Integration and observability

~~~text
[ ] index builds from an existing HeapFile
[ ] Catalog persists and reopens it
[ ] table insert/delete/update maintains it
[ ] RID movement triggers remap or rebuild when applicable
[ ] hash capability excludes range/ordering
[ ] real I/O and structural metrics are available
~~~

## Testing and stage boundary

~~~text
[ ] all Stage 1–4 tests still pass
[ ] unit tests cover hash, directory, bucket, split, and delete
[ ] restart tests recreate all in-memory objects
[ ] multipage directory growth is tested
[ ] deterministic collision tests exist
[ ] differential tests compare against an oracle
[ ] malformed files produce domain errors
[ ] the complete integration workflow passes after restart
[ ] the full configured suite passes
[ ] no Stage 6, SQL, transaction, frontend, or final benchmark work is mixed in
~~~

---

# 40. Not required for completion

Unless another source-of-truth document explicitly requires them:

- buddy merge after deletion;
- directory shrinking;
- concurrent or lock-free hash mutation;
- WAL-based split recovery;
- online index construction;
- range queries through hashing;
- cryptographic hashing;
- production-grade crash atomicity;
- final performance graphs.

Optional work must not destabilize mandatory behavior or delay Stage 6.

---

# 41. Main risks and controls

| Risk | Control |
|---|---|
| Runtime-randomized hashes break restart | Stable algorithm and golden vectors |
| Directory is assumed to fit one page | Paged representation and boundary tests |
| Split redirects wrong aliases | Explicit bit convention and validator |
| Collisions cause endless growth | Maximum depth and bounded collision policy |
| Hash equality is mistaken for key equality | Store and compare full encoded keys |
| Associations are lost during split | Redistribute old plus pending data, then validate |
| Partial growth becomes visible | Documented write order and failure tests |
| Variable keys exceed a bucket page | Serialized byte-capacity checks |
| Aliased bucket is freed twice | Reference checks before reclamation |
| RID becomes stale after movement | Shared remap/rebuild maintenance path |
| Hash claims range capability | Explicit capability distinction from B+ |
| Benchmark work starts early | Expose counters now; defer experiments to Stage 10 |

---

# 42. Recommended prompt to start Stage 5

~~~text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md, and ETAPA_05.md.
Inspect the completed Stage 1–4 code and tests. Do not modify code yet.
Verify the Stage 4 Definition of Done, map the existing Index, key codec, RID,
PageManager, Catalog, maintenance, and metrics components to Stage 5, and report
conflicts or missing prerequisites. Then propose the Task 5.2 decision table
using the repository's current conventions.
~~~

---

# 43. Recommended design-checkpoint prompt

~~~text
Complete Task 5.2 only. Propose the deterministic hash algorithm/version,
canonical key bytes, hash width, selected-bit convention, initial and maximum
depths, directory and bucket layouts, bucket-capacity rule, duplicate policy,
unsplittable-collision policy, deletion/merge/shrink policy, metadata update
ordering, and Catalog fields. Distinguish official requirements from project
decisions. Do not implement code until the persistent format is reviewed.
~~~

---

# 44. Recommended first coding prompt

~~~text
Implement Stage 5 Increment A exactly as approved in Task 5.2: the versioned
header, deterministic hash/key codec, directory model, bucket model, and strict
serializers. Reuse Stage 2–4 abstractions and errors. Add golden-vector,
boundary, malformed-page, and round-trip tests. Do not implement insertion,
splitting, Catalog changes, or Stage 6 work yet. Run the relevant tests and
report changed files and unresolved decisions.
~~~

---

# 45. Condition for starting Stage 6

Do not begin Stage 6 until:

~~~text
the persistent Extendible Hash API works
bucket splitting and directory doubling are correct
collisions have bounded behavior
deletion preserves structural integrity
restart tests pass with new objects
HeapFile and Catalog integration pass
the structural validator passes
real metrics are exposed
all earlier-stage tests remain green
the Stage 5 Definition of Done is satisfied
ETAPA_06.md exists and matches the updated PROJECT_CONTEXT.md
~~~

Stage 6 can then build operators and external algorithms on three validated access families:

~~~text
Heap/Paged Sequential storage
B+ Tree indexes
Extendible Hash indexes
~~~

