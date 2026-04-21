# NATS Remaining Implementation Plan

This is the current implementation plan after the 2026-04-20 review of existing NATS migration plans, branch code, and targeted verification. It mirrors `.omx/plans/autopilot-impl.md` but uses a stable, task-specific filename for handoff.

## State we are at

- Stage A retrieval is complete and verified.
- Stage B has transitional implementation for `terminal-service` and `pipeline-runner` but needs live five-service proof and ownership hardening.
- Stage C remains deferred.

## Where we need to be next

A supported Stage B topology:

```text
open-webui web edge
  + nats/jetstream
  + retrieval-worker
  + terminal-service
  + pipeline-runner
```

The web tier keeps browser HTTP/WebSocket/auth responsibilities. Dedicated services own durable retrieval, terminal lifecycle decisions, and internal pipeline execution where appropriate. Redis remains for session/socket/Yjs responsibilities. Fallback paths remain documented and tested.

## Remaining implementation phases

1. **Docs/plans reconciliation** — update current-state docs so they reflect actual implemented terminal/pipeline capabilities and only list true remaining gaps.
2. **Live Stage B topology proof** — boot/prove the five-service compose topology and capture retrieval, terminal, pipeline, registry, and fallback evidence.
3. **Runtime registry hardening** — enforce service-owned vs derived key semantics, stale/healthy/route-eligible behavior, and admin diagnostics.
4. **Terminal-service lifecycle hardening** — move lifecycle authority beyond create/attach into idempotent create, reconnect/resume, cleanup, conflict handling, and service-owned observability while preserving raw browser transport at the web edge.
5. **Pipeline-runner execution hardening** — define and broaden runner-owned internal execution and durable-stage envelope/error/retry semantics while keeping HTTP compatibility for external pipelines.
6. **Promote Stage B support** — update docs/operator guidance/verification floor once live runtime proof passes.
7. **Stage C planning** — artifact-worker, tool-executor extraction, and stronger isolation belong in a separate follow-on plan.

## Fresh verification evidence

- Backend compileall passed.
- Focused Stage A/B seam tests: `81 passed, 8 warnings`.
- Broader NATS migration tests: `143 passed, 8 warnings`.

See `.omx/context/nats-migration-openwebui-20260420T205419Z.md` and `.omx/plans/autopilot-impl.md` for detailed acceptance criteria and command floor.
