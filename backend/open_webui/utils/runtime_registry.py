import asyncio
import datetime as dt
import json
import logging
from typing import Any

from open_webui.env import (
    NATS_CONNECT_TIMEOUT,
    NATS_NAME,
    RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
    VERSION,
)

log = logging.getLogger(__name__)

REGISTRY_BUCKET = 'owui_registry'
ROUTING_BUCKET = 'owui_routing'
FEATURE_FLAGS_BUCKET = 'owui_feature_flags'
DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS = RUNTIME_REGISTRY_FRESHNESS_SECONDS
DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS = RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS
INSTANCE_REGISTRY_KEY_PREFIX = 'service'
ROUTING_MANAGED_SERVICE_PREFIXES = (
    'tool-executor.',
    'terminal.',
    'terminal-service.',
    'pipeline-runner.',
    'automation-runner.',
)


def build_runtime_service_records(
    *,
    tool_servers: list[dict[str, Any]],
    terminal_servers: list[dict[str, Any]],
    instance_id: str,
    version: str = VERSION,
    freshness_seconds: int = DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    heartbeat_interval_seconds: int = DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
    include_tool_servers: bool = True,
    include_terminal_servers: bool = True,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    if include_tool_servers:
        for server in tool_servers or []:
            server_id = server.get('id') or server.get('name') or 'unknown'
            specs = server.get('specs') or []
            records.append(
                build_custom_runtime_service_record(
                    service_id=f'tool-executor.{server_id}',
                    service_type='tool-executor',
                    instance_id=instance_id,
                    version=version,
                    status='healthy' if specs else 'degraded',
                    subjects=[],
                    capabilities={
                        'tool_server': True,
                        'tool_count': len(specs),
                    },
                    routing={
                        'region': 'local',
                        'workspace_scope': 'shared',
                    },
                    freshness_seconds=freshness_seconds,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                )
            )

    if include_terminal_servers:
        for server in terminal_servers or []:
            server_id = server.get('id') or server.get('name') or 'unknown'
            specs = server.get('specs') or []
            records.append(
                build_custom_runtime_service_record(
                    service_id=f'terminal.{server_id}',
                    service_type='terminal',
                    instance_id=instance_id,
                    version=version,
                    status='healthy' if specs else 'degraded',
                    subjects=[
                        'owui.cmd.terminal.session.create',
                        'owui.cmd.terminal.session.attach',
                    ],
                    capabilities={
                        'terminal': True,
                        'system_prompt': bool(server.get('system_prompt')),
                        'tool_count': len(specs),
                    },
                    routing={
                        'region': 'local',
                        'workspace_scope': 'shared',
                    },
                    freshness_seconds=freshness_seconds,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                )
            )

    return records


def get_runtime_service_records(
    app,
    *,
    service_type: str | None = None,
    require_healthy: bool = True,
    freshness_seconds: int | None = None,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    records = list(getattr(app.state, 'RUNTIME_SERVICE_REGISTRY', []))
    if service_type is not None:
        records = [record for record in records if record.get('service_type') == service_type]
    if require_healthy:
        records = [record for record in records if record.get('status') == 'healthy']
    if freshness_seconds is not None:
        records = [record for record in records if is_runtime_service_record_fresh(record, freshness_seconds, now=now)]
    return records


async def refresh_runtime_registry(app, *, nats_url: str) -> list[dict[str, Any]]:
    if not nats_url:
        return list(getattr(app.state, 'RUNTIME_SERVICE_REGISTRY', []))

    try:
        records = await _load_registry_from_kv(
            nats_url,
            instance_id=getattr(app.state, 'instance_id', None),
        )
        if records:
            app.state.RUNTIME_SERVICE_REGISTRY = records
    except ImportError:
        log.warning('NATS runtime registry read skipped because nats-py is not installed.')
    except Exception:
        log.exception('Failed to refresh runtime registry from JetStream KV.')

    return list(getattr(app.state, 'RUNTIME_SERVICE_REGISTRY', []))


def annotate_runtime_service_metadata(
    app,
    servers: list[dict[str, Any]],
    *,
    service_type: str,
    freshness_seconds: int = DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    prefix = f'{service_type}.'
    registry = {
        record['service_id']: record
        for record in get_runtime_service_records(app, require_healthy=False)
        if record.get('service_id', '').startswith(prefix)
    }

    annotated = []
    for server in servers or []:
        server_id = server.get('id') or server.get('name') or 'unknown'
        service_id = f'{service_type}.{server_id}'
        record = registry.get(service_id)
        enriched = {
            **server,
            'runtime': {
                'service_id': service_id,
                'configured': True,
                'registered': record is not None,
                'fresh': is_runtime_service_record_fresh(record, freshness_seconds, now=now) if record else False,
                'status': record.get('status') if record else None,
                'healthy': record.get('status') == 'healthy' if record else False,
                'route_eligible': (
                    record.get('status') == 'healthy'
                    and is_runtime_service_record_fresh(record, freshness_seconds, now=now)
                    if record
                    else False
                ),
                'observed_at': record.get('observed_at') if record else None,
                'expires_at': record.get('expires_at') if record else None,
                'heartbeat_interval_seconds': record.get('heartbeat_interval_seconds') if record else None,
                'instance_id': record.get('instance_id') if record else None,
                'version': record.get('version') if record else None,
                'subjects': record.get('subjects') if record else None,
                'registration_scope': record.get('registration_scope') if record else None,
                'capabilities': record.get('capabilities') if record else None,
                'routing': record.get('routing') if record else None,
            },
        }
        annotated.append(enriched)

    return annotated


def is_runtime_service_record_fresh(
    record: dict[str, Any],
    freshness_seconds: int,
    *,
    now: dt.datetime | None = None,
) -> bool:
    expires_at = record.get('expires_at')
    current = now or dt.datetime.now(dt.UTC)
    if expires_at:
        expires = _parse_runtime_registry_timestamp(expires_at)
        if expires is not None:
            return current <= expires

    observed_at = record.get('observed_at')
    if not observed_at:
        return False

    observed = _parse_runtime_registry_timestamp(observed_at)
    if observed is None:
        return False

    return (current - observed).total_seconds() <= freshness_seconds


async def sync_runtime_registry(app, *, nats_url: str) -> list[dict[str, Any]]:
    disabled_types = set(getattr(app.state, 'RUNTIME_SERVICE_DISABLED_TYPES', set()))
    records = build_runtime_service_records(
        tool_servers=getattr(app.state, 'TOOL_SERVERS', []),
        terminal_servers=getattr(app.state, 'TERMINAL_SERVERS', []),
        instance_id=getattr(app.state, 'instance_id', 'unknown'),
        freshness_seconds=DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
        heartbeat_interval_seconds=DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
        include_tool_servers='tool-executor' not in disabled_types,
        include_terminal_servers='terminal' not in disabled_types,
    )
    for provider in getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', []):
        provided = provider() or []
        if provided:
            records.extend(provided)
    app.state.RUNTIME_SERVICE_REGISTRY = records

    if not nats_url:
        return records

    try:
        await _sync_registry_to_kv(
            nats_url,
            records,
            instance_id=getattr(app.state, 'instance_id', None),
        )
    except ImportError:
        log.warning('NATS runtime registry sync skipped because nats-py is not installed.')
    except Exception:
        log.exception('Failed to sync runtime registry to JetStream KV.')

    return records


async def periodic_runtime_registry_heartbeat(
    app,
    *,
    nats_url: str,
    heartbeat_interval_seconds: int = DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    while True:
        await sync_runtime_registry(app, nats_url=nats_url)
        await asyncio.sleep(heartbeat_interval_seconds)


async def _sync_registry_to_kv(
    nats_url: str,
    records: list[dict[str, Any]],
    *,
    instance_id: str | None = None,
) -> None:
    nc = await _connect_nats(nats_url, instance_id=instance_id)
    try:
        js = nc.jetstream()
        registry_kv = await _get_or_create_key_value(js, REGISTRY_BUCKET)
        routing_kv = await _get_or_create_key_value(js, ROUTING_BUCKET)
        await _get_or_create_key_value(js, FEATURE_FLAGS_BUCKET)

        current_service_ids = {record['service_id'] for record in records}
        current_service_types = {record.get('service_type') for record in records}
        try:
            existing_routing_keys = await routing_kv.keys() or []
        except Exception as exc:
            if exc.__class__.__name__ != 'NoKeysError':
                raise
            existing_routing_keys = []
        for key in existing_routing_keys:
            if key in current_service_ids:
                continue
            try:
                route_entry = await routing_kv.get(key)
                route_snapshot = json.loads(route_entry.value.decode('utf-8'))
            except Exception:
                continue
            if route_snapshot.get('service_type') in current_service_types:
                await routing_kv.delete(key)

        for record in records:
            await registry_kv.put(_build_runtime_service_instance_key(record), json.dumps(record).encode('utf-8'))
            await routing_kv.put(
                record['service_id'],
                json.dumps(_build_runtime_service_route_snapshot(record)).encode('utf-8'),
            )
    finally:
        await nc.drain()


async def _load_registry_from_kv(
    nats_url: str,
    *,
    instance_id: str | None = None,
) -> list[dict[str, Any]]:
    nc = await _connect_nats(nats_url, instance_id=instance_id)
    try:
        registry_kv = await _get_or_create_key_value(nc.jetstream(), REGISTRY_BUCKET)
        keys = await registry_kv.keys() or []
        records_by_service_id: dict[str, dict[str, Any]] = {}
        for key in keys:
            entry = await registry_kv.get(key)
            record = json.loads(entry.value.decode('utf-8'))
            service_id = record.get('service_id')
            if not service_id:
                continue

            current = records_by_service_id.get(service_id)
            if current is None or _should_replace_runtime_service_record(current, record):
                records_by_service_id[service_id] = record

        return list(records_by_service_id.values())
    finally:
        await nc.drain()


async def _get_or_create_key_value(js, bucket: str):
    from nats.js import api
    from nats.js.errors import BucketNotFoundError

    try:
        return await js.key_value(bucket)
    except BucketNotFoundError:
        return await js.create_key_value(config=api.KeyValueConfig(bucket=bucket))


async def _connect_nats(nats_url: str, *, instance_id: str | None = None):
    import nats

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    return await nats.connect(
        servers=servers,
        name=f'{NATS_NAME}-registry-{instance_id or "runtime"}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )


def _build_runtime_service_record(
    *,
    service_id: str,
    service_type: str,
    instance_id: str,
    version: str,
    status: str,
    subjects: list[str],
    capabilities: dict[str, Any],
    routing: dict[str, Any],
    observed_at: str,
    expires_at: str,
    heartbeat_interval_seconds: int,
) -> dict[str, Any]:
    return {
        'service_id': service_id,
        'service_type': service_type,
        'instance_id': instance_id,
        'registration_scope': 'instance',
        'version': version,
        'status': status,
        'subjects': subjects,
        'capabilities': capabilities,
        'routing': routing,
        'observed_at': observed_at,
        'expires_at': expires_at,
        'heartbeat_interval_seconds': heartbeat_interval_seconds,
    }


def build_custom_runtime_service_record(
    *,
    service_id: str,
    service_type: str,
    instance_id: str,
    version: str,
    status: str,
    subjects: list[str],
    capabilities: dict[str, Any],
    routing: dict[str, Any],
    freshness_seconds: int = DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    heartbeat_interval_seconds: int = DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
) -> dict[str, Any]:
    observed_at = _utc_now()
    expires_at = _compute_runtime_registry_expires_at(observed_at, freshness_seconds)
    return _build_runtime_service_record(
        service_id=service_id,
        service_type=service_type,
        instance_id=instance_id,
        version=version,
        status=status,
        subjects=subjects,
        capabilities=capabilities,
        routing=routing,
        observed_at=observed_at,
        expires_at=expires_at,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


def _build_runtime_service_instance_key(record: dict[str, Any]) -> str:
    return (
        f'{INSTANCE_REGISTRY_KEY_PREFIX}/'
        f'{record["service_type"]}/'
        f'{record["service_id"]}/'
        f'{record["instance_id"]}'
    )


def _build_runtime_service_route_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        'service_id': record['service_id'],
        'service_type': record['service_type'],
        'instance_id': record['instance_id'],
        'status': record['status'],
        'observed_at': record['observed_at'],
        'expires_at': record.get('expires_at'),
        'heartbeat_interval_seconds': record.get('heartbeat_interval_seconds'),
        'route_eligible': record['status'] == 'healthy',
        'registration_scope': 'derived',
    }


def _sort_runtime_record_observed_at(record: dict[str, Any]) -> dt.datetime:
    observed_at = record.get('observed_at')
    if not observed_at:
        return dt.datetime.min.replace(tzinfo=dt.UTC)

    observed = _parse_runtime_registry_timestamp(observed_at)
    if observed is None:
        return dt.datetime.min.replace(tzinfo=dt.UTC)
    return observed


def _runtime_service_record_source_priority(record: dict[str, Any]) -> int:
    capabilities = record.get('capabilities') or {}
    routing = record.get('routing') or {}

    if capabilities.get('service_owner') or routing.get('owner'):
        return 2

    if record.get('service_type') in {'terminal-service', 'pipeline-runner', 'automation-runner'}:
        return 2

    return 1


def _should_replace_runtime_service_record(current: dict[str, Any], candidate: dict[str, Any]) -> bool:
    current_priority = _runtime_service_record_source_priority(current)
    candidate_priority = _runtime_service_record_source_priority(candidate)
    if candidate_priority != current_priority:
        return candidate_priority > current_priority

    return _sort_runtime_record_observed_at(candidate) >= _sort_runtime_record_observed_at(current)


def _compute_runtime_registry_expires_at(observed_at: str, freshness_seconds: int) -> str:
    observed = _parse_runtime_registry_timestamp(observed_at) or dt.datetime.now(dt.UTC)
    return (observed + dt.timedelta(seconds=freshness_seconds)).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _parse_runtime_registry_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')
