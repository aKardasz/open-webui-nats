import asyncio
import datetime as dt
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.utils.runtime_registry import (
    DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
    annotate_runtime_service_metadata,
    build_custom_runtime_service_record,
    build_runtime_service_records,
    get_runtime_service_records,
    is_runtime_service_record_fresh,
    periodic_runtime_registry_heartbeat,
    refresh_runtime_registry,
    sync_runtime_registry,
)


def test_build_runtime_service_records_normalizes_tool_and_terminal_servers():
    records = build_runtime_service_records(
        tool_servers=[{'id': 'tool-1', 'specs': [{'name': 'search'}]}],
        terminal_servers=[{'id': 'term-1', 'specs': [{'name': 'run_command'}], 'system_prompt': 'hi'}],
        instance_id='instance-1',
        version='1.0.0',
    )

    assert records == [
        {
            'service_id': 'tool-executor.tool-1',
            'service_type': 'tool-executor',
            'instance_id': 'instance-1',
            'registration_scope': 'instance',
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': [],
            'capabilities': {'tool_server': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': records[0]['observed_at'],
            'expires_at': records[0]['expires_at'],
            'heartbeat_interval_seconds': DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
        },
        {
            'service_id': 'terminal.term-1',
            'service_type': 'terminal',
            'instance_id': 'instance-1',
            'registration_scope': 'instance',
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': ['owui.cmd.terminal.session.create', 'owui.cmd.terminal.session.attach'],
            'capabilities': {'terminal': True, 'system_prompt': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': records[1]['observed_at'],
            'expires_at': records[1]['expires_at'],
            'heartbeat_interval_seconds': DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
        },
    ]


@pytest.mark.asyncio
async def test_sync_runtime_registry_updates_app_state_and_publishes_when_nats_enabled():
    app = SimpleNamespace(
        state=SimpleNamespace(
            TOOL_SERVERS=[{'id': 'tool-1', 'specs': [{'name': 'search'}]}],
            TERMINAL_SERVERS=[{'id': 'term-1', 'specs': [{'name': 'run_command'}], 'system_prompt': 'hi'}],
            instance_id='instance-1',
        )
    )

    with patch('open_webui.utils.runtime_registry._sync_registry_to_kv', new=AsyncMock()) as sync:
        records = await sync_runtime_registry(app, nats_url='nats://nats:4222')

    assert app.state.RUNTIME_SERVICE_REGISTRY == records
    sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_runtime_registry_skips_publish_when_nats_disabled():
    app = SimpleNamespace(
        state=SimpleNamespace(
            TOOL_SERVERS=[{'id': 'tool-1', 'specs': []}],
            TERMINAL_SERVERS=[],
            instance_id='instance-1',
        )
    )

    with patch('open_webui.utils.runtime_registry._sync_registry_to_kv', new=AsyncMock()) as sync:
        records = await sync_runtime_registry(app, nats_url='')

    assert app.state.RUNTIME_SERVICE_REGISTRY == records
    sync.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_runtime_registry_prefers_kv_records_when_available():
    app = SimpleNamespace(state=SimpleNamespace(RUNTIME_SERVICE_REGISTRY=[]))

    with patch(
        'open_webui.utils.runtime_registry._load_registry_from_kv',
        new=AsyncMock(return_value=[{'service_id': 'terminal.term-1', 'service_type': 'terminal'}]),
    ):
        records = await refresh_runtime_registry(app, nats_url='nats://nats:4222')

    assert records == [{'service_id': 'terminal.term-1', 'service_type': 'terminal'}]
    assert app.state.RUNTIME_SERVICE_REGISTRY == records


@pytest.mark.asyncio
async def test_load_registry_from_kv_prefers_service_owned_record_over_newer_web_snapshot():
    js = object()
    nc = SimpleNamespace(drain=AsyncMock(), jetstream=lambda: js)
    registry_kv = SimpleNamespace(
        keys=AsyncMock(
            return_value=[
                'service/terminal/terminal.term-1/web-instance',
                'service/terminal/terminal.term-1/service-instance',
            ]
        ),
        get=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    value=json.dumps(
                        {
                            'service_id': 'terminal.term-1',
                            'service_type': 'terminal',
                            'instance_id': 'web-instance',
                            'status': 'healthy',
                            'observed_at': '2026-04-20T20:00:05Z',
                            'routing': {'region': 'local', 'workspace_scope': 'shared'},
                            'capabilities': {'terminal': True},
                        }
                    ).encode('utf-8')
                ),
                SimpleNamespace(
                    value=json.dumps(
                        {
                            'service_id': 'terminal.term-1',
                            'service_type': 'terminal',
                            'instance_id': 'service-instance',
                            'status': 'healthy',
                            'observed_at': '2026-04-20T20:00:00Z',
                            'routing': {
                                'region': 'local',
                                'workspace_scope': 'shared',
                                'owner': 'terminal-service',
                            },
                            'capabilities': {
                                'terminal': True,
                                'service_owner': 'terminal-service',
                            },
                        }
                    ).encode('utf-8')
                ),
            ]
        ),
    )

    with (
        patch('open_webui.utils.runtime_registry._connect_nats', new=AsyncMock(return_value=nc)),
        patch('open_webui.utils.runtime_registry._get_or_create_key_value', new=AsyncMock(return_value=registry_kv)),
    ):
        from open_webui.utils.runtime_registry import _load_registry_from_kv

        records = await _load_registry_from_kv('nats://nats:4222', instance_id='web-instance')

    assert records == [
        {
            'service_id': 'terminal.term-1',
            'service_type': 'terminal',
            'instance_id': 'service-instance',
            'status': 'healthy',
            'observed_at': '2026-04-20T20:00:00Z',
            'routing': {
                'region': 'local',
                'workspace_scope': 'shared',
                'owner': 'terminal-service',
            },
            'capabilities': {
                'terminal': True,
                'service_owner': 'terminal-service',
            },
        }
    ]


@pytest.mark.asyncio
async def test_sync_registry_to_kv_deletes_only_stale_records_for_current_service_type():
    registry_put = AsyncMock()
    routing_put = AsyncMock()
    routing_delete = AsyncMock()
    registry_kv = SimpleNamespace(
        keys=AsyncMock(return_value=['service/tool-executor/tool-executor.tool-1/instance-1']),
        put=registry_put,
    )
    async def get_route_snapshot(key):
        snapshots = {
            'tool-executor.tool-old': {'service_id': 'tool-executor.tool-old', 'service_type': 'tool-executor'},
            'terminal.term-old': {'service_id': 'terminal.term-old', 'service_type': 'terminal'},
            'pipeline-runner.default': {'service_id': 'pipeline-runner.default', 'service_type': 'pipeline-runner'},
        }
        return SimpleNamespace(value=json.dumps(snapshots[key]).encode('utf-8'))

    routing_kv = SimpleNamespace(
        keys=AsyncMock(
            return_value=[
                'tool-executor.tool-1',
                'tool-executor.tool-old',
                'terminal.term-old',
                'pipeline-runner.default',
            ]
        ),
        get=AsyncMock(side_effect=get_route_snapshot),
        put=routing_put,
        delete=routing_delete,
    )
    js = object()
    nc = SimpleNamespace(drain=AsyncMock(), jetstream=lambda: js)
    records = [
        {
            'service_id': 'tool-executor.tool-1',
            'service_type': 'tool-executor',
            'instance_id': 'instance-1',
            'registration_scope': 'instance',
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': [],
            'capabilities': {'tool_server': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': '2026-04-17T18:59:45Z',
            'expires_at': '2026-04-17T19:01:45Z',
            'heartbeat_interval_seconds': DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
        }
    ]

    with (
        patch('open_webui.utils.runtime_registry._connect_nats', new=AsyncMock(return_value=nc)),
        patch(
            'open_webui.utils.runtime_registry._get_or_create_key_value',
            new=AsyncMock(side_effect=[registry_kv, routing_kv, object()]),
        ),
    ):
        from open_webui.utils.runtime_registry import _sync_registry_to_kv

        await _sync_registry_to_kv('nats://nats:4222', records, instance_id='instance-1')

    routing_delete.assert_awaited_once_with('tool-executor.tool-old')
    registry_put.assert_awaited_once()
    routing_put.assert_awaited_once()


def test_is_runtime_service_record_fresh_respects_freshness_window():
    now = dt.datetime(2026, 4, 17, 19, 0, 0, tzinfo=dt.UTC)

    assert is_runtime_service_record_fresh(
        {'observed_at': '2026-04-17T18:59:45Z'},
        30,
        now=now,
    )
    assert not is_runtime_service_record_fresh(
        {'observed_at': '2026-04-17T18:58:00Z'},
        30,
        now=now,
    )


def test_is_runtime_service_record_fresh_prefers_expires_at_when_present():
    now = dt.datetime(2026, 4, 17, 19, 0, 0, tzinfo=dt.UTC)

    assert is_runtime_service_record_fresh(
        {
            'observed_at': '2026-04-17T18:58:00Z',
            'expires_at': '2026-04-17T19:00:05Z',
        },
        30,
        now=now,
    )
    assert not is_runtime_service_record_fresh(
        {
            'observed_at': '2026-04-17T18:59:45Z',
            'expires_at': '2026-04-17T18:59:59Z',
        },
        30,
        now=now,
    )


def test_get_runtime_service_records_filters_by_service_type_health_and_freshness():
    app = SimpleNamespace(
        state=SimpleNamespace(
            RUNTIME_SERVICE_REGISTRY=[
                {
                    'service_id': 'tool-executor.tool-1',
                    'service_type': 'tool-executor',
                    'status': 'healthy',
                    'observed_at': '2026-04-17T18:59:45Z',
                },
                {
                    'service_id': 'tool-executor.tool-2',
                    'service_type': 'tool-executor',
                    'status': 'degraded',
                    'observed_at': '2026-04-17T18:59:45Z',
                },
                {
                    'service_id': 'terminal.term-1',
                    'service_type': 'terminal',
                    'status': 'healthy',
                    'observed_at': '2026-04-17T18:58:00Z',
                },
            ]
        )
    )

    records = get_runtime_service_records(
        app,
        service_type='tool-executor',
        freshness_seconds=30,
        now=dt.datetime(2026, 4, 17, 19, 0, 0, tzinfo=dt.UTC),
    )

    assert records == [
        {
            'service_id': 'tool-executor.tool-1',
            'service_type': 'tool-executor',
            'status': 'healthy',
            'observed_at': '2026-04-17T18:59:45Z',
        }
    ]


def test_annotate_runtime_service_metadata_marks_registration_and_freshness():
    app = SimpleNamespace(
        state=SimpleNamespace(
            RUNTIME_SERVICE_REGISTRY=[
                {
                    'service_id': 'terminal.term-1',
                    'service_type': 'terminal',
                    'instance_id': 'instance-1',
                    'registration_scope': 'instance',
                    'version': '1.0.0',
                    'status': 'healthy',
                    'subjects': ['owui.cmd.terminal.session.create'],
                    'capabilities': {
                        'terminal': True,
                        'session_registry_entries': 2,
                        'active_session_count': 1,
                    },
                    'routing': {'owner': 'terminal-service'},
                    'observed_at': '2026-04-17T18:59:45Z',
                    'expires_at': '2026-04-17T19:01:45Z',
                    'heartbeat_interval_seconds': DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
                }
            ]
        )
    )

    annotated = annotate_runtime_service_metadata(
        app,
        [{'id': 'term-1', 'name': 'Terminal One'}, {'id': 'term-2', 'name': 'Terminal Two'}],
        service_type='terminal',
        freshness_seconds=DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
        now=dt.datetime(2026, 4, 17, 19, 0, 0, tzinfo=dt.UTC),
    )

    assert annotated == [
        {
            'id': 'term-1',
            'name': 'Terminal One',
            'runtime': {
                'service_id': 'terminal.term-1',
                'configured': True,
                'registered': True,
                'fresh': True,
                'status': 'healthy',
                'healthy': True,
                'route_eligible': True,
                'observed_at': '2026-04-17T18:59:45Z',
                'instance_id': 'instance-1',
                'version': '1.0.0',
                'subjects': ['owui.cmd.terminal.session.create'],
                'registration_scope': 'instance',
                'expires_at': '2026-04-17T19:01:45Z',
                'heartbeat_interval_seconds': DEFAULT_RUNTIME_REGISTRY_HEARTBEAT_INTERVAL_SECONDS,
                'capabilities': {
                    'terminal': True,
                    'session_registry_entries': 2,
                    'active_session_count': 1,
                },
                'routing': {'owner': 'terminal-service'},
            },
        },
        {
            'id': 'term-2',
            'name': 'Terminal Two',
            'runtime': {
                'service_id': 'terminal.term-2',
                'configured': True,
                'registered': False,
                'fresh': False,
                'status': None,
                'healthy': False,
                'route_eligible': False,
                'observed_at': None,
                'expires_at': None,
                'heartbeat_interval_seconds': None,
                'instance_id': None,
                'version': None,
                'subjects': None,
                'registration_scope': None,
                'capabilities': None,
                'routing': None,
            },
        },
    ]


@pytest.mark.asyncio
async def test_periodic_runtime_registry_heartbeat_syncs_until_cancelled():
    app = SimpleNamespace(state=SimpleNamespace())
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])

    with (
        patch('open_webui.utils.runtime_registry.sync_runtime_registry', new=AsyncMock()) as sync,
        patch('open_webui.utils.runtime_registry.asyncio.sleep', new=sleep),
    ):
        with pytest.raises(asyncio.CancelledError):
            await periodic_runtime_registry_heartbeat(app, nats_url='nats://nats:4222', heartbeat_interval_seconds=5)

    assert sync.await_count == 2


@pytest.mark.asyncio
async def test_sync_runtime_registry_supports_provider_records_and_disabled_types():
    app = SimpleNamespace(
        state=SimpleNamespace(
            TOOL_SERVERS=[],
            TERMINAL_SERVERS=[{'id': 'term-1', 'specs': [{'name': 'run_command'}]}],
            instance_id='instance-1',
            RUNTIME_SERVICE_DISABLED_TYPES={'terminal'},
            RUNTIME_SERVICE_RECORD_PROVIDERS=[
                lambda: [
                    build_custom_runtime_service_record(
                        service_id='terminal.term-1',
                        service_type='terminal',
                        instance_id='instance-1',
                        version='1.0.0',
                        status='healthy',
                        subjects=['owui.cmd.terminal.session.create'],
                        capabilities={'terminal': True, 'service_owner': 'terminal-service'},
                        routing={'owner': 'terminal-service'},
                    )
                ]
            ],
        )
    )

    with patch('open_webui.utils.runtime_registry._sync_registry_to_kv', new=AsyncMock()) as sync:
        records = await sync_runtime_registry(app, nats_url='nats://nats:4222')

    assert len(records) == 1
    assert records[0]['service_id'] == 'terminal.term-1'
    assert records[0]['capabilities']['service_owner'] == 'terminal-service'
    sync.assert_awaited_once()
