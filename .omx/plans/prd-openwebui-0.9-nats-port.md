# PRD — OpenWebUI 0.9.x Upstream Port for NATS Fork

Date: 2026-04-21
Scope: bring selected Open WebUI `main` updates from upstream `0.9.0` / `0.9.1` into `open-webui-nats`, adapting new runtime features to the fork's NATS-first architecture.

## Requirements Summary

### Goal
Upgrade the fork from the current upstream baseline (`0.8.12`) toward upstream `0.9.x` feature parity where the new functionality materially improves the product, while preserving and strengthening the fork's existing NATS control-plane architecture.

### Non-goals
- Do not perform a raw upstream backend rebase first.
- Do not replace the existing NATS runtime seams with upstream single-process `asyncio` background loops.
- Do not begin with the full upstream async ORM/session migration.

## Source-of-truth findings

- Local fork version is still `0.8.12`.
  - `package.json:3`
  - `CHANGELOG.md:8`
- Upstream `main` is `0.9.1` as of 2026-04-21, with the major feature drop in `0.9.0` on 2026-04-20.
  - `/tmp/open-webui-upstream/package.json:3`
  - `/tmp/open-webui-upstream/CHANGELOG.md:8`
  - `/tmp/open-webui-upstream/CHANGELOG.md:15`
- Local fork already has NATS-based distributed seams for task stop/eventing, retrieval, pipelines, terminal lifecycle, and runtime registry.
  - `backend/open_webui/utils/task_messaging.py:23-35`
  - `backend/open_webui/utils/retrieval_transport.py:90-179`
  - `backend/open_webui/utils/retrieval_worker.py:13-25`
  - `backend/open_webui/utils/pipeline_runner.py:17-38`
  - `backend/open_webui/utils/runtime_registry.py:17-28`
  - `backend/open_webui/main.py:661-686`

## Product Decision

Adopt upstream `0.9.x` in **feature slices**, not as a monolithic merge:

1. absorb low-risk dependency and schema fixes
2. port chat/storage improvements that are mostly local data-model changes
3. port chat task/unread UX on top of the existing NATS task/eventing control plane
4. port automations/calendar, but redesign execution ownership around NATS service lanes
5. treat the upstream async DB/session conversion as a later, isolated migration program

## Prioritized Port Lanes

### Lane 1 — Immediate low-risk sync

#### 1.1 Package metadata alignment
Pull upstream package metadata fixes needed for `0.9.1` compatibility.

Files:
- `pyproject.toml`
- `backend/requirements.txt`

Required upstream deltas:
- add `aiosqlite`
- add `asyncpg`

Evidence:
- local omits them: `pyproject.toml:38-41`
- upstream includes them: `/tmp/open-webui-upstream/pyproject.toml:30-33`

Acceptance criteria:
- package metadata includes the missing async DB driver deps
- install/build paths remain compatible with current local tooling

#### 1.2 Pinned notes
Port note pinning.

Files:
- `backend/open_webui/migrations/versions/e1f2a3b4c5d6_add_is_pinned_to_note.py`
- local note model/router/UI files that need the field surfaced

Evidence:
- upstream migration exists: `/tmp/open-webui-upstream/backend/open_webui/migrations/versions/e1f2a3b4c5d6_add_is_pinned_to_note.py:18-19`

Acceptance criteria:
- notes can be pinned/unpinned
- sidebar/admin surfaces reflect pin state
- migration is forward/backward safe

### Lane 2 — Chat/share model improvements

#### 2.1 Shared chat refactor
Replace local phantom shared chats with upstream-style `shared_chat` snapshots.

Local current state:
- shared chats are cloned into `chat` rows with `user_id=f"shared-{chat_id}"`
  - `backend/open_webui/models/chats.py:525-557`

Upstream target:
- dedicated `shared_chat` table/model
  - `/tmp/open-webui-upstream/backend/open_webui/models/shared_chats.py:20-45`
  - `/tmp/open-webui-upstream/backend/open_webui/migrations/versions/c1d2e3f4a5b6_add_shared_chat_table.py:62-131`

Files:
- `backend/open_webui/models/chats.py`
- `backend/open_webui/models/shared_chats.py` (new)
- `backend/open_webui/routers/chats.py`
- share-related frontend components/APIs

Required local adaptation:
- preserve existing share URLs and existing `share_id` contract
- prefer upstream snapshot table
- optionally continue publishing share-related events through existing local eventing later, but eventing is not required for the first slice

Acceptance criteria:
- creating a share creates/updates a `shared_chat` snapshot instead of a phantom `chat` row
- deleting a share deletes the snapshot and clears `chat.share_id`
- access grants for shared chats continue to work or improve
- old shared links either migrate cleanly or are explicitly handled in migration notes

#### 2.2 Chat model extension: tasks, summary, last_read_at
Bring upstream chat metadata additions.

Upstream target:
- `/tmp/open-webui-upstream/backend/open_webui/models/chats.py:58-61`
- `/tmp/open-webui-upstream/backend/open_webui/migrations/versions/a3dd5bedd151_add_tasks_and_summary_to_chat.py:21-23`
- `/tmp/open-webui-upstream/backend/open_webui/migrations/versions/b7c8d9e0f1a2_add_last_read_at_to_chat.py:20-23`

Local gap:
- `backend/open_webui/models/chats.py:50-88`

Files:
- `backend/open_webui/models/chats.py`
- `backend/open_webui/routers/chats.py`
- chat/sidebar frontend files

Acceptance criteria:
- chats store task list and summary fields
- chats track `last_read_at`
- sidebar unread state is derived correctly from message/chat activity

### Lane 3 — Chat task UX on top of local NATS control plane

Goal:
Adopt upstream task UI behavior without replacing the local distributed task-stop path.

Upstream references:
- task UI: `/tmp/open-webui-upstream/src/lib/components/chat/Messages/ResponseMessage/TaskList.svelte:10-32`
- task event handling: `/tmp/open-webui-upstream/src/lib/components/chat/Chat.svelte:462-480`
- stop-by-chat endpoint: `/tmp/open-webui-upstream/backend/open_webui/main.py:2146-2158`

Local control-plane references:
- `backend/open_webui/utils/task_messaging.py:49-66`
- `backend/open_webui/utils/task_messaging.py:152-173`
- `backend/open_webui/main.py:1933-1939`
- `backend/open_webui/main.py:2100-2123`

Files:
- `backend/open_webui/main.py`
- `backend/open_webui/models/chats.py`
- `backend/open_webui/socket/main.py`
- `src/lib/components/chat/Chat.svelte`
- `src/lib/components/chat/Messages/ResponseMessage/TaskList.svelte` (new or ported)
- `src/lib/components/layout/Sidebar.svelte`
- `src/lib/apis/index.ts`
- `src/lib/apis/tasks/*`

Required local adaptation:
- keep `task_messaging.py` as the distributed stop/event bus
- add upstream-style `/api/tasks/chat/{chat_id:path}/stop`
- keep NATS/Redis fallback behavior for stop dispatch
- support local chats where upstream now uses `local:{socket_id}` patterns

Acceptance criteria:
- active task list renders in-chat
- chat cancel UI uses current local stop-task primitives
- stop-by-chat works for persisted chats and local chats
- unread count/read-marking behavior does not regress

### Lane 4 — Automations and calendar, redesigned as NATS-owned services

Goal:
Port the new product features, but move execution ownership to NATS-compatible services rather than keeping upstream's in-process scheduler loop as authority.

Upstream feature files:
- `backend/open_webui/models/automations.py`
- `backend/open_webui/models/calendar.py`
- `backend/open_webui/routers/automations.py`
- `backend/open_webui/routers/calendar.py`
- `backend/open_webui/utils/automations.py`
- `backend/open_webui/utils/calendar.py`
- `backend/open_webui/migrations/versions/d4e5f6a7b8c9_add_automation_tables.py`
- `backend/open_webui/migrations/versions/56359461a091_add_calendar_tables.py`
- frontend directories:
  - `src/routes/(app)/automations`
  - `src/routes/(app)/calendar`
  - `src/lib/apis/automations`
  - `src/lib/apis/calendar`
  - `src/lib/components/automations/*`
  - `src/lib/components/calendar/*`

Upstream runtime shape to avoid copying directly:
- scheduler started in app process:
  - `/tmp/open-webui-upstream/backend/open_webui/main.py:677-679`

Local runtime seams to build on:
- NATS runtime config: `backend/open_webui/env.py:454-525`
- runtime registry: `backend/open_webui/utils/runtime_registry.py:31-98`
- task/domain events: `backend/open_webui/utils/task_messaging.py:69-99`
- terminal lifecycle/control: `backend/open_webui/routers/terminals.py:108-120`
- pipeline runner service model: `backend/open_webui/utils/pipeline_runner.py:28-45`

Implementation approach:
- port upstream API/data/UI surfaces first
- introduce an `automation-runner` provider/service lane patterned after `pipeline-runner` / `terminal-service`
- publish automation execution requests/results as domain events
- publish calendar alert events through the same app event channel abstraction
- keep browser/socket UX at the web edge; move scheduling ownership out of the web app process over time

Initial acceptable transitional state:
- APIs/UI shipped
- a single-process scheduler may exist temporarily if needed for first integration
- but all execution boundaries must be written so they can be lifted into a dedicated NATS-owned runner without another full rewrite

Acceptance criteria:
- users can CRUD automations and calendar data
- scheduled work executes reliably in the fork
- the execution seam is explicit and portable to a dedicated runtime service
- terminal-aware automation execution uses local terminal routing surfaces, not a brand-new bypass path

### Lane 5 — Deferred async DB/session migration

Do not include in the first upstream feature port.

Evidence:
- local DB layer is sync/session oriented:
  - `backend/open_webui/internal/db.py:158-181`
- upstream now depends heavily on async DB layers:
  - `/tmp/open-webui-upstream/backend/open_webui/internal/db.py:30-31`
  - `/tmp/open-webui-upstream/backend/open_webui/internal/db.py:383-417`

Decision:
- keep this as a separate migration track after the feature slices land

Acceptance criteria for deferral:
- feature slices do not force a full async conversion first
- any small async islands introduced are isolated and intentional

## Implementation Sequence

### Phase A
1. package metadata fixes
2. pinned notes

### Phase B
3. shared chat migration + router updates
4. chat schema additions (`tasks`, `summary`, `last_read_at`)

### Phase C
5. task list UI + unread/read UX + stop-by-chat endpoint on local NATS task messaging

### Phase D
6. automations/calendar backend models/routes/migrations
7. automations/calendar frontend routes/components/apis
8. extract or introduce runner seam for scheduled execution in NATS style

### Phase E
9. reassess upstream async DB/session adoption after the product slices are stable

## Risks and Mitigations

### Risk 1 — Raw merge conflict explosion
Mitigation:
- port by subsystem, not by bulk rebase

### Risk 2 — Scheduler ownership split-brain
Mitigation:
- define one execution owner per automation run path
- prefer dedicated service ownership over multiple web instances

### Risk 3 — Share-link breakage
Mitigation:
- use upstream migration pattern that converts legacy share rows to `shared_chat`
- explicitly regression-test existing shared links

### Risk 4 — Task UX mismatched with local distributed cancellation
Mitigation:
- preserve `task_messaging.py` as the authoritative stop/event seam
- port only UI/API semantics, not upstream's simpler authority assumptions

### Risk 5 — Async DB churn blocking feature delivery
Mitigation:
- keep async DB migration out of the first execution tranche

## Verification Strategy

### Required for every slice
- targeted backend pytest coverage
- frontend type/lint checks for touched UI
- migration smoke path for schema changes

### Required for task/chat slices
- task start/stop by task id
- task stop by chat id
- local chat id path support
- unread/read state regression checks

### Required for automations/calendar slices
- CRUD API tests
- schedule computation tests
- runtime ownership tests for scheduled execution
- multi-instance safety checks or explicit single-owner transitional guards

## Immediate first execution slice

Start with:
1. package metadata alignment
2. pinned notes
3. shared chat refactor

Reason:
- lowest architectural risk
- clears storage/model debt before task/calendar UI work
- creates a safer baseline for the later chat and automation slices
