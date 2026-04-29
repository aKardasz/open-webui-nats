# Implemented State And Next Steps

This document records what the `nats-refactor` branch currently implements relative to the NATS architecture documents and what still remains before the broader service-first target is complete.

## Current Implemented State

As of 2026-04-27, the branch is beyond a simple Stage A retrieval port. It now supports a proven Stage A retrieval topology plus a broader transitional Stage B service set.

### Foundation and messaging

The branch now includes:

- task-control messaging abstraction with Redis/NATS coexistence
- NATS and JetStream runtime wiring in `backend/open_webui/env.py` and `backend/open_webui/main.py`
- instance-scoped runtime registry records with derived routing snapshots
- initial KV runtime registry materialization into:
  - `owui_registry`
  - `owui_routing`
  - `owui_feature_flags`
- web-tier runtime registry heartbeats with explicit freshness windows and annotated runtime state

### Durable retrieval lane

The retrieval lane is the most mature part of the refactor and supports a real Stage A topology:

- retrieval job envelope helpers with signatures
- retrieval transport boundary with inline-local enforcement
- durable retrieval publish/consume path over JetStream
- retrying retrieval worker startup
- dedicated `python -m open_webui retrieval-worker` worker-only mode
- DB-backed projection of retrieval progress into `file.data.retrieval_job`
- file process status endpoint returns retrieval job metadata
- rollback-safe local fallback when NATS/JetStream is unavailable

### Terminal-service seam

The terminal lane now has a genuine extracted-service seam, even though the browser edge still owns raw WebSocket transport:

- advisory runtime registration metadata in terminal cache snapshots
- route-eligible runtime preference with config fallback preserved
- embedded or worker-only `terminal-service` mode via `python -m open_webui terminal-service`
- Core NATS request/reply routing for terminal create/attach lifecycle decisions
- session lifecycle state tracking from terminal events
- closed/failed-session attach rejection when the service has authoritative state
- service-owned runtime registration and heartbeat records, including `terminal-service.default`
- TTL pruning for stale session-registry state
- session-aware HTTP proxy routing/validation beyond WebSocket attach alone
- response/event observability fields such as lifecycle source and session status
- surfaced runtime metadata including capabilities, routing details, and service-owned session counts

### Pipeline-runner seam

The pipeline lane now has a real transport boundary and runner lane:

- adapter factory seam for pipeline filter/admin HTTP calls
- Core NATS request/reply path for internal execution with safe HTTP fallback when NATS is unavailable or no responder answers
- embedded or worker-only `pipeline-runner` mode via `python -m open_webui pipeline-runner`
- service-owned runtime registration and heartbeat records, including `pipeline-runner.default`
- non-HTTP execution seams for internal filters, functions, pipes, and actions
- inherited/config-tagged pipeline metadata that preserves `connection_type`, `internal_executor_id`, and explicit durable `pipeline.execution='jetstream'`
- top-level `execution_mode` metadata on surfaced models/descriptors
- durable JetStream pipeline-stage lane on `owui.cmd.pipeline.stage.run`
- adapter-level durable-stage publish + reply-subject handling

### Automation-runner seam

The automation lane now also has a service-owned seam and should be treated as part of the active NATS program state:

- embedded or worker-only `automation-runner` mode via `python -m open_webui automation-runner`
- Core NATS request/reply path for manual automation run requests
- due-schedule polling and execution loop in runner mode
- service-owned runtime registration and heartbeat records, including `automation-runner.default`
- automation lifecycle event publication for started/completed/failed runs
- compose/test coverage that expects the runner to participate in the NATS overlay

## Supported And Transitional Deployment Shapes

### Supported Stage A shape

The branch supports this topology as the current proven NATS-enabled Stage A shape:

1. `open-webui` web process
2. `nats` broker with JetStream
3. `retrieval-worker` process

Properties:

- browser HTTP/WebSocket contracts stay in the web tier
- retrieval worker owns durable background ingestion
- Redis remains in place for session/socket/Yjs responsibilities
- retrieval submission can still fall back to local execution when NATS/JetStream is unavailable

### Transitional Stage B shape

The branch also provisions this broader transitional Stage B topology in `docker-compose.nats.yaml`:

1. `open-webui` web process with embedded retrieval, automation, terminal, and pipeline runners disabled
2. `nats` broker with JetStream
3. `retrieval-worker` process
4. `automation-runner` process
5. `terminal-service` process
6. `pipeline-runner` process

In the current compose smoke environment, `ollama` is still booted as an application dependency of `open-webui`, but it is not part of the Stage B NATS service contract itself.

Properties:

- automation execution can be exercised either through the embedded web-tier runner seam or through a dedicated `python -m open_webui automation-runner` process during the transition
- terminal registration and create/attach lifecycle routing can be exercised either through the embedded web-tier terminal service or through a dedicated `python -m open_webui terminal-service` process during the transition
- pipeline request/reply and durable-stage execution can be exercised either through the embedded web-tier runner or a dedicated `python -m open_webui pipeline-runner` process during the transition
- `automation-runner.default`, `terminal-service.default`, and `pipeline-runner.default` records expose service-owned runtime metadata for registry materialization
- the compose overlay shape and embedded-mode disablement are covered by tests

Stage B should not be labeled fully supported until the live Stage B smoke in `07-stage-b-smoke-runbook.md` has been refreshed against the current extracted-service set and the evidence is recorded.

## What Is Still Transitional

The branch is not yet at the full target architecture.

Still transitional:

- retrieval event fanout still uses generic subjects in addition to job-scoped envelope metadata
- runtime registry is still advisory rather than the sole source of routing truth; terminal routing can consume route-eligible hints, while config/local fallback remains authoritative when registry data is missing or stale
- terminal routing still uses configured server IDs as the browser-facing contract; `terminal-service` now owns registration, create/attach routing decisions, and bounded session-state validation, but fuller lifecycle authority remains at the web edge
- pipeline execution is still transitional: internal execution has requester, responder, service-owned registration/heartbeat ownership, repo-native non-HTTP seams, and a durable JetStream stage lane, but external compatibility still relies on the HTTP adapter and broader live runtime proof is still pending
- automation execution is still transitional: `automation-runner` exists and participates in the overlay, but the branch still needs a final proof/ownership pass to show that the web process is no longer the primary execution owner in NATS mode

## Not Yet Implemented

The following remain outside the currently implemented scope:

- a standalone registry service that exclusively owns registry materialization and routing-view generation
- stricter enforcement that service-owned heartbeat keys and web-owned derived routing keys cannot overwrite each other
- registry-driven runner selection beyond the current configured NATS transport and surfaced runner records
- terminal lifecycle authority beyond today's registration, create/attach routing, session-state validation, TTL pruning, and observability
- browser terminal transport ownership outside the web edge
- broader pipeline-runner ownership for all internal orchestration paths; external compatibility still depends on the HTTP adapter fallback
- broader automation-runner ownership proof for both manual and scheduled execution in NATS mode
- refreshed full Stage B live smoke proof for `web + nats + retrieval-worker + automation-runner + terminal-service + pipeline-runner` in the target runtime environment
- artifact-worker
- tool-executor extraction
- stronger isolation with NATS accounts or leaf nodes

## Rollback Position

The branch remains rollback-oriented.

Current rollback-safe properties:

- retrieval submission can still fall back to local execution
- task control can still fall back to Redis
- browser-facing contracts are unchanged
- terminal raw transport remains local/WebSocket-based
- pipeline external HTTP compatibility remains intact
- automation execution can still be kept local/transitional while the runner lane is being hardened

## Verification Proven On Branch

### Fresh repo-local proof from this review

On 2026-04-27 the following focused verification ran successfully:

- `./.venv/Scripts/python.exe -m compileall backend/open_webui`
- focused pytest slice covering task messaging, retrieval transport/worker, runtime registry, terminal service/eventing, pipeline adapter/runner, automation runner/utils, and compose overlay shape
- result: `135 passed, 10 warnings`

### Functional proof already codified on the branch

The branch has repo-local evidence for:

- repeatable Stage A retrieval verification, including publish fallback to local execution, duplicate/idempotent handling, and redelivery-after-restart preserving DB-projected retrieval status
- terminal-service routing and observability proof for service-owned registration providers, create/attach request/reply delegation, closed-session rejection, TTL cleanup, session-aware proxy routing, runtime capability details, and per-terminal lifecycle-state summaries
- pipeline-runner responder, registration/heartbeat, non-HTTP execution, inherited/config-tagged runtime metadata, chat/action integration, and durable JetStream stage behavior
- automation-runner request payload handling, service-record surfacing, automation route integration, and compose overlay expectations
- compose overlay config validity and embedded-mode disablement for `retrieval-worker`, `automation-runner`, `terminal-service`, and `pipeline-runner`

### Partial live Stage B startup smoke from this review

On 2026-04-27, the current Stage B topology was also booted locally with:

- `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe compose`
- `docker.exe compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d --build nats ollama open-webui retrieval-worker automation-runner terminal-service pipeline-runner`

Evidence collected from that live startup smoke:

- `docker compose ps` showed all expected containers running: `nats`, `ollama`, `open-webui`, `retrieval-worker`, `automation-runner`, `terminal-service`, and `pipeline-runner`
- NATS monitor health returned `{"status":"ok"}`
- Open WebUI health returned `{"status":true}`
- NATS `connz` reported distinct clients for the web tier plus the four extracted runners/services
- JetStream streams existed for:
  - `KV_owui_registry`
  - `KV_owui_routing`
  - `KV_owui_feature_flags`
  - `owui_retrieval_jobs` with one consumer
  - `owui_pipeline_jobs` with one consumer
- Raw KV registry entries were present for:
  - `automation-runner.default`
  - `pipeline-runner.default`
  - `terminal-service.default`

Not yet covered by this 2026-04-27 startup smoke:

- authenticated retrieval submission through the UI/API
- terminal lifecycle requests with a configured terminal server
- pipeline request/reply or durable-stage execution through a configured internal pipeline model/action
- manual and due automation execution against seeded automation data
- stopped-service fallback behavior after registry freshness expiry

Treat this as **current live startup/topology evidence**, not full Stage B promotion evidence. The remaining functional and fallback checks still belong to `07-stage-b-smoke-runbook.md`.

## Live Stage B Functional Smoke Evidence — 2026-04-27

The current branch state was exercised further on 2026-04-27 against a live local stack.

Environment and setup additions:

- first admin account created through `POST /api/v1/auths/signup`
- persistent config updated through `POST /api/v1/configs/import` so `ui.enable_automations=true` and `ui.enable_calendar=true`
- admin-created internal function models used to probe pipeline-runner paths:
  - `stageb_rr_pipe` with `execution_mode=request_reply`
  - `stageb_js_pipe` with `durable_stage=true` / `execution_mode=jetstream`
- an external Open Terminal instance was started separately as `ghcr.io/open-webui/open-terminal:slim` on `http://host.docker.internal:8000` and registered through `/api/v1/configs/terminal_servers`

Functional proof collected:

- retrieval path:
  - uploaded `stageb.txt` through `POST /api/v1/files/`
  - received queued retrieval metadata immediately
  - `GET /api/v1/files/{id}/process/status` advanced from `processing` to `completed`
  - final retrieval record reported `document_count: 1`
- automation path:
  - manual run request accepted with `owner: automation-runner`
  - one intentionally invalid automation recorded a durable error state (`400: Model not found`)
  - a second automation using `stageb_rr_pipe` recorded successful runs in `/api/v1/automations/{id}/runs`
- terminal path:
  - `POST /api/v1/configs/terminal_servers/verify` succeeded against the external Open Terminal instance
  - after restarting `terminal-service` so it reloaded the updated terminal connection config, `GET /api/v1/terminals/srv1/api/config` and `POST /api/v1/terminals/srv1/api/terminals` both succeeded
  - proxied responses exposed `X-OWUI-Terminal-Route: runtime` and `X-OWUI-Terminal-Lifecycle: routing_fallback`
- pipeline path:
  - `GET /api/models` exposed both internal function models with the expected execution metadata
  - `POST /api/chat/completions` succeeded for `stageb_rr_pipe`
  - `POST /api/chat/completions` also returned a successful response for `stageb_js_pipe`

Fallback behavior observed live:

- after stopping `pipeline-runner`, both `stageb_rr_pipe` and `stageb_js_pipe` still returned successful chat completions, which proves the current web-tier fallback path remains active
- after stopping `terminal-service`, terminal config and terminal creation requests still succeeded against the configured Open Terminal instance, again showing fallback behavior remains active
- after stopping `automation-runner`, a newly created automation could still be run successfully, which shows the web tier is still capable of owning automation execution when the runner is unavailable

Important blockers revealed by this smoke:

1. **Automation-runner is not yet the sole effective owner in NATS mode.**
   Successful automation execution with `automation-runner` stopped means the current fallback path is still stronger than the intended extracted-service ownership model.
2. **Durable pipeline-stage success is not yet fully promotable as end-to-end proof.**
   Although `stageb_js_pipe` returned a successful API response, `pipeline-runner` logs still recorded JetStream stage execution failures for that trace, so the exact success path still needs hard proof before Stage B can claim a clean durable-stage win.
3. **Terminal-service currently benefits from restart-based config reloading in this smoke.**
   After changing terminal connection config through the admin API, restarting `terminal-service` was needed before the service-owned control seam could see the updated connection cleanly.

## Ownership Hardening Slice — 2026-04-27

After the functional smoke above, the branch received a focused ownership-hardening pass:

- durable internal pipe models no longer silently fall back to direct web-tier pipe execution when the NATS runner path fails; this prevents a successful API response from masking a failed JetStream pipeline-stage execution
- durable stage publishers now bind publishes to the `owui_pipeline_jobs` stream and flush the reply subscription before publish where the client supports it
- terminal-service now exposes `owui.cmd.terminal.config.refresh`; the admin terminal-server config route publishes refresh requests so the extracted terminal service can reload connection state without a container restart
- manual automation requests in NATS mode now have regression coverage proving runner request failures do not schedule a web-local fallback task or call local `execute_automation`

Verification on 2026-04-27:

- focused regression slice: `36 passed, 8 warnings`
- broader NATS/service slice: `146 passed, 10 warnings`
- automation ownership regression: `backend/open_webui/test/util/test_automation_runner.py` reported `5 passed, 1 warning`
- final combined NATS/service regression slice after the automation guard: `152 passed, 10 warnings`
- targeted `compileall` passed for the changed modules

Live re-proof from the same 2026-04-27 slice:

- the NATS compose stack rebuilt and started successfully after the hardening changes
- updating terminal-server config through `POST /api/v1/configs/terminal_servers` was immediately visible to `terminal-service` without a service restart
- `GET /api/v1/terminals/srv-refresh/api/config` returned `200` with `X-OWUI-Terminal-Route: runtime` and `X-OWUI-Terminal-Lifecycle: routing_fallback`
- `POST /api/v1/terminals/srv-refresh/api/terminals` returned `200` without restarting `terminal-service`
- a direct JetStream durable-stage probe returned `status=ok` with the expected `stage-b-jetstream-ok` completion payload
- with `pipeline-runner` active, both `stageb_rr_pipe` and `stageb_js_pipe` returned successful chat completions
- with `pipeline-runner` stopped, `stageb_js_pipe` returned a clear `503` JSON error (`Durable pipeline runner unavailable: nats: timeout`) instead of direct-executing locally

Remaining live-proof caveat: one stale `trace_pipe_stageb_js_pipe` warning was observed while draining old durable-stage work from before the unique-trace-id follow-up. The code now emits unique durable pipe trace ids, so future smoke logs should be attributable per request.

Conclusion from the 2026-04-27 functional smoke:

- retrieval is live and healthy
- request/reply internal pipeline execution is live
- manual automation execution is live
- terminal proxying through configured Open Terminal connections is live
- fallback behavior remains intentionally present for some non-durable paths, but durable internal pipe fallback masking has been closed
- strict automation-runner ownership is unit-guarded for manual NATS requests, but still needs a fresh stopped-runner live smoke before final Stage B promotion; durable pipeline-stage proof is materially improved but should also be re-smoked with fresh unique trace ids before final promotion

## Earlier Live Transitional Smoke Evidence — 2026-04-20

A live smoke was previously recorded on 2026-04-20 in a Docker Desktop + WSL environment using:

- `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe compose`
- `docker.exe compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d nats ollama open-webui retrieval-worker terminal-service pipeline-runner`

That earlier smoke proved a transitional runtime with:

- healthy `nats` and `open-webui`
- running `retrieval-worker`, `terminal-service`, and `pipeline-runner`
- JetStream stream/consumer presence for retrieval and pipeline lanes
- KV registry materialization for `pipeline-runner.default` and `terminal-service.default`

That evidence is still useful, but it predates the current Stage B definition that also includes `automation-runner`. It should therefore be treated as **partial historical smoke evidence**, not as the current promotion gate for Stage B support.

## Recommended Next Steps

Proceed in this order:

1. Reconcile the roadmap/current-state docs so they explicitly match the current extracted-service set and support status.
2. Run and record the refreshed live Stage B smoke from `07-stage-b-smoke-runbook.md` against the current topology, including `automation-runner`.
3. Harden runtime registry ownership so service-owned heartbeat records and web-owned derived routing views have explicit non-overlapping authority.
4. Move more terminal session lifecycle authority beyond create/attach routing and bounded session-state validation into the extracted service boundary without removing existing fallback paths.
5. Expand the pipeline-runner internal execution contract beyond the current function/filter/pipe/action seams where needed, and prove request/reply plus durable-stage paths end to end.
6. Finish the automation-runner ownership pass so NATS mode no longer depends primarily on the web process for automation execution.
7. Plan Stage C separately for artifact-worker, tool-executor, and NATS account/leaf-node isolation.

## Final Position

The branch is well beyond a prototype NATS port. Retrieval is real, terminal/pipeline/automation service seams exist, and the remaining work is mainly proof closure, authority hardening, and finishing the service-first extraction story without breaking the current browser edge.
