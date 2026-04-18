import aiohttp
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL


class PipelineAdapterError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class HttpPipelineAdapter:
    request: Any

    def _resolve_target(self, url_idx: Any) -> tuple[Optional[str], Optional[str]]:
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
