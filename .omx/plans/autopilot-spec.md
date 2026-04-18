# Autopilot Spec - NATS Migration

This run starts from the committed baseline in `3c1f85f269` and reuses the existing migration artifacts instead of re-expanding the architecture from scratch:

- `.omx/plans/prd-nats-migration.md`
- `.omx/plans/test-spec-nats-migration.md`
- `docs/architecture/nats/03-target-architecture-and-contracts.md`
- `docs/architecture/nats/04-phased-retrofit-roadmap.md`
- `docs/architecture/nats/05-service-first-roadmap.md`

## Current execution focus

Complete the remaining Phase 2 groundwork before service extraction by making retrieval transport policy authoritative at the submission boundary, then use that cleaner boundary to prepare retrieval worker extraction.

## Required outcomes

1. Retrieval submission remains centralized behind one helper.
2. Router code does not encode transport policy for normal user-facing retrieval paths.
3. Inline maintenance behavior that must remain local is captured intentionally at the submission boundary instead of via ad hoc router overrides.
4. The active app transport remains the default for normal retrieval submissions.
5. Existing retrieval job envelope and retrieval event semantics remain stable.
6. The next slice after this one can focus on worker extraction instead of reopening router transport logic.

## Non-goals for this slice

1. Do not introduce KV registry or runtime heartbeats yet.
2. Do not extract `pipeline-runner` or terminal services yet.
3. Do not replace Redis session, websocket, or Yjs behavior.
4. Do not make JetStream mandatory for correctness in this slice.
