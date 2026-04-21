import logging
import sys
import inspect
import json
from uuid import uuid4

from typing import Any

from fastapi import Request

from open_webui.models.users import UserModel
from open_webui.models.functions import Functions

from open_webui.socket.main import get_event_call, get_event_emitter
from open_webui.utils.plugin import get_function_module_from_cache
from open_webui.utils.models import get_all_models
from open_webui.utils.middleware import process_tool_result

from open_webui.env import GLOBAL_LOG_LEVEL, NATS_CONNECT_TIMEOUT, NATS_NAME

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
PIPELINE_STAGE_JOB_SUBJECT = 'owui.cmd.pipeline.stage.run'


def build_action_flag(function_module) -> dict:
    action_flag = {'type': 'action'}
    execution = getattr(function_module, 'execution', None)
    durable_stage = getattr(function_module, 'durable_stage', None)
    if execution:
        action_flag['execution'] = execution
    if durable_stage:
        action_flag['durable_stage'] = True
        action_flag.setdefault('execution', 'jetstream')
    return action_flag


def is_durable_action_flag(action_flag: dict) -> bool:
    return action_flag.get('execution') == 'jetstream' or bool(action_flag.get('durable_stage'))


async def request_action_via_runner(request: Request, action_id: str, form_data: dict, user: Any, model: dict):
    nats_url = getattr(request.app.state.config, 'NATS_URL', None)
    if not nats_url:
        raise RuntimeError('NATS_URL is not configured')

    import nats

    if '.' in action_id:
        root_action_id, sub_action_id = action_id.split('.')
    else:
        root_action_id, sub_action_id = action_id, None

    function_module, _, _ = get_function_module_from_cache(request, root_action_id)
    action_flag = build_action_flag(function_module)

    envelope = {
        'trace_id': f'trace_action_{uuid4().hex}',
        'payload_version': 'v1',
        'payload': {
            'pipeline_id': action_id,
            'pipeline': {
                'id': action_id,
                'connection_type': 'internal',
                'internal_executor_id': root_action_id,
                'action': action_flag,
            },
            'stage': 'action',
            'action_id': root_action_id,
            'sub_action_id': sub_action_id,
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
        name=f'{NATS_NAME}-action-{getattr(request.app.state, "instance_id", "runtime")}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )
    try:
        timeout = getattr(request.app.state.config, 'PIPELINE_NATS_REQUEST_TIMEOUT', 10.0)
        if is_durable_action_flag(action_flag):
            reply_subject = f'owui.reply.pipeline.stage.{uuid4().hex}'
            subscription = await nc.subscribe(reply_subject)
            await nc.jetstream().publish(
                PIPELINE_STAGE_JOB_SUBJECT,
                json.dumps({**envelope, 'reply_subject': reply_subject}).encode('utf-8'),
            )
            response = await subscription.next_msg(timeout=timeout)
            await subscription.unsubscribe()
        else:
            response = await nc.request(
                getattr(request.app.state.config, 'PIPELINE_NATS_SUBJECT', 'owui.cmd.pipeline.run'),
                json.dumps(envelope).encode('utf-8'),
                timeout=timeout,
            )
        payload = json.loads(response.data.decode('utf-8'))
        if payload.get('status') != 'ok':
            raise RuntimeError(payload.get('detail') or 'Internal action execution failed')
        data = payload.get('data') or {}
        body = data.get('body')
        if body is None:
            raise RuntimeError('Internal action execution returned invalid payload')
        return body
    finally:
        await nc.drain()


async def chat_action(request: Request, action_id: str, form_data: dict, user: Any):
    if '.' in action_id:
        action_id, sub_action_id = action_id.split('.')
    else:
        sub_action_id = None

    action = Functions.get_function_by_id(action_id)
    if not action:
        raise Exception(f'Action not found: {action_id}')

    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    data = form_data
    model_id = data['model']

    if model_id not in models:
        raise Exception('Model not found')
    model = models[model_id]

    if model.get('connection_type') == 'internal':
        try:
            return await request_action_via_runner(request, action_id, form_data, user, model)
        except Exception as e:
            log.warning('Falling back to direct internal action execution after runner failure: %s', e)

    __event_emitter__ = get_event_emitter(
        {
            'chat_id': data['chat_id'],
            'message_id': data['id'],
            'session_id': data['session_id'],
            'user_id': user.id,
        }
    )
    __event_call__ = get_event_call(
        {
            'chat_id': data['chat_id'],
            'message_id': data['id'],
            'session_id': data['session_id'],
            'user_id': user.id,
        }
    )

    function_module, _, _ = get_function_module_from_cache(request, action_id)

    if hasattr(function_module, 'valves') and hasattr(function_module, 'Valves'):
        valves = Functions.get_function_valves_by_id(action_id)
        function_module.valves = function_module.Valves(**(valves if valves else {}))

    if hasattr(function_module, 'action'):
        try:
            action = function_module.action

            # Get the signature of the function
            sig = inspect.signature(action)
            params = {'body': data}

            # Extra parameters to be passed to the function
            extra_params = {
                '__model__': model,
                '__id__': sub_action_id if sub_action_id is not None else action_id,
                '__event_emitter__': __event_emitter__,
                '__event_call__': __event_call__,
                '__request__': request,
            }

            # Add extra params in contained in function signature
            for key, value in extra_params.items():
                if key in sig.parameters:
                    params[key] = value

            if '__user__' in sig.parameters:
                __user__ = user.model_dump() if isinstance(user, UserModel) else {}

                try:
                    if hasattr(function_module, 'UserValves'):
                        __user__['valves'] = function_module.UserValves(
                            **Functions.get_user_valves_by_id_and_user_id(action_id, user.id)
                        )
                except Exception as e:
                    log.exception(f'Failed to get user values: {e}')

                params = {**params, '__user__': __user__}

            if inspect.iscoroutinefunction(action):
                data = await action(**params)
            else:
                data = action(**params)

            # Process action result for Rich UI embeds (HTMLResponse, tuple with headers)
            processed_result, _, action_embeds = process_tool_result(
                request,
                action_id,
                data,
                'action',
            )

            if action_embeds:
                await __event_emitter__(
                    {
                        'type': 'embeds',
                        'data': {
                            'embeds': action_embeds,
                        },
                    }
                )
                # Replace data with the processed status dict so we don't
                # try to serialize the raw HTMLResponse / tuple back to the client
                data = processed_result

        except Exception as e:
            raise Exception(f'Error: {e}')

    return data
