from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from starlette.responses import JSONResponse
from open_webui.utils.chat import generate_chat_completion


def _request(model):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                MODELS={model['id']: model},
            )
        ),
        state=SimpleNamespace(
            bypass_filter=False,
            metadata={},
        ),
    )


@pytest.mark.asyncio
async def test_generate_chat_completion_uses_runner_for_non_stream_internal_pipe_model():
    model = {
        'id': 'pipe-1',
        'pipe': {'type': 'pipe'},
        'connection_type': 'internal',
    }
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'pipe-1', 'stream': False}

    with (
        patch(
            'open_webui.utils.chat.request_function_chat_completion_via_runner',
            new=AsyncMock(return_value={'ok': True}),
        ) as via_runner,
        patch(
            'open_webui.utils.chat.generate_function_chat_completion',
            new=AsyncMock(return_value={'fallback': True}),
        ) as direct_pipe,
    ):
        result = await generate_chat_completion(request, form_data, user)

    assert result == {'ok': True}
    via_runner.assert_awaited_once_with(request, form_data, user, model)
    direct_pipe.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_chat_completion_falls_back_to_direct_pipe_when_runner_fails():
    model = {
        'id': 'pipe-1',
        'pipe': {'type': 'pipe'},
        'connection_type': 'internal',
    }
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'pipe-1', 'stream': False}

    with (
        patch(
            'open_webui.utils.chat.request_function_chat_completion_via_runner',
            new=AsyncMock(side_effect=RuntimeError('boom')),
        ) as via_runner,
        patch(
            'open_webui.utils.chat.generate_function_chat_completion',
            new=AsyncMock(return_value={'fallback': True}),
        ) as direct_pipe,
    ):
        result = await generate_chat_completion(request, form_data, user)

    assert result == {'fallback': True}
    via_runner.assert_awaited_once()
    direct_pipe.assert_awaited_once_with(request, form_data, user=user, models=request.app.state.MODELS)


@pytest.mark.asyncio
async def test_generate_chat_completion_does_not_mask_durable_pipe_runner_failure():
    model = {
        'id': 'pipe-1',
        'pipe': {'type': 'pipe', 'execution': 'jetstream'},
        'connection_type': 'internal',
    }
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'pipe-1', 'stream': False}

    with (
        patch(
            'open_webui.utils.chat.request_function_chat_completion_via_runner',
            new=AsyncMock(side_effect=RuntimeError('runner unavailable')),
        ) as via_runner,
        patch(
            'open_webui.utils.chat.generate_function_chat_completion',
            new=AsyncMock(return_value={'fallback': True}),
        ) as direct_pipe,
    ):
        result = await generate_chat_completion(request, form_data, user)

    via_runner.assert_awaited_once()
    direct_pipe.assert_not_awaited()
    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    assert b'Durable pipeline runner unavailable: runner unavailable' in result.body


@pytest.mark.asyncio
async def test_generate_chat_completion_skips_runner_for_streaming_internal_pipe_model():
    model = {
        'id': 'pipe-1',
        'pipe': {'type': 'pipe'},
        'connection_type': 'internal',
    }
    request = _request(model)
    user = SimpleNamespace(id='user-1', role='admin')
    form_data = {'model': 'pipe-1', 'stream': True}

    with (
        patch(
            'open_webui.utils.chat.request_function_chat_completion_via_runner',
            new=AsyncMock(return_value={'ok': True}),
        ) as via_runner,
        patch(
            'open_webui.utils.chat.generate_function_chat_completion',
            new=AsyncMock(return_value={'fallback': True}),
        ) as direct_pipe,
    ):
        result = await generate_chat_completion(request, form_data, user)

    assert result == {'fallback': True}
    via_runner.assert_not_awaited()
    direct_pipe.assert_awaited_once_with(request, form_data, user=user, models=request.app.state.MODELS)
