import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.utils.terminal_service import (
    TERMINAL_SESSION_ATTACH_SUBJECT,
    TERMINAL_SESSION_CREATE_SUBJECT,
    TerminalService,
    build_terminal_service_records,
    request_terminal_lifecycle_control,
    should_start_terminal_service,
    start_terminal_service_with_retry,
)


def _app():
    return SimpleNamespace(
        state=SimpleNamespace(
            instance_id='instance-1',
            TERMINAL_SERVERS=[
                {
                    'id': 'server-1',
                    'url': 'http://runtime.example',
                    'specs': [{'name': 'run_command'}],
                    'system_prompt': 'hi',
                    'runtime': {'route_eligible': True},
                }
            ],
            RUNTIME_SERVICE_DISABLED_TYPES=set(),
            RUNTIME_SERVICE_RECORD_PROVIDERS=[],
            config=SimpleNamespace(
                NATS_URL='nats://nats:4222',
                TERMINAL_SESSION_REGISTRY_TTL_SECONDS=600,
                TERMINAL_SERVER_CONNECTIONS=[
                    {
                        'id': 'server-1',
                        'url': 'http://configured.example',
                        'enabled': True,
                    }
                ]
            ),
        )
    )


class FakeSubscription:
    def __init__(self):
        self.unsubscribe = AsyncMock()


class FakeNatsResponse:
    def __init__(self, payload):
        self.data = payload


class FakeNatsConnection:
    def __init__(self, payload=None):
        self._payload = payload
        self.subscribe = AsyncMock(side_effect=[FakeSubscription() for _ in range(6)])
        self.request = AsyncMock(return_value=FakeNatsResponse(payload))
        self.drain = AsyncMock()


def test_should_start_terminal_service_requires_connections_and_nats():
    assert not should_start_terminal_service(
        terminal_connections=[],
        nats_url='nats://nats:4222',
        enable_embedded_service=True,
        terminal_service_only_mode=False,
    )
    assert not should_start_terminal_service(
        terminal_connections=[{'id': 'server-1'}],
        nats_url='',
        enable_embedded_service=True,
        terminal_service_only_mode=False,
    )
    assert should_start_terminal_service(
        terminal_connections=[{'id': 'server-1'}],
        nats_url='nats://nats:4222',
        enable_embedded_service=True,
        terminal_service_only_mode=False,
    )


def test_build_terminal_service_records_marks_service_owned_capabilities():
    app = _app()
    app.state._TERMINAL_SESSION_REGISTRY = {
        'session-1': {'status': 'created', 'server_id': 'server-1'},
        'session-2': {'status': 'disconnected', 'server_id': 'server-1'},
    }
    records = build_terminal_service_records(app)

    assert len(records) == 2
    assert records[0]['service_id'] == 'terminal-service.default'
    assert records[0]['service_type'] == 'terminal-service'
    assert records[0]['capabilities']['service_owner'] == 'terminal-service'
    assert records[0]['capabilities']['session_registry_entries'] == 2
    assert records[0]['capabilities']['active_session_count'] == 1
    assert records[0]['capabilities']['lifecycle_state'] == 'active'
    assert records[1]['service_id'] == 'terminal.server-1'
    assert records[1]['capabilities']['service_owner'] == 'terminal-service'
    assert records[1]['capabilities']['tool_count'] == 1
    assert records[1]['capabilities']['session_registry_entries'] == 2
    assert records[1]['capabilities']['active_session_count'] == 1
    assert records[1]['capabilities']['lifecycle_state'] == 'active'


@pytest.mark.asyncio
async def test_terminal_service_start_disables_web_owned_terminal_records_and_primes_cache():
    app = _app()
    service = TerminalService(app, 'nats://nats:4222')
    fake_nc = FakeNatsConnection()

    with (
        patch(
            'open_webui.utils.terminal_service.set_terminal_servers',
            new=AsyncMock(return_value=app.state.TERMINAL_SERVERS),
        ),
        patch('open_webui.utils.terminal_service._connect_nats', new=AsyncMock(return_value=fake_nc)),
    ):
        started = await service.start()

    assert started is True
    assert 'terminal' in app.state.RUNTIME_SERVICE_DISABLED_TYPES
    assert len(app.state.RUNTIME_SERVICE_RECORD_PROVIDERS) == 1
    assert fake_nc.subscribe.await_count == 6
    await service.close()
    assert app.state.RUNTIME_SERVICE_RECORD_PROVIDERS == []
    fake_nc.drain.assert_awaited_once()


def test_terminal_service_handle_control_request_prefers_runtime_route():
    app = _app()
    service = TerminalService(app, 'nats://nats:4222')

    result = service.handle_control_request('create', {'server_id': 'server-1'})

    assert result == {
        'status': 'ok',
        'data': {
            'server_id': 'server-1',
            'action': 'create',
            'resolved_url': 'http://runtime.example',
            'route_source': 'runtime',
            'session_status': None,
            'lifecycle_source': 'routing_fallback',
        },
    }


def test_terminal_service_handle_control_request_uses_session_registry_for_attach():
    app = _app()
    service = TerminalService(app, 'nats://nats:4222')
    service.record_session_event(
        {
            'event_type': 'terminal.session.created',
            'occurred_at': '2026-04-20T12:00:00Z',
            'data': {
                'session_id': 'session-1',
                'server_id': 'server-1',
                'status': 'created',
                'route_source': 'runtime',
                'resolved_url': 'http://session-owner.example',
            },
        }
    )

    result = service.handle_control_request('attach', {'server_id': 'server-1', 'session_id': 'session-1'})

    assert result == {
        'status': 'ok',
        'data': {
            'server_id': 'server-1',
            'action': 'attach',
            'resolved_url': 'http://session-owner.example',
            'route_source': 'runtime',
            'session_status': 'created',
            'lifecycle_source': 'session_registry',
        },
    }


def test_terminal_service_handle_control_request_rejects_closed_session_attach():
    app = _app()
    service = TerminalService(app, 'nats://nats:4222')
    service.record_session_event(
        {
            'event_type': 'terminal.session.disconnected',
            'occurred_at': '2026-04-20T12:05:00Z',
            'data': {
                'session_id': 'session-1',
                'server_id': 'server-1',
                'status': 'disconnected',
                'route_source': 'runtime',
                'resolved_url': 'http://session-owner.example',
            },
        }
    )

    result = service.handle_control_request('attach', {'server_id': 'server-1', 'session_id': 'session-1'})

    assert result == {
        'status': 'error',
        'status_code': 409,
        'detail': 'Terminal session is not active',
    }


def test_terminal_service_prune_session_registry_removes_stale_entries():
    app = _app()
    service = TerminalService(app, 'nats://nats:4222')
    service.record_session_event(
        {
            'event_type': 'terminal.session.created',
            'occurred_at': '2026-04-20T12:00:00Z',
            'data': {
                'session_id': 'session-1',
                'server_id': 'server-1',
                'status': 'created',
                'route_source': 'runtime',
                'resolved_url': 'http://session-owner.example',
            },
        }
    )

    service.prune_session_registry(
        ttl_seconds=60,
        now=dt.datetime(2026, 4, 20, 12, 2, 0, tzinfo=dt.UTC),
    )

    assert service._session_registry == {}


@pytest.mark.asyncio
async def test_request_terminal_lifecycle_control_uses_create_subject():
    app = _app()
    fake_nc = FakeNatsConnection(payload=b'{"status":"ok","data":{"resolved_url":"http://runtime.example","route_source":"runtime"}}')

    with patch('open_webui.utils.terminal_service._connect_nats', new=AsyncMock(return_value=fake_nc)):
        result = await request_terminal_lifecycle_control(app, server_id='server-1', action='create')

    assert result == {'status': 'ok', 'data': {'resolved_url': 'http://runtime.example', 'route_source': 'runtime'}}
    fake_nc.request.assert_awaited_once()
    assert fake_nc.request.await_args.args[0] == TERMINAL_SESSION_CREATE_SUBJECT
    fake_nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_terminal_lifecycle_control_uses_attach_subject():
    app = _app()
    fake_nc = FakeNatsConnection(payload=b'{"status":"ok","data":{"resolved_url":"http://runtime.example","route_source":"runtime"}}')

    with patch('open_webui.utils.terminal_service._connect_nats', new=AsyncMock(return_value=fake_nc)):
        await request_terminal_lifecycle_control(app, server_id='server-1', action='attach', session_id='session-1')

    assert fake_nc.request.await_args.args[0] == TERMINAL_SESSION_ATTACH_SUBJECT
    assert b'"session_id": "session-1"' in fake_nc.request.await_args.args[1]


@pytest.mark.asyncio
async def test_start_terminal_service_with_retry_returns_supervisor():
    app = _app()

    with patch(
        'open_webui.utils.terminal_service.RetryingTerminalService.start',
        new=AsyncMock(return_value=None),
    ):
        supervisor = await start_terminal_service_with_retry(app, 'nats://nats:4222', retry_delay=0.01)

    assert supervisor is not None
