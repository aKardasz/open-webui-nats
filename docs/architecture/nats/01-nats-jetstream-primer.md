# NATS / JetStream Primer For Open WebUI

This primer covers the NATS and JetStream features that matter most for this repository. It is intentionally scoped to the current codebase rather than serving as a general NATS tutorial.

## Core NATS Request/Reply

Core NATS request/reply is the best fit for low-latency internal RPC where the caller wants an immediate answer and durable replay is not required. In this repo, that maps well to service discovery, capability lookup, fast terminal control calls, and synchronous internal pipeline or tool routing.

Official references:

- [Request/Reply](https://docs.nats.io/nats-concepts/core-nats/reqreply)
- [Building Services](https://docs.nats.io/using-nats/developer/services)
- [Service Infrastructure](https://docs.nats.io/nats-concepts/service_infrastructure)

Why this matters here:

- `backend/open_webui/routers/pipelines.py` already calls remote filter endpoints synchronously.
- `backend/open_webui/routers/terminals.py` already proxies synchronous terminal lifecycle operations.
- `backend/open_webui/utils/tools.py` already resolves remote capabilities and server metadata before use.

## Queue Groups And Stateless Service Scale-Out

Core NATS queue groups let multiple service instances share work on the same subject so only one responder handles each message. This fits stateless, horizontally scaled responders where at-most-once delivery is acceptable and replay is unnecessary.

Official references:

- [Queue Subscriptions / Queue Groups](https://docs.nats.io/nats-concepts/core-nats/queue)
- [Request/Reply](https://docs.nats.io/nats-concepts/core-nats/reqreply)

Why this matters here:

- Internal services such as `pipeline-runner`, `tool-executor`, and `terminal` can scale behind a shared subject without changing callers.
- This is a cleaner fit for live control paths than trying to persist every internal request in JetStream.

## NATS Services API

The Services API gives a standardized way for services to expose metadata, health, and stats. It is useful when services should be able to register themselves as capabilities instead of being known only through static startup configuration.

Official references:

- [Building Services](https://docs.nats.io/using-nats/developer/services)
- [Service Infrastructure](https://docs.nats.io/nats-concepts/service_infrastructure)

Why this matters here:

- `backend/open_webui/utils/tools.py` and `backend/open_webui/routers/terminals.py` already rely on registry-style discovery for tool servers and terminal servers.
- A future NATS-backed registry can reuse the same conceptual model while allowing workers and capability providers to join dynamically.

## JetStream Streams And Consumers

JetStream adds durability, replay, consumer state, redelivery, and backpressure controls. Streams should be used for durable event logs and retryable work. Consumers should be durable for important jobs and configured explicitly for ack policy, delivery attempts, and flow control.

Official references:

- [JetStream Overview](https://docs.nats.io/nats-concepts/jetstream)
- [Streams](https://docs.nats.io/nats-concepts/jetstream/streams)
- [Consumers](https://docs.nats.io/nats-concepts/jetstream/consumers)
- [JetStream Model Deep Dive](https://docs.nats.io/using-nats/developer/develop_jetstream/model_deep_dive)

Why this matters here:

- `backend/open_webui/routers/files.py` currently starts file processing in FastAPI background tasks.
- `backend/open_webui/routers/retrieval.py` and `backend/open_webui/routers/knowledge.py` perform durable, retry-worthy work such as extraction, chunking, transcription, embedding, and indexing.
- `backend/open_webui/tasks.py` already models distributed task control, but it relies on Redis pub/sub and in-memory task ownership rather than durable job semantics.

## JetStream KV

JetStream Key/Value is a good fit for coordination and shared cluster state that benefits from watches, revision checks, and lightweight compare-and-set semantics. It is not a replacement for the application database.

Official references:

- [Key/Value Store Concepts](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
- [KV Developer Guide](https://docs.nats.io/using-nats/developer/develop_jetstream/kv)

Why this matters here:

- `backend/open_webui/utils/tools.py` currently caches tool server and terminal server metadata in Redis.
- A future NATS-aware control plane will need registry entries, worker heartbeats, routing hints, and feature flags that multiple instances can observe consistently.
- The relational DB should remain the source of truth for users, chats, files, skills, and other application entities.

## JetStream Object Store

JetStream Object Store is appropriate for moving moderately large blobs through the NATS control plane when pairing metadata and artifact transfer is helpful. It should stay optional and should not replace the main storage provider.

Official references:

- [Object Store Concepts](https://docs.nats.io/nats-concepts/jetstream/obj_store)
- [Object Store Developer Guide](https://docs.nats.io/using-nats/developer/develop_jetstream/object)

Why this matters here:

- `backend/open_webui/storage/provider.py` already provides the primary file storage abstraction.
- Object Store is only compelling for inter-service artifact handoff, such as generated bundles, notebook exports, or temporary pipeline artifacts that are awkward to move through existing APIs.

## Subject Mapping And Partitioning

Subjects are the long-lived contract surface of a NATS-based architecture. Subject mapping and careful subject design matter for routing, versioning, partitioning, canaries, and preserving order where needed.

Official references:

- [Subject Mapping](https://docs.nats.io/nats-concepts/subject_mapping)

Why this matters here:

- Terminal session lifecycle and job progress events need ordering per session or per resource, not global ordering.
- A subject scheme such as `owui.evt.terminal.session.<session_id>.status` or `owui.evt.retrieval.job.<job_id>.progress` lets the system partition safely without pretending queue groups preserve order.

## Accounts, Leaf Nodes, And Future Topology

Accounts and leaf nodes matter when the architecture grows beyond a single deployment boundary. Accounts are useful for controlled multi-tenant isolation or domain separation. Leaf nodes are useful when services live in different clusters, networks, or edge locations.

Official references:

- [Accounts](https://docs.nats.io/running-a-nats-service/configuration/securing_nats/accounts)
- [Leaf Nodes](https://docs.nats.io/running-a-nats-service/configuration/leafnodes)
- [JetStream Clustering](https://docs.nats.io/running-a-nats-service/configuration/clustering/jetstream_clustering)

Why this matters here:

- `docker-compose.yaml` shows a mostly single-container deployment today, but the target direction includes moving terminals, pipelines, and workers into separate services.
- These features are not needed for the first retrofit milestone, but they are the clean path for later cross-container or multi-cluster decomposition.

## Slow Consumers, Reconnects, And Operational Guardrails

Core NATS favors fast consumers and will protect the system from slow consumers. JetStream adds durability but still needs careful consumer sizing and retry policies. Clients should also handle reconnects intentionally.

Official references:

- [Slow Consumers](https://docs.nats.io/running-a-nats-service/nats_admin/slow_consumers)
- [Automatic Reconnections](https://docs.nats.io/using-nats/developer/connecting/reconnect)
- [JetStream Resource Management](https://docs.nats.io/running-a-nats-service/configuration/resource_management)

Why this matters here:

- `backend/open_webui/socket/main.py` and `backend/open_webui/utils/chat.py` already manage live, user-visible streams where latency and backpressure matter.
- High-frequency browser-facing traffic should remain on HTTP/WebSocket edges at first, with NATS used for domain events and internal control paths rather than raw token or terminal byte streaming.

## Recommended Default Split For This Repo

The recommended default split is:

- Core NATS for fast service RPC, control messages, and live internal fanout.
- JetStream for durable background jobs and replayable domain events.
- JetStream KV for registry and orchestration state.
- Object Store only for optional artifact transfer.
- Redis remains in place initially for session storage, Socket.IO clustering, and Yjs or CRDT-related coordination.

Why this matters here:

- It matches the current architecture instead of forcing a rewrite.
- It creates a migration path from the existing monolith to a more modular system without moving every request path or stream onto the bus on day one.
