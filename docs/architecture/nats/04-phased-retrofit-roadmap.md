# Phased Retrofit Roadmap

This roadmap describes the low-risk adoption path for NATS and JetStream inside the existing monolith. It is designed to produce value early, preserve rollback options, and avoid replacing Redis, HTTP, WebSocket, or browser contracts prematurely.

## Phase 1: Messaging Abstraction Inside The Monolith

### Goal

Introduce a messaging abstraction and an adjacent NATS deployment without changing the browser contract or replacing Redis-backed session and websocket coordination.

### Entry Criteria

- Existing monolith deployment remains the primary runtime.
- No external worker services are required yet.
- The codebase can add a NATS client dependency and configuration safely.

### Implementation Tasks

- Add a small internal messaging layer that can publish Core NATS control messages and optionally JetStream events.
- Wrap the task stop and control behavior in `backend/open_webui/tasks.py` behind the new abstraction.
- Define the initial subject namespace using the contracts in `03-target-architecture-and-contracts.md`.
- Publish non-critical domain events first, such as task stop requested, task stop acknowledged, terminal session created, and retrieval job queued.
- Keep Redis as the active execution and session coordinator while NATS runs in parallel.
- Document an adjacent NATS deployment option alongside the current `docker-compose.yaml` shape.

### Acceptance Criteria

- Task control code no longer depends directly on Redis pub/sub as its only messaging contract.
- At least one control path and one event path use the new messaging layer.
- Browser behavior and admin workflows remain unchanged.
- Redis remains the source of truth for session and websocket cluster behavior.

### Rollback Notes

- The messaging abstraction should be swappable back to the current Redis-only path.
- No existing endpoint contract should require NATS for correctness in this phase.

### Dependencies

- NATS client configuration
- subject naming standards
- logging and observability around publish and subscribe failures

## Phase 2: Durable Background Work On JetStream

### Goal

Move durable, retry-worthy background work out of FastAPI background tasks and into JetStream-backed workers while preserving existing file and knowledge UX.

### Entry Criteria

- Phase 1 messaging abstraction is in place.
- Subjects and envelope formats are stable enough for job submission and progress events.
- Worker processes can read the same DB and storage provider.

### Implementation Tasks

- Introduce a `retrieval-worker` service or worker mode for file ingestion, OCR or transcription, chunking, embeddings, and indexing.
- Move work currently triggered from `backend/open_webui/routers/files.py`, `backend/open_webui/routers/retrieval.py`, and `backend/open_webui/routers/knowledge.py` onto JetStream streams.
- Use durable consumers with explicit ack, bounded `MaxAckPending`, bounded `MaxDeliver`, and backoff.
- Emit progress and completion events that the web tier can translate into existing status APIs or SSE updates.
- Keep the DB and storage provider as the durable sources of truth for file metadata and artifacts.

### Acceptance Criteria

- File ingestion jobs survive web process restarts.
- Failed jobs can retry without losing the audit trail.
- The browser can still query or stream status through existing endpoints.
- Duplicate execution is tolerated through idempotent worker behavior.

### Rollback Notes

- The web process can fall back to the old in-process background task path if workers are unavailable.
- Existing DB-backed file status fields remain compatible.

### Dependencies

- Shared storage access
- worker deployment shape
- idempotent job handlers
- progress event schema

## Phase 3: Externalize Selected Services

### Goal

Move the right responsibilities out of the monolith while preserving stable browser contracts and admin configuration semantics.

### Entry Criteria

- Phase 2 workers are operating successfully.
- Subject taxonomy and event conventions are stable.
- Capability registration and routing metadata are defined.

### Implementation Tasks

- Externalize terminal lifecycle and registration logic into a `terminal` service while keeping browser WebSocket transport at the web edge.
- Externalize internal pipeline execution into a `pipeline-runner` with Core NATS request/reply for fast internal filters and JetStream for long-running stages.
- Introduce KV-backed runtime registry state for service presence, capabilities, and routing hints while preserving admin-configured access control.
- Optionally introduce an `artifact-worker` for notebook exports or generated bundles.

### Acceptance Criteria

- The monolith no longer owns all background execution responsibilities.
- At least one externalized service registers itself dynamically and can be routed to without startup hardcoding.
- Browser-facing endpoints and auth behavior remain stable.

### Rollback Notes

- External services should be removable without deleting the NATS contract layer.
- The web tier should still be able to operate with local fallback implementations for critical paths where feasible.

### Dependencies

- KV-backed registry model
- service heartbeat conventions
- routing and partitioning rules
- service health reporting

## Recommended Sequence By Subsystem

Start in this order:

1. `backend/open_webui/tasks.py`
2. `backend/open_webui/routers/files.py`
3. `backend/open_webui/routers/retrieval.py`
4. `backend/open_webui/routers/knowledge.py`
5. terminal lifecycle around `backend/open_webui/routers/terminals.py`
6. registry evolution in `backend/open_webui/utils/tools.py`
7. internal pipeline execution in `backend/open_webui/routers/pipelines.py`

Delay these until the above are stable:

- raw terminal transport changes
- model token streaming changes
- plugin execution distribution in `backend/open_webui/utils/plugin.py`

## Rollback-Safe Milestone

The first rollback-safe milestone is:

- add NATS alongside Redis
- route task control through a messaging abstraction
- publish retrieval and terminal lifecycle events without making correctness depend on them

This milestone delivers value because it establishes the contract surface and observability needed for later workers without forcing service extraction.

## Failure Scenarios To Design For

- lost Core NATS control message
- unavailable responder for request/reply
- slow consumer on a hot event subject
- JetStream redelivery after worker crash
- duplicate execution of a retrieval job
- stale registry entry after an unclean worker shutdown
- partial progress visibility if the UI misses an event but can still read final state from DB

Official references:

- [Request/Reply](https://docs.nats.io/nats-concepts/core-nats/reqreply)
- [Consumers](https://docs.nats.io/nats-concepts/jetstream/consumers)
- [KV](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
- [Slow Consumers](https://docs.nats.io/running-a-nats-service/nats_admin/slow_consumers)
