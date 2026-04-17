from types import SimpleNamespace
from unittest.mock import Mock, patch

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_commands import build_process_file_command
from open_webui.utils.retrieval_transport import (
    JetStreamRetrievalTransport,
    LocalRetrievalTransport,
    build_retrieval_transport,
    get_retrieval_transport,
)


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


def test_local_retrieval_transport_queues_background_job_and_emits_event():
    transport = LocalRetrievalTransport()
    file_item = _file_model()
    queued_file = file_item.model_copy(update={'data': {'status': 'pending'}})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    background_tasks = Mock()
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_transport.Users.get_user_by_id', return_value=SimpleNamespace(id='user-1', role='user')),
        patch('open_webui.utils.retrieval_transport.Files.update_file_data_by_id', return_value=queued_file) as update,
        patch('open_webui.utils.retrieval_transport.publish_app_event_sync') as publish,
    ):
        returned_file, retrieval_job = transport.submit_file_job(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=background_tasks,
            db=db,
        )

    assert returned_file == queued_file
    assert retrieval_job['resource_id'] == 'file-1'
    assert retrieval_job['payload']['processing_mode'] == 'background_task'
    assert retrieval_job['payload']['source'] == 'upload'
    update.assert_called_once()
    publish.assert_called_once()
    background_tasks.add_task.assert_called_once()
    assert background_tasks.add_task.call_args.args[1:] == (request, retrieval_job)


def test_local_retrieval_transport_runs_inline_job_and_refreshes_file():
    transport = LocalRetrievalTransport()
    file_item = _file_model()
    queued_file = file_item.model_copy(update={'data': {'status': 'pending'}})
    completed_file = file_item.model_copy(update={'data': {'status': 'completed'}})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='inline',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_transport.Users.get_user_by_id', return_value=SimpleNamespace(id='user-1', role='user')),
        patch('open_webui.utils.retrieval_transport.Files.update_file_data_by_id', return_value=queued_file),
        patch('open_webui.utils.retrieval_transport.Files.get_file_by_id', return_value=completed_file) as get_file,
        patch('open_webui.utils.retrieval_transport.publish_app_event_sync'),
        patch('open_webui.utils.retrieval_transport.execute_retrieval_job') as execute,
    ):
        returned_file, retrieval_job = transport.submit_file_job(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=None,
            db=db,
        )

    execute.assert_called_once_with(request, retrieval_job, db=db)
    get_file.assert_called_once_with('file-1', db=db)
    assert returned_file == completed_file


def test_local_retrieval_transport_uses_custom_collection_name_and_payload_extra():
    transport = LocalRetrievalTransport()
    file_item = _file_model()
    queued_file = file_item.model_copy(update={'data': {'status': 'pending'}})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    command = build_process_file_command(
        file_id='file-1',
        source='knowledge_add',
        processing_mode='inline',
        content_type='text/plain',
        collection_name='knowledge-1',
    )

    with (
        patch('open_webui.utils.retrieval_transport.Users.get_user_by_id', return_value=SimpleNamespace(id='user-1', role='user')),
        patch('open_webui.utils.retrieval_transport.Files.update_file_data_by_id', return_value=queued_file),
        patch('open_webui.utils.retrieval_transport.Files.get_file_by_id', return_value=queued_file),
        patch('open_webui.utils.retrieval_transport.publish_app_event_sync'),
        patch('open_webui.utils.retrieval_transport.execute_retrieval_job'),
    ):
        _, retrieval_job = transport.submit_file_job(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            db=Mock(),
        )

    assert retrieval_job['payload']['collection_name'] == 'knowledge-1'
    assert retrieval_job['payload']['source'] == 'knowledge_add'
    assert retrieval_job['payload']['content_supplied'] is False


def test_get_retrieval_transport_prefers_app_state_transport():
    custom_transport = Mock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=custom_transport)))

    assert get_retrieval_transport(request) is custom_transport


def test_get_retrieval_transport_falls_back_to_local_transport():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    transport = get_retrieval_transport(request)

    assert isinstance(transport, LocalRetrievalTransport)


def test_build_retrieval_transport_returns_local_by_default():
    transport = build_retrieval_transport('local', '')

    assert isinstance(transport, LocalRetrievalTransport)


def test_build_retrieval_transport_returns_jetstream_transport():
    transport = build_retrieval_transport('jetstream', 'nats://nats:4222')

    assert isinstance(transport, JetStreamRetrievalTransport)


def test_jetstream_transport_publishes_job_to_jetstream():
    transport = JetStreamRetrievalTransport(nats_url='nats://nats:4222')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    file_item = _file_model()
    db = Mock()
    queued_file = file_item.model_copy(update={'data': {'status': 'pending'}})
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_transport.Users.get_user_by_id', return_value=SimpleNamespace(id='user-1', role='user')),
        patch('open_webui.utils.retrieval_transport.Files.update_file_data_by_id', return_value=queued_file),
        patch('open_webui.utils.retrieval_transport.publish_app_event_sync'),
        patch('open_webui.utils.retrieval_transport.publish_retrieval_job_sync') as publish,
    ):
        returned_file, retrieval_job = transport.submit_file_job(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=None,
            db=db,
        )

    publish.assert_called_once_with(request.app, 'nats://nats:4222', retrieval_job)
    assert returned_file == queued_file
    assert retrieval_job['payload']['delivery_mode'] == 'jetstream'


def test_jetstream_transport_falls_back_to_local_execution_when_publish_fails():
    transport = JetStreamRetrievalTransport(nats_url='nats://nats:4222')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    file_item = _file_model()
    queued_file = file_item.model_copy(update={'data': {'status': 'pending'}})
    completed_file = file_item.model_copy(update={'data': {'status': 'completed'}})
    background_tasks = Mock()
    db = Mock()
    command = build_process_file_command(
        file_id='file-1',
        source='upload',
        processing_mode='background_task',
        content_type='text/plain',
    )

    with (
        patch('open_webui.utils.retrieval_transport.Users.get_user_by_id', return_value=SimpleNamespace(id='user-1', role='user')),
        patch('open_webui.utils.retrieval_transport.Files.update_file_data_by_id', return_value=queued_file),
        patch('open_webui.utils.retrieval_transport.publish_app_event_sync'),
        patch('open_webui.utils.retrieval_transport.publish_retrieval_job_sync', side_effect=RuntimeError('boom')),
        patch('open_webui.utils.retrieval_transport.execute_retrieval_job') as execute,
        patch('open_webui.utils.retrieval_transport.Files.get_file_by_id', return_value=completed_file),
    ):
        returned_file, retrieval_job = transport.submit_file_job(
            request,
            file_item=file_item,
            user_id='user-1',
            command=command,
            background_tasks=background_tasks,
            db=db,
        )

    execute.assert_not_called()
    assert background_tasks.add_task.call_args.args[1:] == (request, retrieval_job)
    assert returned_file == queued_file
