# Context Snapshot — NATS Migration

- **Task statement:** Plan and execute a staged migration of internal control-plane and durable background work from the current Redis/local model toward Core NATS, JetStream, and JetStream KV using worktrees and small reviewable commits.
- **Desired outcome:** A concrete, staged branch/worktree/commit plan plus the first implementation lane grounded in repo reality, with rollback-safe sequencing and verification checkpoints.

## Known facts / evidence

- NATS architecture docs exist under `docs/architecture/nats/`.
- Current branch is `main`; current worktree list contains only the primary checkout.
- Untracked local state exists under `.omx/`; it should not be committed.
- `docs/architecture/` is currently untracked and should likely be committed as a docs-only first step.
- `backend/open_webui/main.py` owns startup/lifespan wiring, Redis initialization, and startup cache warming.
- `backend/open_webui/tasks.py` currently mixes local task runtime, Redis metadata storage, and Redis pub/sub stop signaling.
- `backend/open_webui/routers/files.py` uses `BackgroundTasks` for file processing.
- `backend/open_webui/routers/retrieval.py` and `backend/open_webui/routers/knowledge.py` own durable/retry-worthy ingestion and indexing flows.
- `backend/open_webui/routers/terminals.py` proxies HTTP/WebSocket terminal traffic and should keep raw transport local in early phases.
- `backend/open_webui/utils/tools.py` caches tool/terminal capability data in app state and Redis.
- `backend/open_webui/socket/main.py` and `backend/open_webui/utils/chat.py` are hot browser-facing paths that should remain local initially.

## Constraints

- Preserve browser contracts and current Redis-backed session/websocket/Yjs behavior in early phases.
- Use small, reviewable, rollback-safe commits.
- Follow Lore commit protocol for commit messages.
- Ralph planning gate requires canonical PRD and test-spec artifacts before implementation work.
- Avoid early parallelization across branches that all edit `backend/open_webui/main.py`.

## Unknowns / open questions

- Exact Python NATS client choice and configuration details.
- Whether retrieval jobs should first reuse file metadata as job state or add a dedicated job table immediately.
- Whether runtime registry materialization should initially live in the web tier or a later dedicated registry service.
- Availability and shape of targeted backend tests for new messaging abstractions.

## Likely codebase touchpoints

- `backend/open_webui/main.py`
- `backend/open_webui/env.py`
- `backend/open_webui/config.py`
- `backend/open_webui/tasks.py`
- `backend/open_webui/routers/files.py`
- `backend/open_webui/routers/retrieval.py`
- `backend/open_webui/routers/knowledge.py`
- `backend/open_webui/routers/terminals.py`
- `backend/open_webui/routers/pipelines.py`
- `backend/open_webui/utils/tools.py`
- `backend/open_webui/socket/main.py`
- `backend/open_webui/utils/chat.py`
- new `backend/open_webui/messaging/*`
