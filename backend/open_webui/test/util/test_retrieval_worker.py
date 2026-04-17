import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from open_webui.utils.retrieval_jobs import build_retrieval_job
from open_webui.utils.retrieval_worker import JetStreamRetrievalWorker, publish_retrieval_job_sync


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
