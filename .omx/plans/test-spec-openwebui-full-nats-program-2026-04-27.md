# Test Spec — Open WebUI Full NATS Program

Date: 2026-04-27

## Fresh proof already gathered in this review

- `./.venv/Scripts/python.exe -m compileall backend/open_webui`
- focused pytest slice across:
  - `test_task_messaging.py`
  - `test_retrieval_transport.py`
  - `test_retrieval_worker.py`
  - `test_runtime_registry.py`
  - `test_terminal_service.py`
  - `test_terminal_eventing.py`
  - `test_pipeline_adapter.py`
  - `test_pipeline_runner.py`
  - `test_automation_runner.py`
  - `test_automations_utils.py`
  - `test_automation_calendar_routes.py`
  - `test_docker_compose_nats_overlay.py`
- result: `135 passed, 10 warnings`

## Remaining verification program

### Phase 0 — Docs reconciliation
- confirm updated docs agree on:
  - extracted service set,
  - Stage B scope,
  - transitional vs supported wording,
  - deferred Stage C items.

### Phase 1 — Live Stage B proof
Live smoke must cover:
- NATS monitor healthy,
- Open WebUI healthy,
- `retrieval-worker`, `automation-runner`, `terminal-service`, and `pipeline-runner` all running,
- fresh runtime registry records for all extracted services.

Functional proof required:
- retrieval submit/consume/complete,
- automation enqueue/claim/execute/result,
- terminal create/attach lifecycle route using service seam,
- pipeline request/reply lane,
- at least one durable-stage pipeline lane,
- stopped-service fallback after freshness expiry.

### Phase 2 — Registry authority hardening
Add tests for:
- service-owned heartbeat keys vs derived routing keys,
- stale/fresh/healthy/route-eligible state transitions,
- no cross-service deletion of authoritative keys.

### Phase 3 — Terminal-service ownership
Add tests for:
- reconnect/resume decisions,
- cleanup and conflict handling,
- explicit service-owned denial and fallback behavior.

### Phase 4 — Pipeline-runner ownership
Add tests for:
- additional internal execution lanes beyond the current narrow seams,
- durable-stage orchestration behavior,
- runtime metadata parity with actual ownership.

### Phase 5 — Automation-runner ownership
Add tests for:
- scheduled due-work ownership by the runner,
- no embedded web scheduler in NATS-owned mode,
- runtime metadata reflecting real ownership,
- restart/idempotency behavior.

## Promotion gate

Do not call the Open WebUI NATS refactor complete until:
- the focused util suite stays green,
- Stage B live proof is refreshed and recorded,
- registry ownership tests exist,
- automation/terminal/pipeline ownership are no longer only transitional.
