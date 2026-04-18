# Context Snapshot - NATS Migration

- **Task statement:** Continue executing the staged NATS migration plan in the existing `open-webui-nats` workspace using the work already completed across task control, lifecycle events, retrieval job identity, and retrieval submission centralization.
- **Desired outcome:** Push the current implementation from a local-only retrieval submission path to a transport-selectable design that keeps behavior stable now and makes a later JetStream submission backend a contained change.

## Known facts / evidence

- Existing migration docs live under `docs/architecture/nats/`.
- Canonical planning artifacts already exist:
  - `.omx/plans/prd-nats-migration.md`
  - `.omx/plans/test-spec-nats-migration.md`
- Phase 1 code already added:
  - optional NATS runtime config in `backend/open_webui/env.py`
  - task control messaging/runtime in `backend/open_webui/utils/task_messaging.py`
  - task stop transport refactor in `backend/open_webui/tasks.py`
  - terminal and retrieval lifecycle events
  - optional `docker-compose.nats.yaml`
- Phase 2 entry work already added:
  - retrieval job envelope helper in `backend/open_webui/utils/retrieval_jobs.py`
  - job persistence in `file.data.retrieval_job`
  - retrieval events keyed by `job_id`
  - retrieval submission helper and local transport boundary
- Retrieval submission is now centralized for:
  - file uploads
  - file content update
  - knowledge add/update
- Bulk knowledge reindex still calls `process_file(...)` directly and is intentionally left as an internal maintenance path for now.
- Targeted unit-test files were added for task messaging, retrieval jobs, retrieval submission, and retrieval transport, but the environment still lacks `pytest` and some runtime dependencies, so validation has been syntax-first.

## Constraints

- Preserve browser-facing HTTP/WebSocket contracts.
- Preserve Redis-backed session/socket/Yjs behavior.
- Keep diffs reviewable and rollback-safe.
- Do not force NATS/JetStream for correctness yet.
- Follow the staged migration ordering in `.omx/plans/prd-nats-migration.md`.
- Leave `.omx/` as local workflow state unless explicitly asked to commit it.

## Unknowns / open questions

- Exact transport selection config shape for retrieval submission (`local` vs `jetstream`).
- Whether the first JetStream transport step should be a stub/no-op placeholder or a real publish-only adapter.
- Whether retrieval job state should remain embedded in `file.data` through the first worker milestone or be lifted into a dedicated store.
- How much runtime validation is possible in this environment without installing missing Python dependencies.

## Likely codebase touchpoints

- `backend/open_webui/main.py`
- `backend/open_webui/env.py`
- `backend/open_webui/utils/retrieval_transport.py`
- `backend/open_webui/utils/retrieval_submission.py`
- `backend/open_webui/utils/retrieval_jobs.py`
- `backend/open_webui/routers/files.py`
- `backend/open_webui/routers/knowledge.py`
- `backend/open_webui/routers/retrieval.py`
- targeted backend tests under `backend/open_webui/test/util/`
