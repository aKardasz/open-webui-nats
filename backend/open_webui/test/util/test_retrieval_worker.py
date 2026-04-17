import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nats.errors import TimeoutError as NatsTimeoutError

from open_webui.utils.retrieval_jobs import build_retrieval_job
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
