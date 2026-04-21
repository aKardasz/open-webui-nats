from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.routers.pipelines import get_pipelines, process_pipeline_inlet_filter
from open_webui.utils.pipeline_adapter import (
    HttpPipelineAdapter,
    NatsPipelineAdapter,
    PipelineAdapterError,
    build_pipeline_adapter,
    get_pipeline_adapter,
)


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

    def request(self, *_args, **_kwargs):
        return self._response


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                instance_id='instance-1',
                config=SimpleNamespace(
                    OPENAI_API_BASE_URLS=['http://pipeline.example'],
                    OPENAI_API_KEYS=['secret'],
                    NATS_URL='nats://nats:4222',
                    PIPELINE_INTERNAL_TRANSPORT='http',
                    PIPELINE_NATS_SUBJECT='owui.cmd.pipeline.run',
                    PIPELINE_NATS_REQUEST_TIMEOUT=10.0,
                )
            )
        )
    )


@pytest.mark.asyncio
async def test_http_pipeline_adapter_invokes_filter():
    adapter = HttpPipelineAdapter(_request())
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}

    with patch(
        'open_webui.utils.pipeline_adapter.aiohttp.ClientSession',
        return_value=FakeSession(FakeResponse(payload={'ok': True})),
    ):
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

    with patch(
        'open_webui.utils.pipeline_adapter.aiohttp.ClientSession',
        return_value=FakeSession(FakeResponse(payload={'items': []})),
    ):
        result = await adapter.get_json(0, 'pipelines')

    assert result == {'items': []}


@pytest.mark.asyncio
async def test_http_pipeline_adapter_delete_json_returns_payload():
    adapter = HttpPipelineAdapter(_request())

    with patch(
        'open_webui.utils.pipeline_adapter.aiohttp.ClientSession',
        return_value=FakeSession(FakeResponse(payload={'deleted': True})),
    ):
        result = await adapter.delete_json(0, 'pipelines/delete', {'id': 'pipe-1'})

    assert result == {'deleted': True}


@pytest.mark.asyncio
async def test_http_pipeline_adapter_upload_file_returns_payload(tmp_path):
    adapter = HttpPipelineAdapter(_request())
    file_path = tmp_path / 'pipe.py'
    file_path.write_text('print("ok")', encoding='utf-8')

    with patch(
        'open_webui.utils.pipeline_adapter.aiohttp.ClientSession',
        return_value=FakeSession(FakeResponse(payload={'uploaded': True})),
    ):
        result = await adapter.upload_file(0, 'pipelines/upload', file_path=str(file_path), filename='pipe.py')

    assert result == {'uploaded': True}


def test_build_pipeline_adapter_returns_http_adapter_by_default():
    adapter = build_pipeline_adapter(_request())

    assert isinstance(adapter, HttpPipelineAdapter)


def test_build_pipeline_adapter_returns_nats_adapter_when_requested():
    adapter = build_pipeline_adapter(_request(), transport='nats')

    assert isinstance(adapter, NatsPipelineAdapter)


def test_get_pipeline_adapter_uses_request_factory_when_present():
    request = _request()
    custom_adapter = object()
    request.app.state.pipeline_adapter_factory = lambda _request: custom_adapter

    assert get_pipeline_adapter(request) is custom_adapter


def test_get_pipeline_adapter_builds_nats_adapter_when_configured():
    request = _request()
    request.app.state.config.PIPELINE_INTERNAL_TRANSPORT = 'nats'

    assert isinstance(get_pipeline_adapter(request), NatsPipelineAdapter)


@pytest.mark.asyncio
async def test_process_pipeline_inlet_filter_uses_adapter_factory():
    request = _request()
    adapter = SimpleNamespace(invoke_filter=AsyncMock(return_value={'model': 'model-1', 'ok': True}))
    request.app.state.pipeline_adapter_factory = lambda _request: adapter
    user = SimpleNamespace(id='user-1', email='user@example.com', name='User', role='admin')
    payload = {'model': 'model-1'}
    models = {
        'model-1': {
            'id': 'model-1',
            'urlIdx': 0,
            'pipeline': {'type': 'filter', 'pipelines': ['*'], 'priority': 0},
        }
    }

    result = await process_pipeline_inlet_filter(request, payload, user, models)

    assert result == {'model': 'model-1', 'ok': True}
    assert adapter.invoke_filter.await_count == 2


@pytest.mark.asyncio
async def test_get_pipelines_uses_adapter_factory():
    request = _request()
    adapter = SimpleNamespace(get_json=AsyncMock(return_value={'items': []}))
    request.app.state.pipeline_adapter_factory = lambda _request: adapter

    result = await get_pipelines(request, urlIdx=0, user=SimpleNamespace(id='admin-1', role='admin'))

    assert result == {'items': []}
    adapter.get_json.assert_awaited_once_with(0, 'pipelines')


class FakeNatsResponse:
    def __init__(self, payload):
        self.data = payload


class FakeNatsConnection:
    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.request = AsyncMock(side_effect=self._handle_request)
        self.drain = AsyncMock()
        self.publish = AsyncMock()
        reply_payload = payload or b'{"status":"ok","data":{"body":{"durable":true}}}'
        self._subscription = SimpleNamespace(
            next_msg=AsyncMock(return_value=FakeNatsResponse(reply_payload)),
            unsubscribe=AsyncMock(),
        )
        self.subscribe = AsyncMock(return_value=self._subscription)
        self._js = SimpleNamespace(publish=AsyncMock())

    async def _handle_request(self, *_args, **_kwargs):
        if self._error is not None:
            raise self._error
        return FakeNatsResponse(self._payload)

    def jetstream(self):
        return self._js


@pytest.mark.asyncio
async def test_nats_pipeline_adapter_invokes_filter_over_request_reply():
    request = _request()
    adapter = NatsPipelineAdapter(request)
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}
    nc = FakeNatsConnection(payload=b'{"status":"ok","data":{"body":{"model":"model-1","ok":true}}}')

    with patch('open_webui.utils.pipeline_adapter._connect_nats', new=AsyncMock(return_value=nc)):
        result = await adapter.invoke_filter(
            pipeline,
            'inlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'model': 'model-1', 'ok': True}
    nc.request.assert_awaited_once()
    assert b'"pipeline"' in nc.request.await_args.args[1]
    nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_nats_pipeline_adapter_falls_back_to_http_on_request_timeout():
    request = _request()
    adapter = NatsPipelineAdapter(request)
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}
    nc = FakeNatsConnection(error=TimeoutError())

    with (
        patch('open_webui.utils.pipeline_adapter._connect_nats', new=AsyncMock(return_value=nc)),
        patch.object(
            adapter.http_adapter,
            'invoke_filter',
            new=AsyncMock(return_value={'model': 'model-1', 'fallback': True}),
        ) as http_invoke,
    ):
        result = await adapter.invoke_filter(
            pipeline,
            'outlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'model': 'model-1', 'fallback': True}
    http_invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_nats_pipeline_adapter_falls_back_to_http_on_no_responder():
    request = _request()
    adapter = NatsPipelineAdapter(request)
    pipeline = {'id': 'pipe-1', 'urlIdx': 0}
    nc = FakeNatsConnection(error=RuntimeError('no responders available'))

    with (
        patch('open_webui.utils.pipeline_adapter._connect_nats', new=AsyncMock(return_value=nc)),
        patch.object(
            adapter.http_adapter,
            'invoke_filter',
            new=AsyncMock(return_value={'model': 'model-1', 'fallback': 'http'}),
        ) as http_invoke,
    ):
        result = await adapter.invoke_filter(
            pipeline,
            'inlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'model': 'model-1', 'fallback': 'http'}
    http_invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_nats_pipeline_adapter_falls_back_to_http_when_nats_disabled():
    request = _request()
    request.app.state.config.NATS_URL = ''
    adapter = NatsPipelineAdapter(request)

    with patch.object(
        adapter.http_adapter,
        'invoke_filter',
        new=AsyncMock(return_value={'model': 'model-1', 'fallback': True}),
    ) as http_invoke:
        result = await adapter.invoke_filter(
            {'id': 'pipe-1', 'urlIdx': 0},
            'inlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'model': 'model-1', 'fallback': True}
    http_invoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_nats_pipeline_adapter_uses_durable_stage_lane_when_pipeline_marked_durable():
    request = _request()
    adapter = NatsPipelineAdapter(request)
    pipeline = {'id': 'pipe-1', 'urlIdx': 0, 'pipeline': {'execution': 'jetstream'}}
    nc = FakeNatsConnection(payload=b'{"status":"ok","data":{"body":{"durable":true}}}')

    with patch('open_webui.utils.pipeline_adapter._connect_nats', new=AsyncMock(return_value=nc)):
        result = await adapter.invoke_filter(
            pipeline,
            'inlet',
            user={'id': 'user-1'},
            payload={'model': 'model-1'},
        )

    assert result == {'durable': True}
    nc._js.publish.assert_awaited_once()
    nc.subscribe.assert_awaited_once()
    nc._subscription.next_msg.assert_awaited_once()
    nc._subscription.unsubscribe.assert_awaited_once()
