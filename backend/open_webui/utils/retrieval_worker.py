import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Optional

from open_webui.env import NATS_CONNECT_TIMEOUT, NATS_NAME
from open_webui.utils.retrieval_execution import execute_retrieval_job

log = logging.getLogger(__name__)

RETRIEVAL_JOB_STREAM = 'owui_retrieval_jobs'
RETRIEVAL_JOB_SUBJECT = 'owui.cmd.retrieval.file_ingest'
RETRIEVAL_JOB_CONSUMER = 'owui_retrieval_worker'
RETRIEVAL_JOB_MSG_ID_HEADER = 'Nats-Msg-Id'
RETRIEVAL_JOB_DUPLICATE_WINDOW = 120.0
RETRIEVAL_JOB_ACK_WAIT = 60.0
RETRIEVAL_JOB_BACKOFF = [1.0, 5.0, 30.0]
RETRIEVAL_JOB_MAX_DELIVER = 3
RETRIEVAL_JOB_MAX_ACK_PENDING = 1


async def publish_retrieval_job(nats_url: str, retrieval_job: dict, *, instance_id: Optional[str] = None) -> None:
    nc = await _connect_nats(nats_url, instance_id=instance_id)
    try:
        js = nc.jetstream()
        await ensure_retrieval_stream(js)
        await js.publish(
            RETRIEVAL_JOB_SUBJECT,
            json.dumps(retrieval_job).encode('utf-8'),
            stream=RETRIEVAL_JOB_STREAM,
            headers={RETRIEVAL_JOB_MSG_ID_HEADER: retrieval_job['job_id']},
        )
    finally:
        await nc.drain()


def publish_retrieval_job_sync(app, nats_url: str, retrieval_job: dict, timeout: float = 5.0) -> None:
    future = asyncio.run_coroutine_threadsafe(
        publish_retrieval_job(
            nats_url,
            retrieval_job,
            instance_id=getattr(app.state, 'instance_id', None),
        ),
        app.state.main_loop,
    )
    future.result(timeout=timeout)


async def start_retrieval_worker(app, nats_url: str):
    worker = JetStreamRetrievalWorker(app, nats_url, getattr(app.state, 'instance_id', None))
    started = await worker.start()
    if started:
        return worker
    return None


class JetStreamRetrievalWorker:
    def __init__(self, app, nats_url: str, instance_id: Optional[str] = None):
        self.app = app
        self.nats_url = nats_url
        self.instance_id = instance_id or 'unknown'
        self._nc = None
        self._subscription = None
        self._task = None

    async def start(self) -> bool:
        if not self.nats_url:
            return False

        try:
            self._nc = await _connect_nats(self.nats_url, instance_id=self.instance_id)
        except ImportError:
            log.warning('RETRIEVAL_TRANSPORT=jetstream selected, but nats-py is not installed.')
            return False
        except Exception:
            log.exception('Failed to connect embedded JetStream retrieval worker.')
            return False

        js = self._nc.jetstream()
        await ensure_retrieval_stream(js)
        await ensure_retrieval_consumer(js)
        self._subscription = await js.pull_subscribe(
            RETRIEVAL_JOB_SUBJECT,
            durable=RETRIEVAL_JOB_CONSUMER,
            stream=RETRIEVAL_JOB_STREAM,
        )
        self._task = asyncio.create_task(self._run())
        return True

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._subscription is not None:
            try:
                await self._subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe retrieval worker.', exc_info=True)
            self._subscription = None

        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                log.debug('Failed to drain retrieval worker NATS connection.', exc_info=True)
            self._nc = None

    async def _run(self) -> None:
        from nats.js.errors import FetchTimeoutError

        while True:
            try:
                messages = await self._subscription.fetch(batch=1, timeout=1)
            except FetchTimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('JetStream retrieval worker fetch failed.')
                await asyncio.sleep(1)
                continue

            for message in messages:
                await self._handle_message(message)

    async def _handle_message(self, message) -> None:
        try:
            retrieval_job = json.loads(message.data.decode('utf-8'))
        except Exception:
            log.exception('JetStream retrieval worker received invalid retrieval payload.')
            await message.ack()
            return

        try:
            await asyncio.to_thread(
                execute_retrieval_job,
                SimpleNamespace(app=self.app),
                retrieval_job,
            )
        except Exception:
            log.exception('JetStream retrieval worker execution failed for job %s.', retrieval_job.get('job_id'))
            await message.nak()
            return

        await message.ack()


async def ensure_retrieval_stream(js) -> None:
    from nats.js import api
    from nats.js.errors import NotFoundError

    try:
        await js.stream_info(RETRIEVAL_JOB_STREAM)
        return
    except NotFoundError:
        pass

    await js.add_stream(
        config=api.StreamConfig(
            name=RETRIEVAL_JOB_STREAM,
            subjects=[RETRIEVAL_JOB_SUBJECT],
            storage=api.StorageType.FILE,
            retention=api.RetentionPolicy.LIMITS,
            duplicate_window=RETRIEVAL_JOB_DUPLICATE_WINDOW,
        )
    )


async def ensure_retrieval_consumer(js) -> None:
    from nats.js import api
    from nats.js.errors import NotFoundError

    try:
        await js.consumer_info(RETRIEVAL_JOB_STREAM, RETRIEVAL_JOB_CONSUMER)
        return
    except NotFoundError:
        pass

    await js.add_consumer(
        RETRIEVAL_JOB_STREAM,
        config=api.ConsumerConfig(
            durable_name=RETRIEVAL_JOB_CONSUMER,
            ack_policy=api.AckPolicy.EXPLICIT,
            ack_wait=RETRIEVAL_JOB_ACK_WAIT,
            max_deliver=RETRIEVAL_JOB_MAX_DELIVER,
            backoff=RETRIEVAL_JOB_BACKOFF,
            max_ack_pending=RETRIEVAL_JOB_MAX_ACK_PENDING,
            filter_subject=RETRIEVAL_JOB_SUBJECT,
        ),
    )


async def _connect_nats(nats_url: str, *, instance_id: Optional[str] = None):
    import nats

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    return await nats.connect(
        servers=servers,
        name=f'{NATS_NAME}-retrieval-{instance_id or "worker"}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )
