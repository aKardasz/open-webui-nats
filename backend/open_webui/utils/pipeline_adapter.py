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

    async def invoke_filter(self, pipeline: dict, stage: str, *, user: dict, payload: dict) -> dict:
        url, key = self._resolve_target(pipeline.get('urlIdx'))
        if not url or not key:
            return payload

        request_data = {
            'user': user,
            'body': payload,
        }

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                f'{url}/{pipeline["id"]}/filter/{stage}',
                headers={'Authorization': f'Bearer {key}'},
                json=request_data,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                try:
                    response.raise_for_status()
                except aiohttp.ClientResponseError:
                    detail = None
                    if response.content_type and 'application/json' in response.content_type:
                        try:
                            detail = await response.json()
                        except Exception:
                            detail = None
                    raise PipelineAdapterError(response.status, detail or 'Pipeline filter request failed')

                return await response.json()

    async def get_json(self, url_idx: Any, path: str) -> dict:
        url, key = self._resolve_target(url_idx)
        if not url or not key:
            raise PipelineAdapterError(404, 'Pipeline not found')

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                f'{url}/{path.lstrip("/")}',
                headers={'Authorization': f'Bearer {key}'},
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                try:
                    response.raise_for_status()
                except aiohttp.ClientResponseError:
                    detail = None
                    if response.content_type and 'application/json' in response.content_type:
                        try:
                            detail = await response.json()
                        except Exception:
                            detail = None
                    raise PipelineAdapterError(response.status, detail or 'Pipeline request failed')

                return await response.json()

    async def post_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        url, key = self._resolve_target(url_idx)
        if not url or not key:
            raise PipelineAdapterError(404, 'Pipeline not found')

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                f'{url}/{path.lstrip("/")}',
                headers={'Authorization': f'Bearer {key}'},
                json=payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                try:
                    response.raise_for_status()
                except aiohttp.ClientResponseError:
                    detail = None
                    if response.content_type and 'application/json' in response.content_type:
                        try:
                            detail = await response.json()
                        except Exception:
                            detail = None
                    raise PipelineAdapterError(response.status, detail or 'Pipeline request failed')

                return await response.json()

    async def delete_json(self, url_idx: Any, path: str, payload: dict) -> dict:
        url, key = self._resolve_target(url_idx)
        if not url or not key:
            raise PipelineAdapterError(404, 'Pipeline not found')

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.delete(
                f'{url}/{path.lstrip("/")}',
                headers={'Authorization': f'Bearer {key}'},
                json=payload,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                try:
                    response.raise_for_status()
                except aiohttp.ClientResponseError:
                    detail = None
                    if response.content_type and 'application/json' in response.content_type:
                        try:
                            detail = await response.json()
                        except Exception:
                            detail = None
                    raise PipelineAdapterError(response.status, detail or 'Pipeline request failed')

                return await response.json()

    async def upload_file(self, url_idx: Any, path: str, *, file_path: str, filename: str) -> dict:
        url, key = self._resolve_target(url_idx)
        if not url or not key:
            raise PipelineAdapterError(404, 'Pipeline not found')

        async with aiohttp.ClientSession(trust_env=True) as session:
            with open(Path(file_path), 'rb') as f:
                form_data = aiohttp.FormData()
                form_data.add_field(
                    'file',
                    f,
                    filename=filename,
                    content_type='application/octet-stream',
                )
                async with session.post(
                    f'{url}/{path.lstrip("/")}',
                    headers={'Authorization': f'Bearer {key}'},
                    data=form_data,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as response:
                    try:
                        response.raise_for_status()
                    except aiohttp.ClientResponseError:
                        detail = None
                        if response.content_type and 'application/json' in response.content_type:
                            try:
                                detail = await response.json()
                            except Exception:
                                detail = None
                        raise PipelineAdapterError(response.status, detail or 'Pipeline upload failed')

                    return await response.json()
