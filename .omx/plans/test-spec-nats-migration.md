# Test Spec — NATS Migration

## Verification philosophy

Each migration milestone must prove:

1. existing behavior is preserved where intended
2. the new messaging boundary works in isolation
3. regressions are caught as close as possible to the touched area

## Global checks

- `python -m compileall backend/open_webui`
- targeted pytest for any new backend helper/module touched
- `npm run check` only if frontend files are changed
- `npm run test:frontend` only if frontend behavior is changed

## Milestone-specific verification

### M0 — Docs / planning
- files exist:
  - `.omx/context/nats-migration-*.md`
  - `.omx/plans/prd-nats-migration.md`
  - `.omx/plans/test-spec-nats-migration.md`
- docs tree staged cleanly without `.omx/`

### M1 — Messaging foundation

Touched areas:
- `backend/open_webui/messaging/*`
- `backend/open_webui/main.py`
- `backend/open_webui/env.py`
- optional config surface

Checks:
- `python -m compileall backend/open_webui`
- startup smoke test succeeds with Redis-only mode
- startup smoke test succeeds with NATS disabled
- existing app readiness path still works when optional NATS is unavailable

### M2 — Task control

Touched areas:
- `backend/open_webui/tasks.py`
- startup/listener wiring

Checks:
- `python -m compileall backend/open_webui`
- targeted tests for:
  - task creation
  - task cleanup
  - stop signaling dispatch
  - local cancellation on received stop command
- manual check:
  - create task
  - list task
  - stop task
  - list tasks by chat/item id

### M3 — Domain events

Touched areas:
- `backend/open_webui/routers/files.py`
- `backend/open_webui/routers/terminals.py`

Checks:
- `python -m compileall backend/open_webui`
- manual file upload + process still works
- manual terminal proxy still works
- event emission failure does not break request success path

### M4 — Durable retrieval jobs

Touched areas:
- retrieval/file/knowledge handlers and worker mode

Checks:
- `python -m compileall backend/open_webui`
- targeted tests for:
  - job envelope creation
  - idempotent duplicate job handling
  - retry-safe state transitions
- manual check:
  - upload file
  - observe queued/started/completed flow
  - restart worker / simulate retry
  - final file status remains correct

### M5 — KV registry

Touched areas:
- `backend/open_webui/utils/tools.py`
- runtime registry helpers

Checks:
- `python -m compileall backend/open_webui`
- targeted tests for:
  - runtime capability record normalization
  - freshness filtering / stale entry handling
- manual check:
  - startup cache still works
  - runtime records can be materialized without changing admin policy behavior

### M6 — Pipeline adapter / terminal prep

Checks:
- `python -m compileall backend/open_webui`
- pipeline HTTP compatibility unchanged
- terminal browser websocket path unchanged

## Architect sign-off floor

Every code-bearing milestone requires at least STANDARD architect verification before completion.
