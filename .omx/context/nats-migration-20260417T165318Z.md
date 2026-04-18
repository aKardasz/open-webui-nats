# Context Snapshot - NATS Migration

- **Task statement:** Continue the NATS migration from the newly committed rollback-safe baseline on `nats-refactor`, starting with the remaining Phase 2 work before service extraction.
- **Desired outcome:** Preserve the current browser-facing behavior while making retrieval transport selection authoritative at the submission boundary, keeping inline maintenance flows intentionally local and preparing normal retrieval paths for JetStream-backed execution.

## Known facts / evidence

- Commit `3c1f85f269` established the current baseline:
  - NATS task-control abstraction
  - retrieval job envelope/helpers
  - retrieval submission and transport layers
  - JetStream retrieval publisher and embedded worker
  - terminal lifecycle events
  - NATS architecture docs and focused tests
- Focused verification is available and passing:
  - `uv run python -m pytest backend/open_webui/test/util/test_task_messaging.py backend/open_webui/test/util/test_retrieval_jobs.py backend/open_webui/test/util/test_retrieval_transport.py backend/open_webui/test/util/test_retrieval_worker.py backend/open_webui/test/util/test_retrieval_submission.py backend/open_webui/test/util/test_retrieval_execution.py backend/open_webui/test/util/test_retrieval_service.py backend/open_webui/test/util/test_terminal_eventing.py backend/open_webui/test/util/test_retrieval_route_process_file.py backend/open_webui/test/util/test_knowledge_retrieval_submission.py backend/open_webui/test/util/test_file_content_update_submission.py -q`
- `submit_file_retrieval(...)` is the central router-facing submission boundary.
- `knowledge.py` still hardcodes `LocalRetrievalTransport()` for bulk reindex, which preserves inline rebuild behavior but leaks transport policy into the router.
- The retrieval worker still starts inside the web-app lifespan; no dedicated worker entrypoint/service exists yet.
- Registry, KV heartbeats, and pipeline-runner contracts are still documentation-only.

## Constraints

- Preserve browser-facing HTTP/WebSocket contracts.
- Preserve Redis-backed session/socket/Yjs behavior.
- Keep changes small, reversible, and test-backed.
- Do not make NATS mandatory for correctness yet.
- Keep `.omx/` as local workflow state unless explicitly requested otherwise.

## Unknowns / open questions

- Which inline maintenance flows should remain permanently local versus become transport-selectable later.
- Whether the next slice after transport-policy cleanup should be dedicated worker entrypoint extraction or JetStream delivery hardening.
- How much startup/refactor work is required to run retrieval workers outside the web lifespan without duplicating app initialization.

## Likely codebase touchpoints

- `backend/open_webui/utils/retrieval_submission.py`
- `backend/open_webui/utils/retrieval_transport.py`
- `backend/open_webui/routers/knowledge.py`
- `backend/open_webui/test/util/test_retrieval_submission.py`
- `backend/open_webui/test/util/test_knowledge_retrieval_submission.py`
- `backend/open_webui/main.py`
- `backend/open_webui/utils/retrieval_worker.py`
