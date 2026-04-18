# Autopilot Implementation Plan - NATS Migration

## Phase status

- Expansion: complete for this run
- Planning: complete for this slice
- Execution: next

## Immediate execution slice

1. Move retrieval transport-policy decisions into `submit_file_retrieval(...)` / helper code.
2. Remove router-level `LocalRetrievalTransport()` hardcoding from `knowledge.py`.
3. Preserve intentionally local inline maintenance behavior for knowledge reindex by expressing that policy in the submission boundary.
4. Keep the app-selected transport as the default for normal retrieval submissions.
5. Preserve retrieval job persistence and queued/started/completed/failed event contracts.

## Follow-on slice after this one

1. Add a dedicated retrieval-worker entrypoint / runtime mode so JetStream workers can run outside the web lifespan.
2. Update compose/runtime docs to support web + worker topology.
3. Keep service extraction rollback-safe by preserving local fallback.

## QA floor for the current slice

- `python -m compileall backend/open_webui`
- targeted pytest for:
  - `backend/open_webui/test/util/test_retrieval_submission.py`
  - `backend/open_webui/test/util/test_knowledge_retrieval_submission.py`
  - `backend/open_webui/test/util/test_retrieval_transport.py`
- no frontend verification required unless frontend files change

## Validation floor for the current slice

- architect review on boundary shape and future extraction readiness
- code review on regression risk and cohesion
- security review focused on config and transport-policy surfaces
