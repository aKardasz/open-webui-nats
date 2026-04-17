import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from open_webui.env import NATS_CONNECT_TIMEOUT, NATS_NAME, VERSION

log = logging.getLogger(__name__)

REGISTRY_BUCKET = 'owui_registry'
ROUTING_BUCKET = 'owui_routing'
FEATURE_FLAGS_BUCKET = 'owui_feature_flags'


def build_runtime_service_records(
    *,
    tool_servers: List[Dict[str, Any]],
    terminal_servers: List[Dict[str, Any]],
    instance_id: str,
    version: str = VERSION,
) -> List[Dict[str, Any]]:
    observed_at = _utc_now()
    records: List[Dict[str, Any]] = []

    for server in tool_servers or []:
        server_id = server.get('id') or server.get('name') or 'unknown'
        specs = server.get('specs') or []
        records.append(
            _build_runtime_service_record(
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
                observed_at=observed_at,
            )
        )

    for server in terminal_servers or []:
        server_id = server.get('id') or server.get('name') or 'unknown'
        specs = server.get('specs') or []
        records.append(
            _build_runtime_service_record(
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
                observed_at=observed_at,
            )
        )

    return records


async def sync_runtime_registry(app, *, nats_url: str) -> List[Dict[str, Any]]:
    records = build_runtime_service_records(
        tool_servers=getattr(app.state, 'TOOL_SERVERS', []),
        terminal_servers=getattr(app.state, 'TERMINAL_SERVERS', []),
        instance_id=getattr(app.state, 'instance_id', 'unknown'),
    )
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


async def _sync_registry_to_kv(
    nats_url: str,
    records: List[Dict[str, Any]],
    *,
    instance_id: str | None = None,
) -> None:
    nc = await _connect_nats(nats_url, instance_id=instance_id)
    try:
        js = nc.jetstream()
        registry_kv = await _get_or_create_key_value(js, REGISTRY_BUCKET)
        await _get_or_create_key_value(js, ROUTING_BUCKET)
        await _get_or_create_key_value(js, FEATURE_FLAGS_BUCKET)

        for record in records:
            await registry_kv.put(record['service_id'], json.dumps(record).encode('utf-8'))
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
    subjects: List[str],
    capabilities: Dict[str, Any],
    routing: Dict[str, Any],
    observed_at: str,
) -> Dict[str, Any]:
    return {
        'service_id': service_id,
        'service_type': service_type,
        'instance_id': instance_id,
        'version': version,
        'status': status,
        'subjects': subjects,
        'capabilities': capabilities,
        'routing': routing,
        'observed_at': observed_at,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
