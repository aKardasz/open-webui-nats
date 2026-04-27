# Context Snapshot — OpenWebUI 0.9.x Follow-up: NATS Ownership + Async DB

## Task statement
Execute the follow-up plan for the OpenWebUI 0.9.x port: finish moving runtime-owned automation/calendar behavior onto NATS-compatible service ownership, then begin the incremental async DB/session migration for the ported slices.

## Desired outcome
A verified implementation that removes automation execution ownership from the web process in NATS mode, preserves calendar/task/share behavior, and establishes the first safe async DB migration lane.

## Known facts / evidence
- Automation execution is still explicitly transitional/local in `backend/open_webui/utils/automations.py`.
- The web app still starts the embedded automation scheduler in `backend/open_webui/main.py`.
- Manual automation runs still execute directly from the API router via `BackgroundTasks` in `backend/open_webui/routers/automations.py`.
- The DB layer remains synchronous in `backend/open_webui/internal/db.py`, and the automations/calendar table helpers are sync SQLAlchemy wrappers.
- Chat stop-by-chat, shared chat access, and mark-read slices are already ported and verified, so they should be treated as regression-sensitive.
- Existing planning artifact for this lane: `.omx/plans/openwebui-0.9-followup-nats-async-plan.md`.

## Constraints
- Preserve NATS as control-plane authority.
- Do not perform a raw upstream async backend/session merge.
- Keep changes sliceable, reviewable, and verifiable.
- Do not regress existing chat task stop/read/share behavior.
- Prefer explicit runtime ownership and durable state over in-process hidden state.

## Unknowns / open questions
- Exact NATS subject set to use for automation command/request/reply flow.
- Whether the first extraction should support an explicit local fallback path in non-NATS mode or fail closed in runner-owned mode.
- How much of the first async slice can land without touching broader legacy DB helpers.

## Likely codebase touchpoints
- `backend/open_webui/utils/automations.py`
- `backend/open_webui/main.py`
- `backend/open_webui/env.py`
- `backend/open_webui/utils/runtime_registry.py`
- `backend/open_webui/routers/automations.py`
- `backend/open_webui/models/automations.py`
- `backend/open_webui/routers/calendar.py`
- `backend/open_webui/internal/db.py`
- `docker-compose.nats.yaml`
- `backend/open_webui/test/util/test_automations_utils.py`
- `backend/open_webui/test/util/test_automation_calendar_routes.py`
- `backend/open_webui/test/util/test_feature_http_smoke.py`
