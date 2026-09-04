# ETAPA_04.md

> Context version: **1.8** - Stage 4 formally closed on 2026-09-03.

## Stage 4 - B+ Tree

**Part:** Relational Database  
**Status:** Complete and audited — 59/59 Definition of Done criteria  
**Prerequisite:** Stage 3 complete  
**Previous stage:** Stage 3 - Heap File and Paged Sequential File  
**Next stage:** Stage 5 - Extendible Hashing  
**Roadmap:** `PLAN.md`

---

# 1. Purpose

Stage 4 implements the persistent B+ Tree required by Part 1 and integrates it in two physically meaningful ways:

```text
Unclustered B+ Index
Clustered B+ Index
```

It answers:

> **How can the DBMS locate exact keys and key ranges using a balanced, disk-oriented search tree?**

and:

> **How does a B+ index behave differently when the underlying records are physically ordered by the index key?**

The preferred design is one reusable B+ core with different storage integration policies:

```text
                       Persistent B+ core
                     key -> RID or RID list
                              |
               +--------------+--------------+
               |                             |
               v                             v
       Unclustered adapter             Clustered adapter
               |                             |
               v                             v
       unordered HeapFile        ordered PagedSequentialFile
```

Do not implement two unrelated tree algorithms merely to distinguish clustered and unclustered behavior.

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
ETAPA_04.md
    |
    |  detailed Stage 4 work
    v
CODE
```

`AGENTS.md` governs how Codex must work with these documents.

This stage document must not override:

- official requirements in `REQUIREMENTS.md`;
- stable decisions in `PROJECT_CONTEXT.md`;
- operating rules in `AGENTS.md`;
- the persisted page and record format from Stage 2;
- the Heap and Paged Sequential semantics from Stage 3.

When Stage 4 resolves a stable B+ decision, promote it to `PROJECT_CONTEXT.md`.

---

# 3. Stage transition requirement

Stage 3 is assumed to be complete.

Before implementing Stage 4, verify:

```text
[x] Stage 3 Definition of Done is satisfied
[x] all Stage 1-3 tests pass
[x] HeapFile persists records and supports RID lookup
[x] HeapFile scan can expose each active record and RID
[x] HeapFile free-space reuse works
[x] PagedSequentialFile persists records in ordered-key view
[x] PagedSequentialFile exact search works
[x] PagedSequentialFile lazy deletion and reorganization work
[x] Stage 3 RID movement/remapping policy is explicit
[x] RecordCodec, Page, and PageManager remain stable
[x] actual page I/O counters are available if previously adopted
[x] Stage 3 decisions are recorded in PROJECT_CONTEXT.md
```

Because the project has moved to Stage 4, current-stage references should point to:

```text
Stage 4 - B+ Tree
ETAPA_04.md
```

If coordination documents still identify Stage 3 as current, report and correct the mismatch before coding.

---

# 4. Official Stage 4 obligations

The official project requires both:

```text
clustered B+ index
unclustered B+ index
```

The project also requires a later comparison between clustered B+, unclustered B+, and Extendible Hashing using:

```text
exact-equality search
range search
ordering behavior
index construction time
query time
additional disk space
frequent insertion/deletion behavior
```

Stage 4 must make these comparisons possible, but the final 1K/10K/100K experiments, graphs, and conclusions remain in Stage 10.

The B+ implementation must remain visible as an academic algorithm. Do not replace it with a database engine, third-party tree package, or an in-memory sorted dictionary.

---

# 5. Required B+ structural properties

The implementation must preserve the following B+ properties:

```text
all data/index values are referenced from leaf nodes
internal nodes contain routing separators and child pointers
keys inside every node are ordered
all leaves are at the same depth
non-root nodes satisfy the adopted minimum occupancy rule
leaf nodes are linked in key order
the root has special occupancy rules
the tree grows through root splitting
the tree shrinks through root replacement when appropriate
```

For the recommended right-min separator convention:

```text
internal key[i] = minimum key reachable through child[i + 1]
```

When a leaf splits, the first key of the new right leaf is **copied** into the parent and remains in the leaf.

When an internal node splits, the selected separator is **promoted** to the parent according to the adopted internal-node algorithm.

The exact separator convention must be selected once and used consistently in search, insertion, deletion, validation, and persistence.

---

# 6. Scope of Stage 4

## Included

```text
persistent index metadata/header
B+ key/value encoding
leaf-node representation
internal-node representation
node serialization and deserialization
node-page allocation and reuse
empty-tree lifecycle
root persistence
tree descent
exact-key lookup
linked-leaf traversal
range lookup
insertion without split
leaf split
internal split
root split
duplicate-key policy
leaf deletion
redistribution/borrowing
leaf merge
internal underflow repair
root shrink
structural validation
restart persistence
index build from existing storage
unclustered HeapFile integration
clustered PagedSequentialFile integration
index maintenance after record movement
Catalog/IndexMetadata integration
real I/O and structural counters
unit, functional, persistence, and integration tests
architecture documentation updates
```

## Explicitly not included

```text
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
final comparative benchmark report
benchmark charts
B* Tree redistribution across multiple siblings
prefix compression unless explicitly adopted
advanced bulk-loading optimizations unless required
```

Stage 4 must produce an index API that Stage 6 can consume without implementing Stage 6 operators early.

---

# 7. Architectural boundaries

The preferred dependency direction is:

```text
ClusteredBPlusIndex --------+
                            |
UnclusteredBPlusIndex ------+--> BPlusTree --> Index Page I/O
            |                       |                |
            |                       |                v
            |                       +----------> PageManager
            |                                        |
            v                                        v
    HeapFile / PagedSequentialFile                  Disk
```

Important rules:

- the B+ layer owns tree navigation, node splits, merges, and separators;
- storage organizations own records and their physical placement;
- unclustered leaf values normally reference `RID`s in a Heap File;
- clustered behavior requires records physically ordered by the same key;
- `PageManager` owns physical page addressing and I/O;
- index nodes must not parse SQL or execute relational operators;
- a metadata flag alone cannot make an index clustered;
- the frontend must never manipulate B+ nodes directly.

---

# 8. Task 4.1 - Inspect the completed Stage 3 implementation

> **Completed 2026-09-03.** The read-only findings and verified 1284-test
> baseline are recorded in `docs/ETAPA_04_TASK_4_1_INSPECTION.md`. Tasks
> 4.2–4.31 are also complete; formal closure evidence is in
> `docs/ETAPA_04_AUDIT.md`.

## Objective

Determine the exact storage, RID, metadata, and I/O contracts the B+ layer must use.

## Inspect

Codex should review:

- the Stage 1 `Index` and `OrderedIndex` contracts;
- `IndexMetadata` and `Catalog`;
- `Schema`, `Column`, `Record`, and `RID`;
- `HeapFile` insert/read/delete/scan behavior;
- `PagedSequentialFile` ordering, insert, search, delete, and reorganization behavior;
- the Stage 3 duplicate-key policy;
- the Stage 3 RID movement or remapping policy;
- `PageManager` allocation/read/write/flush/close behavior;
- file/organization header extension mechanisms;
- page-I/O counters;
- existing B-tree or B+ code and tests.

## Questions that must be answered

```text
What does the existing Index.search() contract return?
Can storage scans yield (RID, Record)?
Can an index use a separate PageManager/file?
How are free pages represented or reused?
Can PagedSequentialFile insertion move existing records?
What does sequential reorganization return or invalidate?
How are key columns represented in IndexMetadata?
```

## Expected output

Before modifying code, report:

```text
Reusable Stage 1-3 APIs:
- ...

Existing B+ code:
- ...

Missing Stage 4 components:
- ...

Potential conflicts:
- ...

Required minimal extensions:
- ...

Recommended implementation sequence:
- ...
```

## Restriction

Do not modify code during Task 4.1.

---

# 9. Task 4.2 - Resolve Stage 4 architectural decisions

## Objective

Select one coherent disk-oriented B+ design before implementing node formats or algorithms.

## 9.1 Shared core

Confirm that clustered and unclustered variants share one B+ core.

Recommended core contract:

```text
insert(key, rid)
search(key) -> RID collection
range_search(low, high, bounds...) -> ordered RID stream
delete(key, rid)
```

Adapters may resolve returned RIDs to `Record`s, but the core should not duplicate records unless the clustered physical design explicitly stores records in leaves.

## 9.2 Clustered physical design

Choose a physically meaningful model.

The smallest design consistent with completed Stage 3 is:

```text
B+ indexed key == PagedSequentialFile ordering key
leaf entry      == key -> RID or RID collection
data records    == physically ordered by that key
```

An alternative index-organized design, where leaf pages contain complete records, is possible but must not be adopted silently because it changes Stage 2/3 responsibilities.

## 9.3 Unclustered physical design

Recommended model:

```text
leaf entry   == key -> RID or RID collection
data records == HeapFile physical order independent of key order
```

## 9.4 One clustered index per table

Because one data file can have only one physical ordering at a time, enforce at most one clustered index per table.

Any number of unclustered indexes may exist if the Catalog supports them.

## 9.5 Separator convention

Choose and document one convention, preferably:

```text
right-min separators
```

Define equality routing precisely.

## 9.6 Node capacity model

Choose one model:

```text
fixed entry count derived from bounded serialized key/value sizes
```

or:

```text
byte-capacity nodes with minimum occupancy defined by used bytes
```

Do not use a hard-coded degree that can serialize beyond `PAGE_SIZE`.

## 9.7 Key support

Define:

```text
supported DataTypes
deterministic key encoding
maximum encoded key size if needed
comparison semantics
```

## 9.8 Duplicate keys

Choose one representation:

```text
repeated (key, RID) leaf entries
one key with an inline RID collection
one key with an overflow/bucket reference
```

Specify insertion, equality search, range search, and deletion behavior for duplicates.

## 9.9 Leaf links

At minimum, persist a `next_leaf` pointer for forward range scans.

If the course/project adopts a doubly linked leaf list, also persist `previous_leaf` and validate both directions.

## 9.10 Parent navigation

Choose either:

```text
persist parent page_id in every node
```

or:

```text
retain the descent path in memory during mutations
```

Do not mix both without a clear reason.

## 9.11 Deleted-node reuse

Choose how pages released by merges are handled:

```text
persistent free-node list
rebuildable free-node map
documented append-only index pages for this stage
```

Prefer reuse if practical because later experiments measure additional disk space.

## 9.12 Persistence boundary

Decide:

```text
when modified nodes become dirty/persisted
when index header/root metadata is flushed
what close() guarantees
what failures are detectable without WAL
```

Do not claim crash atomicity before Stage 8/recovery work.

## Required output of Task 4.2

Produce a decision set similar to:

```text
BPLUS_CORE_VALUE = ...
CLUSTERED_PHYSICAL_MODEL = ...
UNCLUSTERED_PHYSICAL_MODEL = ...
SEPARATOR_CONVENTION = ...
NODE_CAPACITY_MODEL = ...
KEY_TYPES_AND_ENCODING = ...
DUPLICATE_KEY_POLICY = ...
LEAF_LINK_POLICY = ...
PARENT_NAVIGATION_POLICY = ...
NODE_PAGE_REUSE_POLICY = ...
PERSISTENCE/FLUSH_POLICY = ...
RID_CHANGE_MAINTENANCE_POLICY = ...
```

Promote adopted decisions to `PROJECT_CONTEXT.md` before dependent code becomes stable.

---

# 10. Task 4.3 - Define persistent index metadata and `BPlusFileHeader`

## Objective

Persist enough metadata to open and validate the tree without guessing.

## Possible fields

```text
magic / index signature
format version
index type = BPLUS
cluster mode
root_page_id
first_leaf_page_id
height
entry count
node page count
free-node-list head if adopted
key column identifier
key DataType
uniqueness / duplicate policy
target table or storage identity
page size / capacity model parameters
```

Only persist fields used by the adopted design.

## Required behavior

- detect a non-B+ file;
- detect unsupported versions;
- reject a mismatched page size or key type;
- reject a clustered index opened against the wrong physical ordering;
- persist root changes immediately according to the adopted flush policy.

## Suggested tests

```text
test_bplus_header_round_trip
test_bplus_header_tracks_root
test_bplus_header_tracks_height
test_bplus_header_tracks_entry_count
test_reject_wrong_index_magic
test_reject_unsupported_index_version
test_reject_incompatible_key_metadata
```

---

# 11. Task 4.4 - Implement deterministic key and RID encoding

## Objective

Serialize B+ keys and leaf values consistently across restarts.

## Requirements

- reuse Stage 1 `DataType` semantics;
- use the Stage 2 byte-order decision;
- preserve logical comparison order;
- reject malformed/truncated encodings;
- encode `RID(page_id, slot_id)` deterministically;
- define duplicate collection encoding if used;
- ensure an encoded entry can fit the adopted node format.

## Important rule

The ordering produced by the comparator must agree with the ordering assumed by serialized B+ keys.

Do not compare encoded byte strings unless that encoding is intentionally order-preserving.

## Suggested tests

```text
test_integer_key_round_trip
test_negative_integer_key_round_trip
test_varchar_key_round_trip_if_supported
test_unicode_key_round_trip_if_supported
test_rid_round_trip
test_key_comparator_matches_logical_order
test_reject_oversized_key
test_reject_malformed_key
```

---

# 12. Task 4.5 - Implement the B+ node model and invariants

## Objective

Represent leaf and internal nodes without performing disk I/O inside the data model.

## Leaf node

Conceptually:

```text
page_id
node_type = LEAF
keys[]
values[]
next_leaf_page_id
previous_leaf_page_id if adopted
```

## Internal node

Conceptually:

```text
page_id
node_type = INTERNAL
keys[]
children[]
```

Required relationship:

```text
len(children) == len(keys) + 1
```

## Core invariants

```text
keys are nondecreasing or strictly increasing according to duplicate representation
leaf key/value cardinalities match
internal child cardinality is correct
node serialized size does not exceed PAGE_SIZE
non-root occupancy respects the chosen minimum
page references are valid or explicitly null
```

## Suggested tests

```text
test_create_empty_leaf_node
test_create_empty_internal_node
test_leaf_key_value_cardinality
test_internal_key_child_cardinality
test_node_rejects_unsorted_keys
test_node_capacity_calculation
test_non_root_minimum_occupancy
```

---

# 13. Task 4.6 - Implement node serialization and index-page I/O

## Objective

Persist each B+ node as one disk page using the established physical I/O abstraction.

## Required behavior

- serialize node type and all required metadata;
- serialize keys and values/child page IDs;
- serialize leaf links;
- occupy exactly one configured page;
- deserialize without losing logical state;
- validate corrupted counts, offsets, and page references where practical;
- allocate/read/write through `PageManager` or the adopted index-page equivalent;
- avoid `pickle` or process-specific object serialization.

## Page-layer reuse

Reuse Stage 2 page I/O. If B+ nodes require a dedicated page payload format, isolate that format inside the index module rather than duplicating raw file-offset calculations.

## Suggested tests

```text
test_leaf_node_page_round_trip
test_internal_node_page_round_trip
test_leaf_links_survive_round_trip
test_node_serialization_is_exactly_page_size
test_reject_corrupted_node_type
test_reject_corrupted_key_count
test_reject_invalid_child_page_id
```

---

# 14. Task 4.7 - Implement empty-tree lifecycle

## Objective

Create, open, flush, close, and reopen an empty persistent B+ Tree.

## Minimum conceptual API

```text
create(path, metadata...)
open(path, metadata...)
insert(key, rid)
search(key)
range_search(low, high, ...)
delete(key, rid)
flush()
close()
```

## Empty-tree representation

Choose one:

```text
root_page_id = NULL until first insertion
```

or:

```text
root is an allocated empty leaf
```

Do not support both representations simultaneously.

## Suggested tests

```text
test_create_empty_bplus_tree
test_empty_tree_search
test_empty_tree_range_search
test_empty_tree_delete
test_empty_tree_close_and_reopen
test_operation_after_close_is_rejected
```

---

# 15. Task 4.8 - Implement tree descent and path capture

## Objective

Navigate from the root to the correct leaf using persisted internal nodes.

## Required behavior

- route keys according to the separator convention;
- handle equality at a separator correctly;
- return the target leaf page;
- capture the ancestor path when the mutation algorithm needs it;
- detect invalid child pointers and node-type mismatches;
- count actual page reads through the I/O layer.

Conceptually:

```text
root
  |
  v
internal page
  |
  v
...
  |
  v
target leaf
```

## Suggested tests

```text
test_descend_single_leaf_tree
test_descend_to_leftmost_leaf
test_descend_to_middle_leaf
test_descend_to_rightmost_leaf
test_separator_equality_routes_correctly
test_descent_returns_ancestor_path
test_descent_rejects_invalid_child_pointer
```

---

# 16. Task 4.9 - Implement exact-key search

## Objective

Find the RID or RID collection associated with an exact key.

## Required behavior

- search an empty tree;
- search a one-leaf tree;
- search a multi-level tree;
- return no match for an absent key;
- follow duplicate-key semantics;
- never return internal separator values as data entries;
- detect stale/corrupt leaf values where practical at the adapter layer.

## Suggested tests

```text
test_search_empty_tree
test_search_existing_key
test_search_missing_key
test_search_first_key
test_search_last_key
test_search_duplicate_key_behavior
test_search_after_root_split
test_search_after_reopen
```

---

# 17. Task 4.10 - Implement linked-leaf traversal and range search

## Objective

Use the tree only to find the first relevant leaf, then traverse linked leaves in key order.

## Conceptual path

```text
root descent to low bound
          |
          v
       leaf A -> leaf B -> leaf C -> ...
          |
          v
stop after high bound
```

## Required range semantics

Define support for:

```text
closed [low, high]
open/closed bounds if adopted
unbounded low or high if adopted
low > high
duplicate boundary keys
```

## Required behavior

- results are in nondecreasing key order;
- every qualifying leaf entry appears exactly once;
- no nonqualifying entry appears;
- traversal stops as soon as the upper bound is exceeded;
- broken leaf links fail predictably;
- range traversal does not repeatedly descend from the root for every leaf.

## Suggested tests

```text
test_range_search_empty_tree
test_range_search_one_leaf
test_range_search_across_leaves
test_range_search_exact_boundaries
test_range_search_no_matches
test_range_search_duplicate_boundaries
test_full_leaf_order_scan
test_forward_and_backward_leaf_links_if_doubly_linked
```

---

# 18. Task 4.11 - Implement leaf insertion without split

## Objective

Insert a new `(key, value)` entry into a leaf that has sufficient capacity.

## Required behavior

- preserve sorted key order;
- place duplicate entries according to policy;
- update entry count exactly once;
- persist the modified leaf;
- preserve leaf links;
- preserve all earlier entries;
- avoid unnecessary node allocation.

## Suggested tests

```text
test_insert_first_entry
test_insert_in_ascending_order
test_insert_in_descending_order
test_insert_middle_key
test_insert_without_split_preserves_links
test_insert_duplicate_without_split
```

---

# 19. Task 4.12 - Implement leaf splitting

## Objective

Split an overflowing leaf into two valid leaves and return the separator required by the parent.

## Required behavior

- combine old and new entries before choosing the split point;
- divide entries according to the capacity/occupancy policy;
- keep all entries in leaves;
- copy the first key of the right leaf upward under the recommended convention;
- allocate a new node page;
- update `next_leaf` and `previous_leaf` links;
- update the neighboring leaf when a backward link is stored;
- leave both leaves within capacity and occupancy rules;
- persist all modified nodes through the I/O layer.

## Suggested tests

```text
test_leaf_split_distributes_all_entries
test_leaf_split_preserves_key_order
test_leaf_split_copies_right_min_separator
test_leaf_split_updates_next_link
test_leaf_split_updates_previous_link_if_adopted
test_leaf_split_preserves_duplicate_entries
test_leaf_split_nodes_fit_page
```

---

# 20. Task 4.13 - Implement insertion into internal nodes

## Objective

Insert a separator and new child pointer into a parent after a child split.

## Required behavior

- insert the separator in sorted position;
- place the left/right child pointers correctly;
- preserve `len(children) == len(keys) + 1`;
- update parent references if the adopted design stores them;
- avoid duplicating or losing child pointers;
- persist the modified internal node.

## Suggested tests

```text
test_internal_insert_first_separator
test_internal_insert_left_middle_right
test_internal_insert_preserves_child_order
test_internal_insert_preserves_cardinality
test_internal_insert_updates_parent_reference_if_used
```

---

# 21. Task 4.14 - Implement internal splitting and split propagation

## Objective

Handle internal-node overflow and propagate structural changes toward the root.

## Required behavior

- choose the promoted separator according to one documented algorithm;
- distribute remaining keys and children into valid left/right nodes;
- remove the promoted key from internal-node payload where required;
- update child parent references if persisted;
- propagate the new separator to the parent;
- continue until a non-overflowing ancestor or the root is reached;
- preserve all reachable subtrees exactly once.

## Suggested tests

```text
test_internal_split_promotes_correct_separator
test_internal_split_distributes_all_children
test_internal_split_preserves_routing
test_split_propagates_one_level
test_split_propagates_multiple_levels
test_internal_split_nodes_fit_page
```

---

# 22. Task 4.15 - Implement root split and height growth

## Objective

Create a new root when the old root splits.

## Required behavior

- allocate exactly one new root page;
- point it to the two split children;
- store the correct separator;
- update parent references if used;
- update persisted `root_page_id`;
- increment height exactly once;
- preserve the leftmost leaf metadata;
- survive close/reopen immediately after the root split.

## Suggested tests

```text
test_first_leaf_split_creates_internal_root
test_root_split_updates_header
test_root_split_increases_height
test_root_split_preserves_all_entries
test_root_split_survives_reopen
test_multiple_root_splits_create_multi_level_tree
```

---

# 23. Task 4.16 - Complete duplicate-key handling

## Objective

Make duplicate behavior correct through every structural operation.

## Required behavior

- equality search returns all matching values according to the API;
- range search includes all duplicates at both boundaries;
- insertion never loses an existing RID;
- deletion of `(key, rid)` removes only the requested association;
- deleting the final RID for a key removes the key entry if using collections;
- duplicates spanning leaf boundaries remain discoverable;
- split and merge preserve deterministic duplicate placement.

If the index is declared unique, reject a second distinct RID for the same key with a clear domain error.

## Suggested tests

```text
test_insert_duplicate_key_multiple_rids
test_search_returns_all_duplicate_rids
test_duplicates_across_leaf_split
test_range_includes_all_boundary_duplicates
test_delete_one_duplicate_rid
test_delete_last_duplicate_rid
test_unique_index_rejects_duplicate_key
```

---

# 24. Task 4.17 - Implement deletion without underflow

## Objective

Remove a leaf association when the leaf remains above minimum occupancy.

## Required behavior

- descend to the correct leaf;
- remove the exact `(key, rid)` association;
- follow missing-key/missing-RID policy;
- update the leaf's first key separator in ancestors when required;
- decrement entry count exactly once;
- preserve linked-leaf structure;
- avoid rebalancing when no underflow exists.

## Suggested tests

```text
test_delete_existing_entry_without_underflow
test_delete_missing_key
test_delete_missing_rid_for_duplicate_key
test_delete_updates_entry_count
test_delete_new_leaf_min_updates_separator
test_delete_without_underflow_does_not_allocate_or_merge
```

---

# 25. Task 4.18 - Implement leaf redistribution

## Objective

Repair an underfull leaf by borrowing from an adjacent sibling when possible.

## Required behavior

- consider only siblings with the same parent;
- use one deterministic left/right preference;
- move enough entries to satisfy minimum occupancy;
- preserve global key order;
- update the parent separator;
- preserve leaf links;
- preserve duplicate associations;
- persist the sibling, target leaf, and parent.

## Suggested tests

```text
test_leaf_borrow_from_left
test_leaf_borrow_from_right
test_leaf_redistribution_preserves_order
test_leaf_redistribution_updates_parent_separator
test_leaf_redistribution_preserves_leaf_links
test_leaf_redistribution_with_duplicates
```

---

# 26. Task 4.19 - Implement leaf merge

## Objective

Merge adjacent leaves when redistribution cannot restore minimum occupancy.

## Required behavior

- merge only siblings with the same parent;
- move every surviving entry exactly once;
- keep the chosen survivor within maximum capacity;
- repair forward/backward leaf links;
- remove the obsolete separator and child pointer from the parent;
- release or register the removed node page according to the page-reuse policy;
- propagate parent underflow when necessary.

## Suggested tests

```text
test_merge_leaf_with_left_sibling
test_merge_leaf_with_right_sibling
test_leaf_merge_preserves_all_entries
test_leaf_merge_repairs_links
test_leaf_merge_removes_parent_separator
test_leaf_merge_releases_or_tracks_removed_page
```

---

# 27. Task 4.20 - Implement internal redistribution and merge

## Objective

Repair underfull internal nodes while preserving correct separator semantics.

## Required behavior

- borrow a separator/child from a sibling when possible;
- rotate the parent separator according to the adopted convention;
- update affected child parent references if stored;
- merge internal siblings when redistribution is impossible;
- pull or reconstruct the separating parent key correctly;
- propagate underflow toward the root;
- preserve every subtree exactly once.

## Suggested tests

```text
test_internal_borrow_from_left
test_internal_borrow_from_right
test_internal_redistribution_updates_separators
test_internal_merge
test_internal_merge_preserves_all_children
test_internal_underflow_propagates
test_multi_level_delete_remains_searchable
```

---

# 28. Task 4.21 - Implement root shrink and node-page reuse

## Objective

Reduce tree height after deletion and make released node pages manageable.

## Root rules

If an internal root has zero keys and one child:

```text
the only child becomes the new root
```

If the last leaf entry is deleted, return to the adopted empty-tree representation.

## Required behavior

- decrement height correctly;
- persist the new root page ID;
- clear the new root's parent reference if stored;
- update first-leaf metadata;
- register released root/merged pages for reuse if adopted;
- never leave the header pointing to an unreachable old root.

## Suggested tests

```text
test_internal_root_shrinks_to_child
test_delete_all_entries_returns_empty_tree
test_root_shrink_updates_header
test_root_shrink_survives_reopen
test_released_node_page_is_reused_if_policy_requires
```

---

# 29. Task 4.22 - Implement a structural validator

## Objective

Provide a test/debug function that proves global B+ invariants after complex mutations.

## Validator checks

```text
root exists or empty-tree state is valid
all reachable page IDs are valid
no cycles exist in child pointers
internal child/key cardinality is correct
keys are ordered in every node
separator convention is satisfied
all leaves have the same depth
non-root occupancy is valid
leaf chain order matches tree traversal order
leaf links contain no cycles
each reachable node is visited once
header entry count matches leaf entries
header height matches observed height
```

At the adapter level, optionally validate that every RID resolves to the expected active record/key.

## Suggested tests

```text
test_validator_accepts_valid_tree
test_validator_detects_unsorted_node
test_validator_detects_bad_separator
test_validator_detects_unequal_leaf_depth
test_validator_detects_broken_leaf_link
test_validator_detects_invalid_occupancy
test_validator_detects_wrong_entry_count
test_validator_accepts_tree_after_random_mutations
```

The validator is not a replacement for normal operation tests.

---

# 30. Task 4.23 - Add persistent restart tests

## Objective

Prove that a fresh object graph can recover the complete tree and continue mutating it.

## Required scenario

```text
create index
insert enough entries for leaf, internal, and root splits
flush and close
discard all in-memory nodes/tree objects
open with a new PageManager and BPlusTree instance
run exact and range searches
insert more entries
delete enough entries for redistribution, merge, and root shrink
flush and close again
reopen and validate structure/results
```

## Suggested tests

```text
test_bplus_entries_survive_restart
test_bplus_root_and_height_survive_restart
test_leaf_links_survive_restart
test_bplus_can_split_after_restart
test_bplus_can_merge_after_restart
test_bplus_can_shrink_root_after_restart
test_reused_node_pages_survive_restart_if_adopted
```

Do not treat reading the same in-memory node objects as persistence.

---

# 31. Task 4.24 - Build an index from existing storage

## Objective

Construct a B+ index over records that already exist in a Stage 3 storage organization.

## Baseline build path

```text
storage.scan_with_rids()
        |
        v
extract indexed key
        |
        v
BPlusTree.insert(key, rid)
```

## Required behavior

- validate key column and type;
- skip deleted records because normal storage scans expose only active rows;
- insert every active record exactly once;
- support duplicate keys according to metadata;
- leave no usable partial index after a failed build unless partial state is explicitly marked invalid;
- persist build-complete metadata;
- expose actual construction I/O/time to later benchmarking code without fabricating it.

## Bulk loading

An optimized bottom-up bulk loader is optional in Stage 4. Correct incremental construction is sufficient unless the project explicitly adopts bulk loading.

## Suggested tests

```text
test_build_index_on_empty_storage
test_build_index_from_one_page
test_build_index_from_multiple_pages
test_build_index_skips_deleted_records
test_build_index_with_duplicate_keys
test_build_index_matches_storage_active_count
test_built_index_survives_reopen
```

---

# 32. Task 4.25 - Implement the unclustered B+ adapter

## Objective

Use the B+ core to index an unordered `HeapFile` without changing its physical record order.

## Physical model

```text
B+ leaf order:     key -> RID

HeapFile order:    independent arrival/reuse order
```

## Required behavior

- build from an existing Heap File;
- exact search returns matching Heap RIDs/records;
- range search returns matching associations in key order;
- record fetches use `HeapFile.read(rid)`;
- new Heap inserts update the index through an explicit coordinated path;
- Heap deletion removes the exact index association;
- multiple unclustered indexes on different columns remain possible;
- do not physically reorder the Heap File.

## Suggested tests

```text
test_unclustered_build_from_heap
test_unclustered_exact_lookup_resolves_record
test_unclustered_range_lookup_is_key_ordered
test_unclustered_heap_physical_order_remains_independent
test_unclustered_insert_maintenance
test_unclustered_delete_maintenance
test_two_unclustered_indexes_on_one_table
test_unclustered_restart_integration
```

---

# 33. Task 4.26 - Implement the clustered B+ adapter

## Objective

Provide a B+ index whose key matches the physical ordering of the underlying records.

## Recommended physical model

```text
Clustered B+ key
        ==
PagedSequentialFile ordering key
```

The underlying data scan must remain ordered by the same comparator used by the B+ index.

## Required behavior

- reject creation when the requested clustered key differs from the physical ordering key;
- enforce at most one clustered index per table;
- build from the ordered storage file;
- exact and range searches resolve active records;
- preserve physically meaningful locality for range results;
- integrate with sequential ordered insertion;
- integrate with lazy deletion;
- handle sequential reorganization according to the adopted RID-change policy;
- never implement clustered behavior as only `clustered=True` over an unordered Heap File.

## Suggested tests

```text
test_clustered_build_from_paged_sequential_file
test_clustered_key_matches_storage_order_key
test_clustered_rejects_wrong_order_key
test_only_one_clustered_index_per_table
test_clustered_exact_lookup
test_clustered_range_lookup
test_clustered_insert_maintenance
test_clustered_lazy_delete_maintenance
test_clustered_reorganization_maintenance
test_clustered_restart_integration
```

---

# 34. Task 4.27 - Maintain index/storage consistency

## Objective

Define safe coordinated operations before the transaction layer exists.

## Operations to coordinate

```text
insert record + insert index association
delete index association + delete record
sequential record movement + update RID associations
sequential reorganization + remap/rebuild clustered index
index rebuild after detected inconsistency
```

## RID movement

Follow the Stage 3 policy:

```text
old RID -> new RID mapping
```

or:

```text
RID invalidation -> rebuild dependent indexes
```

Do not leave an index silently pointing to stale RIDs.

## Failure boundary

Stage 4 does not yet provide transactions or WAL. Use the smallest deterministic ordering and best-effort cleanup/rebuild policy, and document what a mid-operation process crash can leave behind.

## Suggested tests

```text
test_index_and_storage_insert_remain_consistent
test_index_and_storage_delete_remain_consistent
test_stale_rid_is_detected
test_clustered_rid_remap_updates_index_if_adopted
test_clustered_reorganization_rebuilds_index_if_adopted
test_rebuild_restores_index_storage_equivalence
```

---

# 35. Task 4.28 - Integrate `IndexMetadata` and `Catalog`

## Objective

Make both B+ variants discoverable without coupling the Catalog to tree algorithms.

## Metadata may include

```text
index name
index type = BPLUS
table name/id
indexed column(s)
clustered = true/false
unique = true/false
index file path/identity
key DataType
valid/build state
```

## Required behavior

- register clustered and unclustered B+ indexes;
- reject duplicate index names;
- reject unknown tables/columns;
- enforce one clustered index per table;
- distinguish index metadata from open runtime tree objects;
- preserve existing Catalog responsibilities;
- do not add SQL `CREATE INDEX` parsing yet.

## Suggested tests

```text
test_register_unclustered_bplus_metadata
test_register_clustered_bplus_metadata
test_reject_second_clustered_index
test_reject_unknown_index_column
test_catalog_lists_bplus_indexes
test_index_metadata_round_trip_if_catalog_is_persistent
```

---

# 36. Task 4.29 - Add instrumentation, errors, and boundaries

## Objective

Expose real behavior for debugging and later experiments while failing predictably on invalid state.

## Possible structural counters

```text
node_splits
node_merges
redistributions
root_splits
root_shrinks
height
entry_count
```

Physical I/O counters must continue to come from the actual page I/O layer:

```text
pages_read
pages_written
pages_allocated
```

## Boundary/error cases

```text
invalid key type
oversized key/entry
invalid RID
closed index
wrong index file
corrupt node
broken child pointer
broken leaf link
duplicate key in a unique index
delete missing association
clustered key/storage mismatch
stale RID after storage movement
```

Add only useful domain errors, for example:

```text
IndexErrorBase or project equivalent
CorruptIndexError
DuplicateIndexKeyError
IndexStorageMismatchError
```

Avoid shadowing Python's built-in `IndexError` with a confusing project class.

## Suggested tests

```text
test_split_counter_matches_real_split
test_merge_counter_matches_real_merge
test_bplus_reads_increment_page_io_counter
test_bplus_writes_increment_page_io_counter
test_reject_oversized_index_entry
test_reject_corrupt_node_page
test_reject_operation_after_close
```

---

# 37. Task 4.30 - Add Stage 4 end-to-end integration tests

## Objective

Connect the persistent B+ core to both completed Stage 3 storage organizations.

## 37.1 Generic B+ scenario

```text
insert enough shuffled keys for height >= 3
verify exact search
verify multi-leaf range search
delete keys to force redistribution
delete more keys to force merges/root shrink
close/reopen
validate the tree and all expected results
```

## 37.2 Unclustered scenario

```text
HeapFile records
  -> build unclustered B+
  -> equality/range RID lookup
  -> fetch Heap records
  -> insert/delete maintenance
  -> close/reopen
```

## 37.3 Clustered scenario

```text
PagedSequentialFile ordered by key
  -> build clustered B+
  -> equality/range lookup
  -> ordered insertion/lazy deletion
  -> sequential reorganization
  -> remap or rebuild index
  -> close/reopen
```

## 37.4 Comparative correctness

Using the same logical dataset:

```text
clustered B+ results == expected records
unclustered B+ results == expected records
both range result key sequences are ordered
physical storage ordering remains different and documented
```

## Suggested tests

```text
test_stage4_generic_bplus_end_to_end
test_stage4_unclustered_end_to_end
test_stage4_clustered_end_to_end
test_stage4_clustered_unclustered_logical_equivalence
```

Use enough entries to force multiple leaves, internal nodes, and at least one multi-level split. Include a deterministic stress test with 100+ entries or another capacity-derived count that guarantees height growth.

---

# 38. Task 4.31 - Update architecture and stage documentation

> **Completed 2026-09-03.** Stable decisions are consolidated in
> `PROJECT_CONTEXT.md`; closure evidence is recorded in
> `docs/ETAPA_04_AUDIT.md`.

## Objective

Promote stable Stage 4 decisions and prepare the repository for Stage 5.

## Update `PROJECT_CONTEXT.md`

At minimum document:

```text
shared B+ core architecture
clustered physical model
unclustered physical model
one-clustered-index-per-table rule
node page/header layout
separator convention
node capacity/occupancy model
key encoding and supported types
duplicate-key policy
leaf-link policy
parent-navigation policy
root/height persistence
node-page reuse policy
flush guarantees and crash limitations
RID remap/rebuild integration
Catalog metadata fields
instrumentation behavior
```

## Update current-stage references

While Stage 4 is active:

```text
Stage 4 - B+ Tree
ETAPA_04.md
```

After the Stage 4 Definition of Done is satisfied and Stage 5 begins:

```text
Stage 5 - Extendible Hashing
ETAPA_05.md
```

Do not advance the documented stage before the implementation and tests are complete.

---

# 39. Recommended implementation order

```text
4.1  Inspect Stage 3 and existing index contracts
          |
          v
4.2  Resolve B+ architecture decisions
          |
          v
4.3  Persistent index metadata/header
          |
          v
4.4  Key and RID encoding
          |
          v
4.5  Leaf/internal node model
          |
          v
4.6  Node serialization and page I/O
          |
          v
4.7  Empty-tree lifecycle
          |
          v
4.8  Tree descent/path capture
          |
          +------------------------+
          |                        |
          v                        v
4.9  Exact search          4.10 Leaf/range traversal
          |                        |
          +------------+-----------+
                       |
                       v
               4.11 Leaf insertion
                       |
                       v
               4.12 Leaf split
                       |
                       v
               4.13 Internal insertion
                       |
                       v
               4.14 Internal split propagation
                       |
                       v
               4.15 Root split/height growth
                       |
                       v
               4.16 Duplicate-key completion
                       |
                       v
               4.17 Simple deletion
                       |
                       v
               4.18 Leaf redistribution
                       |
                       v
               4.19 Leaf merge
                       |
                       v
               4.20 Internal repair
                       |
                       v
               4.21 Root shrink/page reuse
                       |
                       v
               4.22 Structural validator
                       |
                       v
               4.23 Restart persistence tests
                       |
                       v
               4.24 Build from storage
                       |
          +------------+-------------+
          |                          |
          v                          v
4.25 Unclustered adapter     4.26 Clustered adapter
          |                          |
          +------------+-------------+
                       |
                       v
               4.27 Consistency maintenance
                       |
                       v
               4.28 Catalog integration
                       |
                       v
               4.29 Instrumentation/errors
                       |
                       v
               4.30 Integration tests
                       |
                       v
               4.31 Documentation
```

Search/range work may proceed alongside early insertion work after node I/O and descent are stable. Clustered and unclustered adapters should not begin before the generic B+ core is structurally reliable.

Do not collapse the entire tree into one unreviewable change.

---

# 40. Recommended test organization

A possible layout is:

```text
tests/
├── indexes/
│   ├── test_bplus_header.py
│   ├── test_bplus_codec.py
│   ├── test_bplus_node.py
│   ├── test_bplus_persistence.py
│   ├── test_bplus_search.py
│   ├── test_bplus_range.py
│   ├── test_bplus_insert.py
│   ├── test_bplus_delete.py
│   ├── test_bplus_validator.py
│   ├── test_unclustered_bplus.py
│   └── test_clustered_bplus.py
│
└── integration/
    ├── test_stage4_bplus_pipeline.py
    ├── test_stage4_unclustered_pipeline.py
    └── test_stage4_clustered_pipeline.py
```

This layout is illustrative. Follow an existing coherent repository structure.

Use temporary index/data files so tests leave no artifacts in the repository.

---

# 41. Recommended commit strategy

Possible incremental commits:

```text
docs: start stage 4 bplus plan

feat(indexes): add persistent bplus metadata and codecs

feat(indexes): add bplus leaf and internal node pages

feat(indexes): add tree descent and exact lookup

feat(indexes): add linked-leaf range traversal

feat(indexes): implement leaf insertion and split

feat(indexes): implement internal and root splits

feat(indexes): complete duplicate-key behavior

feat(indexes): implement bplus deletion redistribution and merge

feat(indexes): add root shrink and node reuse

test(indexes): add validator and restart persistence tests

feat(indexes): build bplus from existing storage

feat(indexes): integrate unclustered bplus with heap storage

feat(indexes): integrate clustered bplus with ordered storage

feat(catalog): register clustered and unclustered bplus indexes

test(stage4): add bplus integration and stress coverage

docs: record stage 4 architecture decisions
```

Exact commit boundaries may differ according to the repository state.

---

# 42. Recommended validation commands

If the project uses pytest:

```bash
pytest tests/indexes/test_bplus_node.py -q
```

Then insertion/search/range:

```bash
pytest tests/indexes/test_bplus_insert.py -q
pytest tests/indexes/test_bplus_search.py -q
pytest tests/indexes/test_bplus_range.py -q
```

Then deletion/persistence:

```bash
pytest tests/indexes/test_bplus_delete.py -q
pytest tests/indexes/test_bplus_persistence.py -q
```

Run the full index suite:

```bash
pytest tests/indexes -q
```

Run integration tests:

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

Adapt paths to the actual repository. Do not create placeholder tests solely to make these exact commands valid.

---

# 43. Stage 4 Definition of Done

Stage 4 is complete only when all applicable items below are satisfied.

## Stage transition

```text
[x] Stage 3 Definition of Done was verified
[x] Stage 1-3 tests still pass
[x] coordination documents identify Stage 4 correctly
```

## Persistent B+ foundation

```text
[x] index header/metadata is persisted and validated
[x] leaf and internal nodes have deterministic page formats
[x] node pages occupy exactly PAGE_SIZE
[x] root page ID and height survive reopen
[x] key/RID encoding is deterministic
[x] capacity and minimum occupancy rules are explicit
[x] node-page reuse or non-reuse policy is explicit
```

## Search and traversal

```text
[x] descent follows one separator convention
[x] exact-key search works in empty, single-level, and multi-level trees
[x] linked leaves are persisted
[x] range search traverses leaves in order
[x] range boundaries and duplicates behave as documented
```

## Insertion

```text
[x] insertion without split works
[x] leaf split works
[x] leaf split copies the right separator correctly
[x] internal insertion works
[x] internal split works
[x] split propagation works across multiple levels
[x] root split increases height and persists the new root
[x] shuffled insertion preserves all invariants
```

## Deletion

```text
[x] exact association deletion works
[x] leaf redistribution works from both sides
[x] leaf merge repairs links and parent separators
[x] internal redistribution works
[x] internal merge and cascading underflow work
[x] root shrink works
[x] deleting all entries returns a valid empty tree
[x] released-node handling follows the adopted policy
```

## Integrity and persistence

```text
[x] structural validator checks global invariants
[x] all leaves remain at the same depth
[x] all reachable entries are returned exactly once
[x] close/reopen uses fresh objects
[x] search, insert, delete, split, merge, and root shrink work after reopen
[x] malformed index state fails predictably where practical
```

## Unclustered B+

```text
[x] uses key -> Heap RID associations
[x] Heap physical order remains independent
[x] equality and range lookup resolve correct active records
[x] insert/delete maintenance works
[x] multiple unclustered indexes remain possible
[x] persistent reopen works
```

## Clustered B+

```text
[x] underlying records are physically ordered by the indexed key
[x] clustered key matches PagedSequentialFile ordering metadata
[x] at most one clustered index exists per table
[x] equality and range lookup resolve correct active records
[x] ordered insert/lazy delete maintenance works
[x] reorganization/RID changes update or rebuild the index correctly
[x] persistent reopen works
```

## Integration and future readiness

```text
[x] one reusable B+ core serves both variants
[x] both variants satisfy the Stage 1 index contract plus range access
[x] Catalog/IndexMetadata distinguishes clustered/unclustered indexes
[x] actual I/O counters remain accurate if adopted
[x] same logical dataset yields equivalent results in both variants
[x] deterministic stress test forces multi-level growth and shrinkage
[x] all unit, functional, persistence, and integration tests pass
[x] stable Stage 4 decisions are recorded in PROJECT_CONTEXT.md
[x] no Stage 5 or later algorithm was implemented unnecessarily
```

Only after this checklist is satisfied should the project move to Stage 5.

Closure evidence: [Stage 4 audit](docs/ETAPA_04_AUDIT.md). The checklist was
verified with 1544 passing tests under warnings-as-errors. Stage 5 was not
started during this closure.

---

# 44. What is NOT required to complete Stage 4

Do not require any of the following before declaring Stage 4 complete:

```text
[ ] Extendible Hashing
[ ] SQL CREATE INDEX syntax
[ ] SQL query planning
[ ] IndexScan operator
[ ] transaction locks
[ ] concurrent tree mutation
[ ] buffer pool replacement algorithm
[ ] WAL or crash recovery
[ ] B* Tree optimization
[ ] prefix key compression
[ ] production-grade crash atomicity
[ ] frontend tree visualization
[ ] final benchmark graphs
[ ] 100,000-record performance target
```

These belong to later stages unless the project explicitly changes its roadmap.

---

# 45. Risks to watch during Stage 4

## 45.1 Building an in-memory tree only

A tree whose Python objects disappear after process exit does not satisfy the disk-oriented architecture.

Persist individual nodes and root metadata through the adopted page I/O layer.

## 45.2 Confusing B-tree and B+ leaf split rules

In the adopted B+ convention, leaf data stays in leaves and the right leaf minimum is copied upward. Internal-node promotion follows a different rule.

## 45.3 Hard-coding a degree unrelated to page capacity

A logical order is valid only if every serialized node still fits one physical page.

## 45.4 Incorrect separator updates after deletion

Deleting or borrowing the smallest key of a right subtree may require updating ancestors even when no merge occurs.

## 45.5 Broken duplicate behavior across leaves

Equality and range lookup must find every duplicate even if splits place equal keys across adjacent leaves.

## 45.6 Broken leaf links after split/merge

Exact search may still pass while range search silently loses records. Validate the leaf chain separately.

## 45.7 Labeling an unordered index as clustered

`clustered=True` is insufficient. The data file must be physically ordered by the same key.

## 45.8 Ignoring Stage 3 RID movement

Paged Sequential insertion/reorganization may move records. The clustered index must remap RIDs or rebuild according to the adopted policy.

## 45.9 Partial index/storage updates

Transactions do not exist yet. Document operation ordering and provide validation/rebuild instead of claiming atomicity.

## 45.10 Fake I/O metrics

Page access counts must come from actual node/data page operations, not theoretical estimates presented as measurements.

## 45.11 Premature Stage 5/6 work

Do not mix hash buckets, SQL planning, or `IndexScan` execution into the B+ core.

---

# 46. Recommended prompt to start Stage 4 with Codex

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
ETAPA_01.md, ETAPA_02.md, ETAPA_03.md, and ETAPA_04.md.

Stages 1, 2, and 3 are complete.

First inspect the repository and verify the completed storage, RID,
PageManager, HeapFile, and PagedSequentialFile APIs and tests.
Inspect existing index abstractions and any B-tree/B+ code.

Do not modify files yet.

Report:
1. reusable Stage 1-3 APIs;
2. existing B+ or index code;
3. the exact RID movement policy from Stage 3;
4. whether index nodes can use the existing PageManager cleanly;
5. all unresolved decisions listed in Task 4.2;
6. conflicts between code and project documents;
7. the smallest safe implementation sequence for Stage 4.

Do not implement Extendible Hashing, relational operators, SQL,
transactions, API, frontend, or final benchmarks.
```

---

# 47. Recommended prompt for Task 4.2

After repository inspection:

```text
Work only on Task 4.2 from ETAPA_04.md.

Based on the existing Stage 1-3 implementation, propose the smallest
coherent persistent B+ architecture for:

- one shared B+ core;
- clustered and unclustered physical models;
- separator routing convention;
- node capacity and minimum occupancy;
- key/RID encoding;
- duplicate-key representation;
- leaf links;
- parent navigation;
- released-node page reuse;
- persistence and flush behavior;
- RID changes caused by PagedSequentialFile operations.

Do not implement code yet.

Clearly separate:
1. official requirements;
2. stable existing decisions;
3. recommended new decisions;
4. rejected alternatives and why.

The adopted decisions must be recorded in PROJECT_CONTEXT.md before
dependent implementation becomes stable.
```

---

# 48. Recommended prompt for the first coding task

After Task 4.2 decisions are approved and documented:

```text
Implement only the next incomplete task from ETAPA_04.md.

Reuse the completed Stage 1-3 abstractions.
Do not duplicate PageManager, RID, HeapFile, PagedSequentialFile,
or raw physical-offset logic.

Add or update only the relevant tests.
Run the relevant tests and report the results.

If implementation reveals a new stable architectural decision,
state it explicitly so PROJECT_CONTEXT.md can be updated.

Do not implement Stage 5 or later functionality.
```

---

# 49. Condition for moving to Stage 5

Move to Stage 5 only when:

```text
completed Stage 1 abstractions
      +
stable Stage 2 page persistence
      +
completed Stage 3 file organizations
      +
persistent balanced B+ core
      +
exact and range lookup
      +
leaf/internal/root splits
      +
redistribution/merge/root shrink
      +
linked leaf traversal
      +
clustered B+ over physically ordered data
      +
unclustered B+ over independent physical order
      +
RID movement/rebuild integration
      +
Stage 4 tests and structural validation
      +
documented B+ decisions
      =
READY FOR STAGE 5
```

Stage 5 should implement Extendible Hashing through the shared index/storage boundaries rather than modifying the B+ core.
