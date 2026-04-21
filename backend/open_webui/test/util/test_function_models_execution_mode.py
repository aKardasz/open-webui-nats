from types import SimpleNamespace
from unittest.mock import patch

import pytest
from open_webui.functions import get_function_models


@pytest.mark.asyncio
async def test_get_function_models_marks_request_reply_pipe_execution_mode():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(FUNCTIONS={})))
    function_row = SimpleNamespace(id='pipe-1', name='Pipe 1', type='pipe', created_at=1)
    module = SimpleNamespace()

    with (
        patch('open_webui.functions.Functions.get_functions_by_type', return_value=[function_row]),
        patch('open_webui.functions.get_function_module_by_id', return_value=module),
    ):
        models = await get_function_models(request)

    assert models == [
        {
            'id': 'pipe-1',
            'name': 'Pipe 1',
            'object': 'model',
            'created': 1,
            'owned_by': 'openai',
            'connection_type': 'internal',
            'internal_executor_id': 'pipe-1',
            'execution_mode': 'request_reply',
            'pipe': {'type': 'pipe'},
            'has_user_valves': False,
        }
    ]


@pytest.mark.asyncio
async def test_get_function_models_marks_durable_pipe_execution_mode():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(FUNCTIONS={})))
    function_row = SimpleNamespace(id='pipe-1', name='Pipe 1', type='pipe', created_at=1)
    module = SimpleNamespace(durable_stage=True)

    with (
        patch('open_webui.functions.Functions.get_functions_by_type', return_value=[function_row]),
        patch('open_webui.functions.get_function_module_by_id', return_value=module),
    ):
        models = await get_function_models(request)

    assert models[0]['execution_mode'] == 'jetstream'
    assert models[0]['pipe']['execution'] == 'jetstream'
