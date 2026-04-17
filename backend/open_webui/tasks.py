import asyncio
from typing import Dict, List, Optional
from uuid import uuid4

from redis.asyncio import Redis

from open_webui.env import REDIS_KEY_PREFIX
from open_webui.utils.task_messaging import (
    TaskMessagingRuntime,
    build_task_stop_command,
    deserialize_task_record,
    get_task_messaging_runtime,
    publish_redis_task_command,
    serialize_task_record,
    set_task_messaging_runtime,
)

tasks: Dict[str, asyncio.Task] = {}
item_tasks = {}

REDIS_TASKS_KEY = f'{REDIS_KEY_PREFIX}:tasks'
REDIS_ITEM_TASKS_KEY = f'{REDIS_KEY_PREFIX}:tasks:item'


async def task_command_listener(app):
    runtime = TaskMessagingRuntime(app.state.redis, getattr(app.state, 'instance_id', None))
    set_task_messaging_runtime(runtime)

    try:
        await runtime.start(handle_task_stop_command)
        await asyncio.Future()
    finally:
        set_task_messaging_runtime(None)
        await runtime.close()


redis_task_command_listener = task_command_listener


async def redis_save_task(redis: Redis, task_id: str, item_id: Optional[str], instance_id: Optional[str]):
    pipe = redis.pipeline()
    pipe.hset(REDIS_TASKS_KEY, task_id, serialize_task_record(item_id, instance_id))
    if item_id:
        pipe.sadd(f'{REDIS_ITEM_TASKS_KEY}:{item_id}', task_id)
    await pipe.execute()


async def redis_cleanup_task(redis: Redis, task_id: str, item_id: Optional[str]):
    pipe = redis.pipeline()
    pipe.hdel(REDIS_TASKS_KEY, task_id)
    if item_id:
        pipe.srem(f'{REDIS_ITEM_TASKS_KEY}:{item_id}', task_id)
        await pipe.execute()
        if await redis.scard(f'{REDIS_ITEM_TASKS_KEY}:{item_id}') == 0:
            await redis.delete(f'{REDIS_ITEM_TASKS_KEY}:{item_id}')
    else:
        await pipe.execute()


async def redis_list_tasks(redis: Redis) -> List[str]:
    return list(await redis.hkeys(REDIS_TASKS_KEY))


async def redis_list_item_tasks(redis: Redis, item_id: str) -> List[str]:
    return list(await redis.smembers(f'{REDIS_ITEM_TASKS_KEY}:{item_id}'))


async def redis_send_command(redis: Redis, command: dict):
    await publish_redis_task_command(redis, command)


async def cleanup_task(redis, task_id: str, id=None):
    if redis:
        await redis_cleanup_task(redis, task_id, id)

    tasks.pop(task_id, None)

    if id and task_id in item_tasks.get(id, []):
        item_tasks[id].remove(task_id)
        if not item_tasks[id]:
            item_tasks.pop(id, None)


async def create_task(redis, coroutine, id=None):
    task_id = str(uuid4())
    task = asyncio.create_task(coroutine)

    task.add_done_callback(lambda t: asyncio.create_task(cleanup_task(redis, task_id, id)))
    tasks[task_id] = task

    if item_tasks.get(id):
        item_tasks[id].append(task_id)
    else:
        item_tasks[id] = [task_id]

    if redis:
        await redis_save_task(redis, task_id, id, _current_instance_id())

    return task_id, task


async def list_tasks(redis):
    if redis:
        return await redis_list_tasks(redis)
    return list(tasks.keys())


async def list_task_ids_by_item_id(redis, id):
    if redis:
        return await redis_list_item_tasks(redis, id)
    return item_tasks.get(id, [])


async def stop_task(redis, task_id: str):
    runtime = get_task_messaging_runtime()

    if redis:
        task_record = deserialize_task_record(await redis.hget(REDIS_TASKS_KEY, task_id))
        item_id = task_record.get('item_id')
        target_instance_id = task_record.get('instance_id')
        if runtime is not None:
            await runtime.dispatch_stop_command(
                task_id,
                item_id or None,
                target_instance_id=target_instance_id,
            )
        else:
            await redis_send_command(
                redis,
                build_task_stop_command(
                    task_id,
                    item_id or None,
                    target_instance_id=target_instance_id,
                ),
            )
        await redis_cleanup_task(redis, task_id, item_id or None)
        return {'status': True, 'message': f'Task {task_id} stopped.'}

    item_id = _find_item_id_for_task(task_id)
    if runtime is not None:
        await runtime.publish_task_stop_requested(task_id, item_id=item_id)

    task = tasks.pop(task_id, None)
    if not task:
        return {'status': False, 'message': f'Task with ID {task_id} not found.'}

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        if runtime is not None:
            await runtime.publish_task_stop_acknowledged(task_id, item_id=item_id, source='local')
        return {'status': True, 'message': f'Task {task_id} successfully stopped.'}

    if task.cancelled() or task.done():
        if runtime is not None:
            await runtime.publish_task_stop_acknowledged(task_id, item_id=item_id, source='local')
        return {'status': True, 'message': f'Task {task_id} successfully cancelled.'}

    return {'status': True, 'message': f'Cancellation requested for {task_id}.'}


async def stop_item_tasks(redis: Redis, item_id: str):
    task_ids = await list_task_ids_by_item_id(redis, item_id)
    if not task_ids:
        return {'status': True, 'message': f'No tasks found for item {item_id}.'}

    for task_id in task_ids:
        result = await stop_task(redis, task_id)
        if not result['status']:
            return result

    return {'status': True, 'message': f'All tasks for item {item_id} stopped.'}


async def has_active_tasks(redis, chat_id: str) -> bool:
    task_ids = await list_task_ids_by_item_id(redis, chat_id)
    return len(task_ids) > 0


async def get_active_chat_ids(redis, chat_ids: List[str]) -> List[str]:
    active = []
    for chat_id in chat_ids:
        if await has_active_tasks(redis, chat_id):
            active.append(chat_id)
    return active


async def handle_task_stop_command(command: dict, source: str):
    task_id = command.get('task_id')
    if not task_id:
        return

    local_task = tasks.get(task_id)
    if local_task is None:
        return

    local_task.cancel()

    runtime = get_task_messaging_runtime()
    if runtime is not None:
        await runtime.publish_task_stop_acknowledged(
            task_id,
            item_id=command.get('item_id') or _find_item_id_for_task(task_id),
            source=source,
        )


def _find_item_id_for_task(task_id: str) -> Optional[str]:
    for item_id, task_ids in item_tasks.items():
        if task_id in task_ids:
            return item_id
    return None


def _current_instance_id() -> Optional[str]:
    runtime = get_task_messaging_runtime()
    if runtime is None:
        return None
    return runtime.instance_id
