# Stage 9 closure audit

**Stage:** 9 — API and Frontend  
**Closed:** 2026-10-01, at the user's request ("if Stage 9 is complete, start Stage 10")  
**Plan:** `PART_01/ETAPA_09.md`, Tasks 9.1–9.18, Section 11 checklists, and the
Stage 8 handoff checklist in `docs/ETAPA_08_STAGE_9_HANDOFF.md`  
**Audited source:** Git `HEAD` `1c9b0a409c831de842a531f3299768fb5cde97a1` (`main`, equal to `origin/main`, clean worktree)  
**Environment:** Linux (WSL2), Python 3.11.9, pytest 8.4.2, FastAPI 0.141.1, Node 20.19.1

Every item of the Stage 9 completion checklists is satisfied. The only open
item before this audit was the formal closure decision itself. This audit
re-ran the complete evidence on the audited commit instead of relying on the
dated reviews, because the 2026-09-30 correction did not repeat the full suite
or a live browser run.

## Checklist audit

| Checklist (ETAPA_09 §11) | Result | Evidence |
|---|---|---|
| Current GUI and transport (7 items) | Satisfied | Four real panels; one execution per statement; bounded previews with truthful totals; lossless values. `tests/api/test_engine_service.py`, `test_http.py`, `test_serialization.py`, `test_presets.py`; browser runs below |
| Optional writes (5 items) | Satisfied | Writes only with `--allow-writes`; provisional vs committed counts; no replay; rollback success requires `ABORTED`. `test_gui_tables.py`, `test_sessions.py`, `test_engine_service.py` |
| Transaction-aware integration (7 items) | Satisfied | Opaque session tokens over Stage 8 `SqlSession`s; concurrent HTTP schedules; failed restoration shown as `ABORT_FAILED`. `tests/api/test_sessions.py`; `frontend/src/session.test.ts` |
| Formal closure decision and audit | Recorded here | — |
| Stage 8 handoff checklist (10 items) | Satisfied | `docs/ETAPA_08_STAGE_9_HANDOFF.md`, each item with its test |

## Verification on the audited commit

| Check | Result |
|---|---|
| Complete repository suite, warnings as errors | **2889 passed in 276.76 s** |
| Frontend | `tsc --noEmit` clean; **32 Vitest tests** passed in 4 files; production build passed |
| Real browser, table creation and CSV import (Chromium headless, Playwright 1.63 in an isolated environment outside the repository) | **16/16** checks: CSV preview and type inference, hash + B+ indexes used by the plan, CSV error with line/column, empty Paged Sequential table with clustered B+ and key order, reload persistence, no JavaScript exceptions |
| Real browser, two tabs | **13/13** checks: separate sessions, provisional INSERT, visible lock wait with its blocker, END releasing the waiter, cancel, ROLLBACK, execute error aborting the group, EXPLAIN ANALYZE, closing a tab releasing its locks, no JavaScript exceptions |

Commands:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q -W error -p no:cacheprovider
(cd frontend && npx tsc --noEmit && npx vitest run && npm run build)
.venv/bin/python -m api --data-dir <copy of data/generated/demo> --port 8765 --allow-writes
```

## Known limits carried forward

- A real network drop in the middle of a request was not simulated. The
  documented policy: the statement finishes and closes its cursor; an explicit
  group keeps its locks until END, ROLLBACK, session close or idle expiry.
- SQL `CREATE TABLE` stays disabled in the legacy demo owner; tables are created
  from the Files panel. Migrating to the manifest-backed owner would require
  widening its manifest (Heap and primary-key B+ only today).
- Guarantees are Stage 8 in-process undo and clean reopen, not crash recovery.
- The demo data directory used for development contains orphan files from an
  uncommitted 2026-09-18 CSV experiment (`alumnos.*`, `csv_tables.json`). The
  owner ignores them; `scripts/setup_demo.py --reset` removes them.

## Handoff to Stage 10

Stage 10 (experiments, integration and delivery) starts from
`PART_01/ETAPA_10.md`. Its Task 10.1 inspection found that storage-level page
re-validation makes 100,000-row loads impractical; see that document before
running benchmarks.
