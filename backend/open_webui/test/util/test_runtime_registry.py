from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from open_webui.utils.runtime_registry import build_runtime_service_records, sync_runtime_registry


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
