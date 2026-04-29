# Target Architecture And Contracts

This document defines the target NATS integration model for this repository. It standardizes the first subject namespace, service taxonomy, message envelopes, registry shape, and workload partitioning rules so later implementation work does not need to invent those decisions repeatedly.

## Target Architecture Summary

The target architecture is a hybrid:

- the web application remains the browser-facing edge for HTTP, WebSocket, Socket.IO, and existing auth and access control flows
- Core NATS becomes the internal low-latency RPC and control plane
- JetStream becomes the durable job and domain-event plane
- JetStream KV becomes the shared registry and orchestration-state plane
- Object Store remains optional and is used only when inter-service artifact transfer is genuinely easier than using the existing storage provider

Redis remains in place initially for session storage, Socket.IO clustering, and Yjs or CRDT-related coordination.

Official references:

- [Request/Reply](https://docs.nats.io/nats-concepts/core-nats/reqreply)
- [JetStream Overview](https://docs.nats.io/nats-concepts/jetstream)
- [KV](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
- [Object Store](https://docs.nats.io/nats-concepts/jetstream/obj_store)
- [Services](https://docs.nats.io/using-nats/developer/services)

## Service Taxonomy

The initial internal service identities are:

- `terminal-service`
- `pipeline-runner`
- `automation-runner`
- `retrieval-worker`
- `artifact-worker`
- `tool-executor`
- `registry`

These names should be treated as stable service-family identifiers even if multiple concrete implementations or versions exist.

Recommended responsibilities:

- `terminal-service`
  Owns terminal lifecycle control, terminal capability metadata, runtime registration, and future terminal fleet coordination. It does not replace browser WebSocket transport in v1.
- `pipeline-runner`
  Owns pipeline-stage execution that can run outside the web process. It supports fast RPC for synchronous internal filters and JetStream jobs for longer-running stages.
- `automation-runner`
  Owns manual automation run requests, due-schedule polling, automation execution lifecycle, and runtime registration when Open WebUI is in NATS-owned automation mode.
- `retrieval-worker`
  Owns file ingestion, OCR or transcription, chunking, embeddings, indexing, and retryable knowledge-processing jobs.
- `artifact-worker`
  Owns artifact generation, notebook exports, or bundle-producing work that is asynchronous and retriable.
- `tool-executor`
  Owns isolated or remote execution of risky or expensive tools when the plugin system is eventually adapted behind a service boundary.
- `registry`
  Owns service registration policy, KV-backed capability materialization, and optional health aggregation.

## Subject Namespace

The first standardized subject prefix is:

- `owui`

Command subjects use:

- `owui.cmd.<domain>.<action>`

Event subjects use:

- `owui.evt.<domain>.<event>`

Suggested initial domains:

- `task`
- `terminal`
- `pipeline`
- `automation`
- `retrieval`
- `artifact`
- `registry`
- `tool`
- `chat`

Examples:

- `owui.cmd.task.stop`
- `owui.cmd.pipeline.run`
- `owui.cmd.pipeline.stage.run`
- `owui.cmd.terminal.session.create`
- `owui.cmd.automation.run`
- `owui.evt.terminal.session.created`
- `owui.evt.retrieval.job.progress`
- `owui.evt.pipeline.completed`
- `owui.evt.automation.run.completed`
- `owui.evt.chat.tool_invoked`

Official references:

- [Subject Mapping](https://docs.nats.io/nats-concepts/subject_mapping)
- [Queue Groups](https://docs.nats.io/nats-concepts/core-nats/queue)

## Message Envelopes

### Job Envelope

All durable job submissions should use this envelope shape:

```json
{
  "job_id": "job_01HT0EXAMPLE",
  "tenant_id": null,
  "actor_id": "user_123",
  "resource_id": "file_456",
  "requested_at": "2026-04-15T20:00:00Z",
  "reply_to": "owui.evt.retrieval.job.job_01HT0EXAMPLE",
  "trace_id": "trace_789",
  "payload_version": "v1",
  "payload": {}
}
```

Field rules:

- `job_id`
  Required and globally unique.
- `tenant_id`
  Optional until tenancy requires it.
- `actor_id`
  Required for auditability when an actor exists.
- `resource_id`
  Required when the job is about a specific file, chat, session, artifact, or automation run.
- `requested_at`
  Required UTC timestamp.
- `reply_to`
  Required when progress or completion events are expected.
- `trace_id`
  Required for cross-service tracing when available.
- `payload_version`
  Required to allow contract evolution.
- `payload`
  Domain-specific body.

### Event Envelope

All published domain events should use this envelope shape:

```json
{
  "event_id": "evt_01HT0EXAMPLE",
  "event_type": "retrieval.job.progress",
  "occurred_at": "2026-04-15T20:00:05Z",
  "producer": "retrieval-worker",
  "resource_type": "file",
  "resource_id": "file_456",
  "trace_id": "trace_789",
  "data": {}
}
```

Field rules:

- `event_id`
  Required and unique for deduplication and observability.
- `event_type`
  Required, stable, and namespaced by domain.
- `occurred_at`
  Required UTC timestamp.
- `producer`
  Required service identity.
- `resource_type`
  Required when the event belongs to a domain entity.
- `resource_id`
  Required when `resource_type` is set.
- `trace_id`
  Required when available.
- `data`
  Domain-specific event body.

## Registry Metadata Shape

The registry should materialize a normalized service record in KV. Initial record shape:

```json
{
  "service_id": "terminal-service.default",
  "service_type": "terminal-service",
  "instance_id": "terminal-service-7f58b9d9d4-x2r9q",
  "version": "1.0.0",
  "status": "healthy",
  "subjects": [
    "owui.cmd.terminal.session.create",
    "owui.cmd.terminal.session.attach"
  ],
  "capabilities": {
    "terminal": true,
    "system_prompt": true
  },
  "routing": {
    "region": "local",
    "workspace_scope": "shared"
  },
  "observed_at": "2026-04-15T20:00:10Z"
}
```

This should not replace admin-managed access control or DB-backed configuration. It is a runtime capability view.

## KV And Object Store Names

The initial KV buckets are:

- `owui_registry`
- `owui_routing`
- `owui_feature_flags`

The initial Object Store bucket is:

- `owui_artifacts`

Official references:

- [KV Concepts](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
- [Object Store Concepts](https://docs.nats.io/nats-concepts/jetstream/obj_store)

## Partitioning And Ordering Rules

Queue groups do not guarantee ordered processing. Ordered workloads in this repo must therefore partition by session or resource key instead of relying on random worker selection.

Required partitioning rules:

- terminal session events partition by `session_id`
- retrieval progress events partition by `job_id`
- long-running pipeline progress events partition by `job_id`
- automation run progress or status events partition by `request_id` or `run_id`
- artifact build progress events partition by `job_id`
- if chat-scoped ordering is ever needed for non-token side effects, partition by `chat_id`

Example subject patterns:

- `owui.evt.terminal.session.<session_id>.status`
- `owui.evt.retrieval.job.<job_id>.progress`
- `owui.evt.pipeline.job.<job_id>.progress`
- `owui.evt.automation.run.<run_id>.status`

Official references:

- [Subject Mapping](https://docs.nats.io/nats-concepts/subject_mapping)
- [Queue Groups](https://docs.nats.io/nats-concepts/core-nats/queue)

## Contract Examples

### Example: File Ingestion Job Submission

Submission subject:

- `owui.cmd.retrieval.file_ingest`

Envelope:

```json
{
  "job_id": "job_file_123",
  "tenant_id": null,
  "actor_id": "user_42",
  "resource_id": "file_123",
  "requested_at": "2026-04-15T20:10:00Z",
  "reply_to": "owui.evt.retrieval.job.job_file_123",
  "trace_id": "trace_ingest_123",
  "payload_version": "v1",
  "payload": {
    "file_id": "file_123",
    "content_type": "application/pdf",
    "storage_path": "uploads/file_123.pdf"
  }
}
```
