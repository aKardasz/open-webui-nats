import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nats.errors import TimeoutError as NatsTimeoutError
from open_webui.routers.files import get_file_process_status
from open_webui.utils.retrieval_jobs import build_retrieval_job, build_retrieval_job_record
from open_webui.utils.retrieval_worker import (
    JetStreamRetrievalWorker,
    publish_retrieval_job_sync,
    should_start_retrieval_worker,
    start_retrieval_worker_with_retry,
)


def test_publish_retrieval_job_sync_schedules_on_main_loop():
    loop = Mock()
    future = Mock()
    future.result.return_value = None
    app = SimpleNamespace(state=SimpleNamespace(main_loop=loop, instance_id='instance-1'))
    retrieval_job = {'job_id': 'job-1', 'payload': {}}

    with patch('open_webui.utils.retrieval_worker.asyncio.run_coroutine_threadsafe', return_value=future) as schedule:
        publish_retrieval_job_sync(app, 'nats://nats:4222', retrieval_job)

    schedule.assert_called_once()
    schedule.call_args.args[0].close()
    future.result.assert_called_once()


@pytest.mark.asyncio
async def test_worker_acks_messages_after_successful_execution():
    app = SimpleNamespace(state=SimpleNamespace())
    worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')
    retrieval_job = build_retrieval_job(actor_id='user-1', resource_id='file-1', job_id='job-1', payload={})
    message = SimpleNamespace(
        data=json.dumps(retrieval_job).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch('open_webui.utils.retrieval_worker.asyncio.to_thread', new=AsyncMock()) as to_thread:
        await worker._handle_message(message)

    to_thread.assert_awaited_once()
    message.ack.assert_awaited_once()
    message.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_naks_messages_after_execution_failure():
    app = SimpleNamespace(state=SimpleNamespace())
    worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')
    retrieval_job = build_retrieval_job(actor_id='user-1', resource_id='file-1', job_id='job-1', payload={})
    message = SimpleNamespace(
        data=json.dumps(retrieval_job).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch('open_webui.utils.retrieval_worker.asyncio.to_thread', new=AsyncMock(side_effect=RuntimeError('boom'))):
        await worker._handle_message(message)

    message.ack.assert_not_awaited()
    message.nak.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_acks_invalidly_signed_messages_without_executing():
    app = SimpleNamespace(state=SimpleNamespace())
    worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')
    message = SimpleNamespace(
        data=json.dumps({'job_id': 'job-1', 'payload': {}, 'signature': 'invalid'}).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch('open_webui.utils.retrieval_worker.asyncio.to_thread', new=AsyncMock()) as to_thread:
        await worker._handle_message(message)

    to_thread.assert_not_awaited()
    message.ack.assert_awaited_once()
    message.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_retrieval_worker_with_retry_retries_transient_failures_until_started():
    app = SimpleNamespace(state=SimpleNamespace(instance_id='instance-1'))
    attempts = []

    class FakeWorker:
        def __init__(self, _app, _nats_url, _instance_id):
            self.retryable_failure = False

        async def start(self):
            attempts.append('start')
            if len(attempts) == 1:
                self.retryable_failure = True
                return False
            return True

        async def close(self):
            return None

    with patch('open_webui.utils.retrieval_worker.JetStreamRetrievalWorker', FakeWorker):
        supervisor = await start_retrieval_worker_with_retry(app, 'nats://nats:4222', retry_delay=0)
        await asyncio.wait_for(supervisor._task, timeout=1)

    assert len(attempts) == 2
    await supervisor.close()


@pytest.mark.asyncio
async def test_start_retrieval_worker_with_retry_stops_on_permanent_failure():
    app = SimpleNamespace(state=SimpleNamespace(instance_id='instance-1'))
    attempts = []

    class FakeWorker:
        def __init__(self, _app, _nats_url, _instance_id):
            self.retryable_failure = False

        async def start(self):
            attempts.append('start')
            self.retryable_failure = False
            return False

        async def close(self):
            return None

    with patch('open_webui.utils.retrieval_worker.JetStreamRetrievalWorker', FakeWorker):
        supervisor = await start_retrieval_worker_with_retry(app, 'nats://nats:4222', retry_delay=0)
        await asyncio.wait_for(supervisor._task, timeout=1)

    assert len(attempts) == 1
    await supervisor.close()


def test_should_start_retrieval_worker_respects_mode_and_embedding_flags():
    assert should_start_retrieval_worker(
        transport_name='jetstream',
        nats_url='nats://nats:4222',
        enable_embedded_worker=True,
        worker_only_mode=False,
    )
    assert should_start_retrieval_worker(
        transport_name='jetstream',
        nats_url='nats://nats:4222',
        enable_embedded_worker=False,
        worker_only_mode=True,
    )
    assert not should_start_retrieval_worker(
        transport_name='jetstream',
        nats_url='nats://nats:4222',
        enable_embedded_worker=False,
        worker_only_mode=False,
    )
    assert not should_start_retrieval_worker(
        transport_name='local',
        nats_url='nats://nats:4222',
        enable_embedded_worker=True,
        worker_only_mode=True,
    )


@pytest.mark.asyncio
async def test_worker_run_ignores_nats_timeout_errors_between_fetches():
    app = SimpleNamespace(state=SimpleNamespace())
    worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')
    worker._subscription = SimpleNamespace(fetch=AsyncMock(side_effect=[NatsTimeoutError(), asyncio.CancelledError()]))

    with pytest.raises(asyncio.CancelledError):
        await worker._run()

    assert worker._subscription.fetch.await_count == 2


@pytest.mark.asyncio
async def test_worker_redelivery_after_restart_preserves_completed_status_projection():
    app = SimpleNamespace(state=SimpleNamespace())
    user = SimpleNamespace(id='user-1', role='user')
    retrieval_job = build_retrieval_job(
        actor_id='user-1',
        resource_id='file-1',
        job_id='job-1',
        payload={
            'command_type': 'process_file',
            'file_id': 'file-1',
            'source': 'upload',
            'processing_mode': 'background_task',
            'delivery_mode': 'jetstream',
        },
    )
    projected_state = {'status': 'pending'}

    def current_file():
        return SimpleNamespace(
            id='file-1',
            user_id='user-1',
            data=dict(projected_state),
        )

    attempts = 0

    def execute_side_effect(_request, job):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            projected_state.update(
                {
                    'status': 'failed',
                    'retrieval_job': build_retrieval_job_record(
                        job,
                        status='failed',
                        collection_name='file-file-1',
                        error='boom',
                    ),
                    'error': 'boom',
                }
            )
            raise RuntimeError('boom')

        projected_state.update(
            {
                'status': 'completed',
                'retrieval_job': build_retrieval_job_record(
                    job,
                    status='completed',
                    collection_name='file-file-1',
                    document_count=1,
                ),
            }
        )
        projected_state.pop('error', None)

    async def run_job_inline(func, *args):
        return func(*args)

    first_message = SimpleNamespace(
        data=json.dumps(retrieval_job).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )
    second_message = SimpleNamespace(
        data=json.dumps(retrieval_job).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    first_worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')
    second_worker = JetStreamRetrievalWorker(app, 'nats://nats:4222', 'instance-1')

    with (
        patch('open_webui.utils.retrieval_worker.asyncio.to_thread', side_effect=run_job_inline),
        patch('open_webui.utils.retrieval_worker.execute_retrieval_job', side_effect=execute_side_effect),
        patch('open_webui.routers.files.Files.get_file_by_id', side_effect=lambda *_args, **_kwargs: current_file()),
    ):
        await first_worker._handle_message(first_message)
        await second_worker._handle_message(second_message)
        status_payload = await get_file_process_status('file-1', stream=False, user=user, db=Mock())

    first_message.ack.assert_not_awaited()
    first_message.nak.assert_awaited_once()
    second_message.ack.assert_awaited_once()
    second_message.nak.assert_not_awaited()
    assert status_payload == {
        'status': 'completed',
        'retrieval_job': projected_state['retrieval_job'],
    }
