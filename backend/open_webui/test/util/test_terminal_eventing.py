from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from open_webui.routers.terminals import list_terminal_servers, proxy_terminal, ws_terminal


class FakeWebSocket:
    def __init__(self):
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.accept = AsyncMock()
        self.receive = AsyncMock(return_value={'type': 'websocket.disconnect'})
        self.send_text = AsyncMock()
        self.send_bytes = AsyncMock()
        self.close = AsyncMock()


class FakeUpstream:
    def __init__(self, messages):
        self.messages = list(messages)
        self.send_str = AsyncMock()
        self.send_bytes = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)


class FakeClientSession:
    def __init__(self, upstream):
        self._upstream = upstream
        self.close = AsyncMock()

    def ws_connect(self, _url):
        return self._upstream

    async def request(self, *_args, **_kwargs):
        return self._upstream


class FakeHttpResponse:
    def __init__(self, *, status=200, body=b'{}', headers=None, content_type='application/json'):
        self.status = status
        self._body = body
        self.headers = headers or {'content-type': content_type}

    async def read(self):
        return self._body

    async def release(self):
        return None


@pytest.mark.asyncio
async def test_list_terminal_servers_includes_runtime_metadata_when_available():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TERMINAL_SERVER_CONNECTIONS=[
                        {'id': 'server-1', 'url': 'http://terminal.example', 'name': 'Terminal One', 'enabled': True}
                    ]
                )
            )
        )
    )
    user = SimpleNamespace(id='user-1', role='user')

    with (
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'runtime': {
                            'service_id': 'terminal.server-1',
                            'registered': True,
                            'fresh': True,
                            'status': 'healthy',
                            'route_eligible': True,
                            'capabilities': {
                                'session_registry_entries': 2,
                                'active_session_count': 1,
                                'lifecycle_state': 'active',
                            },
                        },
                    }
                ]
            ),
        ),
    ):
        result = await list_terminal_servers(request, user)

    assert result == [
        {
            'id': 'server-1',
            'url': 'http://terminal.example',
            'name': 'Terminal One',
            'session_registry_entries': 2,
            'active_session_count': 1,
            'lifecycle_state': 'active',
            'runtime': {
                'service_id': 'terminal.server-1',
                'registered': True,
                'fresh': True,
                'status': 'healthy',
                    'route_eligible': True,
                    'capabilities': {
                        'session_registry_entries': 2,
                        'active_session_count': 1,
                        'lifecycle_state': 'active',
                    },
                },
                'route_source': 'runtime',
        }
    ]


@pytest.mark.asyncio
async def test_proxy_terminal_prefers_runtime_route_when_eligible():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TERMINAL_SERVER_CONNECTIONS=[
                        {'id': 'server-1', 'url': 'http://configured.example', 'auth_type': 'bearer', 'key': 'secret'}
                    ]
                )
            )
        ),
        method='GET',
        query_params='',
        headers={},
        cookies={},
        body=AsyncMock(return_value=b''),
        state=SimpleNamespace(token=SimpleNamespace(credentials='session-token')),
    )
    user = SimpleNamespace(id='user-1', role='user')
    response = FakeHttpResponse(body=b'{"ok": true}')
    session = SimpleNamespace(request=AsyncMock(return_value=response), close=AsyncMock())

    with (
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=session),
    ):
        result = await proxy_terminal('server-1', 'api/terminals', request, user)

    session.request.assert_awaited_once()
    assert session.request.await_args.kwargs['url'] == 'http://runtime.example/api/terminals'
    assert result.headers['x-owui-terminal-route'] == 'runtime'


@pytest.mark.asyncio
async def test_proxy_terminal_uses_terminal_service_control_for_create_when_available():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TERMINAL_SERVER_CONNECTIONS=[
                        {'id': 'server-1', 'url': 'http://configured.example', 'auth_type': 'bearer', 'key': 'secret'}
                    ]
                )
            )
        ),
        method='POST',
        query_params='',
        headers={'content-type': 'application/json'},
        cookies={},
        body=AsyncMock(return_value=b'{}'),
        state=SimpleNamespace(token=SimpleNamespace(credentials='session-token')),
    )
    user = SimpleNamespace(id='user-1', role='user')
    response = FakeHttpResponse(body=b'{"id": "session-1"}')
    session = SimpleNamespace(request=AsyncMock(return_value=response), close=AsyncMock())

    with (
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch(
            'open_webui.routers.terminals.request_terminal_lifecycle_control',
            AsyncMock(
                return_value={
                    'status': 'ok',
                    'data': {
                        'resolved_url': 'http://service-owned.example',
                        'route_source': 'runtime',
                    },
                }
            ),
        ),
        patch('open_webui.routers.terminals.publish_app_event', AsyncMock()),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=session),
    ):
        result = await proxy_terminal('server-1', 'api/terminals', request, user)

    session.request.assert_awaited_once()
    assert session.request.await_args.kwargs['url'] == 'http://service-owned.example/api/terminals'
    assert result.headers['x-owui-terminal-route'] == 'runtime'
    assert result.headers['x-owui-terminal-lifecycle'] == 'service_control'


@pytest.mark.asyncio
async def test_proxy_terminal_uses_session_id_for_service_owned_attach_routing():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TERMINAL_SERVER_CONNECTIONS=[
                        {'id': 'server-1', 'url': 'http://configured.example', 'auth_type': 'bearer', 'key': 'secret'}
                    ]
                )
            )
        ),
        method='GET',
        query_params='',
        headers={},
        cookies={},
        body=AsyncMock(return_value=b''),
        state=SimpleNamespace(token=SimpleNamespace(credentials='session-token')),
    )
    user = SimpleNamespace(id='user-1', role='user')
    response = FakeHttpResponse(body=b'{"ok": true}')
    session = SimpleNamespace(request=AsyncMock(return_value=response), close=AsyncMock())

    with (
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch(
            'open_webui.routers.terminals.request_terminal_lifecycle_control',
            AsyncMock(
                return_value={
                    'status': 'ok',
                    'data': {
                        'resolved_url': 'http://session-owner.example',
                        'route_source': 'runtime',
                        'session_status': 'created',
                        'lifecycle_source': 'session_registry',
                    },
                }
            ),
        ) as control_request,
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=session),
    ):
        result = await proxy_terminal('server-1', 'api/terminals/session-1/resize', request, user)

    control_request.assert_awaited_once_with(
        request.app,
        server_id='server-1',
        action='attach',
        session_id='session-1',
    )
    session.request.assert_awaited_once()
    assert session.request.await_args.kwargs['url'] == 'http://session-owner.example/api/terminals/session-1/resize'
    assert result.headers['x-owui-terminal-route'] == 'runtime'
    assert result.headers['x-owui-terminal-lifecycle'] == 'session_registry'
    assert result.headers['x-owui-terminal-session-status'] == 'created'


@pytest.mark.asyncio
async def test_proxy_terminal_rejects_closed_session_from_service_control():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    TERMINAL_SERVER_CONNECTIONS=[
                        {'id': 'server-1', 'url': 'http://configured.example', 'auth_type': 'bearer', 'key': 'secret'}
                    ]
                )
            )
        ),
        method='GET',
        query_params='',
        headers={},
        cookies={},
        body=AsyncMock(return_value=b''),
        state=SimpleNamespace(token=SimpleNamespace(credentials='session-token')),
    )
    user = SimpleNamespace(id='user-1', role='user')

    with (
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch(
            'open_webui.routers.terminals.request_terminal_lifecycle_control',
            AsyncMock(return_value={'status': 'error', 'status_code': 409, 'detail': 'Terminal session is not active'}),
        ),
    ):
        result = await proxy_terminal('server-1', 'api/terminals/session-1/resize', request, user)

    assert result.status_code == 409
    assert result.body == b'{"error":"Terminal session is not active"}'


@pytest.mark.asyncio
async def test_ws_terminal_emits_attached_only_after_first_upstream_frame():
    ws = FakeWebSocket()
    user = SimpleNamespace(id='user-1')
    connection = {'url': 'http://terminal.example', 'auth_type': 'bearer', 'key': 'secret'}
    upstream = FakeUpstream([SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data='hello')])

    with (
        patch(
            'open_webui.routers.terminals._resolve_authenticated_connection',
            AsyncMock(
                return_value=(
                    user,
                    connection,
                    'runtime',
                    'http://terminal.example',
                    'session_registry',
                    'created',
                )
            ),
        ),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=FakeClientSession(upstream)),
        patch('open_webui.routers.terminals.publish_app_event', AsyncMock()) as publish,
    ):
        await ws_terminal(ws, 'server-1', 'session-1')

    event_types = [call.args[1]['event_type'] for call in publish.await_args_list]
    assert event_types == ['terminal.session.attached', 'terminal.session.disconnected']
    assert all(call.args[1]['data']['route_source'] == 'runtime' for call in publish.await_args_list)
    assert all(call.args[1]['data']['lifecycle_source'] == 'session_registry' for call in publish.await_args_list)
    assert all(call.args[1]['data']['session_status'] == 'created' for call in publish.await_args_list)


@pytest.mark.asyncio
async def test_ws_terminal_does_not_emit_attached_when_upstream_closes_without_frame():
    ws = FakeWebSocket()
    user = SimpleNamespace(id='user-1')
    connection = {'url': 'http://terminal.example', 'auth_type': 'bearer', 'key': 'secret'}
    upstream = FakeUpstream([SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None)])

    with (
        patch(
            'open_webui.routers.terminals._resolve_authenticated_connection',
            AsyncMock(
                return_value=(
                    user,
                    connection,
                    'config_fallback',
                    'http://terminal.example',
                    'routing_fallback',
                    None,
                )
            ),
        ),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=FakeClientSession(upstream)),
        patch('open_webui.routers.terminals.publish_app_event', AsyncMock()) as publish,
    ):
        await ws_terminal(ws, 'server-1', 'session-1')

    event_types = [call.args[1]['event_type'] for call in publish.await_args_list]
    assert event_types == []


@pytest.mark.asyncio
async def test_resolve_authenticated_connection_uses_terminal_service_control_for_attach():
    ws = FakeWebSocket()
    ws.receive_text = AsyncMock(return_value='{"type":"auth","token":"jwt"}')
    ws.app = SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                TERMINAL_SERVER_CONNECTIONS=[
                    {'id': 'server-1', 'url': 'http://configured.example', 'enabled': True}
                ]
            )
        )
    )
    user = SimpleNamespace(id='user-1', role='user')

    with (
        patch('open_webui.routers.terminals.decode_token', return_value={'id': 'user-1'}),
        patch('open_webui.routers.terminals.Users.get_user_by_id', return_value=user),
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch(
            'open_webui.routers.terminals.request_terminal_lifecycle_control',
            AsyncMock(
                return_value={
                    'status': 'ok',
                    'data': {
                        'resolved_url': 'http://service-owned.example',
                        'route_source': 'runtime',
                    },
                }
            ),
        ),
    ):
        from open_webui.routers.terminals import _resolve_authenticated_connection

        result = await _resolve_authenticated_connection(ws, 'server-1', 'session-1')

    assert result[0] is user
    assert result[2] == 'runtime'
    assert result[3] == 'http://service-owned.example'
    assert result[4] == 'service_control'
    assert result[5] is None


@pytest.mark.asyncio
async def test_resolve_authenticated_connection_rejects_closed_session_from_terminal_service():
    ws = FakeWebSocket()
    ws.receive_text = AsyncMock(return_value='{"type":"auth","token":"jwt"}')
    ws.app = SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                TERMINAL_SERVER_CONNECTIONS=[
                    {'id': 'server-1', 'url': 'http://configured.example', 'enabled': True}
                ]
            )
        )
    )
    user = SimpleNamespace(id='user-1', role='user')

    with (
        patch('open_webui.routers.terminals.decode_token', return_value={'id': 'user-1'}),
        patch('open_webui.routers.terminals.Users.get_user_by_id', return_value=user),
        patch('open_webui.routers.terminals.Groups.get_groups_by_member_id', return_value=[]),
        patch('open_webui.routers.terminals.has_connection_access', return_value=True),
        patch(
            'open_webui.routers.terminals.get_cached_terminal_servers',
            AsyncMock(
                return_value=[
                    {
                        'id': 'server-1',
                        'url': 'http://runtime.example',
                        'runtime': {'route_eligible': True},
                    }
                ]
            ),
        ),
        patch(
            'open_webui.routers.terminals.request_terminal_lifecycle_control',
            AsyncMock(return_value={'status': 'error', 'status_code': 409, 'detail': 'Terminal session is not active'}),
        ),
    ):
        from open_webui.routers.terminals import _resolve_authenticated_connection

        result = await _resolve_authenticated_connection(ws, 'server-1', 'session-1')

    assert result is None
    ws.close.assert_awaited_once_with(code=4008, reason='Terminal session is not active')
