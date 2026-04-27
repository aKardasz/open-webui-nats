# Plan — Remaining OpenWebUI 0.9.x Follow-up for NATS Ownership and Async DB Migration

Date: 2026-04-24
Context: follow-on plan after the selected upstream `0.9.x` feature slices were ported into `open-webui-nats` and left in verification/closeout.

## Requirements Summary

### Goal
Finish the remaining architecture work after the `0.9.x` slice port by:
1. moving runtime-owned automation execution fully behind NATS-compatible service ownership, and
2. creating an incremental async DB/session migration path for the newly ported slices without destabilizing the existing fork.

### Current-state evidence
- The port intentionally deferred full async DB/session adoption to a later phase.
  - `.omx/plans/prd-openwebui-0.9-nats-port.md:35-41`
  - `.omx/plans/prd-openwebui-0.9-nats-port.md:222-259`
- Automation execution is still explicitly transitional/local.
  - `backend/open_webui/utils/automations.py:62-67`
  - `backend/open_webui/utils/automations.py:241-242`
- The web app still owns the embedded automation scheduler loop.
  - `backend/open_webui/main.py:718-723`
  - `backend/open_webui/main.py:846-849`
  - `backend/open_webui/utils/automations.py:262-275`
- Manual automation runs still execute locally from the API tier via `BackgroundTasks`.
  - `backend/open_webui/routers/automations.py:177-189`
- Automation/calendar persistence still uses synchronous SQLAlchemy sessions and sync helpers.
  - `backend/open_webui/internal/db.py:158-180`
  - `backend/open_webui/models/automations.py:103-246`
  - `backend/open_webui/models/calendar.py:187-260`
- The chat task/read/shared-chat slices are already ported and should be treated as regression-sensitive, not primary NATS rework targets.
  - `backend/open_webui/main.py:2197-2209`
  - `backend/open_webui/routers/chats.py:818-904`
  - `src/lib/components/chat/Chat.svelte:464-465`
  - `src/lib/components/chat/Chat.svelte:2408`

### Non-goals
- Do not attempt a raw upstream async backend/session rebase.
- Do not rewrite all legacy DB access in one tranche.
- Do not re-open already-working chat task stop/read/shared-chat behavior unless a regression or routing dependency requires it.

## Architecture Decision

### Decision
Implement the remaining work in **two ordered tracks**:
1. **Track A — NATS ownership for automations/calendar runtime behavior**
2. **Track B — incremental async DB/session migration for the ported slices**

### Why this order
- The biggest current architecture gap is that automation execution is still owned by the web process, even though the port plan expected a dedicated NATS-compatible runner seam.
  - `backend/open_webui/utils/automations.py:62-67`
  - `backend/open_webui/main.py:721-722`
- Converting the DB/session layer before extracting runtime ownership would mix two high-risk changes in the same execution path.
- Calendar itself is primarily a DB/API/UI surface; the runtime-owned part is scheduled automation execution and any event/alert fanout, not basic CRUD.

## Acceptance Criteria

### A. NATS ownership / runtime criteria
1. Automation execution can be requested without calling `execute_automation` directly from the API router.
2. When NATS automation-runner mode is enabled, the web app does not start the embedded scheduler loop.
3. Due automation claiming/execution is owned by a dedicated runner lane, not the web API process.
4. Automation run requests and lifecycle events have explicit subjects/contracts and are observable in runtime registry metadata.
5. Runtime registry reports `automation-runner` as healthy and no longer marks execution as `transitional-local` in NATS-owned mode.
6. Calendar scheduled-task projection remains correct for upcoming runs and recorded runs after the runner extraction.
7. Existing task stop/read/share behavior remains green.

### B. Async DB/session criteria
1. An async engine/session factory exists alongside the current sync path with a controlled migration boundary.
2. The automations/calendar/shared-chat/chat-read slices use explicit repository/service boundaries that can operate with async sessions.
3. At least one complete vertical slice (recommended: automations + calendar) is migrated off sync request-path DB access.
4. No converted route depends on `SessionLocal`/`get_db_context` for its mainline path.
5. Migrations/tests run on both empty and representative local DB state for the converted slices.

## Implementation Steps

### Phase 1 — Freeze the runtime contract before moving code
**Files:**
- `backend/open_webui/utils/automations.py`
- `backend/open_webui/utils/runtime_registry.py`
- `backend/open_webui/env.py`
- `docs/architecture/nats/*.md`
- `.omx/plans/test-spec-openwebui-0.9-nats-port.md`

**Tasks:**
1. Define the automation command/event contract explicitly:
   - add command subjects for enqueue/claim/ack/result (for example `owui.cmd.automation.run`, plus any claim/result subjects needed)
   - keep the existing lifecycle event subjects as the outward-facing run event stream
2. Decide whether scheduling is:
   - **Option A (recommended):** owned entirely by the automation-runner service, or
   - **Option B:** web tier enqueues only manual runs while runner owns due scheduling
3. Extend runtime-registry metadata so automation-runner is a first-class routeable service, not just an informational record.

**Deliverable:**
A small ADR/update in docs and plan notes that fixes subject names, ownership, and fallback behavior before code moves.

### Phase 2 — Extract automation-runner service ownership
**Files:**
- `backend/open_webui/utils/automations.py`
- `backend/open_webui/main.py`
- `backend/open_webui/env.py`
- `backend/open_webui/utils/runtime_registry.py`
- `docker-compose.nats.yaml`
- likely new file: `backend/open_webui/utils/automation_runner.py`

**Tasks:**
1. Split current automation logic into three seams:
   - request/enqueue boundary
   - due-work claiming loop
   - execution worker
2. Move `scheduler_worker_loop` out of embedded web startup into a dedicated runner path.
3. Introduce automation-runner startup/close helpers patterned after pipeline-runner / terminal-service startup.
4. Add config gates for:
   - embedded automation runner allowed/disabled
   - runner-only mode
   - NATS subject names / timeouts / durable consumer settings if needed
5. Update runtime registry so the automation-runner advertises its command subjects and an execution mode that reflects reality.

**Deliverable:**
A dedicated runner surface that can be started independently and that removes the web-process scheduler from the primary NATS deployment path.

### Phase 3 — Rewire the web/API edge to enqueue instead of execute
**Files:**
- `backend/open_webui/routers/automations.py`
- `backend/open_webui/utils/automations.py`
- `backend/open_webui/models/automations.py`
- `src/lib/apis/automations/index.ts`
- `src/routes/(app)/automations/+page.svelte`
- `src/routes/(app)/automations/[id]/+page.svelte`

**Tasks:**
1. Replace `background_tasks.add_task(execute_automation, ...)` in `POST /{id}/run` with an enqueue/request boundary.
2. Add a run-request identifier / correlation shape so UI and logs can distinguish:
   - accepted
   - running
   - succeeded
   - failed
3. Ensure automation-run records are written from the execution owner, not optimistically by the API edge.
4. Decide and document fallback behavior when NATS is unavailable:
   - fail closed in NATS-owned mode, or
   - explicit local fallback only in dev/transitional mode

**Deliverable:**
The web tier becomes an API/UX edge; it stops directly owning automation execution.

### Phase 4 — Align calendar with the extracted runner
**Files:**
- `backend/open_webui/routers/calendar.py`
- `backend/open_webui/models/calendar.py`
- `backend/open_webui/models/automations.py`
- `backend/open_webui/utils/calendar.py`
- optional new event/projection helper under `backend/open_webui/utils/`

**Tasks:**
1. Keep calendar CRUD/read paths local DB-backed.
2. Re-check the “Scheduled Tasks” virtual calendar against the new runner-owned run/write flow.
3. If user-facing reminders/alerts are desired, add explicit calendar/automation alert event payloads rather than implicitly coupling them to the web process.
4. Make sure projected runs are sourced from persisted automation state + run history, not hidden in-process scheduler state.

**Deliverable:**
Calendar stays a read/API surface while runtime-owned scheduled work is sourced from durable runner state.

### Phase 5 — Add focused NATS verification and deployment proof
**Files:**
- `backend/open_webui/test/util/test_automations_utils.py`
- `backend/open_webui/test/util/test_automation_calendar_routes.py`
- `backend/open_webui/test/util/test_feature_http_smoke.py`
- new runner-focused tests under `backend/open_webui/test/util/`
- `docs/architecture/nats/07-stage-b-smoke-runbook.md`

**Tasks:**
1. Add tests for enqueue -> claim -> execute -> result flow.
2. Add restart/idempotency coverage for the automation-runner.
3. Add runtime-registry proof that automation-runner is discoverable and healthy.
4. Add compose smoke proof for `open-webui + nats + automation-runner (+ retrieval-worker/terminal-service/pipeline-runner as applicable)`.

**Deliverable:**
A reproducible NATS-enabled smoke run that proves automation execution no longer depends on the web process.

### Phase 6 — Introduce async DB/session scaffolding without breaking sync slices
**Files:**
- `backend/open_webui/internal/db.py`
- likely new files under `backend/open_webui/internal/` for async session helpers
- ported slice repositories/services under `backend/open_webui/models/` or a new `services/` layer

**Tasks:**
1. Add async engine + async session factory alongside the existing sync engine.
2. Add explicit repository/service boundaries for the ported slices instead of letting routes talk directly to sync table helpers forever.
3. Decide the migration unit:
   - **recommended first async slice:** automations + calendar
   - **second async slice:** shared_chat + chat read state
4. Keep migrations and startup compatibility intact while dual-stack exists.

**Deliverable:**
A controlled dual-stack DB layer that allows slice-by-slice async adoption.

### Phase 7 — Convert the first vertical slice to async
**Files:**
- `backend/open_webui/models/automations.py`
- `backend/open_webui/models/calendar.py`
- `backend/open_webui/routers/automations.py`
- `backend/open_webui/routers/calendar.py`
- `backend/open_webui/internal/db.py`
- related tests

**Tasks:**
1. Replace sync session usage in the selected slice with async session usage.
2. Remove sync `db.commit()/db.refresh()` request-path ownership from converted routes.
3. Convert tests for the slice so they validate async session behavior explicitly.
4. Preserve API contracts and response payloads.

**Deliverable:**
One end-to-end async slice with stable API parity.

### Phase 8 — Convert chat/share follow-up DB paths only after the first slice is stable
**Files:**
- `backend/open_webui/models/shared_chats.py`
- `backend/open_webui/models/chats.py`
- `backend/open_webui/routers/chats.py`
- related tests

**Tasks:**
1. Migrate shared-chat snapshot and access-grant lookups to the new async repository/service pattern.
2. Migrate `last_read_at` / mark-read persistence path.
3. Re-verify stop-by-chat behavior for persisted and `local:{socket_id}` chats.

**Deliverable:**
The remaining `0.9.x` persistence slices are on the new async path without reopening unrelated chat behavior.

## Risks and Mitigations

### Risk 1 — Split-brain execution between web and runner
**Mitigation:**
- Make one owner authoritative per mode.
- In NATS-owned mode, disable embedded scheduler startup entirely.
- Persist a clear execution mode in config/runtime metadata.

### Risk 2 — Async migration bleeds into unrelated legacy code
**Mitigation:**
- Convert one vertical slice at a time.
- Introduce repository/service boundaries before bulk route conversion.
- Keep unchanged legacy routes on sync until their slice is scheduled.

### Risk 3 — Calendar becomes over-coupled to runtime internals
**Mitigation:**
- Keep calendar CRUD local.
- Source scheduled-task views from persisted automation state/run records and explicit event contracts.
- Avoid direct in-memory dependencies on runner state.

### Risk 4 — Verification regresses because global checks remain noisy
**Mitigation:**
- Keep the focused util-suite and live-smoke gates as the primary proof path.
- Continue to record whole-project `npm run check` limitations separately until that lane is stabilized.

## Verification Steps

### Runtime/NATS verification
```bash
cd /mnt/c/dev/NatsWebUI/open-webui-nats
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_automations_utils.py \
  backend/open_webui/test/util/test_automation_calendar_routes.py \
  backend/open_webui/test/util/test_runtime_registry.py \
  backend/open_webui/test/util/test_task_messaging.py \
  backend/open_webui/test/util/test_pipeline_runner.py \
  backend/open_webui/test/util/test_terminal_service.py -q
```

### Async slice verification
```bash
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_automations_utils.py \
  backend/open_webui/test/util/test_calendar_utils.py \
  backend/open_webui/test/util/test_automation_calendar_routes.py \
  backend/open_webui/test/util/test_notes_and_shared_chat_routes.py \
  backend/open_webui/test/util/test_feature_http_smoke.py -q
```

### Broader regression floor
```bash
./.venv/Scripts/python.exe -m compileall backend/open_webui
./.venv/Scripts/python.exe -m pytest backend/open_webui/test/util -q
npm run check
```

### Live deployment proof
- Add/update compose proof for `open-webui`, `nats`, and the new `automation-runner` service.
- Prove:
  - app readiness
  - automation enqueue acceptance
  - runner claim/execute/result path
  - scheduled-task calendar projection still correct
  - protected routes still enforce auth

## Recommended Execution Order
1. Phase 1 — contract freeze
2. Phase 2 — runner extraction
3. Phase 3 — API enqueue boundary
4. Phase 4 — calendar alignment
5. Phase 5 — NATS smoke proof
6. Phase 6 — async DB scaffolding
7. Phase 7 — first async vertical slice
8. Phase 8 — chat/share follow-up async migration

## Stop Conditions / Handoff Notes
- Stop Track A only when the web tier is no longer the primary execution owner for automations in NATS mode.
- Stop Track B only after at least one vertical slice is fully async and the remaining sync slices are explicitly tracked, not implicit.
- Do not merge Track B ahead of Track A unless a concrete blocker proves the runner extraction depends on async DB first.
