from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from open_webui.models.files import FileModel
from open_webui.utils.task_messaging import (
    RETRIEVAL_JOB_COMPLETED_SUBJECT,
    RETRIEVAL_JOB_PROGRESS_SUBJECT,
    RETRIEVAL_JOB_STARTED_SUBJECT,
)
from open_webui.utils.retrieval_service import (
    ProcessFileForm,
    RetrievalServiceError,
    _resolve_retrieval_job,
    process_file,
)


def _request(*, bypass: bool = True):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    BYPASS_EMBEDDING_AND_RETRIEVAL=bypass,
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
        patch('open_webui.utils.retrieval_service.publish_app_event_sync') as publish,
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
    subjects = [call.args[1] for call in publish.call_args_list]
    assert subjects == [
        RETRIEVAL_JOB_STARTED_SUBJECT,
        RETRIEVAL_JOB_PROGRESS_SUBJECT,
        RETRIEVAL_JOB_COMPLETED_SUBJECT,
    ]


def test_process_file_non_bypass_path_publishes_progress_before_completion():
    request = _request(bypass=False)
    file_item = _file_item()
    user = SimpleNamespace(id='user-1', role='user')
    db = Mock()
    db.commit = Mock()
    session = Mock()

    @contextmanager
    def fake_get_db():
        yield session

    with (
        patch('open_webui.utils.retrieval_service.Files.get_file_by_id_and_user_id', return_value=file_item),
        patch('open_webui.utils.retrieval_service.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_service.Files.update_file_metadata_by_id'),
        patch('open_webui.utils.retrieval_service.Files.update_file_hash_by_id'),
        patch('open_webui.utils.retrieval_service.save_docs_to_vector_db', return_value=True),
        patch('open_webui.utils.retrieval_service.get_db', side_effect=fake_get_db),
        patch('open_webui.utils.retrieval_service.publish_app_event_sync') as publish,
    ):
        result = process_file(
            request,
            ProcessFileForm(file_id='file-1', content='hello'),
            user=user,
            db=db,
        )

    assert result['status'] is True
    subjects = [call.args[1] for call in publish.call_args_list]
    assert subjects == [
        RETRIEVAL_JOB_STARTED_SUBJECT,
        RETRIEVAL_JOB_PROGRESS_SUBJECT,
        RETRIEVAL_JOB_PROGRESS_SUBJECT,
        RETRIEVAL_JOB_COMPLETED_SUBJECT,
    ]
    progress_events = [call.args[2]['data'] for call in publish.call_args_list if call.args[1] == RETRIEVAL_JOB_PROGRESS_SUBJECT]
    assert progress_events[0]['step'] == 'content_extracted'
    assert progress_events[0]['progress'] == 50
    assert progress_events[1]['step'] == 'indexed'
    assert progress_events[1]['progress'] == 90


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
