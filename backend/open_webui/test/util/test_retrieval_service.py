from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_service import (
    ProcessFileForm,
    RetrievalServiceError,
    _resolve_retrieval_job,
    process_file,
)


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    BYPASS_EMBEDDING_AND_RETRIEVAL=True,
                )
            )
        )
    )


def _file_item() -> FileModel:
    return FileModel(
        id='file-1',
        user_id='user-1',
        hash=None,
        filename='doc.txt',
        path='/tmp/doc.txt',
        data={},
        meta={'content_type': 'text/plain', 'data': {}},
        created_at=1,
        updated_at=1,
    )


def test_process_file_raises_not_found_when_user_cannot_access_file():
    request = _request()
    user = SimpleNamespace(id='user-1', role='user')

    with patch('open_webui.utils.retrieval_service.Files.get_file_by_id_and_user_id', return_value=None):
        with pytest.raises(RetrievalServiceError) as exc_info:
            process_file(request, ProcessFileForm(file_id='file-1'), user=user, db=Mock())

    assert exc_info.value.status_code == 404


def test_process_file_bypass_path_returns_completed_payload():
    request = _request()
    file_item = _file_item()
    user = SimpleNamespace(id='user-1', role='user')

    with (
        patch('open_webui.utils.retrieval_service.Files.get_file_by_id_and_user_id', return_value=file_item),
        patch('open_webui.utils.retrieval_service.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_service.Files.update_file_hash_by_id'),
        patch('open_webui.utils.retrieval_service.publish_app_event_sync'),
    ):
        result = process_file(
            request,
            ProcessFileForm(file_id='file-1', content='hello'),
            user=user,
            db=Mock(),
        )

    assert result == {
        'status': True,
        'collection_name': None,
        'filename': 'doc.txt',
        'content': 'hello',
    }


def test_resolve_retrieval_job_uses_process_file_command_contract():
    file_item = _file_item()

    retrieval_job = _resolve_retrieval_job(
        file_item,
        'user-1',
        'file-file-1',
        ProcessFileForm(file_id='file-1', content='hello'),
    )

    assert retrieval_job['payload'] == {
        'command_type': 'process_file',
        'file_id': 'file-1',
        'source': 'process_file',
        'processing_mode': 'inline',
        'content_type': 'text/plain',
        'collection_name': 'file-file-1',
        'inline_content': 'hello',
        'content_supplied': True,
    }
