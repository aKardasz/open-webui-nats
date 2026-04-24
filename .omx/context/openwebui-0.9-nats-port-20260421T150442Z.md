# Context Snapshot — OpenWebUI 0.9.x Port into NATS Fork

## Task statement
Port selected upstream Open WebUI 0.9.x features into `open-webui-nats`, working through all implementation slices while adapting runtime-owned features to the fork's NATS-first architecture.

## Desired outcome
A verified series of code changes that incrementally brings in upstream 0.9.x improvements without regressing the existing NATS control plane.

## Known facts / evidence
- Local fork baseline is upstream 0.8.12.
- Upstream main is 0.9.1 (major 0.9.0 feature drop on 2026-04-20).
- Local fork already has NATS seams for retrieval, pipeline runner, terminal service, task messaging, and runtime registry.
- Planning artifacts created:
  - `.omx/plans/prd-openwebui-0.9-nats-port.md`
  - `.omx/plans/test-spec-openwebui-0.9-nats-port.md`

## Constraints
- Preserve NATS as control-plane authority.
- Do not raw-merge upstream async backend/session refactor first.
- Keep changes sliceable, reviewable, and verifiable.
- No new dependencies beyond those required to align with upstream 0.9.x package metadata.

## Unknowns / open questions
- Exact amount of frontend conflict for chat/unread/task UI slices.
- Whether any local customizations rely on legacy shared-chat phantom rows beyond current router/model usage.
- Whether automation/calendar should ship with a transitional in-process scheduler before runner extraction.

## Likely codebase touchpoints
- `pyproject.toml`
- `backend/open_webui/models/chats.py`
- `backend/open_webui/routers/chats.py`
- `backend/open_webui/main.py`
- `backend/open_webui/models/notes.py` / note routes/components
- `backend/open_webui/migrations/versions/*`
- `src/lib/components/chat/*`
- `src/lib/components/layout/Sidebar.svelte`
