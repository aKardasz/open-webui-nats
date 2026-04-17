# Implemented State And Next Steps

This document records what the `nats-refactor` branch currently implements relative to the NATS architecture documents and what still remains before the broader service-first target is complete.

## Current Implemented State

The branch now supports a real Stage A-style retrieval topology:

- browser-facing web tier remains in `backend/open_webui/main.py`
- NATS with JetStream can run alongside Redis
- retrieval work can be consumed by a dedicated `retrieval-worker` runtime

Implemented pieces:

- task-control messaging abstraction with Redis/NATS coexistence
- retrieval job envelope helpers with signatures
- retrieval transport boundary with inline-local enforcement
- durable retrieval publish/consume path over JetStream
- retrying retrieval worker startup
- dedicated `python -m open_webui retrieval-worker` worker-only mode
- coarse retrieval progress events
- DB-backed projection of retrieval progress into `file.data.retrieval_job`
- file process status endpoint returns retrieval job metadata
- initial KV runtime registry materialization into:
  - `owui_registry`
  - `owui_routing`
  - `owui_feature_flags`
- terminal cache snapshots include advisory runtime registration metadata
- pipeline filter/admin HTTP calls run through a shared adapter boundary

## Supported Deployment Shape

The branch supports this topology as the current recommended NATS-enabled shape:

1. `open-webui` web process
2. `nats` broker with JetStream
3. `retrieval-worker` process

Properties:

- browser HTTP/WebSocket contracts stay in the web tier
- retrieval worker owns durable background ingestion
- Redis remains in place for session/socket/Yjs responsibilities
- tool and terminal runtime capability state is additive and observational

## What Is Still Transitional

The branch is not yet at the full target architecture.

Still transitional:

- retrieval event fanout still uses generic subjects in addition to job-scoped envelope metadata
- runtime registry is advisory; routing does not yet depend on it
- terminal runtime metadata is visible to the web tier, but terminal routing still follows the existing config model
- pipeline execution still uses HTTP transport; the adapter boundary exists, but no NATS request/reply or durable-stage execution has been introduced

## Not Yet Implemented

The following remain outside the currently implemented scope:

- registry heartbeat refresh protocol beyond cache/materialization timing
- registry-driven routing selection for terminal or pipeline execution
- terminal service extraction
- pipeline-runner service extraction
- artifact-worker
- tool-executor extraction
- stronger isolation with NATS accounts or leaf nodes

## Rollback Position

The branch remains rollback-oriented.

Current rollback-safe properties:

- retrieval submission can still fall back to local execution
- task control can still fall back to Redis
- browser-facing contracts are unchanged
- terminal raw transport remains local/WebSocket-based
- pipeline external HTTP compatibility remains intact

## Verification Proven On Branch

The branch has evidence for:

- compile success on backend Python modules
- focused retrieval/runtime/registry/terminal/pipeline adapter unit tests
- compose overlay config validity
- live NATS retrieval job publish/consume
- live route-level background upload submission reaching the worker
- live worker-only boot and JetStream consumer registration
- live KV registry materialization into `owui_registry`

## Recommended Next Steps

Proceed in this order:

1. Add stronger service-health/heartbeat semantics for runtime registry entries.
2. Use runtime registry data in terminal and later pipeline routing decisions without removing existing fallback paths.
3. Introduce the next execution mode behind the pipeline adapter:
   - Core NATS request/reply for fast internal stages
   - JetStream for long-running or retryable stages
4. Document Stage B (`web + nats + retrieval-worker + terminal + pipeline-runner`) as implementation-ready only after the above is proven.

## Final Position

The branch is beyond foundation and beyond retrieval-only scaffolding. It now has a real durable retrieval runtime, a first registry materialization layer, terminal registration metadata surfacing, and a pipeline execution seam. What remains is to turn those seams into actual routing and service-ownership behavior without breaking the current browser edge.
