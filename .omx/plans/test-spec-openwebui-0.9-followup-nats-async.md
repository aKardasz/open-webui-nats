# Test Spec — OpenWebUI 0.9.x Follow-up: NATS Ownership and Async DB Migration

Date: 2026-04-24
Companion PRD: `.omx/plans/prd-openwebui-0.9-followup-nats-async.md`

## Verification goals
Prove that:
- automation execution no longer depends primarily on the web process in NATS mode,
- calendar scheduled-task projections remain correct,
- chat task stop/read/share behavior does not regress,
- the first async DB slice preserves API behavior and testability.

## Test lanes

### Lane 1 — Automation runner ownership
- manual run path enqueues/requests work instead of directly calling local execution
- due scheduling/claiming runs in the dedicated runner lane
- runner restart/idempotency behavior is deterministic
- runtime registry marks automation-runner healthy and routeable

### Lane 2 — Calendar projection consistency
- scheduled-task virtual calendar still shows upcoming runs
- run history still appears correctly after execution ownership changes
- auth and CRUD behavior remain unchanged

### Lane 3 — Regression floor
- stop by chat id still works for persisted chats and `local:{socket_id}` chats
- shared-chat access routes still work
- mark-read / `last_read_at` behavior remains intact

### Lane 4 — Async DB vertical slice
- async session helpers can be created and used alongside sync helpers
- converted slice no longer depends on sync request-path `SessionLocal` ownership
- converted routes preserve payload shape and persistence semantics

## Command floor
```bash
cd /mnt/c/dev/NatsWebUI/open-webui-nats
./.venv/Scripts/python.exe -m compileall backend/open_webui
./.venv/Scripts/python.exe -m pytest backend/open_webui/test/util -q
npm run check
```

## Focused proof commands
```bash
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_automations_utils.py \
  backend/open_webui/test/util/test_automation_calendar_routes.py \
  backend/open_webui/test/util/test_feature_http_smoke.py \
  backend/open_webui/test/util/test_runtime_registry.py \
  backend/open_webui/test/util/test_task_messaging.py -q
```
