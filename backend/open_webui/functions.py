import logging
import sys
import inspect
import json
import asyncio
from uuid import uuid4

from pydantic import BaseModel
from typing import AsyncGenerator, Generator, Iterator
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from starlette.responses import Response, StreamingResponse


from open_webui.constants import ERROR_MESSAGES
from open_webui.socket.main import (
    get_event_call,
    get_event_emitter,
)


from open_webui.models.users import UserModel
from open_webui.models.functions import Functions
from open_webui.models.models import Models

from open_webui.utils.plugin import (
    load_function_module_by_id,
    get_function_module_from_cache,
)
from open_webui.utils.tools import get_tools

from open_webui.env import GLOBAL_LOG_LEVEL, NATS_CONNECT_TIMEOUT, NATS_NAME

from open_webui.utils.misc import (
    add_or_update_system_message,
    get_last_user_message,
    prepend_to_first_user_message_content,
    openai_chat_chunk_message_template,
    openai_chat_completion_message_template,
)
from open_webui.utils.payload import (
    apply_model_params_to_body_openai,
    apply_system_prompt_to_body,
)

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
PIPELINE_STAGE_JOB_STREAM = 'owui_pipeline_jobs'
PIPELINE_STAGE_JOB_SUBJECT = 'owui.cmd.pipeline.stage.run'


def get_function_module_by_id(request: Request, pipe_id: str):
    function_module, _, _ = get_function_module_from_cache(request, pipe_id)

    if hasattr(function_module, 'valves') and hasattr(function_module, 'Valves'):
        Valves = function_module.Valves
        valves = Functions.get_function_valves_by_id(pipe_id)

        if valves:
            try:
                function_module.valves = Valves(**{k: v for k, v in valves.items() if v is not None})
            except Exception as e:
                log.exception(f'Error loading valves for function {pipe_id}: {e}')
                raise e
        else:
            function_module.valves = Valves()

    return function_module


async def get_function_models(request):
    pipes = Functions.get_functions_by_type('pipe', active_only=True)
    pipe_models = []

    for pipe in pipes:
        try:
            function_module = get_function_module_by_id(request, pipe.id)

            has_user_valves = False
            if hasattr(function_module, 'UserValves'):
                has_user_valves = True

            # Check if function is a manifold
            if hasattr(function_module, 'pipes'):
                sub_pipes = []

                # Handle pipes being a list, sync function, or async function
                try:
                    if callable(function_module.pipes):
                        if asyncio.iscoroutinefunction(function_module.pipes):
                            sub_pipes = await function_module.pipes()
                        else:
                            sub_pipes = function_module.pipes()
                    else:
                        sub_pipes = function_module.pipes
                except Exception as e:
                    log.exception(e)
                    sub_pipes = []

                log.debug(f"get_function_models: function '{pipe.id}' is a manifold of {sub_pipes}")

                for p in sub_pipes:
                    sub_pipe_id = f'{pipe.id}.{p["id"]}'
                    sub_pipe_name = p['name']

                    if hasattr(function_module, 'name'):
                        sub_pipe_name = f'{function_module.name}{sub_pipe_name}'

                    pipe_flag = build_pipe_flag(function_module, pipe.type)

                    pipe_models.append(
                        {
                            'id': sub_pipe_id,
                            'name': sub_pipe_name,
                            'object': 'model',
                            'created': pipe.created_at,
                            'owned_by': 'openai',
                            'connection_type': 'internal',
                            'internal_executor_id': pipe.id,
                            'execution_mode': pipe_flag.get('execution', 'request_reply'),
                            'pipe': pipe_flag,
                            'has_user_valves': has_user_valves,
                        }
                    )
            else:
                pipe_flag = build_pipe_flag(function_module, 'pipe')

                log.debug(
                    f"get_function_models: function '{pipe.id}' is a single pipe {{ 'id': {pipe.id}, 'name': {pipe.name} }}"
                )

                pipe_models.append(
                    {
                        'id': pipe.id,
                        'name': pipe.name,
                        'object': 'model',
                        'created': pipe.created_at,
                        'owned_by': 'openai',
                        'connection_type': 'internal',
                        'internal_executor_id': pipe.id,
                        'execution_mode': pipe_flag.get('execution', 'request_reply'),
                        'pipe': pipe_flag,
                        'has_user_valves': has_user_valves,
                    }
                )
        except Exception as e:
            log.exception(e)
            continue

    return pipe_models


def build_pipe_flag(function_module, pipe_type: str) -> dict:
    pipe_flag = {'type': pipe_type}
    execution = getattr(function_module, 'execution', None)
    durable_stage = getattr(function_module, 'durable_stage', None)
    if execution:
        pipe_flag['execution'] = execution
    if durable_stage:
        pipe_flag['durable_stage'] = True
        pipe_flag.setdefault('execution', 'jetstream')
    return pipe_flag


def is_durable_pipe_model(model: dict) -> bool:
    pipe_meta = model.get('pipe') or {}
    return pipe_meta.get('execution') == 'jetstream' or bool(pipe_meta.get('durable_stage'))


async def request_function_chat_completion_via_runner(request, form_data, user, model):
    nats_url = getattr(request.app.state.config, 'NATS_URL', None)
    if not nats_url:
        raise RuntimeError('NATS_URL is not configured')

    import nats

    pipe_id = form_data['model'].split('.', 1)[0]
    pipe_meta = model.get('pipe', {'type': 'pipe'})
    envelope = {
        'trace_id': f'trace_pipe_{pipe_id}_{uuid4().hex}',
        'payload_version': 'v1',
        'payload': {
            'pipeline_id': form_data['model'],
            'pipeline': {
                'id': form_data['model'],
                'connection_type': 'internal',
                'internal_executor_id': model.get('internal_executor_id', pipe_id),
                'pipe': pipe_meta,
            },
            'stage': 'pipe',
            'user': {
                'id': user.id,
                'name': getattr(user, 'name', None),
                'email': getattr(user, 'email', None),
                'role': getattr(user, 'role', None),
            },
            'body': form_data,
        },
    }

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    nc = await nats.connect(
        servers=servers,
        name=f'open-webui-function-pipe-{getattr(request.app.state, "instance_id", "runtime")}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )
    try:
        timeout = getattr(request.app.state.config, 'PIPELINE_NATS_REQUEST_TIMEOUT', 10.0)
        if is_durable_pipe_model(model):
            reply_subject = f'owui.reply.pipeline.stage.{uuid4().hex}'
            subscription = await nc.subscribe(reply_subject)
            try:
                if hasattr(nc, 'flush'):
                    await nc.flush()
                await nc.jetstream().publish(
                    PIPELINE_STAGE_JOB_SUBJECT,
                    json.dumps({**envelope, 'reply_subject': reply_subject}).encode('utf-8'),
                    stream=PIPELINE_STAGE_JOB_STREAM,
                )
                response = await subscription.next_msg(timeout=timeout)
            finally:
                await subscription.unsubscribe()
        else:
            response = await nc.request(
                getattr(request.app.state.config, 'PIPELINE_NATS_SUBJECT', 'owui.cmd.pipeline.run'),
                json.dumps(envelope).encode('utf-8'),
                timeout=timeout,
            )
        payload = json.loads(response.data.decode('utf-8'))
        if payload.get('status') != 'ok':
            raise RuntimeError(payload.get('detail') or 'Internal pipe execution failed')
        data = payload.get('data') or {}
        body = data.get('body')
        if not isinstance(body, dict):
            raise RuntimeError('Internal pipe execution returned invalid payload')
        return body
    finally:
        await nc.drain()


async def generate_function_chat_completion(request, form_data, user, models: dict = {}):
    async def execute_pipe(pipe, params):
        if inspect.iscoroutinefunction(pipe):
            return await pipe(**params)
        else:
            return pipe(**params)

    async def get_message_content(res: str | Generator | AsyncGenerator) -> str:
        if isinstance(res, str):
            return res
        if isinstance(res, Generator):
            return ''.join(map(str, res))
        if isinstance(res, AsyncGenerator):
            return ''.join([str(stream) async for stream in res])

    def process_line(form_data: dict, line):
        if isinstance(line, BaseModel):
            line = line.model_dump_json()
            line = f'data: {line}'
        if isinstance(line, dict):
            line = f'data: {json.dumps(line)}'

        try:
            line = line.decode('utf-8')
        except Exception:
            pass

        if line.startswith('data:'):
            return f'{line}\n\n'
        else:
            line = openai_chat_chunk_message_template(form_data['model'], line)
            return f'data: {json.dumps(line)}\n\n'

    def get_pipe_id(form_data: dict) -> str:
        pipe_id = form_data['model']
        if '.' in pipe_id:
            pipe_id, _ = pipe_id.split('.', 1)
        return pipe_id

    def get_function_params(function_module, form_data, user, extra_params=None):
        if extra_params is None:
            extra_params = {}

        pipe_id = get_pipe_id(form_data)

        # Get the signature of the function
        sig = inspect.signature(function_module.pipe)
        params = {'body': form_data} | {k: v for k, v in extra_params.items() if k in sig.parameters}

        if '__user__' in params and hasattr(function_module, 'UserValves'):
            user_valves = Functions.get_user_valves_by_id_and_user_id(pipe_id, user.id)
            try:
                params['__user__']['valves'] = function_module.UserValves(**user_valves)
            except Exception as e:
                log.exception(e)
                params['__user__']['valves'] = function_module.UserValves()

        return params

    model_id = form_data.get('model')
    model_info = Models.get_model_by_id(model_id)

    metadata = form_data.pop('metadata', {})

    files = metadata.get('files', [])
    tool_ids = metadata.get('tool_ids', [])
    # Check if tool_ids is None
    if tool_ids is None:
        tool_ids = []

    __event_emitter__ = None
    __event_call__ = None
    __task__ = None
    __task_body__ = None

    if metadata:
        if all(k in metadata for k in ('session_id', 'chat_id', 'message_id')):
            __event_emitter__ = get_event_emitter(metadata)
            __event_call__ = get_event_call(metadata)
        __task__ = metadata.get('task', None)
        __task_body__ = metadata.get('task_body', None)

    oauth_token = None
    try:
        if request.cookies.get('oauth_session_id', None):
            oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                user.id,
                request.cookies.get('oauth_session_id', None),
            )
    except Exception as e:
        log.error(f'Error getting OAuth token: {e}')

    extra_params = {
        '__event_emitter__': __event_emitter__,
        '__event_call__': __event_call__,
        '__chat_id__': metadata.get('chat_id', None),
        '__session_id__': metadata.get('session_id', None),
        '__message_id__': metadata.get('message_id', None),
        '__task__': __task__,
        '__task_body__': __task_body__,
        '__files__': files,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__oauth_token__': oauth_token,
        '__request__': request,
    }
    extra_params['__tools__'] = await get_tools(
        request,
        tool_ids,
        user,
        {
            **extra_params,
            '__model__': models.get(form_data['model'], None),
            '__messages__': form_data['messages'],
            '__files__': files,
        },
    )

    if model_info:
        if model_info.base_model_id:
            form_data['model'] = model_info.base_model_id

        params = model_info.params.model_dump()

        if params:
            system = params.pop('system', None)
            form_data = apply_model_params_to_body_openai(params, form_data)
            form_data = apply_system_prompt_to_body(system, form_data, metadata, user)

    pipe_id = get_pipe_id(form_data)
    function_module = get_function_module_by_id(request, pipe_id)

    pipe = function_module.pipe
    params = get_function_params(function_module, form_data, user, extra_params)

    if form_data.get('stream', False):

        async def stream_content():
            try:
                res = await execute_pipe(pipe, params)

                # Directly return if the response is a StreamingResponse
                if isinstance(res, StreamingResponse):
                    async for data in res.body_iterator:
                        yield data
                    return
                if isinstance(res, dict):
                    yield f'data: {json.dumps(res)}\n\n'
                    return

            except Exception as e:
                log.error(f'Error: {e}')
                yield f'data: {json.dumps({"error": {"detail": str(e)}})}\n\n'
                return

            if isinstance(res, str):
                message = openai_chat_chunk_message_template(form_data['model'], res)
                yield f'data: {json.dumps(message)}\n\n'

            if isinstance(res, Iterator):
                for line in res:
                    yield process_line(form_data, line)

            if isinstance(res, AsyncGenerator):
                async for line in res:
                    yield process_line(form_data, line)

            if isinstance(res, str) or isinstance(res, Generator):
                finish_message = openai_chat_chunk_message_template(form_data['model'], '')
                finish_message['choices'][0]['finish_reason'] = 'stop'
                yield f'data: {json.dumps(finish_message)}\n\n'
                yield 'data: [DONE]'

        return StreamingResponse(stream_content(), media_type='text/event-stream')
    else:
        try:
            res = await execute_pipe(pipe, params)

        except Exception as e:
            log.error(f'Error: {e}')
            return {'error': {'detail': str(e)}}

        if isinstance(res, StreamingResponse) or isinstance(res, dict):
            return res
        if isinstance(res, BaseModel):
            return res.model_dump()

        message = await get_message_content(res)
        return openai_chat_completion_message_template(form_data['model'], message)
