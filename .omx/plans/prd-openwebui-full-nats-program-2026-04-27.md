# PRD — Open WebUI Full NATS Program

Date: 2026-04-27
Branch: `nats-refactor`

## Problem

The Open WebUI fork already has substantial NATS integration, but the overall program is fragmented across older phase docs, newer follow-up plans, and implementation that has moved ahead in some areas. The result is that the branch has real extraction work in place, but the exact "what is done / what is transitional / what is next" story is harder to follow than it should be.

## Goal

Define one current program plan that finishes the full Open WebUI NATS refactor from the branch's actual 2026-04-27 state.

## Current-state call

### Proven / operationally meaningful
- task messaging coexistence,
- durable retrieval worker lane,
- runtime registry materialization,
- terminal-service service seam,
- pipeline-runner service seam,
- automation-runner service seam,
- compose overlay and focused regression coverage.

### Still transitional
- registry authority split,
- terminal lifecycle authority,
- broader pipeline-runner ownership and live proof,
- automation-runner closeout as the real primary owner in NATS mode,
- complete Stage B promotion evidence.

### Deferred follow-on domains
- artifact-worker,
- tool-executor,
- stronger account/leaf-node isolation.

## Program done definition

The Open WebUI NATS refactor is done only when:

1. docs describe the branch as it actually exists,
2. Stage B live proof covers retrieval, terminal, pipeline, and automation lanes,
3. runtime registry ownership is explicit and non-overlapping,
4. extracted services are the real authorities in NATS mode for the lanes they own,
5. fallback/rollback behavior is documented and tested,
6. deferred Stage C work is separated cleanly instead of mixed into Stage B closeout.

## Ordered phases

### Phase 0 — Reconcile the roadmap with reality
Update the main docs/plan surfaces so they explicitly account for:
- automation-runner,
- the four extracted runtime lanes now in play,
- what is live-proven vs unit/compose-proven,
- which items remain Stage B vs Stage C.

Done when:
- a new reader can answer "where are we at?" from one current artifact set.

### Phase 1 — Close Stage B live proof
Use the compose/runbook path to prove all extracted-service lanes in a live topology:
- retrieval-worker,
- automation-runner,
- terminal-service,
- pipeline-runner.

Required proof:
- app + NATS health,
- service registration/freshness,
- functional path success per lane,
- stopped-service fallback behavior after freshness expiry.

Done when:
- Stage B can be called supported with evidence, not only test scaffolding.

### Phase 2 — Harden runtime registry authority
Split ownership clearly between:
- service-owned heartbeat records,
- derived routing/materialization views,
- any future registry-service ownership.

Done when:
- no service can accidentally delete or overwrite another service's authoritative heartbeat state,
- stale/non-routeable state is explicit.

### Phase 3 — Finish terminal-service ownership boundaries
Keep browser WebSocket termination at the web edge, but continue moving lifecycle authority into the extracted service:
- create/attach already exist,
- extend to reconnect/resume/cleanup/conflict handling and service-owned observability.

Done when:
- the web tier is no longer the hidden primary lifecycle owner in NATS mode.

### Phase 4 — Finish pipeline-runner ownership boundaries
Broaden the runner-owned execution story beyond the currently proven narrow seams:
- request/reply internal execution,
- durable-stage execution,
- descriptor/runtime metadata accuracy,
- live functional proof for request/reply and durable-stage lanes.

Done when:
- the web tier is no longer the hidden primary execution owner for the NATS-enabled internal pipeline lanes.

### Phase 5 — Finish automation-runner ownership boundaries
Make automation-runner the real primary owner in NATS mode:
- due scheduling,
- enqueue/claim/execute/result flow,
- runtime metadata that no longer claims `transitional-local` when the runner owns execution.

Done when:
- manual and scheduled automation execution no longer primarily depend on the web process in NATS mode.

### Phase 6 — Stage C planning split
Create separate post-Stage-B plans for:
- artifact-worker,
- tool-executor,
- stronger isolation.

Done when:
- Stage B closeout is no longer blocked by unrelated future architecture ambitions.

## Priority order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 5
5. Phase 3
6. Phase 4
7. Phase 6

Reasoning:
- first make the branch understandable,
- then prove the current topology,
- then harden shared authority,
- then finish the remaining service-owner transitions.
