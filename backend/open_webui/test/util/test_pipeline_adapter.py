from types import SimpleNamespace
from unittest.mock import patch

import pytest

from open_webui.utils.pipeline_adapter import HttpPipelineAdapter, PipelineAdapterError


class FakeResponse:
    def __init__(self, *, status=200, payload=None, content_type='application/json'):
        self.status = status
        self._payload = payload or {}
        self.content_type = content_type

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self):
        import aiohttp

        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,
                history=(),
                status=self.status,
                message='boom',
                headers=None,
            )

    async def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def post(self, *_args, **_kwargs):
        return self._response

    def get(self, *_args, **_kwargs):
        return self._response

    def delete(self, *_args, **_kwargs):
        return self._response


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    OPENAI_API_BASE_URLS=['http://pipeline.example'],
                    OPENAI_API_KEYS=['secret'],
                )
            )
        )
    )


@pytest.mark.asyncio
async def test_http_pipeline_adapter_invokes_filter():
    adapter = HttpPipelineAdapter(_request())
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}

    with patch('open_webui.utils.pipeline_adapter.aiohttp.ClientSession', return_value=FakeSession(FakeResponse(payload={'ok': True}))):
        result = await adapter.invoke_filter(
            pipeline,
            'inlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'ok': True}


@pytest.mark.asyncio
async def test_http_pipeline_adapter_raises_pipeline_adapter_error_on_http_error():
    adapter = HttpPipelineAdapter(_request())
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}

    with patch(
        'open_webui.utils.pipeline_adapter.aiohttp.ClientSession',
        return_value=FakeSession(FakeResponse(status=400, payload={'detail': 'bad request'})),
    ):
        with pytest.raises(PipelineAdapterError) as exc:
            await adapter.invoke_filter(
                pipeline,
                'outlet',
                user={'id': 'user-1'},
                payload={'model': 'model-1'},
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == {'detail': 'bad request'}


@pytest.mark.asyncio
async def test_http_pipeline_adapter_get_json_returns_payload():
    adapter = HttpPipelineAdapter(_request())

    with patch('open_webui.utils.pipeline_adapter.aiohttp.ClientSession', return_value=FakeSession(FakeResponse(payload={'items': []}))):
        result = await adapter.get_json(0, 'pipelines')

    assert result == {'items': []}


@pytest.mark.asyncio
async def test_http_pipeline_adapter_delete_json_returns_payload():
    adapter = HttpPipelineAdapter(_request())

    with patch('open_webui.utils.pipeline_adapter.aiohttp.ClientSession', return_value=FakeSession(FakeResponse(payload={'deleted': True}))):
        result = await adapter.delete_json(0, 'pipelines/delete', {'id': 'pipe-1'})

    assert result == {'deleted': True}
