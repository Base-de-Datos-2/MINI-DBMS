# ETAPA_01.md

> Context version: **1.1** — aligned with `AGENTS.md`, `PROJECT_CONTEXT.md`, `REQUIREMENTS.md`, and `PLAN.md`.

## Stage 1 — Architecture and Data Model

**Part:** Relational Database  
**Dependencies:** None  
**Next stage:** Stage 2 — Pages, Records, and Base Persistence  
**Roadmap:** `PLAN.md`

## Implementation status

- Completed: repository inspection (1.1), initial directory/package structure,
  Python/test configuration, Git exclusions, and introductory README.
- Completed with unit tests: `DataType` (1.2), `Column` (1.3), `Schema` (1.4),
  `RID` (1.5), `Record` (1.6), `TableMetadata` (1.7), minimal `IndexMetadata`
  (1.8), and the in-memory `Catalog` (1.9).
- The model/catalog integration test described in 1.12 also exists; it checks
  the implemented components with file-opening APIs blocked.
- Completed: abstract Storage, Index/OrderedIndex, and Operator contracts
  (1.10), plus minimal domain errors (1.11) integrated with the current model
  and catalog. New interface/error tests pass along with all previous tests.
- Next pending work: final integration/Definition-of-Done review. Stage 1 has
  not been formally closed. No physical implementation was introduced; empty
  packages and directory markers still reserve future locations only.

Adopted model and catalog semantics are recorded in `PROJECT_CONTEXT.md`.

---

# 1. Purpose

Stage 1 establishes the foundational abstractions and contracts used by the rest of the Mini-DBMS.

It answers:

> **What should be implemented now, before physical storage begins?**

This stage does **not** attempt to persist complete records into binary disk pages.

Its purpose is to define a stable conceptual model for:

- data types;
- columns;
- schemas;
- records;
- physical record identifiers;
- table metadata;
- index metadata;
- catalog metadata;
- storage contracts;
- index contracts;
- operator contracts;
- base domain errors.

The goal is to reduce the probability that later stages must redefine fundamental concepts.

---

# 2. Relationship with the project documents

Before implementation, Codex must follow the documentation roles established by `AGENTS.md`.

For Stage 1:

```text
REQUIREMENTS.md
    |
    |  official requirements
    v
PROJECT_CONTEXT.md
    |
    |  stable architecture decisions
    v
PLAN.md
    |
    |  Part 1 roadmap
    v
ETAPA_01.md
    |
    |  detailed Stage 1 work
    v
CODE
```

This stage document must not override official requirements or stable architectural decisions.

If a conflict is found, stop and report it before implementing the conflicting behavior.

---

# 3. Expected outcome

At the end of Stage 1, code conceptually similar to the following should be possible:

```python
schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("age", DataType.INTEGER),
])

record = Record(
    schema=schema,
    values=[1, "Ana", 21],
)

table = TableMetadata(
    name="students",
    schema=schema,
)

catalog = Catalog()
catalog.register_table(table)

assert catalog.get_table("students").schema == schema
```

A physical record identifier should also exist conceptually:

```python
rid = RID(page_id=4, slot_id=2)
```

even though a real Heap File does not yet exist to generate it.

---

# 4. Required reading before implementation

Before modifying code:

1. read `AGENTS.md`;
2. read `REQUIREMENTS.md`;
3. read `PROJECT_CONTEXT.md`;
4. read `PLAN.md`;
5. read `ETAPA_01.md`;
6. inspect the existing repository;
7. inspect existing tests.

Do not create a new abstraction before checking whether an equivalent one already exists.

For example, do not create all of these if they represent the same concept:

```text
Schema
TableSchema
RelationSchema
```

Reuse compatible existing code.

---

# 5. Scope of Stage 1

## Included

```text
DataType
Column
Schema
Record
RID
TableMetadata
minimal IndexMetadata
Catalog
Storage contract
Index contract
Operator contract
base domain errors
unit tests
Stage 1 integration test
```

## Explicitly not included

```text
binary Page implementation
real PageManager
HeapFile
PagedSequentialFile
B+ Tree implementation
Extendible Hashing implementation
SQL parser
AST execution
Planner
Executor
Transactions
FastAPI
React
Benchmarks
```

If later-stage code already exists in the repository:

- preserve it;
- inspect it;
- do not delete it;
- do not extend it unless needed to keep Stage 1 compatible.

---

# 6. Target package organization

A possible Stage 1 organization is:

```text
engine/
├── __init__.py
│
├── catalog/
│   ├── __init__.py
│   ├── types.py
│   ├── schema.py
│   ├── metadata.py
│   └── catalog.py
│
├── storage/
│   ├── __init__.py
│   ├── rid.py
│   ├── record.py
│   └── base.py
│
├── indexes/
│   ├── __init__.py
│   └── base.py
│
└── operators/
    ├── __init__.py
    └── base.py

tests/
├── catalog/
├── storage/
├── indexes/
└── operators/
```

This structure is **illustrative**, not mandatory.

If the repository already uses a coherent alternative structure, do not reorganize it solely to match this example.

---

# 7. Task 1.1 — Inspect the repository

## Objective

Determine the actual project state before implementation begins.

## Actions

Codex should inspect:

- repository structure;
- schema-related classes;
- record-related classes;
- table metadata;
- RID or equivalent physical identifiers;
- catalog code;
- storage abstractions;
- index abstractions;
- operator abstractions;
- existing tests;
- existing architecture decisions.

## Expected output

Provide a short report:

```text
Existing:
- ...

Missing:
- ...

Potential conflicts:
- ...

Reusable code:
- ...

Recommended Stage 1 implementation order:
- ...
```

## Restriction

Do not modify code during Task 1.1.

---

# 8. Task 1.2 — Define or normalize `DataType`

## Objective

Represent the basic relational data types used by schemas.

## Recommended initial types

```text
INTEGER
FLOAT
BOOLEAN
VARCHAR
```

These are project-level implementation choices, not literal official requirements.

Do not add a large type system unless the project requires it.

---

## Possible interface

```python
from enum import Enum

class DataType(Enum):
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    BOOLEAN = "BOOLEAN"
    VARCHAR = "VARCHAR"
```

This is only an example.

Reuse an existing equivalent implementation when possible.

---

## Requirements

`DataType` should:

- compare predictably;
- be suitable for later serialization;
- remain independent from Lark;
- remain independent from FastAPI;
- remain independent from React.

---

## Suggested tests

```text
test_integer_type_exists
test_float_type_exists
test_boolean_type_exists
test_varchar_type_exists
```

If parsing from text is supported:

```text
test_datatype_from_string
test_invalid_datatype
```

---

## Definition of Done

`DataType` can be used reliably by `Column` and `Schema`.

---

# 9. Task 1.3 — Implement `Column`

## Objective

Represent metadata for one table column.

## Minimum recommended fields

```text
name
data_type
```

Potential future fields may include:

```text
nullable
length
primary_key
```

Do not add them yet unless existing code or current requirements need them.

Avoid building a full constraint system in Stage 1.

---

## Example

```python
Column(
    name="id",
    data_type=DataType.INTEGER,
)
```

---

## Minimum validation

- column name must not be empty;
- data type must be valid.

---

## Suggested tests

```text
test_create_column
test_column_rejects_empty_name
test_column_has_type
```

---

## Definition of Done

A `Column` can be safely included in a `Schema`.

---

# 10. Task 1.4 — Implement `Schema`

## Objective

Represent the ordered set of columns that defines one relational row structure.

## Minimum capabilities

```text
columns
len(schema)
get column by name
get column by position
detect duplicate names
```

---

## Example

```python
schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
])
```

---

## Recommended behavior

A method such as:

```python
schema.column("id")
```

may return the matching column.

A method such as:

```python
schema.index_of("id")
```

may return the column position.

Exact method names are not mandatory.

---

## Validation

- preserve column order;
- reject duplicate column names;
- handle unknown columns clearly.

Do not silently introduce case normalization unless that behavior has been explicitly decided.

---

## Suggested tests

```text
test_schema_preserves_column_order
test_schema_get_column_by_name
test_schema_get_column_by_index
test_schema_rejects_duplicate_names
test_schema_unknown_column
```

---

## Definition of Done

`Schema` provides stable ordered column metadata for `Record` and `TableMetadata`.

---

# 11. Task 1.5 — Implement `RID`

## Objective

Represent a stable physical record identifier.

Current conceptual design from `PROJECT_CONTEXT.md`:

```text
RID(page_id, slot_id)
```

---

## Recommended properties

- immutable;
- comparable;
- hashable;
- validated.

Example:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class RID:
    page_id: int
    slot_id: int
```

---

## Recommended validation

```text
page_id >= 0
slot_id >= 0
```

If later stages require a sentinel value, document that decision before changing the invariant.

---

## Suggested tests

```text
test_create_rid
test_rid_equality
test_rid_hashable
test_rid_rejects_negative_page
test_rid_rejects_negative_slot
```

---

## Future consumers

The RID is expected to be used by components such as:

```text
HeapFile
unclustered B+
Extendible Hashing
IndexScan
```

---

## Definition of Done

`RID` is a stable, reusable identifier independent from any specific file implementation.

---

# 12. Task 1.6 — Implement `Record`

## Objective

Represent one relational row according to a `Schema`.

`Record` must remain independent from:

- `Page`;
- `HeapFile`;
- B+ implementation;
- SQL parser;
- HTTP/API code;
- frontend code.

---

## Recommended model

```text
schema
values
```

Example:

```python
record = Record(
    schema=schema,
    values=[1, "Ana", 21],
)
```

An equivalent representation is acceptable if already present.

---

## Minimum validation

At minimum:

```text
len(values) == len(schema.columns)
```

Prefer also validating value compatibility with `DataType`.

Keep Stage 1 validation understandable and deterministic.

---

## Recommended Python compatibility policy

Conceptually:

```text
INTEGER -> int
FLOAT   -> float, optionally int according to explicit policy
BOOLEAN -> bool
VARCHAR -> str
```

Avoid aggressive implicit coercion.

For example:

```text
"123"
```

should not silently become:

```text
123
```

unless the project explicitly adopts that rule.

---

## Column access

One of these styles is sufficient:

```python
record["name"]
```

or:

```python
record.get("name")
```

Do not implement multiple APIs without need.

---

## Suggested tests

```text
test_create_record
test_record_rejects_wrong_value_count
test_record_access_by_column
test_record_preserves_schema
test_record_type_validation
```

---

## Definition of Done

A `Record` can validate and expose values according to its `Schema` without depending on physical storage.

---

# 13. Task 1.7 — Implement `TableMetadata`

## Objective

Represent a table in the catalog without implementing its physical storage yet.

## Minimum fields

```text
name
schema
```

Potential future fields include:

```text
storage_type
file_path
primary_key
indexes
```

Do not add them prematurely.

---

## Example

```python
TableMetadata(
    name="students",
    schema=student_schema,
)
```

---

## Suggested tests

```text
test_create_table_metadata
test_table_has_schema
test_table_rejects_empty_name
```

---

## Definition of Done

Table identity and schema can be represented independently from Heap File or Sequential File implementations.

---

# 14. Task 1.8 — Implement minimal `IndexMetadata`

## Objective

Allow the catalog to describe indexes without implementing B+ or Extendible Hashing yet.

## Possible fields

```text
name
table_name
column_name
index_type
clustered
```

Keep the first version minimal.

---

## Possible future index types

```text
BPLUS
EXTENDIBLE_HASH
```

This task must not create:

- B+ nodes;
- hash directories;
- hash buckets;
- index disk pages.

---

## Suggested tests

```text
test_create_index_metadata
test_index_references_table
test_index_references_column
```

---

## Definition of Done

The catalog can describe an index definition without depending on an index implementation.

---

# 15. Task 1.9 — Implement `Catalog`

## Objective

Maintain table and minimal index metadata.

The Stage 1 catalog may remain in memory.

Catalog persistence is an unresolved architectural decision unless the repository already establishes it.

---

## Minimum table operations

```text
register_table(table)
get_table(name)
has_table(name)
list_tables()
```

Dropping/unregistering a table may be deferred unless needed.

---

## Minimum index operations

If `IndexMetadata` is included:

```text
register_index(index)
get_indexes(table)
```

---

## Validation

- reject duplicate table registrations;
- handle unknown table lookup clearly;
- validate basic index references;
- avoid accidental mutation that violates catalog invariants.

---

## Suggested tests

```text
test_register_table
test_get_table
test_list_tables
test_reject_duplicate_table
test_unknown_table
test_register_index
test_index_requires_existing_table
```

---

## Definition of Done

The catalog can register and resolve table metadata, and optionally minimal index metadata, without depending on physical persistence.

---

# 16. Task 1.10 — Define abstract contracts

These contracts prepare later stages without implementing their algorithms.

---

## 16A. Storage contract

### Objective

Provide a common behavioral boundary for future storage organizations.

Conceptually:

```python
class Storage:
    def insert(self, record) -> RID: ...
    def read(self, rid) -> Record: ...
    def delete(self, rid) -> None: ...
    def scan(self): ...
```

Possible Python mechanisms:

```text
ABC
Protocol
duck typing
```

Choose the style that best matches the existing repository.

### Must not do in Stage 1

- open real storage files;
- allocate pages;
- implement Heap File;
- implement Paged Sequential File.

---

## 16B. Index contract

Conceptually:

```python
class Index:
    def insert(self, key, rid): ...
    def search(self, key): ...
    def delete(self, key, rid): ...
```

Range search should not be forced onto Extendible Hashing.

A specialized ordered-index contract is acceptable:

```text
Index
└── OrderedIndex
```

with:

```text
OrderedIndex.range_search(...)
```

The exact hierarchy is an architectural choice.

---

## 16C. Operator contract

Conceptually:

```text
open()
next()
close()
```

or an equivalent iterator-based API.

Do not implement `TableScan` yet.

---

## Suggested tests

Pure interfaces may require only lightweight tests, for example:

- dummy implementation compatibility;
- abstract-method enforcement if ABC is used;
- protocol conformance if explicitly testable.

Do not write meaningless tests only to increase test count.

---

## Definition of Done

Future storage, index, and operator implementations have stable contracts to target.

---

# 17. Task 1.11 — Add base domain errors

## Objective

Provide clear domain-specific errors for foundational components.

Potential examples:

```text
DatabaseError
CatalogError
SchemaError
UnknownTableError
DuplicateTableError
UnknownColumnError
```

Do not create a large exception hierarchy without real use cases.

Prefer meaningful errors over generic patterns such as:

```python
raise Exception("bad")
```

---

## Definition of Done

Core Stage 1 modules can signal invalid domain operations clearly without overengineering the error system.

---

# 18. Task 1.12 — Add the Stage 1 integration test

## Objective

Prove that the foundational abstractions work together.

Example:

```python
def test_catalog_schema_record_integration():
    schema = Schema([
        Column("id", DataType.INTEGER),
        Column("name", DataType.VARCHAR),
    ])

    table = TableMetadata(
        name="students",
        schema=schema,
    )

    catalog = Catalog()
    catalog.register_table(table)

    record = Record(
        schema=schema,
        values=[1, "Ana"],
    )

    assert catalog.get_table("students").schema == schema
    assert record["name"] == "Ana"
```

This test must not access disk.

---

## Definition of Done

At least one integration test proves that `Schema`, `Record`, table metadata, and `Catalog` work together.

---

# 19. Recommended implementation order

```text
1.1 Inspect repository
        |
        v
1.2 DataType
        |
        v
1.3 Column
        |
        v
1.4 Schema
        |
        +--------------+
        |              |
        v              v
1.5 RID           1.6 Record
        |              |
        +------+-------+
               |
               v
        1.7 TableMetadata
               |
               v
        1.8 IndexMetadata
               |
               v
        1.9 Catalog
               |
               v
        1.10 Contracts
               |
               v
        1.11 Base Errors
               |
               v
        1.12 Integration Test
```

Tasks may be grouped into one small change when doing so keeps the implementation clear and reviewable.

---

# 20. Recommended commit strategy

Examples:

```text
docs: align stage 1 implementation plan

feat(catalog): add relational data types and columns

feat(catalog): add schema representation

feat(storage): add RID abstraction

feat(storage): add record model

feat(catalog): add table metadata and catalog

feat(core): add storage index and operator contracts

feat(core): add base domain errors

test(stage1): add architecture model integration tests
```

Do not create large commits such as:

```text
finish database
```

if the work can be reviewed incrementally.

---

# 21. Validation commands

If pytest is already the project test framework:

```bash
pytest
```

During development, narrower commands may be used:

```bash
pytest tests/catalog -q
pytest tests/storage -q
pytest tests/indexes -q
pytest tests/operators -q
```

At the end of the stage:

```bash
pytest -q
```

Optional syntax/import validation:

```bash
python -m compileall engine
```

Do not add a new linter/formatter solely for this stage unless the repository already uses it or the user explicitly requests it.

---

# 22. Stage 1 Definition of Done

Stage 1 is complete only when all applicable items are satisfied.

## Architecture

```text
[ ] repository structure remains modular
[ ] no frontend-to-storage dependency was introduced
[ ] no future-stage algorithm was implemented unnecessarily
[ ] existing compatible code was reused instead of duplicated
```

## Data model

```text
[x] DataType
[x] Column
[x] Schema
[x] Record
[x] RID
```

## Metadata

```text
[x] TableMetadata
[x] Catalog
[x] minimal IndexMetadata, if adopted in the Stage 1 design
```

## Contracts

```text
[x] Storage contract
[x] Index contract
[x] Operator contract
```

## Domain errors

```text
[x] foundational modules use clear domain errors where useful
[x] no unnecessary exception hierarchy was introduced
```

## Quality

```text
[ ] relevant unit tests exist
[x] Stage 1 integration test exists
[ ] all relevant tests pass
[ ] imports are stable
[ ] no equivalent foundational abstraction was duplicated
[ ] documentation reflects stable decisions
```

Only after this checklist is satisfied should the project move to Stage 2.

---

# 23. What is NOT required to complete Stage 1

Stage 1 does not require:

```text
[ ] binary page persistence
[ ] Heap File
[ ] Paged Sequential File
[ ] B+ Tree
[ ] Extendible Hashing
[ ] SELECT execution
[ ] Planner
[ ] Executor
[ ] transactions
[ ] FastAPI
[ ] React
[ ] benchmarks
```

Implementing future-stage functionality does not compensate for an incomplete Stage 1 foundation.

---

# 24. Decisions to carry into Stage 2

By the end of Stage 1, the following unresolved decisions should at least be identified clearly.

They do not all need to be solved inside Stage 1.

---

## 24.1 Final page size

The official assignment requires page-based storage but does not prescribe a particular page size.

Example candidate:

```text
4096 bytes
```

Do not treat that value as official until the project adopts it.

Once adopted, record it in `PROJECT_CONTEXT.md`.

---

## 24.2 Binary page layout

A possible layout may include:

```text
PageHeader
SlotDirectory
FreeSpace
Records
```

The final layout belongs to Stage 2 architecture.

---

## 24.3 Record-length strategy

The project must decide how the physical layer handles:

```text
fixed-length records
variable-length records
```

or whether one unified slotted-page strategy will support both.

This decision should consider reusable code already present in the repository.

---

## 24.4 Binary encoding

A coherent encoding policy will be needed for:

```text
integers
floats
booleans
strings
headers
```

Do not design the full serializer inside Stage 1 unless existing code already requires it.

---

## 24.5 Catalog persistence

Decide later whether:

- catalog metadata becomes persistent starting in Stage 2;
- or catalog persistence is introduced in a later integration step.

When the decision becomes stable, record it in `PROJECT_CONTEXT.md`.

---

# 25. Recommended prompt to start Stage 1 with Codex

```text
Read AGENTS.md, REQUIREMENTS.md, PROJECT_CONTEXT.md, PLAN.md,
and ETAPA_01.md.

Then inspect the repository, focusing on existing implementations related to:
- DataType
- Column
- Schema
- Record
- RID
- TableMetadata
- IndexMetadata
- Catalog
- storage contracts
- index contracts
- operator contracts
- base domain errors
- relevant tests

Do not modify any files yet.

Report:
1. which Stage 1 components already exist;
2. which are missing;
3. any naming or architectural conflicts;
4. which existing code should be reused;
5. which stable decisions are already present in the codebase;
6. the smallest safe implementation sequence for the remaining Stage 1 tasks.

Do not implement Stage 2 or later functionality.
```

---

# 26. Recommended prompt for the first implementation step

After reviewing Codex's inspection report:

```text
Implement only the first missing task from ETAPA_01.md.

Reuse existing compatible code.
Do not implement future-stage functionality.

Add or update only the relevant tests.
Run the relevant tests and report the result.

If the task requires making a new stable architectural decision,
state it explicitly so PROJECT_CONTEXT.md can be updated.
```

---

# 27. Condition for moving to Stage 2

Move to Stage 2 only when:

```text
Stage 1 data model
      +
Stage 1 metadata
      +
Stage 1 contracts
      +
Stage 1 base errors
      +
Stage 1 tests
      +
stable imports
      +
documented stable decisions
      =
READY FOR STAGE 2
```

Stage 2 must build on these abstractions rather than replacing them.
