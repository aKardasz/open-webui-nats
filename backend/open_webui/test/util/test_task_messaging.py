import json
import concurrent.futures
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from open_webui import tasks as task_module
from open_webui.utils.task_messaging import (
    TASK_COMMAND_SUBJECT,
    TASK_STOP_ACKNOWLEDGED_SUBJECT,
    TASK_STOP_REQUESTED_SUBJECT,
    build_domain_event,
    build_task_stop_command,
    publish_app_event,
    publish_app_event_sync,
    deserialize_task_record,
    serialize_task_record,
    TaskMessagingRuntime,
    set_task_messaging_runtime,
    verify_task_command,
)


class FakeRedis:
    def __init__(self):
        self.publish = AsyncMock()
        self.execute_command = AsyncMock()


@pytest.fixture(autouse=True)
def clear_task_state():
    task_module.tasks.clear()
    task_module.item_tasks.clear()
    set_task_messaging_runtime(None)
    yield
    task_module.tasks.clear()
    task_module.item_tasks.clear()
    set_task_messaging_runtime(None)


@pytest.mark.asyncio
async def test_task_messaging_runtime_prefers_nats_for_stop_commands():
    redis = FakeRedis()
    runtime = TaskMessagingRuntime(redis=redis, instance_id='instance-1')
    runtime._nats = AsyncMock()

    backend = await runtime.dispatch_stop_command('task-1', 'chat-1', target_instance_id='instance-2')

    assert backend == 'nats'
    assert runtime._nats.publish.await_count == 2

    requested_subject, requested_payload = runtime._nats.publish.await_args_list[0].args
    command_subject, command_payload = runtime._nats.publish.await_args_list[1].args

    assert requested_subject == TASK_STOP_REQUESTED_SUBJECT
    assert command_subject == TASK_COMMAND_SUBJECT
    assert json.loads(requested_payload.decode('utf-8'))['data']['task_id'] == 'task-1'
    command = json.loads(command_payload.decode('utf-8'))
    assert command['task_id'] == 'task-1'
    assert command['target_instance_id'] == 'instance-2'
    assert verify_task_command(command) is True
    redis.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_messaging_runtime_falls_back_to_redis_for_stop_commands():
    redis = FakeRedis()
    runtime = TaskMessagingRuntime(redis=redis, instance_id='instance-1')

    backend = await runtime.dispatch_stop_command('task-1')

    assert backend == 'redis'
    redis.publish.assert_awaited_once()
    subject, payload = redis.publish.await_args.args
    assert json.loads(payload)['task_id'] == 'task-1'
    assert subject.endswith(':tasks:commands')


@pytest.mark.asyncio
async def test_task_messaging_runtime_ignores_unsigned_nats_stop_commands():
    runtime = TaskMessagingRuntime(redis=None, instance_id='instance-1')
    runtime._on_stop_command = AsyncMock()
    message = SimpleNamespace(
        data=json.dumps({'action': 'stop', 'task_id': 'task-1', 'target_instance_id': 'instance-1'}).encode('utf-8')
    )

    await runtime._handle_nats_stop_command(message)

    runtime._on_stop_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_messaging_runtime_ignores_wrong_instance_nats_stop_commands():
    runtime = TaskMessagingRuntime(redis=None, instance_id='instance-1')
    runtime._on_stop_command = AsyncMock()
    command = build_task_stop_command('task-1', target_instance_id='instance-2')
    message = SimpleNamespace(data=json.dumps(command).encode('utf-8'))

    await runtime._handle_nats_stop_command(message)

    runtime._on_stop_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_messaging_runtime_ignores_unsigned_redis_stop_commands():
    runtime = TaskMessagingRuntime(redis=None, instance_id='instance-1')
    runtime._on_stop_command = AsyncMock()

    pubsub = SimpleNamespace(
        subscribe=AsyncMock(),
        unsubscribe=AsyncMock(),
        close=AsyncMock(),
        listen=lambda: _message_iter([{'type': 'message', 'data': json.dumps({'action': 'stop'}).encode('utf-8')}]),
    )
    redis = SimpleNamespace(pubsub=lambda: pubsub)
    runtime.redis = redis

    await runtime._run_redis_listener()

    runtime._on_stop_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_task_messaging_runtime_handles_signed_targeted_redis_stop_commands():
    runtime = TaskMessagingRuntime(redis=None, instance_id='instance-1')
    runtime._on_stop_command = AsyncMock()
    command = build_task_stop_command('task-1', target_instance_id='instance-1')

    pubsub = SimpleNamespace(
        subscribe=AsyncMock(),
        unsubscribe=AsyncMock(),
        close=AsyncMock(),
        listen=lambda: _message_iter([{'type': 'message', 'data': json.dumps(command).encode('utf-8')}]),
    )
    redis = SimpleNamespace(pubsub=lambda: pubsub)
    runtime.redis = redis

    await runtime._run_redis_listener()

    runtime._on_stop_command.assert_awaited_once_with(command, 'redis')


@pytest.mark.asyncio
async def test_task_messaging_runtime_handles_signed_legacy_redis_stop_commands_without_target():
    runtime = TaskMessagingRuntime(redis=None, instance_id='instance-1')
    runtime._on_stop_command = AsyncMock()
    command = build_task_stop_command('task-1')

    pubsub = SimpleNamespace(
        subscribe=AsyncMock(),
        unsubscribe=AsyncMock(),
        close=AsyncMock(),
        listen=lambda: _message_iter([{'type': 'message', 'data': json.dumps(command).encode('utf-8')}]),
    )
    redis = SimpleNamespace(pubsub=lambda: pubsub)
    runtime.redis = redis

    await runtime._run_redis_listener()

    runtime._on_stop_command.assert_awaited_once_with(command, 'redis')


@pytest.mark.asyncio
async def test_stop_task_uses_runtime_dispatch_and_redis_cleanup():
    redis = AsyncMock()
    redis.hget = AsyncMock(return_value=serialize_task_record('chat-1', 'instance-1'))
    runtime = AsyncMock()
    set_task_messaging_runtime(runtime)

    with patch('open_webui.tasks.redis_cleanup_task', new=AsyncMock()) as cleanup:
        result = await task_module.stop_task(redis, 'task-1')

    assert result == {'status': True, 'message': 'Task task-1 stopped.'}
    runtime.dispatch_stop_command.assert_awaited_once_with(
        'task-1',
        'chat-1',
        target_instance_id='instance-1',
    )
    cleanup.assert_awaited_once_with(redis, 'task-1', 'chat-1')


@pytest.mark.asyncio
async def test_handle_task_stop_command_cancels_local_task_and_publishes_ack():
    runtime = AsyncMock()
    set_task_messaging_runtime(runtime)
    local_task = Mock()
    task_module.tasks['task-1'] = local_task
    task_module.item_tasks['chat-1'] = ['task-1']

    await task_module.handle_task_stop_command({'task_id': 'task-1'}, 'nats')

    local_task.cancel.assert_called_once_with()
    runtime.publish_task_stop_acknowledged.assert_awaited_once_with(
        'task-1',
        item_id='chat-1',
        source='nats',
    )


@pytest.mark.asyncio
async def test_handle_task_stop_command_uses_item_id_from_command():
    runtime = AsyncMock()
    set_task_messaging_runtime(runtime)
    local_task = Mock()
    task_module.tasks['task-1'] = local_task

    await task_module.handle_task_stop_command({'task_id': 'task-1', 'item_id': 'chat-1'}, 'redis')

    local_task.cancel.assert_called_once_with()
    runtime.publish_task_stop_acknowledged.assert_awaited_once_with(
        'task-1',
        item_id='chat-1',
        source='redis',
    )
    assert TASK_STOP_ACKNOWLEDGED_SUBJECT == 'owui.evt.task.stop.acknowledged'


def test_build_domain_event_uses_generic_envelope():
    event = build_domain_event(
        event_type='terminal.session.created',
        resource_type='terminal_session',
        resource_id='session-1',
        data={'server_id': 'server-1'},
    )

    assert event['event_type'] == 'terminal.session.created'
    assert event['resource_type'] == 'terminal_session'
    assert event['resource_id'] == 'session-1'
    assert event['producer'] == 'open-webui'
    assert event['data'] == {'server_id': 'server-1'}


def test_task_record_round_trip_preserves_item_and_instance():
    serialized = serialize_task_record('chat-1', 'instance-1')

    assert deserialize_task_record(serialized) == {'item_id': 'chat-1', 'instance_id': 'instance-1'}


def test_task_record_deserialize_supports_legacy_plain_item_id():
    assert deserialize_task_record('chat-1') == {'item_id': 'chat-1', 'instance_id': None}


@pytest.mark.asyncio
async def test_publish_app_event_uses_runtime_when_available():
    runtime = AsyncMock()
    set_task_messaging_runtime(runtime)
    event = build_domain_event(
        event_type='retrieval.job.queued',
        resource_type='file',
        resource_id='file-1',
    )

    await publish_app_event('owui.evt.retrieval.job.queued', event)

    runtime.publish_event.assert_awaited_once_with('owui.evt.retrieval.job.queued', event)


def test_publish_app_event_sync_schedules_publish_on_main_loop():
    runtime = Mock()
    runtime.publish_event = AsyncMock()
    set_task_messaging_runtime(runtime)
    app = SimpleNamespace(state=SimpleNamespace(main_loop=Mock(is_closed=Mock(return_value=False))))
    future = Mock()
    future.result.return_value = None
    event = build_domain_event(
        event_type='retrieval.job.queued',
        resource_type='file',
        resource_id='file-1',
    )

    with patch('open_webui.utils.task_messaging.asyncio.run_coroutine_threadsafe', return_value=future) as schedule:
        result = publish_app_event_sync(app, 'owui.evt.retrieval.job.queued', event)
        scheduled_coro = schedule.call_args.args[0]
        scheduled_coro.close()

    assert result is None
    schedule.assert_called_once()
    future.result.assert_called_once_with(timeout=0.1)


def test_publish_app_event_sync_returns_future_after_timeout():
    runtime = Mock()
    runtime.publish_event = AsyncMock()
    set_task_messaging_runtime(runtime)
    app = SimpleNamespace(state=SimpleNamespace(main_loop=Mock(is_closed=Mock(return_value=False))))
    future = Mock()
    future.result.side_effect = concurrent.futures.TimeoutError()
    event = build_domain_event(
        event_type='retrieval.job.started',
        resource_type='file',
        resource_id='file-1',
    )

    with patch('open_webui.utils.task_messaging.asyncio.run_coroutine_threadsafe', return_value=future) as schedule:
        result = publish_app_event_sync(app, 'owui.evt.retrieval.job.started', event)
        scheduled_coro = schedule.call_args.args[0]
        scheduled_coro.close()

    assert result is future


async def _message_iter(messages):
    for message in messages:
        yield message
