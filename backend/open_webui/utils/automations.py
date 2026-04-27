import logging
import asyncio
import time
from datetime import datetime
from typing import Optional
from uuid import uuid4

from dateutil.rrule import rrulestr
from fastapi import Request
from starlette.datastructures import Headers

from open_webui.constants import ERROR_MESSAGES
from open_webui.env import VERSION
from open_webui.utils.runtime_registry import build_custom_runtime_service_record
from open_webui.utils.task_messaging import build_domain_event, publish_app_event_sync

log = logging.getLogger(__name__)

AUTOMATION_RUN_STARTED_SUBJECT = 'owui.evt.automation.run.started'
AUTOMATION_RUN_COMPLETED_SUBJECT = 'owui.evt.automation.run.completed'
AUTOMATION_RUN_FAILED_SUBJECT = 'owui.evt.automation.run.failed'
SCHEDULER_POLL_INTERVAL = 10


def _now_dt():
    return datetime.utcnow()


def should_start_local_automation_scheduler(
    *,
    enable_automations: bool,
    nats_url: str,
    enable_embedded_runner: bool,
    automation_runner_present: bool,
    worker_only_mode: bool,
) -> bool:
    if worker_only_mode or not enable_automations or automation_runner_present:
        return False
    if nats_url:
        return enable_embedded_runner
    return True


def validate_rrule(rrule_str: str, tz: str = None) -> bool:
    try:
        rule = rrulestr(rrule_str, dtstart=_now_dt())
        if rule.after(_now_dt(), inc=True) is None:
            raise ValueError(ERROR_MESSAGES.AUTOMATION_NO_FUTURE_RUNS)
        return True
    except Exception as e:
        if isinstance(e, ValueError) and str(e) == str(ERROR_MESSAGES.AUTOMATION_NO_FUTURE_RUNS):
            raise
        raise ValueError(ERROR_MESSAGES.AUTOMATION_INVALID_RRULE(e))


def next_run_ns(rrule_str: str, tz: str = None) -> Optional[int]:
    rule = rrulestr(rrule_str, dtstart=_now_dt())
    dt = rule.after(_now_dt(), inc=True)
    if dt is None:
        return None
    return int(dt.timestamp() * 1_000_000_000)


def next_n_runs_ns(rrule_str: str, tz: str = None, count: int = 5) -> list[int]:
    rule = rrulestr(rrule_str, dtstart=_now_dt())
    runs = rule.xafter(_now_dt(), count=count, inc=True)
    return [int(dt.timestamp() * 1_000_000_000) for dt in runs]


def rrule_interval_seconds(rrule_str: str, tz: str = None) -> Optional[int]:
    runs = next_n_runs_ns(rrule_str, tz=tz, count=2)
    if len(runs) < 2:
        return None
    return int((runs[1] - runs[0]) / 1_000_000_000)


def execute_automation(app, automation, *, request_id: str | None = None, trigger: str = 'scheduled') -> None:
    """
    Execute an automation through the existing chat-completion pipeline.
    This remains local execution, but it now uses an explicit scheduler/runner seam
    and emits runtime events so the path can later move behind a NATS-owned runner.
    """
    try:
        from open_webui.models.automations import AutomationRuns
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.models.users import Users
        from open_webui.main import chat_completion as chat_completion_handler

        publish_app_event_sync(
            app,
            AUTOMATION_RUN_STARTED_SUBJECT,
            build_domain_event(
                event_type='automation.run.started',
                resource_type='automation',
                resource_id=automation.id,
                data={
                    'automation_id': automation.id,
                    'request_id': request_id,
                    'trigger': trigger,
                    'status': 'started',
                },
            ),
        )

        user = Users.get_user_by_id(automation.user_id)
        if not user:
            raise RuntimeError('User not found')

        prompt = automation.data['prompt']
        model_id = automation.data['model_id']
        user_msg_id = str(uuid4())
        assistant_msg_id = str(uuid4())

        chat = Chats.insert_new_chat(
            user.id,
            ChatForm(
                chat={
                    'title': automation.name,
                    'models': [model_id],
                    'history': {
                        'currentId': assistant_msg_id,
                        'messages': {
                            user_msg_id: {
                                'id': user_msg_id,
                                'parentId': None,
                                'role': 'user',
                                'content': prompt,
                                'childrenIds': [assistant_msg_id],
                                'timestamp': int(time.time()),
                                'models': [model_id],
                            },
                            assistant_msg_id: {
                                'id': assistant_msg_id,
                                'parentId': user_msg_id,
                                'role': 'assistant',
                                'content': '',
                                'done': False,
                                'model': model_id,
                                'childrenIds': [],
                                'timestamp': int(time.time()),
                            },
                        },
                    },
                    'messages': [{'role': 'user', 'content': prompt}],
                    'meta': {'automation_id': automation.id},
                }
            ),
        )

        if not chat:
            raise RuntimeError('Failed to create chat')

        form_data = {
            'model': model_id,
            'messages': [{'role': 'user', 'content': prompt}],
            'stream': True,
            'chat_id': chat.id,
            'id': assistant_msg_id,
            'parent_id': None,
            'user_message': {
                'id': user_msg_id,
                'parentId': None,
                'role': 'user',
                'content': prompt,
            },
            'session_id': f'automation:{automation.id}',
            'background_tasks': {},
        }

        request = _build_request(app)
        loop = getattr(app.state, 'main_loop', None)
        if loop and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(chat_completion_handler(request, form_data, user=user), loop).result(timeout=10)
        else:
            asyncio.run(chat_completion_handler(request, form_data, user=user))

        AutomationRuns.insert(
            automation_id=automation.id,
            status='success',
            chat_id=chat.id,
            error=None,
        )

        publish_app_event_sync(
            app,
            AUTOMATION_RUN_COMPLETED_SUBJECT,
            build_domain_event(
                event_type='automation.run.completed',
                resource_type='automation',
                resource_id=automation.id,
                data={
                    'automation_id': automation.id,
                    'request_id': request_id,
                    'trigger': trigger,
                    'status': 'success',
                    'chat_id': chat.id,
                },
            ),
        )
    except Exception as exc:
        log.exception('Failed to execute automation.')
        try:
            from open_webui.models.automations import AutomationRuns

            AutomationRuns.insert(
                automation_id=automation.id,
                status='error',
                chat_id=None,
                error=str(exc),
            )
            publish_app_event_sync(
                app,
                AUTOMATION_RUN_FAILED_SUBJECT,
                build_domain_event(
                    event_type='automation.run.failed',
                    resource_type='automation',
                    resource_id=automation.id,
                    data={
                        'automation_id': automation.id,
                        'request_id': request_id,
                        'trigger': trigger,
                        'status': 'error',
                        'error': str(exc),
                    },
                ),
            )
        except Exception:
            log.exception('Failed to record automation failure.')


def _build_request(app) -> Request:
    scope = {
        'type': 'http',
        'asgi': {'version': '3.0', 'spec_version': '2.0'},
        'method': 'POST',
        'path': '/api/v1/automations/internal',
        'query_string': b'',
        'headers': Headers({}).raw,
        'client': ('127.0.0.1', 0),
        'server': ('127.0.0.1', 80),
        'scheme': 'http',
        'app': app,
    }
    request = Request(scope)
    request.state.token = None
    request.state.enable_api_keys = False
    return request


def build_automation_runner_service_record(app, *, execution_mode: str | None = None) -> dict:
    nats_subject = getattr(
        app.state,
        'AUTOMATION_RUNTIME_NATS_SUBJECT',
        getattr(app.state.config, 'AUTOMATION_NATS_SUBJECT', 'owui.cmd.automation.run'),
    )
    mode = execution_mode or getattr(app.state, 'AUTOMATION_RUNTIME_EXECUTION_MODE', 'transitional-local')
    transport = 'nats-request-reply' if 'nats' in mode else 'in-process'
    return build_custom_runtime_service_record(
        service_id='automation-runner.default',
        service_type='automation-runner',
        instance_id=getattr(app.state, 'instance_id', 'unknown') or 'unknown',
        version=VERSION,
        status='healthy' if getattr(app.state.config, 'ENABLE_AUTOMATIONS', False) else 'degraded',
        subjects=[
            nats_subject,
            AUTOMATION_RUN_STARTED_SUBJECT,
            AUTOMATION_RUN_COMPLETED_SUBJECT,
            AUTOMATION_RUN_FAILED_SUBJECT,
        ],
        capabilities={
            'automations': bool(getattr(app.state.config, 'ENABLE_AUTOMATIONS', False)),
            'calendar': bool(getattr(app.state.config, 'ENABLE_CALENDAR', False)),
            'automation_runner': True,
            'transport': transport,
            'service_owner': 'automation-runner',
            'execution_mode': mode,
        },
        routing={
            'region': 'local',
            'workspace_scope': 'shared',
            'owner': 'automation-runner',
        },
    )


def register_automation_runtime_provider(app, *, execution_mode: str = 'transitional-local') -> None:
    app.state.AUTOMATION_RUNTIME_EXECUTION_MODE = execution_mode
    app.state.AUTOMATION_RUNTIME_NATS_SUBJECT = getattr(
        app.state.config,
        'AUTOMATION_NATS_SUBJECT',
        getattr(app.state, 'AUTOMATION_RUNTIME_NATS_SUBJECT', 'owui.cmd.automation.run'),
    )
    providers = list(getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', []))
    if any(getattr(provider, '__name__', '') == '_automation_provider' for provider in providers):
        return

    def _automation_provider():
        return [build_automation_runner_service_record(app)]

    providers.append(_automation_provider)
    app.state.RUNTIME_SERVICE_RECORD_PROVIDERS = providers


async def scheduler_worker_loop(app) -> None:
    log.info('Automation scheduler worker started (poll interval: %ss)', SCHEDULER_POLL_INTERVAL)
    from open_webui.models.automations import Automations

    while True:
        try:
            if getattr(app.state.config, 'ENABLE_AUTOMATIONS', False):
                due = Automations.claim_due(int(time.time_ns()), limit=10)
                for automation in due:
                    asyncio.create_task(
                        asyncio.to_thread(
                            execute_automation,
                            app,
                            automation,
                            request_id=f'scheduled-{uuid4().hex}',
                            trigger='scheduled',
                        )
                    )
        except Exception:
            log.exception('Automation scheduler loop iteration failed.')

        await asyncio.sleep(SCHEDULER_POLL_INTERVAL)
