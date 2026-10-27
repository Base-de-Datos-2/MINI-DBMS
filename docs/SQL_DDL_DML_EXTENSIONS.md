# SQL DDL/DML extensions in the Leaflet demo API

Date: 2026-10-25

## Supported forms

```sql
CREATE INDEX index_name ON table_name (column_name);
CREATE UNIQUE INDEX index_name ON table_name (column_name);
UPDATE table_name SET column_name = literal_or_column [, ...] [WHERE predicate];
DROP INDEX index_name;
DROP TABLE table_name;
```

`WHERE` uses the parser's existing comparison operators and boolean `AND`, `OR`, and `NOT`. `UPDATE` uses a literal or a column reference as each assignment value; no arithmetic, functions, or `NULL` values are accepted.

## Ownership and persistence

The HTTP demo adapter dispatches these statements to `Database` under the owner's schema-change gate. They are standalone operations and are rejected during an explicit transaction. Dynamic indexes on SQL/Files-created tables are stored in `gui_tables.json` and reopened with their table. `DROP TABLE` is limited to dynamically-created tables; fixed Python-declared demo tables are protected from SQL drop. `DROP INDEX` refuses to remove the unique index that enforces a primary key.

`UPDATE` validates the complete resulting row image and unique-index keys before mutation. Since the storage API does not expose a general in-place record replacement contract, the demo rebuilds the table's records and reconstructs all ordinary indexes and the spatial R-Tree. It attempts to restore the previous rows and rebuild indexes if a mutation fails; if restoration itself fails, the owner is quarantined. This is a practical demo implementation, not a claim of crash-atomic WAL-backed UPDATE.

The lower-level standalone `SqlEngine` planner does not yet execute these statement families directly; the frontend uses the HTTP API adapter. General SQL arithmetic, multi-row updates with expression evaluation, transactional DDL/DML semantics, arbitrary index types, and dropping Python-declared fixtures remain out of scope.

## Verification

The API tests cover creating and reopening a B+ index, updating rows, unique-index enforcement, protecting the primary-key index, dropping an index, and dropping a dynamic table. Run them from the repository root with:

```bash
python -m pytest -q tests/api/test_sql_extensions.py
```
