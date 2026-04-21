import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.functions import (
    build_pipe_flag,
    is_durable_pipe_model,
    request_function_chat_completion_via_runner,
)


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                instance_id='instance-1',
                config=SimpleNamespace(
                    NATS_URL='nats://nats:4222',
                    PIPELINE_NATS_SUBJECT='owui.cmd.pipeline.run',
                    PIPELINE_NATS_REQUEST_TIMEOUT=10.0,
                ),
            )
        )
    )


class FakeNatsResponse:
    def __init__(self, payload):
        self.data = payload


class FakeNatsConnection:
    def __init__(self, payload):
        self._payload = payload
        self.request = AsyncMock(return_value=FakeNatsResponse(payload))
        self.drain = AsyncMock()
        self._subscription = SimpleNamespace(
            next_msg=AsyncMock(return_value=FakeNatsResponse(payload)),
            unsubscribe=AsyncMock(),
        )
        self.subscribe = AsyncMock(return_value=self._subscription)
        self._js = SimpleNamespace(publish=AsyncMock())

    def jetstream(self):
        return self._js


def test_build_pipe_flag_marks_durable_stage_execution():
    module = SimpleNamespace(durable_stage=True)

    assert build_pipe_flag(module, 'pipe') == {
        'type': 'pipe',
        'durable_stage': True,
        'execution': 'jetstream',
    }


def test_is_durable_pipe_model_detects_jetstream_pipe():
    assert is_durable_pipe_model({'pipe': {'execution': 'jetstream'}})
    assert is_durable_pipe_model({'pipe': {'durable_stage': True}})
    assert not is_durable_pipe_model({'pipe': {'type': 'pipe'}})


@pytest.mark.asyncio
async def test_request_function_chat_completion_via_runner_uses_request_reply_for_non_durable_pipe():
    request = _request()
    user = SimpleNamespace(id='user-1', role='admin')
    model = {'id': 'pipe-1', 'pipe': {'type': 'pipe'}, 'internal_executor_id': 'pipe-1'}
    form_data = {'model': 'pipe-1'}
    nc = FakeNatsConnection(b'{"status":"ok","data":{"body":{"ok":true}}}')

    with patch.dict(sys.modules, {'nats': SimpleNamespace(connect=AsyncMock(return_value=nc))}):
        result = await request_function_chat_completion_via_runner(request, form_data, user, model)

    assert result == {'ok': True}
    nc.request.assert_awaited_once()
    nc._js.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_function_chat_completion_via_runner_uses_durable_stage_for_jetstream_pipe():
    request = _request()
    user = SimpleNamespace(id='user-1', role='admin')
    model = {'id': 'pipe-1', 'pipe': {'type': 'pipe', 'execution': 'jetstream'}, 'internal_executor_id': 'pipe-1'}
    form_data = {'model': 'pipe-1'}
    nc = FakeNatsConnection(b'{"status":"ok","data":{"body":{"ok":true}}}')

    with patch.dict(sys.modules, {'nats': SimpleNamespace(connect=AsyncMock(return_value=nc))}):
        result = await request_function_chat_completion_via_runner(request, form_data, user, model)

    assert result == {'ok': True}
    nc.request.assert_not_awaited()
    nc.subscribe.assert_awaited_once()
    nc._js.publish.assert_awaited_once()
    nc._subscription.next_msg.assert_awaited_once()
    nc._subscription.unsubscribe.assert_awaited_once()
