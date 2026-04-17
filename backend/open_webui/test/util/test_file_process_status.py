import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from starlette.responses import StreamingResponse

from open_webui.routers.files import get_file_process_status


def _file(status='processing', retrieval_job=None):
    payload = {
        'status': status,
        **({'retrieval_job': retrieval_job} if retrieval_job is not None else {}),
    }
    return SimpleNamespace(
        id='file-1',
        user_id='user-1',
        data=payload,
        model_dump=lambda: {'data': payload},
    )


def _user():
    return SimpleNamespace(id='user-1', role='user')


@pytest.mark.asyncio
async def test_get_file_process_status_returns_retrieval_job_record():
    retrieval_job = {'job_id': 'job-1', 'status': 'started', 'progress': 50, 'step': 'content_extracted'}

    with patch('open_webui.routers.files.Files.get_file_by_id', return_value=_file(retrieval_job=retrieval_job)):
        result = await get_file_process_status('file-1', stream=False, user=_user(), db=Mock())

    assert result == {
        'status': 'processing',
        'retrieval_job': retrieval_job,
    }


@pytest.mark.asyncio
async def test_get_file_process_status_stream_emits_retrieval_job_record():
    retrieval_job = {'job_id': 'job-1', 'status': 'started', 'progress': 90, 'step': 'indexed'}
    file_item = _file(status='completed', retrieval_job=retrieval_job)

    with patch('open_webui.routers.files.Files.get_file_by_id', return_value=file_item):
        response = await get_file_process_status('file-1', stream=True, user=_user(), db=Mock())
        assert isinstance(response, StreamingResponse)
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    payload = json.loads(chunks[0].removeprefix('data: ').strip())
    assert payload == {
        'status': 'completed',
        'retrieval_job': retrieval_job,
    }
