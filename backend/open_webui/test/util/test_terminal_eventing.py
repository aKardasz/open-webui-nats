from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from open_webui.routers.terminals import ws_terminal


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


@pytest.mark.asyncio
async def test_ws_terminal_emits_attached_only_after_first_upstream_frame():
    ws = FakeWebSocket()
    user = SimpleNamespace(id='user-1')
    connection = {'url': 'http://terminal.example', 'auth_type': 'bearer', 'key': 'secret'}
    upstream = FakeUpstream([SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data='hello')])

    with (
        patch('open_webui.routers.terminals._resolve_authenticated_connection', AsyncMock(return_value=(user, connection))),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=FakeClientSession(upstream)),
        patch('open_webui.routers.terminals.publish_app_event', AsyncMock()) as publish,
    ):
        await ws_terminal(ws, 'server-1', 'session-1')

    event_types = [call.args[1]['event_type'] for call in publish.await_args_list]
    assert event_types == ['terminal.session.attached', 'terminal.session.disconnected']


@pytest.mark.asyncio
async def test_ws_terminal_does_not_emit_attached_when_upstream_closes_without_frame():
    ws = FakeWebSocket()
    user = SimpleNamespace(id='user-1')
    connection = {'url': 'http://terminal.example', 'auth_type': 'bearer', 'key': 'secret'}
    upstream = FakeUpstream([SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None)])

    with (
        patch('open_webui.routers.terminals._resolve_authenticated_connection', AsyncMock(return_value=(user, connection))),
        patch('open_webui.routers.terminals.aiohttp.ClientSession', return_value=FakeClientSession(upstream)),
        patch('open_webui.routers.terminals.publish_app_event', AsyncMock()) as publish,
    ):
        await ws_terminal(ws, 'server-1', 'session-1')

    event_types = [call.args[1]['event_type'] for call in publish.await_args_list]
    assert event_types == []
