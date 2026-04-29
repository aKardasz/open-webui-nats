# Stage B Smoke Runbook

This runbook is the promotion gate for the transitional Stage B NATS topology. Unit tests prove compose shape and service contracts, but Stage B is not considered supported until this live smoke passes in the target environment.

## Topology Under Test

The smoke uses the merged compose topology from:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml
```

Expected Stage B services:

- `nats`
- `open-webui`
- `retrieval-worker`
- `automation-runner`
- `terminal-service`
- `pipeline-runner`

Current compose dependency note:

- `ollama` still boots from the base compose file because `open-webui` currently depends on it in this repo's local smoke environment. It is not part of the Stage B NATS service contract itself, but it will appear in `ps` output.

Expected NATS overlay behavior:

- `open-webui` has `NATS_URL=nats://nats:4222`
- `open-webui` disables embedded retrieval, automation, terminal, and pipeline workers
- `retrieval-worker` runs `python -m open_webui retrieval-worker`
- `automation-runner` runs `python -m open_webui automation-runner`
- `terminal-service` runs `python -m open_webui terminal-service`
- `pipeline-runner` runs `python -m open_webui pipeline-runner`

## Prerequisites

- Docker with Compose v2, either as `docker compose` or `docker-compose`.
- For branch validation, build the local image with `--build`; pulling `ghcr.io/open-webui/open-webui:${WEBUI_DOCKER_TAG-main}` can miss branch-only entrypoints such as `python -m open_webui retrieval-worker`.
- The NATS overlay defaults `NATS_SMOKE_USE_SLIM=true` for local smoke builds so branch validation does not spend time downloading optional model weights. Set `NATS_SMOKE_USE_SLIM=false` only when intentionally validating a full production-style image.
- The NATS overlay defaults `WEBUI_SECRET_KEY=nats-smoke-secret` so worker-only services can import the app in authenticated mode during local smoke tests. Override it with a real shared secret for non-local environments.
- Ports are available:
  - `${OPEN_WEBUI_PORT-3000}` for Open WebUI
  - `${NATS_PORT-4222}` for NATS clients
  - `${NATS_MONITOR_PORT-8222}` for NATS monitoring

The commands below use `docker-compose` because this WSL/Rancher Desktop environment exposes Compose that way. Replace it with `docker compose` if your environment uses the plugin form. When running from WSL with Docker Desktop, the Windows Docker CLI may be required, for example `/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe compose ...`.

## 1. Validate Merged Compose Shape

```bash
cd /mnt/c/dev/NatsWebUI/open-webui-nats
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml config --services
```

Expected output includes at least:

```text
nats
ollama
open-webui
automation-runner
pipeline-runner
retrieval-worker
terminal-service
```

Optional detail check:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml config > .tmp/nats-stage-b-compose.yaml
```

Confirm in the rendered config that `open-webui` disables embedded services and the four extracted runtimes have the expected worker-only environment variables.

## 2. Boot The Topology

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d --build \
  nats ollama open-webui retrieval-worker automation-runner terminal-service pipeline-runner
```

Wait for services to settle:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml ps
curl -fsS "http://127.0.0.1:${NATS_MONITOR_PORT:-8222}/healthz"
curl -fsS "http://127.0.0.1:${OPEN_WEBUI_PORT:-3000}/health"
```

Passing condition:

- NATS health endpoint returns success.
- Open WebUI `/health` returns success.
- `retrieval-worker`, `automation-runner`, `terminal-service`, and `pipeline-runner` containers remain running instead of crash-looping.
- The worker-only services start after `open-webui` is healthy so database migrations are not raced by multiple containers on a fresh volume.

## 3. Check Extracted Runtime Startup Evidence

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml logs --tail=200 retrieval-worker automation-runner terminal-service pipeline-runner
```

Passing condition:

- `retrieval-worker` starts in worker-only mode and connects to NATS/JetStream.
- `automation-runner` starts in automation-runner-only mode, subscribes to the configured automation request subject, and owns due-run scheduling.
- `terminal-service` starts in terminal-service-only mode and registers service-owned runtime records.
- `pipeline-runner` starts in pipeline-runner-only mode and subscribes to the configured request/reply subject plus durable stage lane.

## 4. Check Registry Materialization

If the NATS CLI is available, inspect the registry bucket directly:

```bash
nats --server "nats://127.0.0.1:${NATS_PORT:-4222}" kv ls
nats --server "nats://127.0.0.1:${NATS_PORT:-4222}" kv keys owui_registry
```

Expected records include service-owned entries for:

- `terminal-service.default`
- `automation-runner.default`
- `pipeline-runner.default`

If the NATS CLI is unavailable, use the admin runtime registry endpoint after authenticating as an admin:

```bash
curl -fsS -H "Authorization: Bearer <admin-token>" \
  "http://127.0.0.1:${OPEN_WEBUI_PORT:-3000}/api/v1/configs/runtime_registry?include_unhealthy=true"
```

Passing condition:

- automation, terminal, and pipeline service records are present and fresh.
- stale or missing service records are visible diagnostically rather than silently ignored.

## 5. Exercise Functional Paths

### Retrieval worker path

Submit a file-processing request through the normal Open WebUI API or UI, then confirm:

- the file status moves through queued/started/completed or queued/started/failed
- `file.data.retrieval_job` is projected into the status response
- `retrieval-worker` logs show job consumption outside the web process

### Automation-runner path

Trigger both a manual automation run and, if test data exists, one due-schedule execution. Confirm:

- the run request is accepted through the normal API edge
- `automation-runner` logs show the request being claimed/executed outside the web process
- lifecycle events or persisted run state distinguish accepted/running/completed/failed
- runtime registry metadata for `automation-runner.default` remains fresh while the runner is active

Passing condition:

- NATS-owned automation execution is real in the live topology rather than only unit-tested
- in NATS mode, stopping `automation-runner` produces a clear unavailable response and does not schedule web-local `execute_automation`; local fallback is only acceptable when NATS is intentionally disabled

### Terminal lifecycle path

With at least one terminal connection configured, create or attach a terminal session and confirm response/event metadata includes lifecycle routing evidence such as:

- `X-OWUI-Terminal-Route`
- `X-OWUI-Terminal-Lifecycle`
- `X-OWUI-Terminal-Session-Status`

Passing condition:

- the service-owned seam is used when available
- terminal-server config changes are visible to `terminal-service` after the `owui.cmd.terminal.config.refresh` request, without requiring a service restart
- stopping `terminal-service` produces documented local fallback or a clear unavailable response
- raw browser terminal transport remains web-edge owned

### Pipeline runner path

Exercise an internal non-streaming filter, pipe, or action model that is tagged for internal execution, then confirm:

- the request reaches `pipeline-runner` over `owui.cmd.pipeline.run`, or the durable stage lane when `pipeline.execution='jetstream'`
- descriptors expose `execution_mode`, `durable_stage`, and executor identity where applicable
- HTTP compatibility fallback still works for external/legacy pipeline configurations

Passing condition:

- request/reply and at least one durable-stage path are proven in a live NATS topology before Stage B is promoted
- durable internal pipe models must not be counted as passing if direct web-tier fallback produced the successful API response after a runner or JetStream failure

## 6. Failure And Rollback Checks

Stop one extracted service at a time:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml stop automation-runner
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml stop terminal-service
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml stop pipeline-runner
```

Passing condition:

- automation requests either follow the documented fallback mode or fail clearly; they must not silently report service-owned execution when the runner is stale or absent
- terminal requests either fall back to the configured local/web path or return a clear lifecycle error; they must not silently route to stale service state
- pipeline requests fall back to HTTP compatibility where designed or return a clear no-responder/timeout error; durable internal pipe models should fail clearly rather than silently direct-executing in the web tier
- runtime registry freshness marks stopped services as stale/non-route-eligible after the configured freshness window

Restart stopped services before continuing:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d automation-runner terminal-service pipeline-runner
```

## 7. Cleanup

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml down
```

Add `-v` only when you intentionally want to remove NATS/Open WebUI volumes:

```bash
docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml down -v
```

## Evidence To Record

When the smoke passes, update `06-implemented-state-and-next-steps.md` with:

- date and environment
- compose command used
- service list and health result
- registry evidence for `automation-runner.default`, `terminal-service.default`, and `pipeline-runner.default`
- retrieval-worker functional proof
- automation-runner request/claim/execute proof
- terminal lifecycle functional proof
- pipeline runner request/reply and durable-stage proof
- fallback behavior when `automation-runner`, `terminal-service`, and `pipeline-runner` are stopped
