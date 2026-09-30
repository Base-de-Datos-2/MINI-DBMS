# Stage 9 — rollback presentation and documentation correction

**Date:** 2026-09-30
**Scope:** Correct the failed-rollback UI message and synchronize current
Stage 9 documentation with the implemented API/frontend session contract.
Stage 9 formal closure remains pending; this correction does not close it.

## Corrected rollback presentation

An injected before-image restoration failure returned HTTP 503,
`ENGINE_UNAVAILABLE`, and terminal transaction state `ABORT_FAILED`. The API
also returned `details.group_aborted: true` because the session had lost its
explicit group. Previously, `frontend/src/session.ts::failureNote` interpreted
that flag as proof that all changes were undone and locks released.

The frontend now treats the engine's terminal state as the outcome evidence:

| Evidence | UI meaning |
|---|---|
| `ABORTED` with `group_aborted: true` | Confirmed whole-group undo |
| `ABORTED` without that flag | Confirmed abort of the statement's transaction |
| `ABORT_FAILED`, regardless of that flag | Restoration failed; the database is quarantined and needs inspection/repair before reopen |
| Group lost with missing/other terminal state | The group ended; successful restoration is unconfirmed |

The API error contract is preserved. An IDLE session after failed restoration
does not make its owner available. The new HTTP regression injects an actual
undo failure after BEGIN/INSERT and checks the 503 outcome, quarantine,
retained undo/unclean artifacts, and refusal of further SQL. Six frontend
regression cases cover failed and unconfirmed outcomes alongside the existing
successful-abort tests.

## Documentation synchronized

`ETAPA_09.md`, `PROJECT_CONTEXT.md`, `PLAN.md`, `AGENTS.md`, `README.md`,
`docs/demo.md`, `docs/transactions.md`, and the Stage 8 handoff/status now agree:

- Opaque tokens own independent Stage 8 sessions across HTTP requests.
- Independent tokens execute concurrently under engine locks; one token
  allows one active call. Exclusive admission protects sessionless calls only.
- Read-only mode permits SELECT, EXPLAIN, and EXPLAIN ANALYZE. BEGIN/END/ROLLBACK
  require a client session in either mode. Writes require `--allow-writes`.
- GUI creation uses the selected session's standalone schema-change path;
  an open group is refused before execution. SQL CREATE remains disabled under
  the legacy demo owner. Metadata uses the metadata gate without admission.
- Command counts inside a group are provisional until END. Failed restoration
  must not be presented as successful undo.
- Formal Stage 9 closure and Stage 10 experiments/delivery remain pending.

The emergency record and 2026-09-25 review retain their dated measurements,
with explicit pointers distinguishing historical checkpoints from current
behavior. Official academic requirements are unchanged.

## Verification

Commands were run from the repository root on Windows, with frontend commands
run from `frontend/` using the available Node executable:

```powershell
& .venv/Scripts/python.exe -m pytest tests/api tests/transactions -q -W error
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc --noEmit
node node_modules/vite/bin/vite.js build
git diff --check
```

| Check | Result |
|---|---|
| API and transaction regressions, warnings as errors | 246 passed in 190.60 s |
| Frontend Vitest suite | 32 passed across four files |
| TypeScript | Passed |
| Production frontend build | Passed; backend-served assets rebuilt |
| Patch whitespace check | Passed |

This run did not repeat the complete repository suite or a live two-tab
browser demonstration. A real network drop remains unverified. The guarantees
remain Stage 8 in-process undo and clean-reopen behavior; failed restoration
requires explicit inspection/repair, not automatic crash recovery or a blind
server restart.
