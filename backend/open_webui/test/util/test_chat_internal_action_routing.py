from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.utils.actions import chat_action


def _request(model):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                MODELS={model['id']: model},
            )
        ),
        state=SimpleNamespace(
            direct=False,
        ),
    )


@pytest.mark.asyncio
async def test_chat_action_uses_runner_for_internal_model():
    model = {'id': 'model-1', 'connection_type': 'internal'}
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'model-1'}

    with (
        patch('open_webui.utils.actions.Functions.get_function_by_id', return_value=object()),
        patch(
            'open_webui.utils.actions.request_action_via_runner',
            new=AsyncMock(return_value={'ok': True}),
        ) as via_runner,
        patch('open_webui.utils.actions.get_function_module_from_cache') as local_path,
    ):
        result = await chat_action(request, 'action-1', form_data, user)

    assert result == {'ok': True}
    via_runner.assert_awaited_once_with(request, 'action-1', form_data, user, model)
    local_path.assert_not_called()


@pytest.mark.asyncio
async def test_chat_action_falls_back_to_local_execution_when_runner_fails():
    model = {'id': 'model-1', 'connection_type': 'internal'}
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'model-1', 'chat_id': 'chat-1', 'id': 'msg-1', 'session_id': 'session-1'}
    function_module = SimpleNamespace(action=AsyncMock(return_value={'ok': True}))

    with (
        patch('open_webui.utils.actions.Functions.get_function_by_id', return_value=object()),
        patch('open_webui.utils.actions.request_action_via_runner', new=AsyncMock(side_effect=RuntimeError('boom'))),
        patch('open_webui.utils.actions.get_function_module_from_cache', return_value=(function_module, None, None)),
        patch('open_webui.utils.actions.process_tool_result', return_value=({'ok': True}, None, [])),
    ):
        result = await chat_action(request, 'action-1', form_data, user)

    assert result == {'ok': True}
    function_module.action.assert_awaited_once()
