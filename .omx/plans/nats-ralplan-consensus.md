# NATS Ralplan Consensus Plan

## Scope

- Branch assessed: `nats-refactor`
- Primary roadmap sources:
  - `docs/architecture/nats/04-phased-retrofit-roadmap.md`
  - `docs/architecture/nats/05-service-first-roadmap.md`
  - `docs/architecture/nats/06-implemented-state-and-next-steps.md`
- Primary code touchpoints reviewed:
  - `backend/open_webui/env.py`
  - `backend/open_webui/main.py`
  - `backend/open_webui/utils/task_messaging.py`
  - `backend/open_webui/utils/retrieval_transport.py`
  - `backend/open_webui/utils/retrieval_worker.py`
  - `backend/open_webui/utils/runtime_registry.py`
  - `backend/open_webui/utils/tools.py`
  - `backend/open_webui/routers/configs.py`
  - `backend/open_webui/routers/pipelines.py`
  - `docker-compose.nats.yaml`

## Current State

### 04 roadmap status

- Phase 1 `Messaging abstraction inside the monolith`: `COMPLETE`
  - Evidence: NATS/transport env toggles exist in `backend/open_webui/env.py:444`-`458`; startup wires task messaging listener and retrieval transport in `backend/open_webui/main.py:647`-`658` and `backend/open_webui/main.py:758`; task control supports Redis/NATS coexistence in `backend/open_webui/utils/task_messaging.py:198`-`245`.
- Phase 2 `Durable background work on JetStream`: `MOSTLY COMPLETE`
  - Evidence: dedicated JetStream submission boundary exists in `backend/open_webui/utils/retrieval_transport.py:90`-`179`; durable worker stream/consumer behavior exists in `backend/open_webui/utils/retrieval_worker.py:13`-`22`, `backend/open_webui/utils/retrieval_worker.py:160`-`280`; worker-only deployment shape exists in `docker-compose.nats.yaml`.
  - Remaining to fully close the phase: complete environment-stable verification for retrieval/worker tests, tighten progress/event contracts, and prove rollback and restart behavior with repeatable checks rather than doc-only claims.
- Phase 3 `Externalize selected services`: `PARTIAL / PRE-STAGE`
  - Evidence: runtime registry buckets/materialization exist in `backend/open_webui/utils/runtime_registry.py:10`-`13`, `173`-`219`; tool and terminal metadata is synchronized and annotated in `backend/open_webui/utils/tools.py:800`-`833` and `894`-`985`; admin runtime registry endpoint exists in `backend/open_webui/routers/configs.py:249`-`265`.
  - Remaining: heartbeat refresh semantics, registry-driven routing, terminal service extraction, pipeline-runner extraction, optional artifact-worker, later tool-executor isolation.

### 05 roadmap status

- Stage A `web + nats + retrieval-worker`: `MOSTLY COMPLETE`
  - Evidence: the repo already runs the intended topology in `docker-compose.nats.yaml`; retrieval worker ownership is real, not scaffold-only.
  - Gap to close: Stage A is not fully proven until retrieval verification is repeatable in this repo environment and operational checks cover restart/redelivery/idempotent outcomes.
- Stage B `+ terminal + pipeline-runner`: `PARTIAL PREPARATION ONLY`
  - Evidence: registry materialization and terminal metadata surfacing exist, but routing still follows config and pipelines still instantiate `HttpPipelineAdapter` directly in `backend/open_webui/routers/pipelines.py:58`-`256`.
  - Missing: registry-driven routing, terminal service ownership, NATS request/reply pipeline path, JetStream long-running pipeline stages.
- Stage C `stronger isolation`: `NOT STARTED`
  - Missing: accounts, leaf nodes, or equivalent trust-boundary isolation; this remains deliberately deferred by the docs.

### Concise assessment

- The branch is past foundation work and has reached a real `Phase 2 / Stage A` posture for retrieval.
- The repo is not yet in genuine `Stage B`; it has only the enabling seams for Stage B.
- The next correct move is to finish and prove `Phase 2 / Stage A` completely before extracting terminal or pipeline services.

## Phased Plan

### Continuation rule

- Execute the plan phase by phase without treating `Stage A complete` or `Stage B runnable` as the end of the program.
- A phase is complete only when its acceptance criteria and verification checkpoints are both satisfied.
- Do not start a downstream phase on partial evidence from an upstream phase unless the plan explicitly says the work can overlap safely.
- Continue through all listed phases until:
  - `Phase 1` through `Phase 6` are complete, and
  - `Stage A`, `Stage B`, and `Stage C` outcomes are either implemented or explicitly superseded by a newer accepted roadmap decision.

### Global done definition

The NATS roadmap is complete only when all of the following are true:

- `Phase 1` is complete and `Stage A` is proven, repeatable, and rollback-safe.
- `Phase 2`, `Phase 3`, and `Phase 4` are complete and the registry/routing/pipeline contracts are stable enough to support service extraction without executor guesswork.
- `Phase 5` is complete and `Stage B` runs as a documented, testable topology with dynamic registration plus fallback behavior.
- `Phase 6` is complete and the remaining documented work is closed:
  - `artifact-worker`
  - `tool-executor` extraction behind a safer boundary
  - stronger isolation with NATS accounts or leaf nodes where the roadmap still calls for it
- The repository documentation is updated so the implemented state, target architecture, and service-first roadmap no longer contradict the codebase.
- Verification evidence exists for unit, integration, topology, rollback, and failure-path behavior across the final supported deployment shapes.

### Phase 1: Close Phase 2 / Stage A completely

Goal:
- Convert the current retrieval implementation from "working branch state" to "closed and repeatably verified roadmap milestone."

Primary work:
- Unblock repo-local verification for `retrieval_transport`, `retrieval_worker`, and terminal-eventing tests by standardizing pytest/bootstrap env overrides for `DATA_DIR` and `DATABASE_URL`.
- Immediate chosen approach:
  - run the retrieval-focused test slice with explicit test-only env overrides pointing at a repo-local temp path or pytest temp path
  - do not make `env.py` default-path changes a prerequisite for NATS roadmap completion
  - if default-path cleanup is still desirable, track it later as a separate cleanup task
- Expand retrieval-focused tests around restart tolerance, local fallback, duplicate delivery handling, and progress/state projection.
- Make the retrieval contract explicit:
  - the canonical durable contract is the signed retrieval job envelope from `retrieval_jobs.py`
  - required fields are at least `job_id`, `payload_version`, `reply_to`, actor/resource identifiers, and `payload`
  - generic retrieval subjects from `task_messaging.py` remain informational fanout only
  - authoritative end-state comes from DB projection in `file.data.retrieval_job` and `GET /files/{id}/process/status`
- Document the exact supported NATS-enabled Stage A deployment and rollback path around `open-webui + nats + retrieval-worker`.

Likely touchpoints:
- `backend/open_webui/test/util/test_retrieval_transport.py`
- `backend/open_webui/test/util/test_retrieval_worker.py`
- `backend/open_webui/test/util/test_terminal_eventing*.py`
- retrieval execution/submission helpers
- `docs/architecture/nats/06-implemented-state-and-next-steps.md`
- deployment or test setup docs

Acceptance criteria:
- Retrieval tests run in-repo without the current SQLite-path blocker by using explicit test env overrides such as:
  - `DATA_DIR=<repo>\\.tmp\\nats-test-data`
  - `DATABASE_URL=sqlite:///<repo>/.tmp/nats-test-data/webui.db`
- Restart/redelivery behavior is covered by automated tests or deterministic integration checks.
- Stage A rollback path remains intact: local retrieval fallback, Redis task control fallback, unchanged browser contracts.
- `06-implemented-state-and-next-steps.md` can honestly be updated from "real Stage A-style topology" to "Stage A complete."

Verification checkpoints:
- Focused pytest commands:
  - PowerShell:
    - `New-Item -ItemType Directory -Force -Path 'C:\\dev\\NatsWebUI\\open-webui-nats\\.tmp\\nats-test-data' | Out-Null`
    - `$env:DATA_DIR='C:\\dev\\NatsWebUI\\open-webui-nats\\.tmp\\nats-test-data'`
    - `$env:DATABASE_URL='sqlite:///C:/dev/NatsWebUI/open-webui-nats/.tmp/nats-test-data/webui.db'`
    - `C:\\dev\\NatsWebUI\\open-webui-nats\\.venv\\Scripts\\python.exe -m pytest backend/open_webui/test/util/test_task_messaging.py backend/open_webui/test/util/test_runtime_registry.py backend/open_webui/test/util/test_pipeline_adapter.py backend/open_webui/test/util/test_retrieval_transport.py backend/open_webui/test/util/test_retrieval_worker.py backend/open_webui/test/util/test_terminal_eventing.py`
- Compose-based smoke run with `open-webui`, `nats`, and `retrieval-worker` showing job queue, consume, completion, and worker restart recovery.
- Exact proofs:
  - submit a retrieval job, restart `retrieval-worker`, and confirm the job completes or redelivers without losing DB status
  - verify `GET /files/{id}/process/status` still returns the projected `retrieval_job` metadata after worker restart
  - verify local fallback still completes when JetStream publish fails or `NATS_URL` is absent

Exit gate to Phase 2:
- `Stage A` is not just runnable but proven with repeatable repo-local verification and documented rollback behavior.

### Phase 2: Add heartbeat-backed registry freshness and advisory routing

Goal:
- Turn registry materialization from a snapshot cache into a freshness-aware runtime contract without making routing correctness depend on it yet.

Primary work:
- Add heartbeat refresh semantics and make registry authority explicit before any service-owned routing depends on it.
- Choose this ownership model:
  - heartbeat-owned instance keys live under an instance-scoped namespace such as `service/<service_type>/<service_id>/<instance_id>`
  - web-owned snapshots/materialized views live in a distinct namespace or derived KV
  - the web tier must not delete or rewrite heartbeat-owned instance keys
  - `owui_routing` may be a derived materialized view, but only derived keys may be rewritten or deleted by the web tier
- Separate "configured", "registered", "fresh", "healthy", and "route-eligible" states in runtime records and derived views.
- Keep admin/config routing rules authoritative, but use registry freshness to annotate and gate advisory selection candidates.
- Surface stale/healthy registry state clearly via `/runtime_registry`.

Likely touchpoints:
- `backend/open_webui/utils/runtime_registry.py`
- `backend/open_webui/utils/tools.py`
- `backend/open_webui/routers/configs.py`
- any terminal/tool runtime metadata models or cache helpers
- `docs/architecture/nats/06-implemented-state-and-next-steps.md`

Acceptance criteria:
- Registry entries age out based on heartbeat freshness rather than cache timing alone.
- Heartbeat-owned keys and web-owned derived keys cannot conflict by namespace or deletion semantics.
- Tool and terminal records expose enough state to distinguish configured, registered, fresh, and stale endpoints.
- No browser-facing path breaks when registry data is missing or stale.
- Existing config-driven behavior remains the fallback path.

Verification checkpoints:
- Unit tests for heartbeat refresh, expiry, and stale-record filtering.
- Unit tests proving the web tier only rewrites derived keys and never deletes heartbeat-owned keys.
- Admin endpoint verification for healthy vs stale records.
- Failure simulation where a service stops heartbeating and becomes non-eligible without breaking current fallback behavior.

Exit gate to Phase 3:
- Registry authority, freshness, and derived-view rules are stable enough that terminal routing can consume them without redefining the contract.

### Phase 3: Use registry data in terminal routing without full service extraction

Goal:
- Prove registry-driven selection on a bounded path before extracting the terminal service boundary.

Primary work:
- Introduce terminal selection logic that can prefer fresh runtime candidates while preserving current configured fallback behavior.
- Keep raw browser terminal transport at the web edge.
- Route only lifecycle/control decisions through the registry-aware selection layer; do not move websocket transport.
- Record routing decisions and fallback reasons for observability.

Likely touchpoints:
- terminal routing code around `backend/open_webui/routers/terminals.py`
- `backend/open_webui/utils/tools.py`
- `backend/open_webui/utils/runtime_registry.py`
- terminal-related tests and docs

Acceptance criteria:
- Terminal lifecycle decisions can use registry freshness when suitable candidates exist.
- Stale or absent registry entries fall back to the existing config path.
- Browser websocket/auth/session behavior is unchanged.

Verification checkpoints:
- Tests covering candidate selection, stale-entry fallback, and config fallback.
- Smoke verification that terminal metadata still appears in admin surfaces and routing remains deterministic for a target session.

Exit gate to Phase 4:
- Terminal lifecycle routing is registry-aware with safe fallback, while raw browser WebSocket transport remains unchanged.

### Phase 4: Complete pipeline transport extraction before pipeline-runner service extraction

Goal:
- Replace the hardcoded HTTP-only pipeline path with a transport boundary that can host both existing HTTP compatibility and internal NATS execution.

Primary work:
- Refactor `backend/open_webui/routers/pipelines.py` to depend on an adapter factory or transport boundary rather than constructing `HttpPipelineAdapter` directly.
- Preserve current HTTP compatibility as the default implementation.
- Add a Core NATS request/reply path for fast internal pipeline stages.
- Add a JetStream path for long-running or retryable pipeline stages.
- Keep admin/browser contracts unchanged.

Likely touchpoints:
- `backend/open_webui/routers/pipelines.py`
- `backend/open_webui/utils/pipeline_adapter.py`
- new internal pipeline transport abstractions and tests
- roadmap docs 05 and 06

Acceptance criteria:
- Pipeline endpoints no longer hardcode `HttpPipelineAdapter`.
- HTTP remains supported as a compatibility transport.
- At least one internal pipeline path can execute over Core NATS request/reply.
- Long-running pipeline work has a durable JetStream lane where required.

Verification checkpoints:
- Adapter-level unit tests for HTTP, request/reply, and durable-stage behavior.
- Route-level tests proving unchanged HTTP API behavior.
- Failure-path tests for no-responder, timeout, and durable retry conditions.

Exit gate to Phase 5:
- The pipeline contract is transport-agnostic and supports both current HTTP compatibility and internal NATS execution modes.

### Phase 5: Promote to Stage B with narrow service extraction

Goal:
- Extract only the services already prepared by prior seams: terminal service and pipeline-runner.

Primary work:
- Stand up a minimal terminal service boundary around lifecycle/registration/audit ownership only.
- Stand up a minimal pipeline-runner boundary around internal stage execution only.
- Require both services to register/heartbeat into the runtime registry.
- Keep the web tier as browser/auth/websocket edge and preserve Redis for session/socket/Yjs responsibilities.

Likely touchpoints:
- terminal lifecycle code
- pipeline execution code
- service entrypoints / compose overlays
- runtime registry and routing docs

Acceptance criteria:
- Stage B topology is runnable and documented.
- At least one terminal capability and one pipeline capability are dynamically discovered and routed without startup hardcoding.
- Removing either service leaves compatibility fallbacks intact.

Verification checkpoints:
- Compose topology smoke test for `web + nats + retrieval-worker + terminal + pipeline-runner`.
- Registration/heartbeat checks for both extracted services.
- Route verification showing registry-based selection and fallback on service removal.

Exit gate to Phase 6:
- `Stage B` is documented, repeatable, dynamically registered, and safe to operate with service removal fallback.

### Phase 6: Deferred post-Stage-B work

Goal:
- Finish the remaining documented roadmap work after `Stage B` is stable so the overall NATS program reaches a true completion state.

Primary work:
- `artifact-worker`
- `tool-executor` extraction behind a safer boundary
- stronger isolation with NATS accounts or leaf nodes

Acceptance criteria:
- Each extraction has a bounded contract and its own rollback path.
- Isolation changes are justified by a real trust-boundary or deployment need, not by architectural neatness alone.
- `Stage C` is complete when the selected isolation model is implemented, tested, and reflected in the roadmap docs.

Verification checkpoints:
- Service-specific tests and deployment proofs.
- Isolation validation only when accounts/leaf nodes are introduced.

Final exit gate:
- No remaining roadmap items are still marked transitional, deferred, or not yet implemented in the NATS architecture docs unless a newer accepted ADR explicitly replaces them.

## RALPLAN-DR

### Principles

1. Finish the currently proven milestone before widening scope.
2. Preserve browser contracts and Redis ownership for session/socket/Yjs concerns.
3. Prefer reversible transport seams before service extraction.
4. Make runtime discovery advisory first, and separate heartbeat-owned keys from web-owned derived views before any routing depends on it.
5. Do not add dependencies unless an existing documented step truly requires them.

### Decision Drivers

1. Close `Phase 2 / Stage A` with repeatable verification before claiming `Stage B`.
2. Reduce rollout risk by preserving HTTP/browser compatibility, DB-projected retrieval status, and config fallbacks while introducing routing/service seams.
3. Keep service boundaries aligned to the documented target architecture rather than extracting ad hoc pieces.

### Viable Options

#### Option A: Finish Stage A completely, then begin bounded Stage B extraction

Pros:
- Best fit to current repo maturity and roadmap language.
- Keeps verification and rollback simple.
- Prevents mixing retrieval hardening with terminal/pipeline extraction risk.

Cons:
- Delays visible Stage B milestones.
- Requires additional test/env work before new service ownership work begins.

#### Option B: Start Stage B extraction now while hardening retrieval in parallel

Pros:
- Faster path to multi-service topology demos.
- May expose shared routing abstractions earlier.

Cons:
- Higher chance of conflating retrieval defects with routing/service-extraction defects.
- Makes milestone reporting ambiguous because Phase 2 and Phase 3 remain open simultaneously.

#### Option C: Stop after retrieval and keep NATS limited to durable ingestion for now

Pros:
- Lowest execution risk.
- Delivers clear value without broader decomposition work.

Cons:
- Leaves roadmap objectives unfinished.
- Registry, terminal, and pipeline seams remain underused and could drift.

### Recommended option

- Choose `Option A`.

## ADR

### Decision

- Complete `Phase 2 / Stage A` as a verified milestone first using explicit test env overrides for `DATA_DIR` and `DATABASE_URL`, then progress into `Phase 3 / Stage B` through two bounded seams: namespaced registry-backed advisory routing and pipeline transport extraction.

### Drivers

- Retrieval is already the most mature extracted capability.
- The canonical retrieval source of truth is the signed job envelope plus DB projection, not generic event subjects.
- Terminal and pipeline seams exist but are not yet service-owned or routing-driven.
- The roadmap explicitly favors preserving browser contracts, Redis responsibilities, and rollback safety.

### Alternatives considered

- `Option B`: begin terminal and pipeline extraction immediately while retrieval hardening remains open.
- `Option C`: stop after retrieval and defer broader service-first work indefinitely.

### Why chosen

- It matches the actual implementation maturity on `nats-refactor`.
- It creates a clean definition of done for the current milestone.
- It lowers the risk of misattributing failures across retrieval, routing, and new services.
- It avoids turning `env.py` cleanup or registry key ownership ambiguity into blockers for NATS completion.
- It keeps the repo aligned to both roadmap documents without introducing new architectural commitments.

### Consequences

- Near-term effort goes into verification, heartbeat semantics, and bounded routing before more service binaries appear.
- Terminal and pipeline extraction will start later, but with better contracts and lower coupling risk.
- Redis remains intentionally in place for session/socket/Yjs responsibilities.

### Follow-ups

1. Resolve the repo-local blocked test environment for retrieval-related suites with explicit `DATA_DIR` and `DATABASE_URL` overrides in pytest/bootstrap.
2. Add heartbeat/freshness semantics and namespace ownership rules to the runtime registry.
3. Introduce registry-aware terminal selection with fallback.
4. Refactor pipeline routing to a transport boundary, then add NATS execution paths.
5. Promote Stage B only after those checks pass.

## Risks

- The biggest near-term risk is false confidence from doc claims that exceed repeatable repo-local verification.
- Registry-driven routing introduced too early could create split-brain behavior between config truth and runtime truth.
- Pipeline extraction before adapter decoupling would harden the current HTTP assumptions instead of replacing them.

## Final Position

- Status today: `Phase 1 complete`, `Phase 2 mostly complete`, `Phase 3 partial`, `Stage A mostly complete`, `Stage B preparatory only`, `Stage C not started`.
- Recommended path: finish `Phase 2 / Stage A` completely, then move into registry-backed routing and pipeline transport extraction, then promote to a narrow `Stage B`.
