# Autopilot Spec — Open WebUI NATS Migration Review and Remaining Plan

This spec supersedes the older slice-focused retrieval-worker autopilot spec. The active request is a review-and-plan task: inspect the existing NATS migration plans, determine current implementation state, and create the implementation plan for the remaining work.

## Inputs reviewed

- `.omx/plans/prd-nats-migration.md`
- `.omx/plans/test-spec-nats-migration.md`
- `.omx/plans/nats-ralplan-consensus.md`
- `.omx/plans/nats-next-actions-checklist.md`
- `.omx/plans/nats-stage-a-proof-matrix.md`
- `docs/architecture/nats/01-nats-jetstream-primer.md`
- `docs/architecture/nats/02-repo-review-and-fit-analysis.md`
- `docs/architecture/nats/03-target-architecture-and-contracts.md`
- `docs/architecture/nats/04-phased-retrofit-roadmap.md`
- `docs/architecture/nats/05-service-first-roadmap.md`
- `docs/architecture/nats/06-implemented-state-and-next-steps.md`
- current branch code under `backend/open_webui`, `src`, tests, and `docker-compose.nats.yaml`

## Current branch state

Branch: `nats-refactor`
Head observed: `17c39ea980`

The branch is no longer just at retrieval-worker groundwork. Current code and tests show:

1. **Messaging foundation complete**
   - NATS config/env surfaces exist.
   - task stop/control can operate through a runtime abstraction while preserving Redis/local behavior.

2. **Stage A retrieval topology complete**
   - `retrieval-worker` worker-only CLI exists.
   - retrieval job envelopes, signed/durable submission, JetStream worker consume/ack/NAK behavior, local fallback, and DB-projected status are covered by tests.
   - `docker-compose.nats.yaml` includes NATS and retrieval worker topology.

3. **Runtime registry is partially service-ready**
   - runtime records expose configured/registered/fresh/healthy/route-eligible state.
   - records can be materialized to `owui_registry` and derived routing views.
   - service-owned providers exist for terminal and pipeline runner records.
   - registry is still transitional/advisory; ownership and live-service authority need hardening before declaring it a full control plane.

4. **Terminal service is transitional Stage B implementation, not just prep**
   - `terminal-service` worker-only CLI exists.
   - terminal runtime registration, cache priming, service record publication, session registry TTL cleanup, create/attach delegation, closed-session attach rejection, proxy observability headers, lifecycle event metadata, and per-terminal counts are implemented/tested.
   - raw browser transport and fuller lifecycle authority remain at the web edge.

5. **Pipeline runner is transitional Stage B implementation, not just prep**
   - pipeline router calls use `get_pipeline_adapter(...)` factory seam.
   - `NatsPipelineAdapter` supports Core NATS request/reply and durable JetStream stage publish/reply paths with HTTP fallback.
   - `pipeline-runner` worker-only CLI, runtime records, internal filter/pipe/action execution, repo-native function execution, durable stage consumer, and ack/NAK behavior are implemented/tested.
   - broader pipeline orchestration and live five-service runtime proof remain to close.

6. **Stage B is close but not fully supported yet**
   - compose overlay now includes `retrieval-worker`, `terminal-service`, and `pipeline-runner` and disables matching embedded modes in `open-webui`.
   - automated tests prove unit/contract/compose-shape behavior.
   - missing proof: live five-service end-to-end runtime smoke and docs reconciliation.

7. **Stage C remains deferred**
   - artifact-worker, tool-executor extraction, and stronger isolation via NATS accounts/leaf nodes are not implemented.

## Verification evidence from this review

Commands were run with Windows venv execution from WSL and repo-local data paths:

- `./.venv/Scripts/python.exe -m compileall backend/open_webui -q` — passed.
- Focused NATS Stage A/B seam pytest slice — `81 passed, 8 warnings`.
- Broader NATS migration pytest slice — `143 passed, 8 warnings`.

Warnings were pre-existing dependency/deprecation warnings, not test failures.

## Target state for the remaining program

The next target is **supported Stage B**, defined as:

- `web + nats + retrieval-worker + terminal-service + pipeline-runner` runs as a documented topology.
- retrieval remains Stage A-complete and rollback-safe.
- terminal lifecycle authority for routing/session-state moves further into `terminal-service` without moving raw browser terminal bytes yet.
- pipeline-runner owns more non-HTTP execution paths and durable-stage orchestration, with HTTP compatibility preserved as fallback.
- runtime registry records and heartbeats become reliable enough for service selection and operational diagnostics.
- docs, tests, and compose smoke evidence agree on what is implemented, transitional, and deferred.

## Non-goals for the immediate next implementation wave

- Do not replace Redis session/socket/Yjs behavior.
- Do not move raw terminal WebSocket byte transport off the web edge yet.
- Do not make NATS mandatory for default deployments.
- Do not extract tool-executor or artifact-worker until Stage B runtime proof is complete.
- Do not introduce NATS account/leaf-node isolation until service boundaries and trust requirements are explicit.
