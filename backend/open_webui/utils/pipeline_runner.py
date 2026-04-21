import asyncio
import inspect
import json
import logging
from collections.abc import AsyncGenerator, Generator, Iterator
from types import SimpleNamespace
from uuid import uuid4

from open_webui.env import NATS_CONNECT_TIMEOUT, NATS_NAME, PIPELINE_NATS_SUBJECT, VERSION
from open_webui.utils.middleware import process_tool_result
from open_webui.utils.pipeline_adapter import HttpPipelineAdapter, PipelineAdapterError
from open_webui.utils.runtime_registry import build_custom_runtime_service_record, sync_runtime_registry

log = logging.getLogger(__name__)

PIPELINE_RUNNER_RETRY_DELAY = 5.0
PIPELINE_STAGE_JOB_STREAM = 'owui_pipeline_jobs'
PIPELINE_STAGE_JOB_SUBJECT = 'owui.cmd.pipeline.stage.run'
PIPELINE_STAGE_JOB_CONSUMER = 'owui_pipeline_runner'
PIPELINE_STAGE_JOB_MSG_ID_HEADER = 'Nats-Msg-Id'
PIPELINE_STAGE_JOB_DUPLICATE_WINDOW = 120.0
PIPELINE_STAGE_JOB_ACK_WAIT = 60.0
PIPELINE_STAGE_JOB_BACKOFF = [1.0, 5.0, 30.0]
PIPELINE_STAGE_JOB_MAX_DELIVER = 3
PIPELINE_STAGE_JOB_MAX_ACK_PENDING = 1


def should_start_pipeline_runner(
    *,
    transport_name: str,
    nats_url: str,
    enable_embedded_runner: bool,
    pipeline_runner_only_mode: bool,
) -> bool:
    if transport_name != 'nats' or not nats_url:
        return False
    return pipeline_runner_only_mode or enable_embedded_runner


async def start_pipeline_runner(app, nats_url: str):
    runner = CoreNatsPipelineRunner(app, nats_url, getattr(app.state, 'instance_id', None))
    started = await runner.start()
    if started:
        return runner
    return None


async def publish_pipeline_stage_job(nats_url: str, pipeline_job: dict, *, instance_id: str | None = None) -> None:
    nc = await _connect_nats(nats_url, instance_id=instance_id)
    try:
        js = nc.jetstream()
        await ensure_pipeline_stage_stream(js)
        msg_id = pipeline_job.get('trace_id') or pipeline_job.get('job_id') or f'pipeline-stage-{uuid4().hex}'
        await js.publish(
            PIPELINE_STAGE_JOB_SUBJECT,
            json.dumps(pipeline_job).encode('utf-8'),
            stream=PIPELINE_STAGE_JOB_STREAM,
            headers={PIPELINE_STAGE_JOB_MSG_ID_HEADER: msg_id},
        )
    finally:
        await nc.drain()


def publish_pipeline_stage_job_sync(app, nats_url: str, pipeline_job: dict, timeout: float = 5.0) -> None:
    future = asyncio.run_coroutine_threadsafe(
        publish_pipeline_stage_job(
            nats_url,
            pipeline_job,
            instance_id=getattr(app.state, 'instance_id', None),
        ),
        app.state.main_loop,
    )
    future.result(timeout=timeout)


async def start_pipeline_runner_with_retry(
    app,
    nats_url: str,
    *,
    retry_delay: float = PIPELINE_RUNNER_RETRY_DELAY,
):
    supervisor = RetryingCoreNatsPipelineRunner(
        app,
        nats_url,
        getattr(app.state, 'instance_id', None),
        retry_delay=retry_delay,
    )
    await supervisor.start()
    return supervisor


class RetryingCoreNatsPipelineRunner:
    def __init__(self, app, nats_url: str, instance_id: str | None = None, *, retry_delay: float = 5.0):
        self.app = app
        self.nats_url = nats_url
        self.instance_id = instance_id or 'unknown'
        self.retry_delay = retry_delay
        self._runner = None
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._run())
        return self

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._runner is not None:
            await self._runner.close()
            self._runner = None

    async def _run(self) -> None:
        while True:
            runner = CoreNatsPipelineRunner(self.app, self.nats_url, self.instance_id)
            started = await runner.start()
            if started:
                self._runner = runner
                return

            await runner.close()

            if not runner.retryable_failure:
                return

            log.warning(
                'Core NATS pipeline runner startup failed; retrying in %.1f seconds.',
                self.retry_delay,
            )
            await asyncio.sleep(self.retry_delay)


class CoreNatsPipelineRunner:
    def __init__(self, app, nats_url: str, instance_id: str | None = None):
        self.app = app
        self.nats_url = nats_url
        self.instance_id = instance_id or 'unknown'
        self.retryable_failure = False
        self._nc = None
        self._subscription = None
        self._stage_subscription = None
        self._stage_task = None
        self._provider = None
        self._adapter = HttpPipelineAdapter(SimpleNamespace(app=app))

    async def start(self) -> bool:
        if not self.nats_url:
            self.retryable_failure = False
            return False

        try:
            providers = list(getattr(self.app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', []))
            self._provider = lambda: build_pipeline_runner_records(self.app)
            providers.append(self._provider)
            self.app.state.RUNTIME_SERVICE_RECORD_PROVIDERS = providers

            self._nc = await _connect_nats(self.nats_url, instance_id=self.instance_id)
        except ImportError:
            self.retryable_failure = False
            log.warning('PIPELINE_INTERNAL_TRANSPORT=nats selected, but nats-py is not installed.')
            return False
        except Exception:
            self.retryable_failure = True
            self._remove_provider()
            log.exception('Failed to connect embedded Core NATS pipeline runner.')
            return False

        self._subscription = await self._nc.subscribe(
            getattr(self.app.state.config, 'PIPELINE_NATS_SUBJECT', PIPELINE_NATS_SUBJECT),
            cb=self._handle_message,
        )
        js = self._nc.jetstream()
        await ensure_pipeline_stage_stream(js)
        await ensure_pipeline_stage_consumer(js)
        self._stage_subscription = await js.pull_subscribe(
            PIPELINE_STAGE_JOB_SUBJECT,
            durable=PIPELINE_STAGE_JOB_CONSUMER,
            stream=PIPELINE_STAGE_JOB_STREAM,
        )
        try:
            await asyncio.wait_for(sync_runtime_registry(self.app, nats_url=self.nats_url), timeout=2.0)
        except Exception:
            log.exception('Failed to sync pipeline-runner runtime registry record during startup.')
        self._stage_task = asyncio.create_task(self._run_stage_consumer())
        self.retryable_failure = False
        return True

    async def close(self) -> None:
        if self._stage_task is not None:
            self._stage_task.cancel()
            try:
                await self._stage_task
            except asyncio.CancelledError:
                pass
            self._stage_task = None

        if self._stage_subscription is not None:
            try:
                await self._stage_subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe JetStream pipeline stage runner.', exc_info=True)
            self._stage_subscription = None

        if self._subscription is not None:
            try:
                await self._subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe Core NATS pipeline runner.', exc_info=True)
            self._subscription = None

        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                log.debug('Failed to drain Core NATS pipeline runner connection.', exc_info=True)
            self._nc = None

        self._remove_provider()

    async def _handle_message(self, message) -> None:
        response = await self.handle_request_payload(message.data)
        await message.respond(json.dumps(response).encode('utf-8'))

    async def _run_stage_consumer(self) -> None:
        from nats.errors import TimeoutError as NatsTimeoutError
        from nats.js.errors import FetchTimeoutError

        while True:
            try:
                messages = await self._stage_subscription.fetch(batch=1, timeout=1)
            except (FetchTimeoutError, NatsTimeoutError):
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('JetStream pipeline stage fetch failed.')
                await asyncio.sleep(1)
                continue

            for message in messages:
                await self._handle_stage_message(message)

    async def _handle_stage_message(self, message) -> None:
        try:
            payload = json.loads(message.data.decode('utf-8'))
        except Exception:
            log.exception('JetStream pipeline stage received invalid payload.')
            await message.ack()
            return

        response = await self.handle_request_payload(json.dumps(payload).encode('utf-8'))
        reply_subject = payload.get('reply_subject')
        if reply_subject and self._nc is not None:
            try:
                await self._nc.publish(reply_subject, json.dumps(response).encode('utf-8'))
            except Exception:
                log.exception('Failed to publish JetStream pipeline stage reply.')
        if response.get('status') == 'ok':
            await message.ack()
        else:
            log.warning(
                'JetStream pipeline stage execution failed for %s.',
                payload.get('trace_id') or payload.get('payload', {}).get('pipeline_id'),
            )
            await message.nak()

    async def handle_request_payload(self, payload_bytes: bytes) -> dict:
        try:
            envelope = json.loads(payload_bytes.decode('utf-8'))
        except Exception:
            return _error_response(detail='Pipeline request payload is not valid JSON')

        try:
            payload = envelope.get('payload') or {}
            pipeline_id = payload['pipeline_id']
            pipeline = payload.get('pipeline') or {'id': pipeline_id, 'urlIdx': payload.get('url_idx')}
            stage = payload['stage']
            body = payload['body']
            user = payload.get('user') or {}
            url_idx = payload.get('url_idx')

            result = await self._execute_pipeline_filter(
                pipeline={
                    **pipeline,
                    'id': pipeline_id,
                    'urlIdx': url_idx,
                    'internal_executor_id': payload.get('action_id') or pipeline.get('internal_executor_id'),
                    'action_id': payload.get('action_id'),
                    'sub_action_id': payload.get('sub_action_id'),
                },
                stage=stage,
                user=user,
                body=body,
            )
        except KeyError as exc:
            return _error_response(
                trace_id=envelope.get('trace_id'),
                detail=f'Missing pipeline request field: {exc.args[0]}',
            )
        except PipelineAdapterError as exc:
            return _error_response(
                trace_id=envelope.get('trace_id'),
                status_code=exc.status_code,
                detail=exc.detail,
            )
        except Exception:
            log.exception('Core NATS pipeline runner execution failed.')
            return _error_response(trace_id=envelope.get('trace_id'), detail='Pipeline request failed')

        return {
            'trace_id': envelope.get('trace_id'),
            'payload_version': envelope.get('payload_version', 'v1'),
            'status': 'ok',
            'data': {
                'body': result,
            },
        }

    async def _execute_pipeline_filter(self, *, pipeline: dict, stage: str, user: dict, body: dict) -> dict:
        if pipeline.get('action') or stage == 'action':
            executor = _resolve_internal_action_executor(self.app, pipeline)
            if executor is None:
                raise PipelineAdapterError(404, f'Internal action executor not found: {pipeline.get("id")}')

            result = executor(
                user=user,
                body=body,
                pipeline=pipeline,
                app=self.app,
                action_id=pipeline.get('sub_action_id')
                or pipeline.get('action_id')
                or pipeline.get('internal_executor_id')
                or pipeline.get('id'),
            )
            if inspect.isawaitable(result):
                return await result
            return result

        if pipeline.get('pipe'):
            executor = _resolve_internal_pipe_executor(self.app, pipeline)
            if executor is None:
                raise PipelineAdapterError(404, f'Internal pipe executor not found: {pipeline.get("id")}')

            result = executor(
                user=user,
                body=body,
                pipeline=pipeline,
                app=self.app,
            )
            if inspect.isawaitable(result):
                return await result
            return result

        if _is_internal_pipeline(pipeline):
            executor = _resolve_internal_pipeline_executor(self.app, pipeline)
            if executor is None:
                raise PipelineAdapterError(404, f'Internal pipeline executor not found: {pipeline.get("id")}')

            result = executor(
                stage=stage,
                user=user,
                body=body,
                pipeline=pipeline,
                app=self.app,
            )
            if inspect.isawaitable(result):
                return await result
            return result

        return await self._adapter.invoke_filter(
            pipeline,
            stage,
            user=user,
            payload=body,
        )

    def _remove_provider(self) -> None:
        provider = getattr(self, '_provider', None)
        if provider is None:
            return

        providers = [
            current
            for current in getattr(self.app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])
            if current is not provider
        ]
        self.app.state.RUNTIME_SERVICE_RECORD_PROVIDERS = providers
        self._provider = None


def _error_response(
    *,
    trace_id: str | None = None,
    payload_version: str = 'v1',
    status_code: int = 502,
    detail='Pipeline request failed',
) -> dict:
    return {
        'trace_id': trace_id,
        'payload_version': payload_version,
        'status': 'error',
        'status_code': status_code,
        'detail': detail,
    }


async def _connect_nats(nats_url: str, *, instance_id: str | None = None):
    import nats

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    return await nats.connect(
        servers=servers,
        name=f'{NATS_NAME}-pipeline-runner-{instance_id or "runtime"}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )


def build_pipeline_runner_records(app) -> list[dict]:
    filter_executors = getattr(app.state, 'PIPELINE_FILTER_EXECUTORS', {}) or {}
    function_modules = getattr(app.state, 'FUNCTIONS', {}) or {}
    function_filter_count = sum(
        1 for module in function_modules.values() if hasattr(module, 'inlet') or hasattr(module, 'outlet')
    )
    function_pipe_count = sum(1 for module in function_modules.values() if hasattr(module, 'pipe'))
    function_action_count = sum(1 for module in function_modules.values() if hasattr(module, 'action'))

    return [
        build_custom_runtime_service_record(
            service_id='pipeline-runner.default',
            service_type='pipeline-runner',
            instance_id=getattr(app.state, 'instance_id', 'unknown'),
            version=VERSION,
            status='healthy',
            subjects=[
                getattr(app.state.config, 'PIPELINE_NATS_SUBJECT', PIPELINE_NATS_SUBJECT),
                PIPELINE_STAGE_JOB_SUBJECT,
            ],
            capabilities={
                'pipeline_runner': True,
                'transport': 'nats-request-reply',
                'service_owner': 'pipeline-runner',
                'execution_backend': 'internal-executor-or-http-compatibility-adapter',
                'durable_stage_execution': True,
                'registered_executor_count': len(filter_executors),
                'function_filter_count': function_filter_count,
                'function_pipe_count': function_pipe_count,
                'function_action_count': function_action_count,
            },
            routing={
                'region': 'local',
                'workspace_scope': 'shared',
                'owner': 'pipeline-runner',
            },
        )
    ]


async def ensure_pipeline_stage_stream(js) -> None:
    from nats.js import api
    from nats.js.errors import NotFoundError

    try:
        await js.stream_info(PIPELINE_STAGE_JOB_STREAM)
        return
    except NotFoundError:
        pass

    await js.add_stream(
        config=api.StreamConfig(
            name=PIPELINE_STAGE_JOB_STREAM,
            subjects=[PIPELINE_STAGE_JOB_SUBJECT],
            storage=api.StorageType.FILE,
            retention=api.RetentionPolicy.LIMITS,
            duplicate_window=PIPELINE_STAGE_JOB_DUPLICATE_WINDOW,
        )
    )


async def ensure_pipeline_stage_consumer(js) -> None:
    from nats.js import api
    from nats.js.errors import NotFoundError

    try:
        await js.consumer_info(PIPELINE_STAGE_JOB_STREAM, PIPELINE_STAGE_JOB_CONSUMER)
        return
    except NotFoundError:
        pass

    await js.add_consumer(
        PIPELINE_STAGE_JOB_STREAM,
        config=api.ConsumerConfig(
            durable_name=PIPELINE_STAGE_JOB_CONSUMER,
            ack_policy=api.AckPolicy.EXPLICIT,
            ack_wait=PIPELINE_STAGE_JOB_ACK_WAIT,
            max_deliver=PIPELINE_STAGE_JOB_MAX_DELIVER,
            backoff=PIPELINE_STAGE_JOB_BACKOFF,
            max_ack_pending=PIPELINE_STAGE_JOB_MAX_ACK_PENDING,
            filter_subject=PIPELINE_STAGE_JOB_SUBJECT,
        ),
    )


def _is_internal_pipeline(pipeline: dict) -> bool:
    if pipeline.get('connection_type') == 'internal':
        return True
    pipeline_meta = pipeline.get('pipeline') or {}
    return pipeline_meta.get('execution') == 'internal'


def _resolve_internal_pipeline_executor(app, pipeline: dict):
    pipeline_id = pipeline.get('id')
    executors = getattr(app.state, 'PIPELINE_FILTER_EXECUTORS', {}) or {}
    if pipeline_id in executors:
        return executors[pipeline_id]

    executor_id = pipeline.get('internal_executor_id')
    if executor_id and executor_id in executors:
        return executors[executor_id]

    default_executor = getattr(app.state, 'pipeline_filter_executor', None)
    if callable(default_executor):
        return default_executor

    function_executor_id = executor_id or pipeline_id
    if function_executor_id:
        return _build_function_filter_executor(app, function_executor_id)

    return None


def _resolve_internal_pipe_executor(app, pipeline: dict):
    pipeline_id = pipeline.get('id')
    executors = getattr(app.state, 'PIPELINE_FILTER_EXECUTORS', {}) or {}
    if pipeline_id in executors:
        return executors[pipeline_id]

    executor_id = pipeline.get('internal_executor_id') or pipeline_id
    if executor_id and executor_id in executors:
        return executors[executor_id]

    if executor_id:
        return _build_function_pipe_executor(app, executor_id)

    return None


def _resolve_internal_action_executor(app, pipeline: dict):
    pipeline_id = pipeline.get('id')
    executors = getattr(app.state, 'PIPELINE_FILTER_EXECUTORS', {}) or {}
    if pipeline_id in executors:
        return executors[pipeline_id]

    executor_id = pipeline.get('internal_executor_id') or pipeline_id
    if executor_id and executor_id in executors:
        return executors[executor_id]

    if executor_id:
        return _build_function_action_executor(app, executor_id)

    return None


def _build_function_filter_executor(app, function_id: str):
    async def _executor(*, stage: str, user: dict, body: dict, pipeline: dict, app=None):
        from open_webui.models.functions import Functions
        from open_webui.utils.plugin import get_function_module_from_cache

        request = SimpleNamespace(app=app or _app)
        try:
            if hasattr(request.app.state, 'FUNCTIONS') and function_id in request.app.state.FUNCTIONS:
                function_module = request.app.state.FUNCTIONS[function_id]
            else:
                function_module, _, _ = get_function_module_from_cache(request, function_id, load_from_db=False)
        except Exception as exc:
            raise PipelineAdapterError(404, f'Internal pipeline executor not found: {function_id}') from exc

        handler = getattr(function_module, stage, None)
        if handler is None:
            raise PipelineAdapterError(404, f'Internal pipeline handler not found: {function_id}.{stage}')

        if hasattr(function_module, 'valves') and hasattr(function_module, 'Valves'):
            valves = Functions.get_function_valves_by_id(function_id)
            function_module.valves = function_module.Valves(**(valves if valves else {}))

        sig = inspect.signature(handler)
        params = {'body': body}
        params |= {
            key: value
            for key, value in {
                '__id__': function_id,
                '__request__': request,
                '__model__': pipeline,
                '__user__': {**user},
                '__metadata__': body.get('metadata', {}),
                '__files__': body.get('files', []),
            }.items()
            if key in sig.parameters
        }

        if '__user__' in sig.parameters and hasattr(function_module, 'UserValves') and user.get('id'):
            try:
                params['__user__']['valves'] = function_module.UserValves(
                    **Functions.get_user_valves_by_id_and_user_id(function_id, user['id'])
                )
            except Exception:
                log.exception('Failed to load user valves for internal pipeline filter %s.', function_id)

        result = handler(**params)
        if inspect.isawaitable(result):
            return await result
        return result

    _app = app
    return _executor


def _build_function_pipe_executor(app, function_id: str):
    async def _executor(*, user: dict, body: dict, pipeline: dict, app=None):
        from open_webui.utils.plugin import get_function_module_from_cache

        request = SimpleNamespace(app=app or _app)
        try:
            if hasattr(request.app.state, 'FUNCTIONS') and function_id in request.app.state.FUNCTIONS:
                function_module = request.app.state.FUNCTIONS[function_id]
            else:
                function_module, _, _ = get_function_module_from_cache(request, function_id, load_from_db=False)
        except Exception as exc:
            raise PipelineAdapterError(404, f'Internal pipe executor not found: {function_id}') from exc
        pipe = function_module.pipe
        sig = inspect.signature(pipe)
        params = {
            key: value
            for key, value in {
                'body': body,
                '__id__': function_id,
                '__request__': request,
                '__model__': pipeline,
                '__user__': {**user},
                '__metadata__': body.get('metadata', {}),
                '__files__': body.get('files', []),
            }.items()
            if key in sig.parameters
        }

        result = pipe(**params)
        return await _normalize_pipe_result(result)

    _app = app
    return _executor


def _build_function_action_executor(app, function_id: str):
    async def _executor(*, user: dict, body: dict, pipeline: dict, app=None, action_id: str):
        from open_webui.models.functions import Functions
        from open_webui.utils.plugin import get_function_module_from_cache

        request = SimpleNamespace(app=app or _app)
        try:
            if hasattr(request.app.state, 'FUNCTIONS') and function_id in request.app.state.FUNCTIONS:
                function_module = request.app.state.FUNCTIONS[function_id]
            else:
                function_module, _, _ = get_function_module_from_cache(request, function_id, load_from_db=False)
        except Exception as exc:
            raise PipelineAdapterError(404, f'Internal action executor not found: {function_id}') from exc

        action = getattr(function_module, 'action', None)
        if action is None:
            raise PipelineAdapterError(404, f'Internal action handler not found: {function_id}.action')

        if hasattr(function_module, 'valves') and hasattr(function_module, 'Valves'):
            valves = Functions.get_function_valves_by_id(function_id)
            function_module.valves = function_module.Valves(**(valves if valves else {}))

        sig = inspect.signature(action)
        params = {
            key: value
            for key, value in {
                'body': body,
                '__id__': action_id,
                '__request__': request,
                '__model__': pipeline,
                '__event_emitter__': _noop_async,
                '__event_call__': _noop_async,
                '__user__': {**user},
            }.items()
            if key in sig.parameters
        }

        if '__user__' in sig.parameters and hasattr(function_module, 'UserValves') and user.get('id'):
            try:
                params['__user__']['valves'] = function_module.UserValves(
                    **Functions.get_user_valves_by_id_and_user_id(function_id, user['id'])
                )
            except Exception:
                log.exception('Failed to load user valves for internal action %s.', function_id)

        result = action(**params)
        if inspect.isawaitable(result):
            result = await result

        processed_result, _, _ = process_tool_result(request, function_id, result, 'action')
        return processed_result

    _app = app
    return _executor


def _pipe_result_to_completion_dict(content: str) -> dict:
    return {
        'choices': [
            {
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content,
                },
                'finish_reason': 'stop',
            }
        ]
    }


async def _normalize_pipe_result(result) -> dict:
    if inspect.isawaitable(result):
        result = await result

    if hasattr(result, 'model_dump') and callable(result.model_dump):
        result = result.model_dump()

    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return _pipe_result_to_completion_dict(result)
    if isinstance(result, Generator | Iterator):
        return _pipe_result_to_completion_dict(''.join(map(str, result)))
    if isinstance(result, AsyncGenerator):
        parts = []
        async for chunk in result:
            parts.append(str(chunk))
        return _pipe_result_to_completion_dict(''.join(parts))
    return _pipe_result_to_completion_dict(str(result))


async def _noop_async(*_args, **_kwargs):
    return None
