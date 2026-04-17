from types import SimpleNamespace
from unittest.mock import Mock, patch

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_commands import build_process_file_command
from open_webui.utils.retrieval_submission import resolve_retrieval_transport, submit_file_retrieval
from open_webui.utils.retrieval_transport import LocalRetrievalTransport


def _file_model(file_id: str = 'file-1') -> FileModel:
    return FileModel(
        id=file_id,
        user_id='user-1',
        hash=None,
        filename='doc.txt',
        path='/tmp/doc.txt',
        data={},
        meta={'content_type': 'text/plain'},
        created_at=1,
        updated_at=1,
    )


def test_submit_file_retrieval_delegates_to_request_transport():
    transport = Mock()
    transport.submit_file_job.return_value = ('queued-file', {'job_id': 'job-1'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=transport)))
    file_item = _file_model()
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with patch('open_webui.utils.retrieval_submission.get_retrieval_transport', return_value=transport) as get_transport:
        returned_file, retrieval_job = submit_file_retrieval(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=None,
            db=db,
        )

    get_transport.assert_called_once_with(request)
    transport.submit_file_job.assert_called_once_with(
        request,
        file_item=file_item,
        user_id='user-1',
        command=command,
        background_tasks=None,
        db=db,
    )
    assert returned_file == 'queued-file'
    assert retrieval_job == {'job_id': 'job-1'}


def test_submit_file_retrieval_forces_local_transport_for_inline_commands():
    request_transport = Mock()
    explicit_transport = Mock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=request_transport)))
    file_item = _file_model()
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='knowledge_reindex',
        processing_mode='inline',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_submission.get_retrieval_transport', return_value=request_transport) as get_transport,
        patch.object(LocalRetrievalTransport, 'submit_file_job', return_value=('queued-file', {'job_id': 'job-1'})) as submit_local,
    ):
        returned_file, retrieval_job = submit_file_retrieval(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=None,
            db=db,
            transport=explicit_transport,
        )

    get_transport.assert_not_called()
    explicit_transport.submit_file_job.assert_not_called()
    submit_local.assert_called_once_with(
        request,
        file_item=file_item,
        user_id='user-1',
        command=command,
        background_tasks=None,
        db=db,
    )
    assert returned_file == 'queued-file'
    assert retrieval_job == {'job_id': 'job-1'}


def test_submit_file_retrieval_uses_explicit_transport_override():
    request_transport = Mock()
    explicit_transport = Mock()
    explicit_transport.submit_file_job.return_value = ('queued-file', {'job_id': 'job-1'})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=request_transport)))
    file_item = _file_model()
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with patch('open_webui.utils.retrieval_submission.get_retrieval_transport', return_value=request_transport) as get_transport:
        returned_file, retrieval_job = submit_file_retrieval(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=None,
            db=db,
            transport=explicit_transport,
        )

    get_transport.assert_not_called()
    explicit_transport.submit_file_job.assert_called_once_with(
        request,
        file_item=file_item,
        user_id='user-1',
        command=command,
        background_tasks=None,
        db=db,
    )
    assert returned_file == 'queued-file'
    assert retrieval_job == {'job_id': 'job-1'}


def test_resolve_retrieval_transport_returns_local_for_inline_commands():
    request_transport = Mock()
    explicit_transport = Mock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=request_transport)))
    command = build_process_file_command(
        file_id='file-1',
        source='content_update',
        processing_mode='inline',
        content_type='text/plain',
    )

    with patch('open_webui.utils.retrieval_submission.get_retrieval_transport', return_value=request_transport) as get_transport:
        transport = resolve_retrieval_transport(request, command=command, transport=explicit_transport)

    get_transport.assert_not_called()
    assert isinstance(transport, LocalRetrievalTransport)
