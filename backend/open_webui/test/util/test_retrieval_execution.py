from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_commands import build_process_file_command
from open_webui.utils.retrieval_jobs import build_retrieval_job
from open_webui.utils.retrieval_execution import execute_retrieval_job


def _request():
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    STT_SUPPORTED_CONTENT_TYPES=[],
                    CONTENT_EXTRACTION_ENGINE='',
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


def _job(command: dict) -> dict:
    return build_retrieval_job(
        actor_id='user-1',
        resource_id=command['file_id'],
        job_id='job-1',
        payload=command,
    )


def test_execute_retrieval_job_processes_inline_content():
    request = _request()
    file_item = _file_item()
    user = SimpleNamespace(id='user-1', role='user')
    command = build_process_file_command(
        file_id='file-1',
        source='content_update',
        processing_mode='inline',
        inline_content='hello',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id', return_value=user),
        patch('open_webui.utils.retrieval_execution.process_file_service') as process,
    ):
        execute_retrieval_job(request, _job(command), db=Mock())

    process.assert_called_once()
    form = process.call_args.args[1]
    assert form.file_id == 'file-1'
    assert form.content == 'hello'
    assert form.job_id == 'job-1'


def test_execute_retrieval_job_does_not_emit_duplicate_failed_event_after_process_file_boundary():
    request = _request()
    file_item = _file_item()
    user = SimpleNamespace(id='user-1', role='user')
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='inline',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id', return_value=user),
        patch('open_webui.utils.retrieval_execution.process_file_service', side_effect=Exception('boom')),
        patch('open_webui.utils.retrieval_execution.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_execution.publish_app_event_sync') as publish,
    ):
        with pytest.raises(Exception, match='boom'):
            execute_retrieval_job(request, _job(command), db=Mock())

    publish.assert_not_called()


def test_execute_retrieval_job_reraises_inline_failures():
    request = _request()
    file_item = _file_item()
    user = SimpleNamespace(id='user-1', role='user')
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='inline',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id', return_value=user),
        patch('open_webui.utils.retrieval_execution.process_file_service', side_effect=Exception('boom')),
        patch('open_webui.utils.retrieval_execution.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_execution.publish_app_event_sync'),
    ):
        with pytest.raises(Exception, match='boom'):
            execute_retrieval_job(request, _job(command), db=Mock())


def test_execute_retrieval_job_emits_failed_event_for_preprocessing_failures():
    request = _request()
    file_item = _file_item().model_copy(update={'meta': {'content_type': 'image/png', 'data': {}}})
    user = SimpleNamespace(id='user-1', role='user')
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='inline',
        content_type='image/png',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id', return_value=user),
        patch('open_webui.utils.retrieval_execution._is_text_file', return_value=False),
        patch('open_webui.utils.retrieval_execution.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_execution.publish_app_event_sync') as publish,
    ):
        with pytest.raises(Exception, match='File type image/png is not supported for processing'):
            execute_retrieval_job(request, _job(command), db=Mock())

    publish.assert_called_once()
    event = publish.call_args.args[2]
    assert event['data']['job_id'] == 'job-1'
    assert event['data']['collection_name'] == 'file-file-1'
    assert event['data']['status'] == 'failed'


def test_execute_retrieval_job_emits_failed_event_when_file_missing():
    request = _request()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=None),
        patch('open_webui.utils.retrieval_execution.publish_app_event_sync') as publish,
    ):
        execute_retrieval_job(request, _job(command), db=Mock())

    publish.assert_called_once()
    event = publish.call_args.args[2]
    assert event['data']['job_id'] == 'job-1'
    assert event['data']['file_id'] == 'file-1'
    assert event['data']['status'] == 'failed'


def test_execute_retrieval_job_emits_failed_event_when_user_missing():
    request = _request()
    file_item = _file_item()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id', return_value=None),
        patch('open_webui.utils.retrieval_execution.Files.update_file_data_by_id'),
        patch('open_webui.utils.retrieval_execution.publish_app_event_sync') as publish,
    ):
        execute_retrieval_job(request, _job(command), db=Mock())

    publish.assert_called_once()
    event = publish.call_args.args[2]
    assert event['data']['job_id'] == 'job-1'
    assert event['data']['file_id'] == 'file-1'
    assert event['data']['status'] == 'failed'


def test_execute_retrieval_job_skips_duplicate_completed_jobs():
    request = _request()
    file_item = _file_item().model_copy(
        update={'data': {'retrieval_job': {'job_id': 'job-1', 'status': 'completed'}}}
    )
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_execution.Files.get_file_by_id', return_value=file_item),
        patch('open_webui.utils.retrieval_execution.process_file_service') as process,
        patch('open_webui.utils.retrieval_execution.Users.get_user_by_id') as get_user,
    ):
        execute_retrieval_job(request, _job(command), db=Mock())

    process.assert_not_called()
    get_user.assert_not_called()
