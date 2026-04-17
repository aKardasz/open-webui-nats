from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from open_webui.utils.runtime_registry import (
    DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
    annotate_runtime_service_metadata,
    build_runtime_service_records,
    get_runtime_service_records,
    is_runtime_service_record_fresh,
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
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': [],
            'capabilities': {'tool_server': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': records[0]['observed_at'],
        },
        {
            'service_id': 'terminal.term-1',
            'service_type': 'terminal',
            'instance_id': 'instance-1',
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': ['owui.cmd.terminal.session.create', 'owui.cmd.terminal.session.attach'],
            'capabilities': {'terminal': True, 'system_prompt': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': records[1]['observed_at'],
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
async def test_sync_registry_to_kv_deletes_stale_tool_and_terminal_records():
    put = AsyncMock()
    delete = AsyncMock()
    kv = SimpleNamespace(
        keys=AsyncMock(return_value=['tool-executor.tool-1', 'tool-executor.tool-old', 'terminal.term-old']),
        put=put,
        delete=delete,
    )
    js = object()
    nc = SimpleNamespace(drain=AsyncMock(), jetstream=lambda: js)
    records = [
        {
            'service_id': 'tool-executor.tool-1',
            'service_type': 'tool-executor',
            'instance_id': 'instance-1',
            'version': '1.0.0',
            'status': 'healthy',
            'subjects': [],
            'capabilities': {'tool_server': True, 'tool_count': 1},
            'routing': {'region': 'local', 'workspace_scope': 'shared'},
            'observed_at': '2026-04-17T18:59:45Z',
        }
    ]

    with (
        patch('open_webui.utils.runtime_registry._connect_nats', new=AsyncMock(return_value=nc)),
        patch('open_webui.utils.runtime_registry._get_or_create_key_value', new=AsyncMock(side_effect=[kv, object(), object()])),
    ):
        from open_webui.utils.runtime_registry import _sync_registry_to_kv

        await _sync_registry_to_kv('nats://nats:4222', records, instance_id='instance-1')

    delete.assert_any_await('tool-executor.tool-old')
    delete.assert_any_await('terminal.term-old')
    put.assert_awaited_once()


def test_is_runtime_service_record_fresh_respects_freshness_window():
    now = datetime(2026, 4, 17, 19, 0, 0, tzinfo=timezone.utc)

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
        now=datetime(2026, 4, 17, 19, 0, 0, tzinfo=timezone.utc),
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
                    'version': '1.0.0',
                    'status': 'healthy',
                    'subjects': ['owui.cmd.terminal.session.create'],
                    'observed_at': '2026-04-17T18:59:45Z',
                }
            ]
        )
    )

    annotated = annotate_runtime_service_metadata(
        app,
        [{'id': 'term-1', 'name': 'Terminal One'}, {'id': 'term-2', 'name': 'Terminal Two'}],
        service_type='terminal',
        freshness_seconds=DEFAULT_RUNTIME_REGISTRY_FRESHNESS_SECONDS,
        now=datetime(2026, 4, 17, 19, 0, 0, tzinfo=timezone.utc),
    )

    assert annotated == [
        {
            'id': 'term-1',
            'name': 'Terminal One',
            'runtime': {
                'service_id': 'terminal.term-1',
                'registered': True,
                'fresh': True,
                'status': 'healthy',
                'observed_at': '2026-04-17T18:59:45Z',
                'instance_id': 'instance-1',
                'version': '1.0.0',
                'subjects': ['owui.cmd.terminal.session.create'],
            },
        },
        {
            'id': 'term-2',
            'name': 'Terminal Two',
            'runtime': {
                'service_id': 'terminal.term-2',
                'registered': False,
                'fresh': False,
                'status': None,
                'observed_at': None,
                'instance_id': None,
                'version': None,
                'subjects': None,
            },
        },
    ]
