# Review — Open WebUI NATS Refactor Program Status

Date: 2026-04-27
Branch reviewed: `nats-refactor`

## Fresh evidence gathered in this review

### Repo state
- branch: `nats-refactor`
- diff vs `main`: `96 files changed, 16963 insertions(+), 992 deletions(-)` across backend, docs, overlay, and tests
- existing NATS docs present under `docs/architecture/nats/01` through `07`
- existing plan set already present under `.omx/plans`

### Fresh verification run
- `./.venv/Scripts/python.exe -m compileall backend/open_webui`
- focused pytest slice across task messaging, retrieval, runtime registry, terminal service/eventing, pipeline adapter/runner, automation runner/utils, and compose overlay
- result: `135 passed, 10 warnings in 64.26s`
- partial live Stage B startup smoke proved the current six-service topology can boot locally and publish raw KV registry records for `automation-runner.default`, `terminal-service.default`, and `pipeline-runner.default`; full functional/fallback smoke is still pending

## What has been added to Open WebUI for NATS so far

### 1. Messaging + runtime foundation
- NATS env/config wiring in `backend/open_webui/env.py`
- startup/shutdown orchestration in `backend/open_webui/main.py`
- shared task messaging in `backend/open_webui/utils/task_messaging.py`
- runtime registry + derived routing state in `backend/open_webui/utils/runtime_registry.py`

### 2. Durable retrieval lane
- retrieval job contracts and durable submission helpers in:
  - `backend/open_webui/utils/retrieval_jobs.py`
  - `backend/open_webui/utils/retrieval_submission.py`
  - `backend/open_webui/utils/retrieval_transport.py`
- worker runtime in:
  - `backend/open_webui/utils/retrieval_worker.py`
  - `python -m open_webui retrieval-worker`
- route/status integration in:
  - `backend/open_webui/routers/retrieval.py`
  - `backend/open_webui/routers/files.py`

### 3. Terminal service extraction seam
- service-owned terminal runtime and lifecycle helpers in `backend/open_webui/utils/terminal_service.py`
- route delegation + observability in `backend/open_webui/routers/terminals.py`
- registry surfacing in `backend/open_webui/utils/tools.py`

### 4. Pipeline runner extraction seam
- transport boundary in `backend/open_webui/utils/pipeline_adapter.py`
- runner runtime in `backend/open_webui/utils/pipeline_runner.py`
- router adaptation in `backend/open_webui/routers/pipelines.py`
- model/chat/action integration through:
  - `backend/open_webui/utils/models.py`
  - `backend/open_webui/utils/chat.py`
  - `backend/open_webui/utils/actions.py`

### 5. Automation runner extraction seam
- runner lane in `backend/open_webui/utils/automation_runner.py`
- runtime metadata + event helpers in `backend/open_webui/utils/automations.py`
- API edge integration in `backend/open_webui/routers/automations.py`
- CLI/runtime mode in `python -m open_webui automation-runner`

### 6. Compose/operator path
- extracted-service overlay in `docker-compose.nats.yaml`
- overlay regression proof in `backend/open_webui/test/util/test_docker_compose_nats_overlay.py`
- live-smoke runbook in `docs/architecture/nats/07-stage-b-smoke-runbook.md`

## Program-level status call

### Complete enough to rely on
- retrieval-worker lane,
- task messaging coexistence,
- base runtime registry concept,
- compose/test scaffolding for extracted services,
- service-owned seams for terminal, pipeline, and automation.

### In progress / not fully closed
- Stage B as a fully supported topology,
- registry authority hardening,
- terminal lifecycle ownership beyond bounded control/routing,
- broader pipeline-runner ownership and full live runtime proof,
- automation-runner closeout inside the main roadmap narrative.

### Fresh live-smoke takeaways
- retrieval upload/processing is now live-proven on the current stack
- manual automation execution is now live-proven on the current stack
- request/reply internal pipeline execution is now live-proven on the current stack
- terminal proxying through a configured external Open Terminal instance is now live-proven on the current stack
- stopping `pipeline-runner` and `automation-runner` still leaves successful behavior via fallback/local paths, which means extracted-service ownership is still incomplete
- the durable JetStream pipeline-stage lane is still not fully promotable because runner logs recorded stage-execution failures even when the API returned a success response

### Follow-up ownership hardening completed after smoke
- durable internal pipe fallback masking was removed: `execution=jetstream`/`durable_stage` models now re-raise runner failures instead of direct-executing locally
- durable stage publishers now publish against the explicit `owui_pipeline_jobs` stream after establishing the reply subscription
- terminal-service gained a config-refresh NATS control subject so admin terminal connection updates can be pushed without restart
- manual automation requests in NATS mode now have a regression proving runner request failures do not enqueue web-local fallback execution
- regression evidence: focused slice `36 passed, 8 warnings`; broader NATS/service slice `146 passed, 10 warnings`; automation guard `5 passed, 1 warning`; final combined NATS/service slice `152 passed, 10 warnings`; targeted compile passed

### Live re-proof after hardening
- terminal config refresh was re-tested live: config update was visible to `terminal-service` without restart, and terminal config/session creation returned `200` with runtime lifecycle headers
- durable pipeline stage was re-tested live: direct JetStream probe returned `status=ok`, active `stageb_js_pipe` returned the expected `stage-b-jetstream-ok` response, and stopped `pipeline-runner` produced a clear `503` instead of local direct fallback
- remaining caveat: future smoke should use the new unique durable pipe trace ids when reviewing logs, because one stale fixed-trace warning from earlier queued work was still visible in this run
- remaining automation caveat: the no-local-fallback behavior is unit-guarded for manual NATS requests, but the stopped `automation-runner` live smoke still needs to be repeated before Stage B promotion

### Deferred
- artifact-worker,
- tool-executor,
- stronger isolation with accounts/leaf nodes.

## Where the docs currently drift from the code

### Drift 1 — the refactor is broader than the original Stage B story
`06-implemented-state-and-next-steps.md` still frames the main transitional Stage B story around retrieval + terminal + pipeline, but the branch now also contains:
- automation-runner CLI/service mode,
- automation runtime registry records,
- compose/test coverage that expects `automation-runner`.

### Drift 2 — Stage B smoke expectations have expanded
`07-stage-b-smoke-runbook.md` expects:
- `automation-runner`
- `retrieval-worker`
- `terminal-service`
- `pipeline-runner`

That means the program-level "where are we at?" answer should now explicitly say:
- Stage A retrieval is done,
- Stage B has four extracted service lanes in play,
- support/promotion still depends on broader functional and fallback smoke proof.

## Recommended next work for Open WebUI

### P0 — Reconcile docs to current implementation
Update the main roadmap/current-state docs so they explicitly account for:
- automation-runner,
- the expanded extracted-service set,
- what is actually proven versus only unit/compose-proven.

### P1 — Close Stage B live functional proof
Use the runbook to gather or refresh live evidence for:
- retrieval functional path,
- terminal lifecycle path,
- pipeline request/reply + durable-stage path,
- automation-runner request/claim/execute path,
- stopped-service fallback behavior after freshness expiry.

### P2 — Harden runtime-registry authority
Split:
- service-owned heartbeat state,
- derived routing/materialization state,
- eventual registry-service ownership.

### P3 — Finish automation-runner ownership
Repeat the stopped-runner live smoke and scheduled-run ownership check now that manual NATS request fallback is unit-guarded.

### P4 — Stage C pre-planning
Prepare separate follow-on plans for:
- artifact-worker,
- tool-executor,
- isolation boundaries.

## Best current one-line summary

Open WebUI is **well beyond a prototype NATS port**: retrieval is real, terminal/pipeline/automation service seams exist, and the remaining work is mainly **proof closure, authority hardening, and finishing the service-first extraction story**.

## External repo Ralph implementation wave — 2026-04-27

The first external-repo implementation wave moved `open-terminal-nats`, `pipelines-nats`, and `terminals-nats` beyond planning into optional NATS runtime/control-plane code:

- `open-terminal-nats` now advertises Open WebUI-compatible registry records and has optional Core NATS request/reply handlers for non-interactive execute plus terminal session create/list/get/delete.
- `pipelines-nats` now advertises registry records and has optional Core NATS request/reply handlers for inventory, reload, and non-streaming synchronous pipeline execution.
- `terminals-nats` now advertises registry records and has optional queue-group Core NATS handlers for ensure, route, touch, and delete lifecycle operations.

Verification evidence from this wave:

- `open-terminal-nats`: compileall passed; plain Python test runner passed; pytest via the Open WebUI venv reported `5 passed`.
- `pipelines-nats`: compileall passed; plain Python test runner passed; pytest via the Open WebUI venv reported `4 passed`.
- `terminals-nats`: compileall passed; plain Python test runner passed; pytest via the Open WebUI venv reported `7 passed`.

Design constraints preserved:

- NATS remains optional; `nats-py` imports stay inside configured live connection paths.
- Existing HTTP/WebSocket compatibility surfaces are preserved.
- Request/reply subscribers use queue groups where lifecycle fan-out would be unsafe.

Remaining cross-repo work:

- run a live NATS broker smoke for all three services and confirm registry/routing KV records are visible to Open WebUI,
- add Open WebUI caller-side adapters for the new external service subjects where these services should replace direct HTTP/local calls,
- add durable JetStream lanes for long-running execute/pipeline lifecycle work,
- decide whether to promote `nats-py` into each repo's install dependencies or document it as an optional NATS extra.

### External repo live NATS smoke follow-up

A temporary `nats:2-alpine -js` broker on `127.0.0.1:4223` proved the new external repo runtime helpers against a real broker:

- Open Terminal wrote `open-terminal.smoke-open-terminal` to routing KV and replied on `owui.cmd.open-terminal.execute`.
- Pipelines wrote `pipelines.smoke-pipelines` to routing KV and replied on `owui.cmd.pipelines.inventory`.
- Terminals wrote `terminals.smoke-terminals` to routing KV and replied on `owui.cmd.terminals.ensure`.

The live smoke caught and fixed one Pipelines bug: the NATS subscription callback must be an async callback function rather than a synchronous lambda returning a coroutine. Post-fix Pipelines pytest reports `5 passed`.

### Ralph architect-fix follow-up

Architect review rejected the first pass for two issues, both addressed:

1. `pipelines-nats/main.py` referenced `NATS_CONTROL_QUEUE` without importing it. The import is now present, compileall passes, pytest reports `5 passed`, and live broker smoke confirms `owui.cmd.pipelines.inventory` replies.
2. `terminals-nats` originally queue-grouped route/touch/delete despite process-local terminal state. The subscription model now queue-groups only `ensure`; owner-discovery subjects (`route`, `touch`, `delete`) are unqueued so the owning instance can answer. A regression test asserts this, pytest reports `8 passed`, and live broker smoke confirms `ensure` plus `route` replies.

Remaining caller-side work: Open WebUI adapters must handle multiple unqueued route/touch/delete replies by selecting a successful owner response or using routing KV records when available.

### Ralph architect-fix follow-up 2

Second architect review found two remaining issues; both were addressed:

- Pipelines service-record builder now accepts and reports `control_queue`, eliminating the startup signature mismatch. Direct signature reproducer, pytest (`5 passed`), and live broker smoke passed.
- Terminals owner-discovery subjects now support `target_instance_id` / `owner_instance_id` filtering and return explicit ignored responses when a request targets another instance. Pytest now reports `10 passed`, and live broker smoke proved targeted route success plus mismatched-target ignored response.

Caller-side implication: Open WebUI should target route/touch/delete requests using routing KV `instance_id` where possible, or otherwise select a non-ignored successful owner response from unqueued replies.
