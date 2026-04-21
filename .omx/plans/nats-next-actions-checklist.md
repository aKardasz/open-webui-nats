# NATS Next Actions Checklist

Derived from:
- `.omx/plans/nats-ralplan-consensus.md`
- `.omx/plans/prd-nats-migration.md`
- `.omx/plans/test-spec-nats-migration.md`

Fresh evidence gathered on 2026-04-18:
- retrieval-focused verification passed locally after ensuring repo-local runtime data dirs existed
- broader cited NATS pytest slice passed locally
- pipeline routing still directly constructs `HttpPipelineAdapter`
- terminal routing still exposes runtime metadata but does not perform registry-driven selection
- the NATS compose overlay currently provisions `retrieval-worker` only

Updated on 2026-04-20:
- retrieval util tests now self-bootstrap the repo-local runtime data path via `backend/open_webui/test/util/conftest.py`
- explicit redelivery-after-restart status-projection proof now exists in `test_retrieval_worker.py`
- runtime registry now writes instance-scoped heartbeat records plus derived routing snapshots, and annotated runtime metadata distinguishes configured/registered/fresh/healthy/route-eligible states
- terminal routing now prefers route-eligible runtime candidates while preserving config fallback and emits route-source observability
- pipeline routing now resolves adapters through `get_pipeline_adapter(...)` / `build_pipeline_adapter(...)` instead of direct `HttpPipelineAdapter` construction
- runtime registry heartbeats now refresh KV-backed registry records on a background cadence with explicit freshness windows
- internal pipeline filter execution can now attempt Core NATS request/reply through `NatsPipelineAdapter` while preserving HTTP fallback on timeout, missing responder, or disabled NATS
- a transitional embedded/worker-safe `CoreNatsPipelineRunner` now answers `owui.cmd.pipeline.run` requests using the HTTP compatibility adapter as its backend
- a transitional embedded/worker-safe `terminal-service` now owns terminal runtime registration providers and cache priming while preserving the existing web proxy/browser edge
- terminal create/attach lifecycle routing can now delegate to `terminal-service` over Core NATS request/reply while preserving the local fallback path
- terminal-service now tracks session lifecycle events and can reject attach attempts for known closed sessions
- `terminal-service` now publishes a first-class `terminal-service.default` runtime record in addition to per-terminal records
- terminal-service now prunes stale session-registry entries by TTL
- session-specific terminal HTTP proxy requests now route through the service-owned lifecycle seam with session ids
- terminal proxy responses now expose lifecycle-source/session-status headers for service-owned routing decisions
- terminal-service runtime records now expose live session-registry counts
- per-terminal runtime records now expose server-scoped session counts
- annotated runtime metadata now surfaces service capabilities/routing details directly
- terminal session events now propagate lifecycle-source/session-status fields
- terminal listings now surface per-terminal session counts directly
- terminal listings now surface per-terminal lifecycle-state summaries
- `pipeline-runner` now publishes service-owned runtime registry records/heartbeats through provider-backed registry sync, including in dedicated service modes
- `pipeline-runner` now supports a non-HTTP internal filter execution seam via registered executors
- `pipeline-runner` can now execute repo-native internal filter-function modules directly from app state
- direct non-HTTP filter execution now passes through core filter context (`__metadata__`, `__files__`, `__model__`, `__request__`, `__user__`)
- internal pipeline models can now be tagged for non-HTTP execution automatically via `OPENAI_API_CONFIGS` connection metadata
- `OPENAI_API_CONFIGS` can now seed full `pipeline` metadata for statically declared internal pipeline models
- custom/preset models now preserve inherited internal pipeline runtime metadata from their base model
- explicit durable `pipeline.execution='jetstream'` metadata is now preserved through both config tagging and model inheritance
- pipeline-backed models now expose a top-level `execution_mode` field
- non-streaming internal function `pipe` models can now execute through `pipeline-runner`
- chat completion now prefers the runner-backed path for non-streaming internal `pipe` models and falls back locally only on runner failure
- durable non-streaming internal `pipe` models can now route through the JetStream stage lane via the runner helper
- runner-backed `pipe` execution now normalizes generator/async-generator outputs compatibly with the old direct path
- function `pipe` models now expose explicit `execution_mode` metadata
- `pipeline-runner.default` runtime records now expose executor/function inventory counts
- internal action functions can now use the service-owned runner lane with chat-layer fallback
- durable internal action functions can now use the JetStream stage lane via the runner helper
- runner-backed internal actions now preserve sub-action ids
- model action/filter descriptors now expose explicit execution metadata
- action/filter descriptors now expose executor identity metadata too
- `pipeline-runner` now exposes a durable JetStream stage subject/consumer with ack/NAK retry semantics
- `pipeline-adapter` can now publish durable stage jobs and wait on a reply subject through the JetStream lane
- `docker-compose.nats.yaml` now provisions `retrieval-worker`, `pipeline-runner`, and `terminal-service`, and disables the corresponding embedded modes in `open-webui`

## Current program status

- Phase 1: complete
- Phase 2 / Stage A: complete
- Phase 3: in progress
- Stage B: preparatory routing seams advancing
- Stage C: not started

## Priority-ordered execution checklist

### P0 — Close Stage A with repeatable proof ✅

1. Standardize repo-local test bootstrap for retrieval suites.
   - Goal: make retrieval verification repeatable without ad hoc directory creation.
   - Likely touchpoints:
     - `backend/open_webui/test/util/test_retrieval_submission.py`
     - `backend/open_webui/test/util/test_knowledge_retrieval_submission.py`
     - `backend/open_webui/test/util/test_retrieval_transport.py`
     - shared pytest/bootstrap helpers if available
   - Done when:
     - the retrieval suite passes from a documented command path
     - the command explicitly prepares or isolates the DB/data path used under WSL + Windows venv execution

2. Add/confirm restart + fallback proof for retrieval workers.
   - Goal: prove Stage A behavior, not just unit success.
   - Add coverage for:
     - worker restart/redelivery
     - duplicate-delivery idempotency
     - local fallback when `NATS_URL` or JetStream is unavailable
     - DB-projected status survival after restart
   - Done when:
     - these cases are tested or deterministically smoke-tested
     - the expected contract is captured in docs

3. Update Stage A docs from “Stage A-style” to “Stage A complete” only after proof exists.
   - Likely touchpoint:
     - `docs/architecture/nats/06-implemented-state-and-next-steps.md`

#### Stage A verification commands

```bash
cd /mnt/c/dev/NatsWebUI/open-webui-nats
mkdir -p backend/data/cache backend/data/uploads backend/data/vector_db
./.venv/Scripts/python.exe -m compileall backend/open_webui
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_retrieval_submission.py \
  backend/open_webui/test/util/test_knowledge_retrieval_submission.py \
  backend/open_webui/test/util/test_retrieval_transport.py -q
./.venv/Scripts/python.exe -m pytest \
  backend/open_webui/test/util/test_runtime_registry_config.py \
  backend/open_webui/test/util/test_pipeline_adapter.py \
  backend/open_webui/test/util/test_terminal_eventing.py \
  backend/open_webui/test/util/test_runtime_registry.py \
  backend/open_webui/test/util/test_file_process_status.py \
  backend/open_webui/test/util/test_retrieval_service.py \
  backend/open_webui/test/util/test_retrieval_jobs.py \
  backend/open_webui/test/util/test_retrieval_worker.py \
  backend/open_webui/test/util/test_retrieval_submission.py \
  backend/open_webui/test/util/test_knowledge_retrieval_submission.py \
  backend/open_webui/test/util/test_retrieval_transport.py -q
```

### P1 — Finish runtime-registry contract before routing depends on it

4. Add heartbeat/ownership semantics to runtime registry records.
   - Fresh evidence:
     - freshness filtering already exists in `backend/open_webui/utils/runtime_registry.py`
     - admin runtime registry read surface already exists in `backend/open_webui/routers/configs.py`
   - Completed in the current branch:
     - instance-scoped registry records are written under heartbeat-style keys
     - derived routing snapshots are written separately
     - annotated runtime metadata now exposes configured/registered/fresh/healthy/route-eligible state
   - Remaining plan work:
     - true heartbeat refresh cadence beyond sync/materialization timing
     - any future routing adoption must still preserve config fallback

5. Keep registry use advisory until ownership semantics are stable.
   - Do not change browser/session/socket behavior.
   - Preserve config fallback as authority.

### P2 — Make terminal selection registry-aware

6. Move from “runtime metadata visible” to “registry-aware selection with fallback”. ✅
   - Implemented:
     - terminal proxy + websocket routes now resolve route source through runtime metadata
     - stale/missing runtime metadata falls back to config
     - route-source observability is emitted via headers/events
7. Add a transitional terminal-service runtime for service-owned registration. 🟡
   - Implemented:
     - embedded/dedicated `python -m open_webui terminal-service` mode now exists
      - terminal runtime registration can be provided by a service-owned provider instead of the web tier’s derived terminal records
      - terminal service startup primes terminal cache/spec metadata through existing safe paths
      - terminal-service now publishes a first-class service record as well as per-terminal records
      - terminal-service now maintains bounded session-registry state via TTL pruning
      - session-specific terminal HTTP proxy requests now use service-owned session routing/validation too
      - terminal lifecycle decisions are now surfaced via response headers for observability
      - terminal-service runtime records now expose live session-registry counts
      - per-terminal runtime records now expose server-scoped session counts
      - annotated runtime metadata now includes service capabilities/routing detail
      - lifecycle-source/session-status now propagate through terminal event payloads too
      - terminal listings now surface per-terminal session counts directly
      - terminal listings now surface per-terminal lifecycle-state summaries
8. Move terminal create/attach lifecycle routing behind the service seam. 🟡
   - Implemented:
     - terminal create (`POST api/terminals`) and attach routing decisions can now request service-owned control over Core NATS
      - web routes preserve fallback to the existing local resolution path when terminal-service is unavailable
      - focused tests now prove create/attach delegation, fallback-safe behavior, and closed-session attach rejection
   - Still deferred:
      - move more session lifecycle control ownership into the service boundary beyond route selection + session-state validation
      - give the terminal service independent routing/lifecycle authority beyond registration + create/attach control
      - reduce web-tier registry authority once the extracted service becomes the sole owner

### P3 — Finish pipeline transport extraction

9. Replace direct router construction of `HttpPipelineAdapter` with a transport boundary/factory. ✅
   - Implemented:
     - pipeline routes now use `get_pipeline_adapter(...)`
     - adapter creation is centralized behind `build_pipeline_adapter(...)`
     - request-scoped factories can override the transport seam for future internal modes
10. Add Core NATS request/reply path for internal filter execution. 🟡
   - Implemented:
      - `PIPELINE_INTERNAL_TRANSPORT=nats` now selects `NatsPipelineAdapter`
      - internal filter execution can issue Core NATS request/reply calls on `owui.cmd.pipeline.run`
      - timeout / unavailable-responder / disabled-NATS paths fall back to the existing HTTP compatibility adapter
      - focused adapter tests now prove request/reply success and fallback behavior
      - `CoreNatsPipelineRunner` now provides a responder-side path, including worker-only CLI boot via `python -m open_webui pipeline-runner`
      - `pipeline-runner` now owns provider-backed runtime registration/heartbeat records
      - `pipeline-runner` can now execute narrow internal filters through a registered non-HTTP executor seam
      - `pipeline-runner` can now execute repo-native internal filter-function modules directly from app state
      - direct function-module execution now passes through the core filter-context parameters used by existing handlers
      - internal pipeline models can now advertise the non-HTTP lane automatically through connection metadata
      - statically declared internal pipeline models can now receive full pipeline metadata from config
      - custom/preset models no longer drop inherited internal pipeline runtime metadata
      - explicit durable execution metadata is no longer overwritten by generic internal tagging
      - pipeline-backed models now expose top-level execution mode metadata
      - non-streaming internal function `pipe` models can now use the service-owned runner lane
      - the chat entrypoint now routes non-streaming internal `pipe` models to the runner first
      - durable non-streaming internal `pipe` models can now use the JetStream stage lane
      - non-stream `pipe` outputs now normalize compatibly across direct and runner-backed execution
      - function `pipe` models now advertise their execution mode explicitly
      - runtime records now expose the runner’s current executor/function inventory
      - internal action functions can now use the runner-backed lane too
      - durable internal action functions can now use the JetStream stage lane
      - runner-backed internal actions now preserve sub-action ids
      - action/filter descriptors now expose execution metadata to callers
      - action/filter descriptors now expose executor identity to callers
   - Still remaining:
      - expand non-HTTP execution beyond the current narrow internal filter/function seam
11. Add JetStream durable-stage execution where needed. 🟡
   - Implemented:
     - `pipeline-runner` now provisions a JetStream stage lane on `owui.cmd.pipeline.stage.run`
     - durable stage messages are acked on success and nacked on failure for retry semantics
     - `pipeline-adapter` can now route durable stages through the JetStream lane and await a reply subject
   - Still remaining:
     - extend durable-stage routing into additional higher-level pipeline orchestration paths
     - define richer stage envelope semantics where needed
     - prove end-to-end runtime behavior beyond adapter/consumer unit handling

### P4 — Promote to real Stage B

12. Extract a narrow terminal service.
13. Extract a narrow pipeline-runner service.
14. Require both services to register/heartbeat.
15. Add compose/runtime docs for `web + nats + retrieval-worker + terminal + pipeline-runner`.
   - Implemented:
     - `docker-compose.nats.yaml` now provisions `retrieval-worker`, `pipeline-runner`, and `terminal-service`
     - the compose web lane disables embedded retrieval/pipeline/terminal service modes
     - legacy `docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml config` now validates the merged five-service topology
     - pytest now codifies the overlay shape and embedded-mode expectations in `backend/open_webui/test/util/test_docker_compose_nats_overlay.py`
   - Still remaining:
     - verify the full five-service topology at runtime end to end
     - promote the overlay from transitional scaffolding to a fully supported Stage B runtime shape

### P5 — Deferred Stage C work

16. Add `artifact-worker`.
17. Extract `tool-executor` behind a safer boundary.
18. Introduce stronger isolation only when justified by deployment/trust boundaries.
   - Current doc target: NATS accounts or leaf nodes.

## Recommended immediate next slice

If execution resumes now, do this next:
1. move terminal session lifecycle control further into the extracted service boundary beyond create/attach routing + session-state validation while preserving current browser/socket fallback behavior
2. expand the `pipeline-runner` non-HTTP execution seam beyond the current narrow internal filter/function lane and reduce reliance on the compatibility adapter
3. extend and prove the new JetStream durable pipeline-stage lane end to end

## Fresh evidence references

- `backend/open_webui/routers/pipelines.py`
- `backend/open_webui/utils/pipeline_adapter.py`
- `backend/open_webui/utils/pipeline_runner.py`
- `backend/open_webui/routers/terminals.py`
- `backend/open_webui/utils/terminal_service.py`
- `backend/open_webui/routers/terminals.py`
- `backend/open_webui/utils/runtime_registry.py`
- `backend/open_webui/routers/configs.py`
- `docker-compose.nats.yaml`
- `docs/architecture/nats/06-implemented-state-and-next-steps.md`
