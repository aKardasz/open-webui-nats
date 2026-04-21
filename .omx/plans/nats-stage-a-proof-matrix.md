# NATS Stage A Proof Matrix

Goal: convert the current "Stage A-style" retrieval implementation into a milestone that is explicitly proven, repeatable, and ready to be marked complete in the roadmap docs.

Fresh evidence gathered on 2026-04-18:
- `./.venv/Scripts/python.exe -m pytest backend/open_webui/test/util/test_retrieval_execution.py backend/open_webui/test/util/test_retrieval_worker.py backend/open_webui/test/util/test_retrieval_transport.py -q` passed (`24 passed`)
- the retrieval-focused and broader NATS suites had already passed earlier in this session
- there is no shared backend test bootstrap/conftest currently preparing the runtime DB/data path for these retrieval suites

## Existing proof coverage

### Retrieval publish + fallback

Covered now:
- JetStream transport selection exists
- JetStream publish path is tested
- local fallback on publish failure is tested

Evidence:
- `backend/open_webui/test/util/test_retrieval_transport.py`
  - `test_build_retrieval_transport_returns_jetstream_transport`
  - `test_jetstream_transport_publishes_job_to_jetstream`
  - `test_jetstream_transport_falls_back_to_local_execution_when_publish_fails`

### Worker execution + retry loop behavior

Covered now:
- successful message ack
- failure path NAK
- invalid signature is acknowledged without execution
- worker startup retry behavior for transient and permanent failure
- fetch loop tolerates NATS timeout errors

Evidence:
- `backend/open_webui/test/util/test_retrieval_worker.py`
  - `test_worker_acks_messages_after_successful_execution`
  - `test_worker_naks_messages_after_execution_failure`
  - `test_worker_acks_invalidly_signed_messages_without_executing`
  - `test_start_retrieval_worker_with_retry_retries_transient_failures_until_started`
  - `test_start_retrieval_worker_with_retry_stops_on_permanent_failure`
  - `test_worker_run_ignores_nats_timeout_errors_between_fetches`

### Duplicate / idempotent execution behavior

Covered now:
- duplicate failed-event emission suppression at the execution boundary
- duplicate completed jobs are skipped

Evidence:
- `backend/open_webui/test/util/test_retrieval_execution.py`
  - `test_execute_retrieval_job_does_not_emit_duplicate_failed_event_after_process_file_boundary`
  - `test_execute_retrieval_job_skips_duplicate_completed_jobs`

## Remaining proof gaps

### 1. Repo-local bootstrap is still implicit

Observed gap:
- these tests require the repo-local runtime DB/data path to exist under the Windows venv path assumptions used from WSL
- the passing command path still depended on ensuring `backend/data/cache`, `backend/data/uploads`, and `backend/data/vector_db` existed
- no shared pytest bootstrap helper or backend `conftest.py` currently codifies that setup

Implication:
- Stage A proof is still partially operational knowledge rather than fully codified test bootstrap

Recommended closure:
- introduce a shared test bootstrap helper or documented wrapper command for the retrieval suites
- make the retrieval test command self-sufficient

### 2. Restart proof is still indirect

Covered partially:
- worker retry startup is tested
- duplicate/completion handling is tested

Still not explicitly proven:
- a retrieval job survives an actual worker restart with DB-projected status remaining coherent after restart/redelivery

Recommended closure:
- add a deterministic test or smoke flow that submits work, restarts or recreates the worker, then verifies final projected status

### 3. Docs have not yet been upgraded to "Stage A complete"

Observed gap:
- `docs/architecture/nats/06-implemented-state-and-next-steps.md` still frames the branch as a real `Stage A-style` topology and lists Stage B readiness as pending further proof

Recommended closure:
- update the doc only after the bootstrap and restart proof gaps are closed

## Minimum next execution slice

1. Codify retrieval-suite bootstrap so the test setup is not tribal knowledge.
2. Add one explicit restart/redelivery proof path tied to DB-projected status.
3. Then update `docs/architecture/nats/06-implemented-state-and-next-steps.md` to mark Stage A complete.
