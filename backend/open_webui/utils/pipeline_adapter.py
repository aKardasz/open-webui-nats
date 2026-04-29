import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL, NATS_CONNECT_TIMEOUT, NATS_NAME, NATS_URL

log = logging.getLogger(__name__)
PIPELINE_STAGE_JOB_STREAM = 'owui_pipeline_jobs'
PIPELINE_STAGE_JOB_SUBJECT = 'owui.cmd.pipeline.stage.run'


class PipelineAdapterError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def build_pipeline_adapter(request: Any, *, transport: str = 'http'):
    if transport == 'http':
        return HttpPipelineAdapter(request)
    if transport == 'nats':
        return NatsPipelineAdapter(request)
    raise PipelineAdapterError(404, f'Pipeline transport not found: {transport}')


def get_pipeline_adapter(request: Any):
    factory = getattr(request.app.state, 'pipeline_adapter_factory', None)
    if callable(factory):
        return factory(request)

    transport = getattr(request.app.state.config, 'PIPELINE_INTERNAL_TRANSPORT', 'http')
    return build_pipeline_adapter(request, transport=transport)


@dataclass
class HttpPipelineAdapter:
    request: Any

    def _resolve_target(self, url_idx: Any) -> tuple[str | None, str | None]:
        try:
            url_idx = int(url_idx)
        except Exception:
            return None, None

        url = self.request.app.state.config.OPENAI_API_BASE_URLS[url_idx]
        key = self.request.app.state.config.OPENAI_API_KEYS[url_idx]
        if not key:
            return None, None
        return url, key

    async def _response_json(self, response, error_detail: str) -> dict:
        try:
            response.raise_for_status()
        except aiohttp.ClientResponseError:
            detail = await self._read_error_detail(response)
            raise PipelineAdapterError(response.status, detail or error_detail)

        return await response.json()

    async def _read_error_detail(self, response):
        if response.content_type and 'application/json' in response.content_type:
            try:
                return await response.json()
            except Exception:
                return None
        return None

    async def _request_json(
        self,
        method: str,
        *,
        url_idx: Any,
        path: str,
        error_detail: str,
        json_payload: dict | None = None,
        data_payload=None,
    ) -> dict:
        url, key = self._resolve_target(url_idx)
        if not url or not key:
            raise PipelineAdapterError(404, 'Pipeline not found')

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.request(
                method,
                f'{url}/{path.lstrip("/")}',
                headers={'Authorization': f'Bearer {key}'},
                json=json_payload,
                data=data_payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                return await self._response_json(response, error_detail)

    async def invoke_filter(self, pipeline: dict, stage: str, *, user: dict, payload: dict) -> dict:
        if not self._resolve_target(pipeline.get('urlIdx'))[0]:
            return payload

        request_data = {
            'user': user,
            'body': payload,
        }

        return await self._request_json(
            'POST',
            url_idx=pipeline.get('urlIdx'),
            path=f'{pipeline["id"]}/filter/{stage}',
            error_detail='Pipeline filter request failed',
            json_payload=request_data,
        )

    async def get_json(self, url_idx: Any, path: str) -> dict:
        return await self._request_json(
            'GET',
            url_idx=url_idx,
            path=path,
            error_detail='Pipeline request failed',
        )

    async def post_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        return await self._request_json(
            'POST',
            url_idx=url_idx,
            path=path,
            error_detail='Pipeline request failed',
            json_payload=payload,
        )

    async def delete_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        return await self._request_json(
            'DELETE',
            url_idx=url_idx,
            path=path,
            error_detail='Pipeline request failed',
            json_payload=payload,
        )

    async def upload_file(self, url_idx: Any, path: str, *, file_path: str, filename: str) -> dict:
        with open(Path(file_path), 'rb') as f:
            form_data = aiohttp.FormData()
            form_data.add_field(
                'file',
                f,
                filename=filename,
                content_type='application/octet-stream',
            )
            return await self._request_json(
                'POST',
                url_idx=url_idx,
                path=path,
                error_detail='Pipeline upload failed',
                data_payload=form_data,
            )


@dataclass
class NatsPipelineAdapter:
    request: Any

    def __post_init__(self):
        self.http_adapter = HttpPipelineAdapter(self.request)

    async def invoke_filter(self, pipeline: dict, stage: str, *, user: dict, payload: dict) -> dict:
        if not pipeline.get('id'):
            return payload

        nats_url = getattr(self.request.app.state.config, 'NATS_URL', None) or NATS_URL
        if not nats_url:
            return await self.http_adapter.invoke_filter(pipeline, stage, user=user, payload=payload)

        envelope = {
            'trace_id': f'trace_pipeline_{uuid4().hex}',
            'payload_version': 'v1',
            'payload': {
                'pipeline_id': pipeline['id'],
                'pipeline': pipeline,
                'stage': stage,
                'url_idx': pipeline.get('urlIdx'),
                'user': user,
                'body': payload,
            },
        }

        try:
            if _is_durable_pipeline_stage(pipeline):
                response_payload = await self._request_durable_stage(envelope)
            else:
                response_payload = await self._request_nats(envelope)
            return self._extract_filter_payload(response_payload)
        except Exception:
            log.exception(
                'Pipeline NATS request/reply failed for pipeline %s stage %s; falling back to HTTP compatibility path.',
                pipeline.get('id'),
                stage,
            )
            return await self.http_adapter.invoke_filter(pipeline, stage, user=user, payload=payload)

    async def get_json(self, url_idx: Any, path: str) -> dict:
        return await self.http_adapter.get_json(url_idx, path)

    async def post_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        return await self.http_adapter.post_json(url_idx, path, payload)

    async def delete_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        return await self.http_adapter.delete_json(url_idx, path, payload)

    async def upload_file(self, url_idx: Any, path: str, *, file_path: str, filename: str) -> dict:
        return await self.http_adapter.upload_file(url_idx, path, file_path=file_path, filename=filename)

    async def _request_nats(self, envelope: dict) -> dict:
        nats_url = getattr(self.request.app.state.config, 'NATS_URL', None) or NATS_URL
        servers = [server.strip() for server in nats_url.split(',') if server.strip()]
        subject = getattr(self.request.app.state.config, 'PIPELINE_NATS_SUBJECT', 'owui.cmd.pipeline.run')
        timeout = getattr(self.request.app.state.config, 'PIPELINE_NATS_REQUEST_TIMEOUT', 10.0)
        nc = await _connect_nats(
            servers=servers,
            name=f'{NATS_NAME}-pipeline-{getattr(self.request.app.state, "instance_id", "runtime")}',
            connect_timeout=NATS_CONNECT_TIMEOUT,
        )
        try:
            response = await nc.request(subject, json.dumps(envelope).encode('utf-8'), timeout=timeout)
            try:
                return json.loads(response.data.decode('utf-8'))
            except Exception as exc:
                raise PipelineAdapterError(502, 'Pipeline request returned invalid JSON') from exc
        finally:
            await nc.drain()

    async def _request_durable_stage(self, envelope: dict) -> dict:
        nats_url = getattr(self.request.app.state.config, 'NATS_URL', None) or NATS_URL
        servers = [server.strip() for server in nats_url.split(',') if server.strip()]
        timeout = getattr(self.request.app.state.config, 'PIPELINE_NATS_REQUEST_TIMEOUT', 10.0)
        reply_subject = f'owui.reply.pipeline.stage.{uuid4().hex}'
        envelope = {
            **envelope,
            'reply_subject': reply_subject,
        }
        nc = await _connect_nats(
            servers=servers,
            name=f'{NATS_NAME}-pipeline-stage-{getattr(self.request.app.state, "instance_id", "runtime")}',
            connect_timeout=NATS_CONNECT_TIMEOUT,
        )
        try:
            subscription = await nc.subscribe(reply_subject)
            if hasattr(nc, 'flush'):
                await nc.flush()
            await nc.jetstream().publish(
                PIPELINE_STAGE_JOB_SUBJECT,
                json.dumps(envelope).encode('utf-8'),
                stream=PIPELINE_STAGE_JOB_STREAM,
            )
            response = await subscription.next_msg(timeout=timeout)
            try:
                return json.loads(response.data.decode('utf-8'))
            except Exception as exc:
                raise PipelineAdapterError(502, 'Pipeline durable stage returned invalid JSON') from exc
            finally:
                await subscription.unsubscribe()
        finally:
            await nc.drain()

    def _extract_filter_payload(self, response_payload: dict) -> dict:
        if response_payload.get('status') != 'ok':
            raise PipelineAdapterError(
                response_payload.get('status_code', 502),
                response_payload.get('detail') or 'Pipeline request failed',
            )

        data = response_payload.get('data')
        if isinstance(data, dict) and 'body' in data and isinstance(data['body'], dict):
            return data['body']
        if isinstance(data, dict):
            return data

        raise PipelineAdapterError(502, 'Pipeline request returned an invalid response payload')


async def _connect_nats(*, servers: list[str], name: str, connect_timeout: float):
    import nats

    return await nats.connect(
        servers=servers,
        name=name,
        connect_timeout=connect_timeout,
    )


def _is_durable_pipeline_stage(pipeline: dict) -> bool:
    pipeline_meta = pipeline.get('pipeline') or {}
    return pipeline_meta.get('execution') == 'jetstream' or bool(pipeline_meta.get('durable_stage'))
