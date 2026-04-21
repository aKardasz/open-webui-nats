import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from nats.errors import TimeoutError as NatsTimeoutError
from open_webui.utils.pipeline_runner import (
    CoreNatsPipelineRunner,
    build_pipeline_runner_records,
    publish_pipeline_stage_job_sync,
    should_start_pipeline_runner,
    start_pipeline_runner_with_retry,
)


def _app():
    return SimpleNamespace(
        state=SimpleNamespace(
            instance_id='instance-1',
            RUNTIME_SERVICE_RECORD_PROVIDERS=[],
            PIPELINE_FILTER_EXECUTORS={},
            pipeline_filter_executor=None,
            config=SimpleNamespace(
                PIPELINE_NATS_SUBJECT='owui.cmd.pipeline.run',
            ),
        )
    )


class FakeSubscription:
    def __init__(self):
        self.unsubscribe = AsyncMock()


class FakeNatsConnection:
    def __init__(self):
        self.subscribe = AsyncMock(return_value=FakeSubscription())
        self.drain = AsyncMock()
        self._pull_subscription = FakeSubscription()
        self._js = SimpleNamespace(
            pull_subscribe=AsyncMock(return_value=self._pull_subscription),
        )

    def jetstream(self):
        return self._js


def test_should_start_pipeline_runner_requires_nats_transport_and_url():
    assert not should_start_pipeline_runner(
        transport_name='http',
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        pipeline_runner_only_mode=False,
    )
    assert not should_start_pipeline_runner(
        transport_name='nats',
        nats_url='',
        enable_embedded_runner=True,
        pipeline_runner_only_mode=False,
    )
    assert should_start_pipeline_runner(
        transport_name='nats',
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        pipeline_runner_only_mode=False,
    )


@pytest.mark.asyncio
async def test_pipeline_runner_handles_request_payload_success():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')

    with patch.object(
        runner._adapter,
        'invoke_filter',
        new=AsyncMock(return_value={'model': 'model-1', 'ok': True}),
    ) as invoke_filter:
        result = await runner.handle_request_payload(
            b'{"trace_id":"trace-1","payload_version":"v1",'
            b'"payload":{"pipeline_id":"pipe-1","stage":"inlet","url_idx":0,'
            b'"user":{"id":"user-1"},"body":{"model":"model-1"}}}'
        )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {'model': 'model-1', 'ok': True},
        },
    }
    invoke_filter.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_runner_executes_internal_pipeline_without_http_adapter():
    app = _app()
    app.state.PIPELINE_FILTER_EXECUTORS['pipe-1'] = AsyncMock(return_value={'model': 'model-1', 'internal': True})
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    with patch.object(runner._adapter, 'invoke_filter', new=AsyncMock()) as invoke_filter:
        result = await runner.handle_request_payload(
            b'{"trace_id":"trace-1","payload_version":"v1",'
            b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal"},'
            b'"stage":"inlet","url_idx":0,"user":{"id":"user-1"},"body":{"model":"model-1"}}}'
        )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {'model': 'model-1', 'internal': True},
        },
    }
    invoke_filter.assert_not_awaited()
    app.state.PIPELINE_FILTER_EXECUTORS['pipe-1'].assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_runner_executes_internal_filter_function_module_when_registered_in_app_state():
    app = _app()
    captured = {}

    async def inlet(*, body, __user__, __metadata__, __files__, __model__, __request__, __id__):
        captured.update(
            {
                'body': body,
                'user': __user__,
                'metadata': __metadata__,
                'files': __files__,
                'model': __model__,
                'request_app': __request__.app,
                'id': __id__,
            }
        )
        return {'model': body['model'], 'function_internal': True}

    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(
            inlet=inlet,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    with patch.object(runner._adapter, 'invoke_filter', new=AsyncMock()) as invoke_filter:
        result = await runner.handle_request_payload(
            b'{"trace_id":"trace-1","payload_version":"v1",'
            b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal"},'
            b'"stage":"inlet","url_idx":0,"user":{"id":"user-1"},'
            b'"body":{"model":"model-1","metadata":{"trace":"m1"},"files":[{"id":"file-1"}]}}}'
        )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {'model': 'model-1', 'function_internal': True},
        },
    }
    assert captured == {
        'body': {'model': 'model-1', 'metadata': {'trace': 'm1'}, 'files': [{'id': 'file-1'}]},
        'user': {'id': 'user-1'},
        'metadata': {'trace': 'm1'},
        'files': [{'id': 'file-1'}],
        'model': {
            'id': 'pipe-1',
            'connection_type': 'internal',
            'urlIdx': 0,
            'internal_executor_id': None,
            'action_id': None,
            'sub_action_id': None,
        },
        'request_app': app,
        'id': 'pipe-1',
    }
    invoke_filter.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_runner_executes_internal_pipe_function_module_when_registered_in_app_state():
    app = _app()
    captured = {}

    async def pipe(*, body, __user__, __metadata__, __files__, __model__, __request__, __id__):
        captured.update(
            {
                'body': body,
                'user': __user__,
                'metadata': __metadata__,
                'files': __files__,
                'model': __model__,
                'request_app': __request__.app,
                'id': __id__,
            }
        )
        return {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'ok'}, 'finish_reason': 'stop'}]}

    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(
            pipe=pipe,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal","pipe":{"type":"pipe"}},'
        b'"stage":"pipe","user":{"id":"user-1"},'
        b'"body":{"model":"pipe-1","metadata":{"trace":"m1"},"files":[{"id":"file-1"}]}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {
                'choices': [
                    {
                        'index': 0,
                        'message': {'role': 'assistant', 'content': 'ok'},
                        'finish_reason': 'stop',
                    }
                ]
            },
        },
    }
    assert captured == {
        'body': {'model': 'pipe-1', 'metadata': {'trace': 'm1'}, 'files': [{'id': 'file-1'}]},
        'user': {'id': 'user-1'},
        'metadata': {'trace': 'm1'},
        'files': [{'id': 'file-1'}],
        'model': {
            'id': 'pipe-1',
            'connection_type': 'internal',
            'pipe': {'type': 'pipe'},
            'urlIdx': None,
            'internal_executor_id': None,
            'action_id': None,
            'sub_action_id': None,
        },
        'request_app': app,
        'id': 'pipe-1',
    }


@pytest.mark.asyncio
async def test_pipeline_runner_executes_internal_action_function_module_when_registered_in_app_state():
    app = _app()
    captured = {}

    async def action(*, body, __user__, __model__, __request__, __id__, __event_emitter__, __event_call__):
        captured.update(
            {
                'body': body,
                'user': __user__,
                'model': __model__,
                'request_app': __request__.app,
                'id': __id__,
                'event_emitter': __event_emitter__,
                'event_call': __event_call__,
            }
        )
        return {'ok': True}

    app.state.FUNCTIONS = {
        'action-1': SimpleNamespace(
            action=action,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"action-1","pipeline":{"id":"action-1","connection_type":"internal","action":{"type":"action"}},'
        b'"stage":"action","user":{"id":"user-1"},"body":{"model":"pipe-1"},"action_id":"action-1"}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': '{\n  "ok": true\n}',
        },
    }
    assert captured['body'] == {'model': 'pipe-1'}
    assert captured['user'] == {'id': 'user-1'}
    assert captured['model'] == {
        'id': 'action-1',
        'connection_type': 'internal',
        'action': {'type': 'action'},
        'urlIdx': None,
        'internal_executor_id': 'action-1',
        'action_id': 'action-1',
        'sub_action_id': None,
    }
    assert captured['request_app'] == app
    assert captured['id'] == 'action-1'
    assert callable(captured['event_emitter'])
    assert callable(captured['event_call'])


@pytest.mark.asyncio
async def test_pipeline_runner_preserves_sub_action_id_for_internal_action_execution():
    app = _app()
    captured = {}

    async def action(*, __id__):
        captured['id'] = __id__
        return {'ok': True}

    app.state.FUNCTIONS = {
        'action-1': SimpleNamespace(
            action=action,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"action-1.sub-1","pipeline":{"id":"action-1.sub-1","connection_type":"internal","action":{"type":"action"}},'
        b'"stage":"action","user":{"id":"user-1"},"body":{"model":"pipe-1"},"action_id":"action-1","sub_action_id":"sub-1"}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': '{\n  "ok": true\n}',
        },
    }
    assert captured['id'] == 'sub-1'


@pytest.mark.asyncio
async def test_pipeline_runner_normalizes_generator_pipe_output():
    app = _app()

    def pipe(*, body):
        yield 'hello '
        yield body['model']

    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(
            pipe=pipe,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal","pipe":{"type":"pipe"}},'
        b'"stage":"pipe","user":{"id":"user-1"},"body":{"model":"pipe-1"}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {
                'choices': [
                    {
                        'index': 0,
                        'message': {'role': 'assistant', 'content': 'hello pipe-1'},
                        'finish_reason': 'stop',
                    }
                ]
            },
        },
    }


@pytest.mark.asyncio
async def test_pipeline_runner_normalizes_async_generator_pipe_output():
    app = _app()

    async def pipe(*, body):
        yield 'hello '
        yield body['model']

    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(
            pipe=pipe,
        )
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal","pipe":{"type":"pipe"}},'
        b'"stage":"pipe","user":{"id":"user-1"},"body":{"model":"pipe-1"}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'ok',
        'data': {
            'body': {
                'choices': [
                    {
                        'index': 0,
                        'message': {'role': 'assistant', 'content': 'hello pipe-1'},
                        'finish_reason': 'stop',
                    }
                ]
            },
        },
    }


@pytest.mark.asyncio
async def test_pipeline_runner_errors_when_internal_executor_missing():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal"},'
        b'"stage":"inlet","url_idx":0,"user":{"id":"user-1"},"body":{"model":"model-1"}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'error',
        'status_code': 404,
        'detail': 'Internal pipeline executor not found: pipe-1',
    }


@pytest.mark.asyncio
async def test_pipeline_runner_errors_when_internal_action_handler_missing():
    app = _app()
    app.state.FUNCTIONS = {
        'action-1': SimpleNamespace(),
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"action-1","pipeline":{"id":"action-1","connection_type":"internal","action":{"type":"action"}},'
        b'"stage":"action","user":{"id":"user-1"},"body":{"model":"pipe-1"},"action_id":"action-1"}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'error',
        'status_code': 404,
        'detail': 'Internal action handler not found: action-1.action',
    }


@pytest.mark.asyncio
async def test_pipeline_runner_errors_when_internal_pipe_handler_missing():
    app = _app()
    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(),
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal","pipe":{"type":"pipe"}},'
        b'"stage":"pipe","user":{"id":"user-1"},"body":{"model":"pipe-1"}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'error',
        'status_code': 502,
        'detail': 'Pipeline request failed',
    }


@pytest.mark.asyncio
async def test_pipeline_runner_errors_when_internal_function_handler_missing():
    app = _app()
    app.state.FUNCTIONS = {
        'pipe-1': SimpleNamespace(),
    }
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(
        b'{"trace_id":"trace-1","payload_version":"v1",'
        b'"payload":{"pipeline_id":"pipe-1","pipeline":{"id":"pipe-1","connection_type":"internal"},'
        b'"stage":"inlet","url_idx":0,"user":{"id":"user-1"},"body":{"model":"model-1"}}}'
    )

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'error',
        'status_code': 404,
        'detail': 'Internal pipeline handler not found: pipe-1.inlet',
    }


def test_build_pipeline_runner_records_marks_service_owned_capabilities():
    app = _app()
    app.state.PIPELINE_FILTER_EXECUTORS = {
        'exec-1': object(),
        'exec-2': object(),
    }
    app.state.FUNCTIONS = {
        'filter-1': SimpleNamespace(inlet=object()),
        'filter-2': SimpleNamespace(outlet=object()),
        'pipe-1': SimpleNamespace(pipe=object()),
    }
    records = build_pipeline_runner_records(app)

    assert records == [
        {
            'service_id': 'pipeline-runner.default',
            'service_type': 'pipeline-runner',
            'instance_id': 'instance-1',
            'registration_scope': 'instance',
            'version': records[0]['version'],
            'status': 'healthy',
            'subjects': ['owui.cmd.pipeline.run', 'owui.cmd.pipeline.stage.run'],
            'capabilities': {
                'pipeline_runner': True,
                'transport': 'nats-request-reply',
                'service_owner': 'pipeline-runner',
                'execution_backend': 'internal-executor-or-http-compatibility-adapter',
                'durable_stage_execution': True,
                'registered_executor_count': 2,
                'function_filter_count': 2,
                'function_pipe_count': 1,
                'function_action_count': 0,
            },
            'routing': {
                'region': 'local',
                'workspace_scope': 'shared',
                'owner': 'pipeline-runner',
            },
            'observed_at': records[0]['observed_at'],
            'expires_at': records[0]['expires_at'],
            'heartbeat_interval_seconds': records[0]['heartbeat_interval_seconds'],
        }
    ]


@pytest.mark.asyncio
async def test_pipeline_runner_handles_invalid_json_payload():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(b'not-json')

    assert result['status'] == 'error'
    assert result['detail'] == 'Pipeline request payload is not valid JSON'


@pytest.mark.asyncio
async def test_pipeline_runner_handles_missing_fields():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')

    result = await runner.handle_request_payload(b'{"trace_id":"trace-1","payload":{"stage":"inlet"}}')

    assert result == {
        'trace_id': 'trace-1',
        'payload_version': 'v1',
        'status': 'error',
        'status_code': 502,
        'detail': 'Missing pipeline request field: pipeline_id',
    }


@pytest.mark.asyncio
async def test_start_pipeline_runner_with_retry_returns_supervisor():
    app = _app()

    with patch(
        'open_webui.utils.pipeline_runner.RetryingCoreNatsPipelineRunner.start',
        new=AsyncMock(return_value=None),
    ):
        supervisor = await start_pipeline_runner_with_retry(app, 'nats://nats:4222', retry_delay=0.01)

    assert supervisor is not None


@pytest.mark.asyncio
async def test_pipeline_runner_start_registers_provider_and_subscribes():
    app = _app()
    runner = CoreNatsPipelineRunner(app, 'nats://nats:4222', 'instance-1')
    fake_nc = FakeNatsConnection()

    with (
        patch('open_webui.utils.pipeline_runner._connect_nats', new=AsyncMock(return_value=fake_nc)),
        patch('open_webui.utils.pipeline_runner.ensure_pipeline_stage_stream', new=AsyncMock()),
        patch('open_webui.utils.pipeline_runner.ensure_pipeline_stage_consumer', new=AsyncMock()),
    ):
        started = await runner.start()

    assert started is True
    assert len(app.state.RUNTIME_SERVICE_RECORD_PROVIDERS) == 1
    fake_nc.subscribe.assert_awaited_once()
    fake_nc._js.pull_subscribe.assert_awaited_once()
    await runner.close()
    assert app.state.RUNTIME_SERVICE_RECORD_PROVIDERS == []
    fake_nc.drain.assert_awaited_once()


def test_publish_pipeline_stage_job_sync_schedules_on_main_loop():
    loop = Mock()
    future = Mock()
    future.result.return_value = None
    app = SimpleNamespace(state=SimpleNamespace(main_loop=loop, instance_id='instance-1'))
    pipeline_job = {'trace_id': 'trace-1', 'payload': {}}

    with patch('open_webui.utils.pipeline_runner.asyncio.run_coroutine_threadsafe', return_value=future) as schedule:
        publish_pipeline_stage_job_sync(app, 'nats://nats:4222', pipeline_job)

    schedule.assert_called_once()
    schedule.call_args.args[0].close()
    future.result.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_stage_message_acks_after_successful_execution():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')
    message = SimpleNamespace(
        data=json.dumps(
            {
                'trace_id': 'trace-1',
                'payload_version': 'v1',
                'payload': {'pipeline_id': 'pipe-1', 'stage': 'inlet', 'body': {'model': 'm1'}},
            }
        ).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch.object(
        runner,
        'handle_request_payload',
        new=AsyncMock(return_value={'status': 'ok', 'data': {'body': {}}}),
    ):
        await runner._handle_stage_message(message)

    message.ack.assert_awaited_once()
    message.nak.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_stage_message_naks_after_execution_failure():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')
    message = SimpleNamespace(
        data=json.dumps(
            {
                'trace_id': 'trace-1',
                'payload_version': 'v1',
                'payload': {'pipeline_id': 'pipe-1', 'stage': 'inlet', 'body': {'model': 'm1'}},
            }
        ).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch.object(
        runner,
        'handle_request_payload',
        new=AsyncMock(return_value={'status': 'error', 'status_code': 502, 'detail': 'boom'}),
    ):
        await runner._handle_stage_message(message)

    message.ack.assert_not_awaited()
    message.nak.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_stage_message_publishes_reply_when_reply_subject_present():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')
    runner._nc = SimpleNamespace(publish=AsyncMock())
    message = SimpleNamespace(
        data=json.dumps(
            {
                'trace_id': 'trace-1',
                'reply_subject': 'owui.reply.pipeline.stage.123',
                'payload_version': 'v1',
                'payload': {'pipeline_id': 'pipe-1', 'stage': 'inlet', 'body': {'model': 'm1'}},
            }
        ).encode('utf-8'),
        ack=AsyncMock(),
        nak=AsyncMock(),
    )

    with patch.object(
        runner,
        'handle_request_payload',
        new=AsyncMock(return_value={'status': 'ok', 'data': {'body': {'done': True}}}),
    ):
        await runner._handle_stage_message(message)

    runner._nc.publish.assert_awaited_once()
    message.ack.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_stage_run_ignores_nats_timeout_errors_between_fetches():
    runner = CoreNatsPipelineRunner(_app(), 'nats://nats:4222', 'instance-1')
    runner._stage_subscription = SimpleNamespace(
        fetch=AsyncMock(side_effect=[NatsTimeoutError(), asyncio.CancelledError()])
    )

    with pytest.raises(asyncio.CancelledError):
        await runner._run_stage_consumer()

    assert runner._stage_subscription.fetch.await_count == 2
