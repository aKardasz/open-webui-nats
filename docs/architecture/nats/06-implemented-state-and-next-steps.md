# Implemented State And Next Steps

This document records what the `nats-refactor` branch currently implements relative to the NATS architecture documents and what still remains before the broader service-first target is complete.

## Current Implemented State

The branch now supports a real Stage A retrieval topology with repeatable repo-local verification:

- browser-facing web tier remains in `backend/open_webui/main.py`
- NATS with JetStream can run alongside Redis
- retrieval work can be consumed by a dedicated `retrieval-worker` runtime

Implemented pieces:

- task-control messaging abstraction with Redis/NATS coexistence
- retrieval job envelope helpers with signatures
- retrieval transport boundary with inline-local enforcement
- durable retrieval publish/consume path over JetStream
- retrying retrieval worker startup
- dedicated `python -m open_webui retrieval-worker` worker-only mode
- coarse retrieval progress events
- DB-backed projection of retrieval progress into `file.data.retrieval_job`
- file process status endpoint returns retrieval job metadata
- instance-scoped runtime registry records with derived routing snapshots
- initial KV runtime registry materialization into:
  - `owui_registry`
  - `owui_routing`
  - `owui_feature_flags`
- web-tier runtime registry heartbeats now refresh those records on a background cadence with explicit freshness windows
- terminal cache snapshots include advisory runtime registration metadata
- terminal proxy/websocket paths now prefer route-eligible runtime candidates while preserving config fallback
- a transitional embedded or worker-only `terminal-service` can now own terminal runtime registration and cache priming without taking over browser WebSocket termination
- terminal session create/attach routing decisions can now be delegated to `terminal-service` over Core NATS request/reply, while falling back to the existing local resolution path when the service is unavailable
- `terminal-service` now tracks session lifecycle state from terminal events and can reject attach attempts for known closed/failed sessions while preserving fallback when the service is unavailable
- `terminal-service` now publishes its own service-owned runtime registration/heartbeat record in addition to per-terminal records
- `terminal-service` now prunes stale session-registry entries by TTL so extracted lifecycle state does not accumulate indefinitely
- session-specific terminal HTTP proxy requests now also pass session ids into the service-owned lifecycle seam, allowing service-side routing/validation beyond WebSocket attach alone
- terminal proxy responses now expose lifecycle decision source/status headers so service-owned routing decisions are observable at the web edge
- `terminal-service.default` runtime records now expose live session-registry counts (`session_registry_entries`, `active_session_count`)
- per-terminal `terminal.*` runtime records now also expose service-owned session counts for that specific server
- annotated runtime metadata now surfaces service `capabilities` and `routing` details instead of only status/freshness flags
- terminal lifecycle events now include `lifecycle_source` and `session_status` fields so service-owned decision state is visible in emitted event payloads too
- terminal listings now surface per-terminal live session counts directly (`session_registry_entries`, `active_session_count`) instead of requiring callers to read nested runtime capability details
- terminal listings now surface a simple service-owned `lifecycle_state` summary (`active` / `idle`) per terminal
- pipeline filter/admin HTTP calls run through a shared adapter boundary and adapter factory seam
- internal pipeline filter execution can now attempt Core NATS request/reply first and fall back to HTTP compatibility when NATS is unavailable or no responder answers
- an embedded or worker-only `pipeline-runner` can now answer `owui.cmd.pipeline.run` requests using the HTTP compatibility adapter as its execution backend
- `pipeline-runner` now publishes its own service-owned runtime registration/heartbeat records through the shared runtime registry machinery
- `pipeline-runner` now supports a service-owned non-HTTP execution seam for internal filters when an internal executor is registered
- `pipeline-runner` can now execute repo-native internal filter-function modules directly from app state without going through the HTTP compatibility adapter
- direct non-HTTP filter-function execution now passes through core filter context (`__metadata__`, `__files__`, `__model__`, `__request__`, `__user__`) needed by existing filter handlers
- internal pipeline models can now advertise non-HTTP execution automatically through `OPENAI_API_CONFIGS` connection metadata (`connection_type=internal` plus optional `internal_executor_id`)
- `OPENAI_API_CONFIGS` can now seed full `pipeline` metadata for config-declared pipeline models, making the non-HTTP runner lane reachable even when the model is declared statically
- custom/preset models now preserve inherited pipeline runtime metadata (`pipeline`, `connection_type`, `internal_executor_id`) from their base model instead of dropping it
- explicit durable `pipeline.execution='jetstream'` metadata is now preserved instead of being overwritten by generic `connection_type=internal` tagging
- pipeline-backed models created from config or inheritance now also expose a top-level `execution_mode` field for easier orchestration introspection
- non-streaming internal function `pipe` models can now execute through `pipeline-runner` instead of always bypassing the service-owned lane
- function `pipe` models now expose explicit `execution_mode` metadata so callers can tell whether they route through request/reply or the durable stage lane
- the main chat entrypoint now attempts runner-backed execution for non-streaming internal `pipe` models and falls back to the existing direct path only on failure
- durable non-streaming internal `pipe` models can now use the JetStream stage lane through the same runner-backed helper path
- runner-backed `pipe` execution now normalizes string, generator, async-generator, and model-like results the same way the direct non-stream path does
- `pipeline-runner.default` runtime records now expose executor/function inventory counts (`registered_executor_count`, `function_filter_count`, `function_pipe_count`)
- internal action functions can now execute through `pipeline-runner` with safe fallback from the chat action path
- durable internal action functions can now use the JetStream stage lane through the same runner-backed helper path
- runner-backed internal action execution now preserves sub-action ids so action manifolds keep existing selection semantics
- model action/filter descriptors now expose explicit execution metadata (`execution_mode`, `durable_stage`) so service-owned lanes are visible in surfaced capabilities too
- action/filter descriptors now also expose `internal_executor_id` (and `sub_action_id` for manifold actions) so callers can map capabilities to service-owned executors directly
- `pipeline-runner` now includes a durable JetStream pipeline-stage lane (`owui.cmd.pipeline.stage.run`) with explicit ack/NAK handling for retryable work
- `pipeline-adapter` can now route durable pipeline stages through the JetStream lane and await a reply subject, instead of using Core request/reply only

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

The branch also provisions this transitional Stage B topology in `docker-compose.nats.yaml`:

1. `open-webui` web process with embedded retrieval, terminal, and pipeline services disabled
2. `nats` broker with JetStream
3. `retrieval-worker` process
4. `terminal-service` process
5. `pipeline-runner` process

Properties:

- terminal registration can be exercised either from the embedded web-tier terminal service or from a dedicated `python -m open_webui terminal-service` process during the transition
- terminal create/attach lifecycle routing can be exercised either through the embedded web-tier terminal service or through a dedicated `python -m open_webui terminal-service` process during the transition
- pipeline request/reply and durable stage execution can be exercised either through the embedded web-tier runner or a dedicated `python -m open_webui pipeline-runner` process during the transition
- `terminal-service.default` and `pipeline-runner.default` records expose service-owned runtime metadata for registry materialization
- the compose overlay shape and embedded-mode disablement are covered by tests

Stage B should not be labeled fully supported until the live five-service smoke in `07-stage-b-smoke-runbook.md` has been run successfully in the target environment and the evidence is recorded.

## What Is Still Transitional

The branch is not yet at the full target architecture.

Still transitional:

- retrieval event fanout still uses generic subjects in addition to job-scoped envelope metadata
- runtime registry is advisory rather than the sole source of routing truth; terminal routing can consume route-eligible hints, while config/local fallback remains authoritative when registry data is missing or stale
- terminal routing still uses the existing configured server IDs as the browser-facing contract; the transitional terminal service now owns registration, create/attach routing decisions, and basic session-state validation, but raw browser transport and fuller lifecycle authority remain at the web edge
- pipeline execution is still transitional: internal filter execution now has requester, responder, service-owned registration/heartbeat ownership, a repo-native non-HTTP function/executor seam, and a durable JetStream stage lane with adapter-level orchestration, but external compatibility still relies on the HTTP adapter and full live runtime proof is still pending

## Not Yet Implemented

The following remain outside the currently implemented scope:

- a standalone registry service that exclusively owns registry materialization and routing-view generation
- stricter enforcement that service-owned heartbeat keys and web-owned derived routing keys cannot overwrite each other
- registry-driven pipeline runner selection beyond the current configured NATS transport and runner record surfacing
- terminal lifecycle authority beyond today's registration, create/attach routing, session-state validation, TTL pruning, and observability
- browser terminal transport ownership outside the web edge
- broader pipeline-runner ownership for all internal orchestration paths; external compatibility still depends on the HTTP adapter fallback
- live five-service Stage B smoke proof for `web + nats + retrieval-worker + terminal-service + pipeline-runner` in the target runtime environment
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

## Verification Proven On Branch

The branch has evidence for:

- compile success on backend Python modules
- repeatable repo-local Stage A verification for:
  - retrieval submission/transport boundaries
  - JetStream publish fallback to local execution
  - worker ack/NAK and retry-loop behavior
  - duplicate/idempotent retrieval execution handling
  - redelivery-after-restart preserving DB-projected completed retrieval status
- focused retrieval/runtime/registry/terminal/pipeline adapter unit tests
- request/reply pipeline adapter proof with HTTP fallback on timeout/unavailable responder
- terminal-service proof for service-owned runtime registration providers, startup wiring, and cache priming
- terminal lifecycle routing proof for create/attach request/reply delegation with local fallback preserved
- terminal session-state proof for rejecting attach attempts to known closed sessions
- terminal-service registration proof for first-class `terminal-service.default` runtime records
- terminal-service session-registry TTL/cleanup proof for stale lifecycle state removal
- terminal-service proof for session-aware HTTP proxy routing and rejection on closed sessions
- terminal-service observability proof for lifecycle-source/session-status response headers
- terminal-service runtime-record proof for exposing live session-registry counts
- per-terminal runtime-record proof for exposing server-scoped session counts
- runtime-annotation proof for surfacing capability/routing details to callers
- terminal lifecycle event proof for propagating lifecycle-source/session-status in event payloads
- terminal listing proof for surfacing per-terminal session counts directly
- terminal listing proof for surfacing per-terminal lifecycle-state summary
- pipeline-runner responder proof for valid request handling, invalid payload rejection, and startup/supervisor wiring
- pipeline-runner registration/heartbeat proof for service-owned runtime registry providers
- pipeline-runner non-HTTP execution proof for internal filters routed through a registered executor instead of the HTTP compatibility adapter
- pipeline-runner proof for direct execution of repo-native internal filter-function modules from app state
- pipeline-runner proof for direct internal filter execution with core filter-context parameters
- OpenAI connection-metadata proof for automatic internal pipeline execution tagging
- OpenAI config proof for seeding full pipeline metadata on statically declared internal pipeline models
- model-runtime inheritance proof for preserving internal pipeline metadata across custom/preset overlays
- proof that explicit durable pipeline execution metadata survives both config tagging and model inheritance
- proof that pipeline-backed models surface top-level `execution_mode` metadata
- pipeline-runner proof for non-streaming internal function `pipe` execution
- chat-layer proof for preferring the runner-backed `pipe` path with safe local fallback
- durable internal `pipe` proof for using the JetStream stage lane via the runner helper
- runner-backed `pipe` result normalization proof for generator/async-generator compatibility
- function-model proof for explicit `execution_mode` metadata on internal `pipe` models
- pipeline-runner runtime-record proof for exposing executor/function inventory counts
- action-runner proof for internal action execution and chat-layer fallback behavior
- durable action-runner proof for using the JetStream stage lane via the action helper
- action-runner proof for preserving sub-action ids during runner-backed execution
- descriptor proof for surfacing execution metadata on action/filter capability items
- descriptor proof for surfacing executor identity on action/filter capability items
- pipeline-runner JetStream-stage proof for durable consumer startup and ack/NAK behavior
- durable pipeline-stage proof for adapter publish + reply-subject handling across the JetStream lane
- compose overlay config validity
- compose overlay staging for `web + nats + retrieval-worker + terminal-service + pipeline-runner`
- merged compose config validation for the transitional Stage B service set
- compose overlay regression tests covering service presence and embedded-mode disablement
- live NATS retrieval job publish/consume
- live route-level background upload submission reaching the worker
- live worker-only boot and JetStream consumer registration
- live KV registry materialization into `owui_registry`


## Live Stage B Smoke Evidence — 2026-04-20

Environment:

- WSL Ubuntu 24.04 shell using Docker Desktop through `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe`
- Compose command shape: `docker.exe compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d nats ollama open-webui retrieval-worker terminal-service pipeline-runner`
- Local branch image was built with the NATS overlay default `NATS_SMOKE_USE_SLIM=true`

Proof collected:

- NATS monitor health returned `{"status":"ok"}` on `http://127.0.0.1:8222/healthz`.
- Open WebUI health returned `{"status":true}` on `http://127.0.0.1:3000/health`.
- Compose reported all six expected containers running: `nats`, `ollama`, `open-webui`, `retrieval-worker`, `terminal-service`, and `pipeline-runner`.
- NATS `connz` reported four Open WebUI NATS clients:
  - `open-webui-*`
  - `open-webui-retrieval-*`
  - `open-webui-terminal-service-*`
  - `open-webui-pipeline-runner-*`
- JetStream streams/consumers existed for:
  - `owui_retrieval_jobs` with consumer `owui_retrieval_worker`
  - `owui_pipeline_jobs` with consumer `owui_pipeline_runner`
  - `KV_owui_registry`
  - `KV_owui_routing`
  - `KV_owui_feature_flags`
- KV registry records existed for:
  - `pipeline-runner.default` as healthy `pipeline-runner`
  - `terminal-service.default` as healthy `terminal-service`
- KV routing records existed for both `pipeline-runner.default` and `terminal-service.default`; service-specific registry sync no longer deletes another service's routing key.

Not covered by this smoke:

- Authenticated file-upload retrieval request through the UI/API.
- Terminal lifecycle request with a configured terminal server.
- Pipeline request/reply or durable-stage request with a configured internal pipeline model/action.
- Stop-service fallback behavior after the registry freshness window.

These remaining checks still belong to the full Stage B promotion gate in `07-stage-b-smoke-runbook.md`.

## Recommended Next Steps

Proceed in this order:

1. Run and record the live five-service Stage B smoke from `07-stage-b-smoke-runbook.md`. This is the promotion gate for moving the overlay from transitional scaffolding to supported topology.
2. Harden runtime registry ownership so service-owned heartbeat records and web-owned derived routing views have explicit non-overlapping authority.
3. Move more terminal session lifecycle authority beyond create/attach routing and basic session-state validation into the extracted service boundary without removing existing fallback paths.
4. Expand the pipeline-runner internal execution contract beyond the current function/filter/pipe/action seams where needed, and prove request/reply plus durable-stage paths end to end.
5. Once the above are proven, promote Stage B in `05-service-first-roadmap.md` and this document with final operator guidance and rollback steps.
6. Plan Stage C separately for artifact-worker, tool-executor extraction, and NATS account/leaf-node isolation.

## Final Position

The branch is beyond foundation and beyond retrieval-only scaffolding. It now has a real durable retrieval runtime, a first registry materialization layer, terminal registration metadata surfacing, and a pipeline execution seam. What remains is to turn those seams into actual routing and service-ownership behavior without breaking the current browser edge.
