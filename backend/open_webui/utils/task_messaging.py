import asyncio
import concurrent.futures
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional
from uuid import uuid4

from redis.asyncio import Redis

from open_webui.env import (
    NATS_CONNECT_TIMEOUT,
    NATS_NAME,
    NATS_URL,
    REDIS_KEY_PREFIX,
    TASK_COMMAND_SIGNING_SECRET,
)

log = logging.getLogger(__name__)

TASK_COMMAND_SUBJECT = 'owui.cmd.task.stop'
TASK_STOP_REQUESTED_SUBJECT = 'owui.evt.task.stop.requested'
TASK_STOP_ACKNOWLEDGED_SUBJECT = 'owui.evt.task.stop.acknowledged'
TERMINAL_SESSION_CREATED_SUBJECT = 'owui.evt.terminal.session.created'
TERMINAL_SESSION_ATTACHED_SUBJECT = 'owui.evt.terminal.session.attached'
TERMINAL_SESSION_DISCONNECTED_SUBJECT = 'owui.evt.terminal.session.disconnected'
TERMINAL_SESSION_FAILED_SUBJECT = 'owui.evt.terminal.session.failed'
RETRIEVAL_JOB_QUEUED_SUBJECT = 'owui.evt.retrieval.job.queued'
RETRIEVAL_JOB_STARTED_SUBJECT = 'owui.evt.retrieval.job.started'
RETRIEVAL_JOB_PROGRESS_SUBJECT = 'owui.evt.retrieval.job.progress'
RETRIEVAL_JOB_COMPLETED_SUBJECT = 'owui.evt.retrieval.job.completed'
RETRIEVAL_JOB_FAILED_SUBJECT = 'owui.evt.retrieval.job.failed'
REDIS_TASK_COMMAND_CHANNEL = f'{REDIS_KEY_PREFIX}:tasks:commands'

_task_messaging_runtime = None


def set_task_messaging_runtime(runtime) -> None:
    global _task_messaging_runtime
    _task_messaging_runtime = runtime


def get_task_messaging_runtime():
    return _task_messaging_runtime


def build_task_stop_command(
    task_id: str,
    item_id: Optional[str] = None,
    *,
    target_instance_id: Optional[str] = None,
) -> dict:
    payload = {
        'action': 'stop',
        'command_id': f'cmd_{uuid4().hex}',
        'task_id': task_id,
        'requested_at': _utc_now(),
    }
    if item_id:
        payload['item_id'] = item_id
    if target_instance_id:
        payload['target_instance_id'] = target_instance_id
    payload['signature'] = sign_task_command(payload)
    return payload


def build_task_event(event_type: str, task_id: str, **data) -> dict:
    return build_domain_event(
        event_type=event_type,
        resource_type='task',
        resource_id=task_id,
        data={
            'task_id': task_id,
            **{key: value for key, value in data.items() if value is not None},
        },
    )


def build_domain_event(
    event_type: str,
    resource_type: str,
    resource_id: str,
    producer: str = 'open-webui',
    trace_id: Optional[str] = None,
    data: Optional[dict] = None,
) -> dict:
    event = {
        'event_id': f'evt_{uuid4().hex}',
        'event_type': event_type,
        'occurred_at': _utc_now(),
        'producer': producer,
        'resource_type': resource_type,
        'resource_id': resource_id,
        'trace_id': trace_id,
        'data': data or {},
    }
    return event


async def publish_redis_task_command(redis: Redis, command: dict):
    command_json = json.dumps(command)
    # RedisCluster doesn't expose publish() directly, but the
    # PUBLISH command broadcasts across all cluster nodes server-side.
    if hasattr(redis, 'nodes_manager'):
        await redis.execute_command('PUBLISH', REDIS_TASK_COMMAND_CHANNEL, command_json)
    else:
        await redis.publish(REDIS_TASK_COMMAND_CHANNEL, command_json)


class TaskMessagingRuntime:
    def __init__(self, redis: Optional[Redis], instance_id: Optional[str] = None):
        self.redis = redis
        self.instance_id = instance_id or 'unknown'
        self._nats = None
        self._nats_subscription = None
        self._redis_listener_task = None
        self._on_stop_command: Optional[Callable[[dict, str], Awaitable[None]]] = None

    async def start(self, on_stop_command: Callable[[dict, str], Awaitable[None]]):
        self._on_stop_command = on_stop_command

        if self.redis is not None:
            self._redis_listener_task = asyncio.create_task(self._run_redis_listener())

        await self._connect_nats()

    async def close(self):
        if self._redis_listener_task is not None:
            self._redis_listener_task.cancel()
            try:
                await self._redis_listener_task
            except asyncio.CancelledError:
                pass
            self._redis_listener_task = None

        if self._nats_subscription is not None:
            try:
                await self._nats_subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe task control subject.', exc_info=True)
            self._nats_subscription = None

        if self._nats is not None:
            try:
                await self._nats.drain()
            except Exception:
                log.debug('Failed to drain NATS task messaging connection.', exc_info=True)
            self._nats = None

    async def dispatch_stop_command(
        self,
        task_id: str,
        item_id: Optional[str] = None,
        *,
        target_instance_id: Optional[str] = None,
    ) -> Optional[str]:
        command = build_task_stop_command(task_id, item_id, target_instance_id=target_instance_id)
        await self.publish_task_stop_requested(task_id, item_id=item_id)

        if self._nats is not None and target_instance_id:
            try:
                await self._nats.publish(TASK_COMMAND_SUBJECT, json.dumps(command).encode('utf-8'))
                return 'nats'
            except Exception:
                log.exception('Failed to publish task stop command to NATS; falling back to Redis if available.')

        if self.redis is not None:
            await publish_redis_task_command(self.redis, command)
            return 'redis'

        return None

    async def publish_task_stop_requested(self, task_id: str, item_id: Optional[str] = None):
        await self.publish_event(
            TASK_STOP_REQUESTED_SUBJECT,
            build_task_event('task.stop.requested', task_id, item_id=item_id, instance_id=self.instance_id),
        )

    async def publish_task_stop_acknowledged(
        self,
        task_id: str,
        item_id: Optional[str] = None,
        source: Optional[str] = None,
    ):
        await self.publish_event(
            TASK_STOP_ACKNOWLEDGED_SUBJECT,
            build_task_event(
                'task.stop.acknowledged',
                task_id,
                item_id=item_id,
                instance_id=self.instance_id,
                source=source,
            ),
        )

    async def _connect_nats(self):
        servers = [server.strip() for server in NATS_URL.split(',') if server.strip()]
        if not servers:
            return

        try:
            import nats
        except ImportError:
            log.warning('NATS_URL is set but nats-py is not installed. Falling back to Redis task messaging.')
            return

        try:
            self._nats = await nats.connect(
                servers=servers,
                name=f'{NATS_NAME}-{self.instance_id}',
                connect_timeout=NATS_CONNECT_TIMEOUT,
            )
            self._nats_subscription = await self._nats.subscribe(
                TASK_COMMAND_SUBJECT,
                cb=self._handle_nats_stop_command,
            )
        except Exception:
            self._nats = None
            self._nats_subscription = None
            log.exception('Failed to initialize NATS task messaging. Falling back to Redis task messaging.')

    async def _handle_nats_stop_command(self, message):
        try:
            command = json.loads(message.data.decode('utf-8'))
            if (
                command.get('action') == 'stop'
                and command.get('target_instance_id') == self.instance_id
                and verify_task_command(command)
                and self._on_stop_command is not None
            ):
                await self._on_stop_command(command, 'nats')
        except Exception:
            log.exception('Error handling NATS task command.')

    async def publish_event(self, subject: str, event: dict):
        if self._nats is None:
            return

        try:
            await self._nats.publish(subject, json.dumps(event).encode('utf-8'))
        except Exception:
            log.exception('Failed to publish task event to NATS.')

    async def _run_redis_listener(self):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(REDIS_TASK_COMMAND_CHANNEL)

        try:
            async for message in pubsub.listen():
                if message['type'] != 'message':
                    continue

                try:
                    command = json.loads(message['data'])
                    if (
                        command.get('action') == 'stop'
                        and command.get('target_instance_id') in (None, self.instance_id)
                        and verify_task_command(command)
                        and self._on_stop_command is not None
                    ):
                        await self._on_stop_command(command, 'redis')
                except Exception:
                    log.exception('Error handling Redis task command.')
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await pubsub.unsubscribe(REDIS_TASK_COMMAND_CHANNEL)
            except Exception:
                log.debug('Failed to unsubscribe Redis task command channel.', exc_info=True)
            await pubsub.close()


async def publish_app_event(subject: str, event: dict):
    runtime = get_task_messaging_runtime()
    if runtime is not None:
        await runtime.publish_event(subject, event)


def publish_app_event_sync(app, subject: str, event: dict, timeout: float = 0.1):
    runtime = get_task_messaging_runtime()
    if runtime is None:
        return None

    main_loop = getattr(app.state, 'main_loop', None)
    if main_loop is None or main_loop.is_closed():
        return None

    future = asyncio.run_coroutine_threadsafe(runtime.publish_event(subject, event), main_loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return future


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def sign_task_command(command: dict) -> str:
    signing_secret = TASK_COMMAND_SIGNING_SECRET.encode('utf-8')
    return hmac.new(signing_secret, _canonical_task_command_payload(command).encode('utf-8'), hashlib.sha256).hexdigest()


def verify_task_command(command: dict) -> bool:
    signature = command.get('signature')
    if not signature:
        return False
    expected = sign_task_command({key: value for key, value in command.items() if key != 'signature'})
    return hmac.compare_digest(signature, expected)


def serialize_task_record(item_id: Optional[str], instance_id: Optional[str]) -> str:
    return json.dumps(
        {
            'item_id': item_id or '',
            'instance_id': instance_id or '',
        }
    )


def deserialize_task_record(raw_value: Optional[str]) -> dict:
    if not raw_value:
        return {'item_id': None, 'instance_id': None}
    try:
        parsed = json.loads(raw_value)
        if isinstance(parsed, dict):
            return {
                'item_id': parsed.get('item_id') or None,
                'instance_id': parsed.get('instance_id') or None,
            }
    except Exception:
        pass
    return {'item_id': raw_value or None, 'instance_id': None}


def _canonical_task_command_payload(command: dict) -> str:
    payload = {key: value for key, value in command.items() if key != 'signature'}
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))
