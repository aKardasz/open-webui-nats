# PRD — Staged NATS Migration

## Problem

Open WebUI currently mixes local task runtime, Redis signaling/caching, and long-running retrieval work inside the web process. This makes durable background execution, service extraction, and runtime capability discovery harder than they need to be.

## Goal

Introduce a staged migration toward:

- Core NATS for low-latency internal control and RPC
- JetStream for durable jobs and replayable domain events
- JetStream KV for runtime capability and routing state

while preserving:

- browser-facing HTTP/WebSocket contracts
- Redis-backed session/socket/Yjs behavior initially
- rollback-safe incremental delivery

## Non-goals

- Replacing Redis session or Socket.IO infrastructure in v1
- Moving raw terminal bytes onto the bus in v1
- Moving model token streaming onto the bus in v1
- Fully distributing plugin execution in v1

## Success criteria

1. A messaging abstraction exists behind which Redis and NATS can coexist safely.
2. Distributed task stop signaling no longer depends solely on Redis pub/sub.
3. Retrieval and terminal lifecycle events publish through the new messaging layer without breaking current UX.
4. Durable retrieval/file ingestion work can move to JetStream-backed workers with preserved status APIs.
5. Runtime capability state can evolve from Redis/app-state cache into KV-backed records.

## Delivery strategy

### Milestone 0 — Docs and planning artifacts
- Commit NATS architecture docs.
- Create PRD, test spec, and context snapshot.
- Establish branch/worktree sequencing.

### Milestone 1 — Messaging foundation
- Add `backend/open_webui/messaging/*`.
- Add transport-neutral contracts/envelopes.
- Add app startup wiring with safe Redis/NATS fallback behavior.

### Milestone 2 — Task control
- Refactor `backend/open_webui/tasks.py` to split metadata persistence from distributed signaling.
- Route stop signaling through the messaging abstraction.
- Emit task stop requested/acknowledged events.

### Milestone 3 — Domain events
- Emit retrieval lifecycle events from file processing paths.
- Emit terminal lifecycle events without changing raw transport.

### Milestone 4 — Durable retrieval jobs
- Extract retrieval/file/knowledge processing from router-owned flows into service handlers.
- Submit durable jobs instead of relying on FastAPI `BackgroundTasks`.
- Add worker mode/service for durable processing.

### Milestone 5 — Runtime registry
- Separate runtime capability state from admin config-driven policy.
- Evolve tool/terminal capability cache toward JetStream KV.

### Milestone 6 — Pipeline and service extraction prep
- Add a transport-agnostic pipeline executor abstraction.
- Prepare terminal lifecycle ownership and registry-driven discovery for later extraction.

## Worktree / branch model

### Initial sequence
1. `chore/nats-00-docs`
2. `feat/nats-01-foundation`
3. from foundation:
   - `feat/nats-02-task-control`
   - `feat/nats-03-domain-events`
   - `feat/nats-04-registry-groundwork`

### Later sequence
4. `feat/nats-05-retrieval-jobs`
5. `feat/nats-06-kv-registry`
6. `feat/nats-07-pipeline-adapter`
7. `feat/nats-08-terminal-service-prep`

## Commit philosophy

- One architectural boundary per commit when possible.
- Keep commits reversible.
- Use Lore protocol trailers to record constraints, rejected alternatives, and verification.

## Risks

- Merge conflicts around `backend/open_webui/main.py` if too many lanes start at once.
- Hidden coupling in router-owned retrieval flows.
- Redelivery/idempotency issues when durable workers are introduced.
- Overreaching into browser-facing transport paths too early.

## First execution target after planning gate

Build and verify `feat/nats-01-foundation`, then branch task control and domain events from it.
