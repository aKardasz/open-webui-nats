import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.utils.actions import build_action_flag, is_durable_action_flag, request_action_via_runner


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


def test_build_action_flag_marks_durable_stage_execution():
    module = SimpleNamespace(durable_stage=True)

    assert build_action_flag(module) == {
        'type': 'action',
        'durable_stage': True,
        'execution': 'jetstream',
    }


def test_is_durable_action_flag_detects_jetstream_action():
    assert is_durable_action_flag({'execution': 'jetstream'})
    assert is_durable_action_flag({'durable_stage': True})
    assert not is_durable_action_flag({'type': 'action'})


@pytest.mark.asyncio
async def test_request_action_via_runner_uses_request_reply():
    request = _request()
    user = SimpleNamespace(id='user-1', role='admin')
    model = {'id': 'model-1', 'connection_type': 'internal'}
    form_data = {'model': 'model-1'}
    nc = FakeNatsConnection(b'{"status":"ok","data":{"body":{"ok":true}}}')

    with (
        patch.dict(sys.modules, {'nats': SimpleNamespace(connect=AsyncMock(return_value=nc))}),
        patch('open_webui.utils.actions.get_function_module_from_cache', return_value=(SimpleNamespace(), None, None)),
    ):
        result = await request_action_via_runner(request, 'action-1', form_data, user, model)

    assert result == {'ok': True}
    nc.request.assert_awaited_once()
    nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_action_via_runner_uses_durable_stage_for_jetstream_action():
    request = _request()
    user = SimpleNamespace(id='user-1', role='admin')
    model = {'id': 'model-1', 'connection_type': 'internal'}
    form_data = {'model': 'model-1'}
    nc = FakeNatsConnection(b'{"status":"ok","data":{"body":{"ok":true}}}')

    with (
        patch.dict(sys.modules, {'nats': SimpleNamespace(connect=AsyncMock(return_value=nc))}),
        patch(
            'open_webui.utils.actions.get_function_module_from_cache',
            return_value=(SimpleNamespace(durable_stage=True), None, None),
        ),
    ):
        result = await request_action_via_runner(request, 'action-1', form_data, user, model)

    assert result == {'ok': True}
    nc.request.assert_not_awaited()
    nc.subscribe.assert_awaited_once()
    nc._js.publish.assert_awaited_once()
    nc._subscription.next_msg.assert_awaited_once()
    nc._subscription.unsubscribe.assert_awaited_once()
