# Service-First Roadmap

This roadmap documents the more ambitious modular target architecture. It assumes the team wants to move beyond a single application container and have functionality join the system as independently deployable NATS-aware services.

## Target Service Layout

The target deployment keeps the web application as the browser and auth edge, then adds a small set of bounded internal services:

- `open-webui-web`
  Owns HTTP, WebSocket, Socket.IO, auth, access control, browser state fanout, and compatibility endpoints.
- `terminal-service`
  Owns terminal fleet registration, terminal lifecycle control, and session events. Raw browser terminal transport still terminates at the web edge in the early service-first state.
- `retrieval-worker`
  Owns ingestion, OCR or transcription, chunking, embeddings, indexing, and other durable retrieval work.
- `pipeline-runner`
  Owns modular pipeline execution with fast request/reply for synchronous internal stages and JetStream jobs for long-running stages.
- `automation-runner`
  Owns automation run requests, due-schedule polling, execution lifecycle, and runtime registration in NATS-owned automation mode.
- `artifact-worker`
  Owns artifact generation, notebook exports, and optional bundle production.
- `registry`
  Owns runtime capability materialization, heartbeat aggregation, and routing metadata in KV.

Optional later services:

- `tool-executor`
  For isolated tool and plugin execution when the current runtime `exec()` model is moved behind a safer boundary.

## Stable Contracts Across Service Extraction

These contracts stay stable while services are split out:

- browser endpoints and authentication remain anchored in the web tier
- raw browser terminal transport remains WebSocket-based in early extraction stages
- NATS subject prefix remains `owui`
- command and event envelope shapes remain as defined in `03-target-architecture-and-contracts.md`
- DB and primary file storage remain the durable sources of truth for application entities and stored artifacts

The goal is that the same subjects work whether a capability is local to the monolith or served by a remote worker.

## Service Boundaries

### Terminal-Service Boundary

Owns:

- session create and attach lifecycle
- service registration and health
- audit and lifecycle events
- terminal capability metadata such as supported features

Does not own yet:

- browser websocket termination
- browser auth session handling
- raw keystroke and output transport over the public edge

Why:

- This gives modularity without destabilizing the current browser contract.

### Retrieval-Worker Boundary

Owns:

- file ingestion jobs
- OCR or transcription jobs
- chunking, embedding, and indexing
- job progress and completion events

Does not own:

- browser upload endpoints
- DB schema ownership for files and knowledge records
- storage provider ownership

Why:

- This is the cleanest extractable durable-work domain in the codebase.

### Pipeline-Runner Boundary

Owns:

- internal pipeline stage execution
- synchronous internal filters over Core NATS request/reply
- long-running or retryable stages over JetStream

Does not own:

- OpenAI-compatible external pipeline compatibility that the web tier already supports
- browser request handling

Why:

- This lets the current HTTP compatibility model coexist with richer internal service composition.

### Automation-Runner Boundary

Owns:

- manual automation run requests in NATS-owned mode
- due-schedule polling and claiming
- automation execution lifecycle and event emission
- automation runtime registration and health reporting

Does not own:

- browser CRUD pages and auth flows for automations/calendar
- long-lived relational ownership of automation definitions

Why:

- This moves scheduled and operator-triggered runtime work out of the web process without forcing calendar CRUD off the local API/DB path.

### Registry Boundary

Owns:

- runtime capability metadata
- service heartbeats
- routing hints
- feature flags or orchestration hints in KV

Does not own:

- admin authorization rules
- relational persistence for long-lived product configuration

Why:

- Runtime discovery and admin policy should remain separate concerns.

## Deployment Stages

### Stage A: Single NATS Plane, Few Services

Topology:

- web app
- NATS with JetStream
- retrieval worker

Use when:

- the main goal is to externalize durable work without changing user-facing transport.

### Stage B: Add Automation, Terminal, And Pipeline Services

Topology:

- web app
- NATS with JetStream
- retrieval worker
- automation-runner
- terminal-service
- pipeline-runner

Use when:

- the main goal is modular capability ownership and easier cross-container decomposition.

Support gate:

- Stage B is only considered supported when the six-service topology above can be booted from documented compose commands, each extracted runtime publishes fresh registry records, and retrieval, automation, terminal lifecycle, and pipeline execution paths have live smoke evidence with fallback behavior documented.
- In the current compose smoke, `ollama` is still part of the booted container set because `open-webui` depends on it; that dependency does not change the Stage B service contract.
- Unit tests that validate compose shape, adapter contracts, and service-owned records are necessary but not sufficient to promote Stage B without the live topology smoke.

### Stage C: Add Stronger Isolation

Topology:

- web app account
- worker accounts
- optional leaf nodes by network boundary or deployment region

Use when:

- there are trust boundaries, multi-tenant concerns, or edge or remote deployments that should not share one flat subject space.

Official references:

- [Accounts](https://docs.nats.io/running-a-nats-service/configuration/securing_nats/accounts)
- [Leaf Nodes](https://docs.nats.io/running-a-nats-service/configuration/leafnodes)
- [JetStream Clustering](https://docs.nats.io/running-a-nats-service/configuration/clustering/jetstream_clustering)

## Capability Registration Model

Service-first modularity depends on capabilities joining the system at runtime rather than only through startup config. The registration model should be:

- Services announce themselves through the Services API where practical.
- The web tier or registry service materializes capability records into `owui_registry`.
- Routing metadata is stored in `owui_routing`.
- Feature toggles or rollout switches are stored in `owui_feature_flags`.
- Admin-managed access control remains in the application config and database layers.

This is intentionally similar to the current tool server and terminal server registry model in `backend/open_webui/utils/tools.py`, but it removes the assumption that all capabilities are known only at startup.

## What Changes First In A Service-First Build

The first services to extract should be:

1. `retrieval-worker`
2. `automation-runner`
3. `terminal-service`
4. `pipeline-runner`

The last service to extract should be:

- `tool-executor`, because `backend/open_webui/utils/plugin.py` and runtime dependency installation make that boundary more sensitive.

## Operational Risks And Required Mitigations

Lost Core NATS messages:

- Only use Core NATS for flows where loss is acceptable or where the caller retries naturally.
- Use JetStream for durable jobs and must-not-lose events.

Slow consumers:

- Keep hot user-visible streams off JetStream unless durability is required.
- Ensure the web tier does not subscribe to more traffic than it can fan out.

Duplicate JetStream delivery:

- Make retrieval and artifact jobs idempotent.
- Make automation and pipeline jobs idempotent wherever replay or retry is possible.
- Prefer immutable job IDs and explicit completion state in DB.

Unavailable responders:

- Preserve local fallback or compatibility paths for critical flows where feasible.
- Surface no-responder conditions clearly in logs and service health views.

Stale registry entries:

- Require heartbeats and freshness windows.
- Route only to healthy entries with recent `observed_at` timestamps.

Terminal ordering issues:

- Partition by `session_id`.
- Do not rely on queue-group randomness for ordered session control.

Worker crash during file processing or automation execution:

- Use durable consumers with explicit ack and bounded retry policy where durability is required.
- Ensure final status is reflected in DB even if a progress event is missed.

## Success Criteria

The service-first target is successful when:

- services can join and register capabilities without restart-only discovery
- the web tier no longer owns all background execution paths
- browser contracts stay stable through internal service extraction
- retrieval, automation, pipeline, and terminal service boundaries are clear and enforceable
- Redis and NATS responsibilities are distinct and not overlapping chaotically

## Final Position

The service-first path is viable for this repository, but it should still preserve three intentional boundaries:

- Redis remains for session and collaborative state initially
- browser-facing transport remains in the web tier initially
- dynamic plugin execution remains behind adapters until it can be isolated safely

That combination gives modularity without over-promising a full "everything on the bus" rewrite.
