# PRD — OpenWebUI 0.9.x Follow-up: NATS Ownership and Async DB Migration

Date: 2026-04-24
Companion implementation plan: `.omx/plans/openwebui-0.9-followup-nats-async-plan.md`

## Goal
Complete the remaining architectural work after the 0.9.x feature-slice port by:
1. moving automation/calendar runtime-owned behavior behind NATS-compatible service ownership, and
2. introducing an incremental async DB/session migration path for the ported slices.

## Product requirements
- The web tier must stop being the primary automation execution owner in NATS mode.
- Automation execution must be observable through explicit runtime contracts and registry metadata.
- Calendar scheduled-task views must remain accurate after runner extraction.
- Existing chat task stop/read/share behavior must not regress.
- Async DB migration must proceed in vertical slices, starting with automations/calendar.

## Non-goals
- Raw upstream async DB/session rebase.
- One-shot conversion of all legacy DB helpers.
- Reworking already-stable chat features unless required for regression fixes.

## Acceptance criteria
- API routes enqueue/request automation execution instead of directly running it in-process.
- Embedded automation scheduler can be disabled in favor of a dedicated runner lane.
- Automation-runner exposes first-class runtime-registry metadata and command subjects.
- Calendar scheduled-task projection uses durable automation state/run history.
- Async engine/session scaffolding exists beside the current sync DB path.
- At least one async vertical slice is implemented without breaking current verification gates.
