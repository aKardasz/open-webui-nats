# Ralph Context Snapshot — Multi-Repo NATS Refactor

Timestamp: 20260427T204755Z

## Task statement
Work through all changes needed across Open WebUI, Open Terminal, Pipelines, and Terminals to refactor them to use NATS.

## Desired outcome
A verified multi-repo NATS refactor progression where:
- Open WebUI continues to harden its NATS service-first architecture.
- Open Terminal, Pipelines, and Terminals move beyond planning into real optional NATS foundations and then control-plane handlers.
- Each repo has tests, compile/build verification, and updated PRD/test-spec status.

## Known facts/evidence
- Open WebUI branch: `/mnt/c/dev/NatsWebUI/open-webui-nats`, branch `nats-refactor`.
- Open WebUI already has NATS retrieval, pipeline-runner, automation-runner, terminal-service seams, and recent hardening for durable pipe fallback, terminal config refresh, and automation no-local-fallback regression.
- External repos are on `feat/nats-00-planning` branches:
  - `/mnt/c/dev/NatsWebUI/open-terminal-nats`
  - `/mnt/c/dev/NatsWebUI/pipelines-nats`
  - `/mnt/c/dev/NatsWebUI/terminals-nats`
- First-wave optional NATS foundation was added to the three external repos immediately before Ralph activation: env/config, registry KV helpers, startup/lifespan wiring, and record-shape tests.
- `pytest` is not installed in the current shell Python; direct test-function invocation and `compileall` have been used so far.

## Constraints
- Autonomous execution; do not stop for obvious next steps.
- Keep diffs small and reversible.
- No new dependencies without explicit request; NATS import must remain optional at runtime unless NATS is configured.
- Preserve existing HTTP/WebSocket APIs.
- Use Open WebUI-compatible registry/routing KV conventions (`owui_registry`, `owui_routing`).
- Verify before claiming completion.

## Unknowns/open questions
- Whether each external repo has a preferred test runner environment beyond bare `python3`.
- Whether live NATS server/Docker smoke should be run after handler implementation; likely yes once handlers exist.
- Exact control payload shape should be minimal first-wave and compatible with current HTTP models.

## Likely codebase touchpoints
- Open Terminal: `open_terminal/env.py`, `open_terminal/main.py`, `open_terminal/nats_runtime.py`, `tests/test_nats_runtime.py`, `.omx/plans/*open-terminal*`.
- Pipelines: `config.py`, `main.py`, `utils/nats_runtime.py`, `tests/test_nats_runtime.py`, `.omx/plans/*pipelines*`.
- Terminals: `terminals/config.py`, `terminals/main.py`, `terminals/nats_runtime.py`, `tests/test_nats_runtime.py`, `.omx/plans/*terminals*`.
- Open WebUI integration docs/plans and potential client-side usage once external services expose handlers.
