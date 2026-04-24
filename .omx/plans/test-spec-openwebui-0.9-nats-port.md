# Test Spec — OpenWebUI 0.9.x Upstream Port for NATS Fork

Date: 2026-04-21
Companion plan: `.omx/plans/prd-openwebui-0.9-nats-port.md`

## Verification goals

Prove that selected upstream `0.9.x` features can be integrated into `open-webui-nats` without regressing:
- NATS task stop/eventing
- retrieval/pipeline/terminal runtime ownership
- existing chat/share behavior
- existing startup/build/test baselines

## Test lanes

### Lane 1 — Dependency and migration safety

#### 1.1 Dependency metadata
Checks:
- package install metadata includes `aiosqlite`
- package install metadata includes `asyncpg`
- no existing dependency pin is accidentally removed

Proof:
- inspect lock/update diffs
- import smoke if needed

#### 1.2 Schema migration safety
For each added migration:
- migration applies on empty DB
- migration applies on representative local DB
- rollback path is syntactically valid where supported

Target migrations:
- pinned notes
- shared chat table
- chat `tasks` / `summary`
- chat `last_read_at`
- automation tables
- calendar tables

## Lane 2 — Shared chat regression coverage

### Required cases
1. create share from existing chat
2. update existing share after chat changes
3. fetch shared chat by token
4. delete share clears original `share_id`
5. migration from legacy phantom shared chats preserves existing share accessibility
6. access grants on shared chats behave correctly

### Files likely needing tests
- `backend/open_webui/test/util/` new shared-chat tests
- existing chat router/model tests if present

## Lane 3 — Chat task and unread/read coverage

### Required cases
1. chat model persists `tasks`
2. chat model persists `summary`
3. chat marks `last_read_at`
4. unread count increments on new activity
5. unread count clears when opening/marking read
6. stop task by task id still works
7. stop task by chat id works for persisted chats
8. stop task by chat id works for `local:{socket_id}` chats
9. frontend task list renders active tasks and handles cancel signal

### Required touched paths
- `backend/open_webui/main.py`
- `backend/open_webui/models/chats.py`
- `backend/open_webui/socket/main.py`
- `src/lib/components/chat/Chat.svelte`
- `src/lib/components/chat/Messages/ResponseMessage/TaskList.svelte`
- `src/lib/components/layout/Sidebar.svelte`

## Lane 4 — Automations and calendar coverage

### Backend API coverage
Automations:
1. create
2. update
3. toggle
4. run now
5. list/history
6. limit enforcement

Calendar:
1. calendar CRUD
2. event CRUD
3. recurring expansion
4. attendee/RSVP behavior
5. scheduled-task virtual calendar integration if retained

### Runtime/seam coverage
1. scheduler/runner picks due automation once
2. duplicate scheduling is prevented or explicitly deduplicated
3. calendar alerts emit the expected event payload
4. automation execution path is explicit and testable outside the web request path
5. terminal-bound automation execution uses approved terminal routing seam

### NATS-style proof expectations
If a dedicated runner/service is introduced:
1. service registers in runtime registry
2. execution request can be observed as an event/message/job
3. service shutdown/restart behavior is deterministic
4. web tier remains UX/API edge, not hidden execution owner

## Lane 5 — Existing NATS regression floor

Before and after each major slice, rerun the local NATS seam floor:
- task messaging
- retrieval worker/transport
- pipeline runner/adapter
- runtime registry
- terminal service/eventing

Representative current test set:
- `backend/open_webui/test/util/test_task_messaging.py`
- `backend/open_webui/test/util/test_retrieval_transport.py`
- `backend/open_webui/test/util/test_retrieval_worker.py`
- `backend/open_webui/test/util/test_pipeline_runner.py`
- `backend/open_webui/test/util/test_pipeline_adapter.py`
- `backend/open_webui/test/util/test_runtime_registry.py`
- `backend/open_webui/test/util/test_runtime_registry_config.py`
- `backend/open_webui/test/util/test_terminal_service.py`
- `backend/open_webui/test/util/test_terminal_eventing.py`

## Command floor

Run after touched slices:

```bash
cd /mnt/c/dev/NatsWebUI/open-webui-nats
./.venv/Scripts/python.exe -m compileall backend/open_webui
./.venv/Scripts/python.exe -m pytest backend/open_webui/test/util -q
npm run check
```

Then add targeted pytest selections for each slice:

### Shared chat slice
```bash
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_shared_chat_migration.py \
  backend/open_webui/test/util/test_shared_chat_router.py -q
```

### Chat task/unread slice
```bash
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_task_messaging.py \
  backend/open_webui/test/util/test_chat_task_state.py \
  backend/open_webui/test/util/test_chat_last_read_at.py -q
```

### Automations/calendar slice
```bash
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_automations.py \
  backend/open_webui/test/util/test_calendar.py \
  backend/open_webui/test/util/test_automation_runner.py -q
```

## Exit criteria

The port is ready to move from planning into implementation when:
1. shared chat migration path is settled
2. chat task/unread data model is approved
3. automation/calendar execution ownership is explicitly decided
4. the NATS regression floor is preserved as a standing gate

## Recommended first implementation proof

Use the first execution tranche to prove:
1. dependency metadata update
2. note pinning migration
3. shared chat refactor

This gives the lowest-risk proof of upstream slice-porting before touching distributed execution features.
