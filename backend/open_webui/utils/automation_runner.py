import asyncio
import json
import logging
from uuid import uuid4

from open_webui.env import (
    AUTOMATION_NATS_REQUEST_TIMEOUT,
    AUTOMATION_NATS_SUBJECT,
    NATS_CONNECT_TIMEOUT,
    NATS_NAME,
)
from open_webui.utils.automations import (
    execute_automation,
    register_automation_runtime_provider,
    scheduler_worker_loop,
)
from open_webui.utils.runtime_registry import sync_runtime_registry

log = logging.getLogger(__name__)

AUTOMATION_RUNNER_RETRY_DELAY = 5.0


def should_start_automation_runner(
    *,
    enable_automations: bool,
    nats_url: str,
    enable_embedded_runner: bool,
    automation_runner_only_mode: bool,
) -> bool:
    if not enable_automations or not nats_url:
        return False
    return automation_runner_only_mode or enable_embedded_runner


async def start_automation_runner(app, nats_url: str):
    runner = AutomationRunner(app, nats_url, getattr(app.state, 'instance_id', None))
    started = await runner.start()
    if started:
        return runner
    return None


async def start_automation_runner_with_retry(
    app,
    nats_url: str,
    *,
    retry_delay: float = AUTOMATION_RUNNER_RETRY_DELAY,
):
    supervisor = RetryingAutomationRunner(
        app,
        nats_url,
        getattr(app.state, 'instance_id', None),
        retry_delay=retry_delay,
    )
    await supervisor.start()
    return supervisor


async def request_automation_run(app, automation, *, background_tasks=None) -> dict:
    request_id = f'automation-{uuid4().hex}'
    nats_url = getattr(app.state.config, 'NATS_URL', '')
    subject = getattr(app.state.config, 'AUTOMATION_NATS_SUBJECT', AUTOMATION_NATS_SUBJECT)
    timeout = getattr(app.state.config, 'AUTOMATION_NATS_REQUEST_TIMEOUT', AUTOMATION_NATS_REQUEST_TIMEOUT)

    if nats_url:
        nc = await _connect_nats(nats_url, instance_id=getattr(app.state, 'instance_id', None))
        try:
            response = await nc.request(
                subject,
                json.dumps(
                    {
                        'automation_id': automation.id,
                        'request_id': request_id,
                        'trigger': 'manual-request',
                    }
                ).encode('utf-8'),
                timeout=timeout,
            )
            payload = json.loads(response.data.decode('utf-8'))
            if payload.get('status') != 'accepted':
                raise RuntimeError(payload.get('detail', 'Automation runner rejected request'))
            return payload
        except Exception:
            log.exception('Automation run request failed for %s.', automation.id)
            raise RuntimeError('Automation runner unavailable')
        finally:
            await nc.drain()

    if background_tasks is not None:
        background_tasks.add_task(
            execute_automation,
            app,
            automation,
            request_id=request_id,
            trigger='manual-local',
        )
    else:
        asyncio.create_task(
            asyncio.to_thread(
                execute_automation,
                app,
                automation,
                request_id=request_id,
                trigger='manual-local',
            )
        )

    return {
        'status': 'accepted',
        'request_id': request_id,
        'automation_id': automation.id,
        'owner': 'web-local',
    }


class RetryingAutomationRunner:
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
            runner = AutomationRunner(self.app, self.nats_url, self.instance_id)
            started = await runner.start()
            if started:
                self._runner = runner
                return

            await runner.close()

            if not runner.retryable_failure:
                return

            log.warning(
                'Automation runner startup failed; retrying in %.1f seconds.',
                self.retry_delay,
            )
            await asyncio.sleep(self.retry_delay)


class AutomationRunner:
    def __init__(self, app, nats_url: str, instance_id: str | None = None):
        self.app = app
        self.nats_url = nats_url
        self.instance_id = instance_id or 'unknown'
        self.retryable_failure = False
        self._nc = None
        self._subscription = None
        self._scheduler_task = None

    async def start(self) -> bool:
        if not self.nats_url:
            self.retryable_failure = False
            return False

        try:
            self._nc = await _connect_nats(self.nats_url, instance_id=self.instance_id)
        except ImportError:
            self.retryable_failure = False
            log.warning('Automation runner selected, but nats-py is not installed.')
            return False
        except Exception:
            self.retryable_failure = True
            log.exception('Failed to connect automation runner to NATS.')
            return False

        self.app.state.AUTOMATION_RUNTIME_NATS_SUBJECT = getattr(
            self.app.state.config,
            'AUTOMATION_NATS_SUBJECT',
            AUTOMATION_NATS_SUBJECT,
        )
        register_automation_runtime_provider(self.app, execution_mode='nats-runner')
        self._subscription = await self._nc.subscribe(
            getattr(self.app.state.config, 'AUTOMATION_NATS_SUBJECT', AUTOMATION_NATS_SUBJECT),
            cb=self._handle_message,
        )
        self._scheduler_task = asyncio.create_task(scheduler_worker_loop(self.app))
        try:
            await asyncio.wait_for(sync_runtime_registry(self.app, nats_url=self.nats_url), timeout=2.0)
        except Exception:
            log.exception('Failed to sync automation-runner runtime registry record during startup.')
        self.retryable_failure = False
        return True

    async def close(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None

        if self._subscription is not None:
            try:
                await self._subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe automation runner.', exc_info=True)
            self._subscription = None

        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                log.debug('Failed to drain automation runner connection.', exc_info=True)
            self._nc = None

    async def _handle_message(self, message) -> None:
        response = await self.handle_request_payload(message.data)
        await message.respond(json.dumps(response).encode('utf-8'))

    async def handle_request_payload(self, payload_bytes: bytes) -> dict:
        try:
            payload = json.loads(payload_bytes.decode('utf-8'))
        except Exception:
            return _error_response(detail='Automation request payload is not valid JSON')

        automation_id = payload.get('automation_id')
        if not automation_id:
            return _error_response(detail='Missing automation_id', status_code=400)

        from open_webui.models.automations import Automations

        automation = Automations.get_by_id(automation_id)
        if automation is None:
            return _error_response(detail='Automation not found', status_code=404)

        request_id = payload.get('request_id') or f'automation-{uuid4().hex}'
        trigger = payload.get('trigger') or 'manual-request'
        asyncio.create_task(
            asyncio.to_thread(
                execute_automation,
                self.app,
                automation,
                request_id=request_id,
                trigger=trigger,
            )
        )

        return {
            'status': 'accepted',
            'request_id': request_id,
            'automation_id': automation.id,
            'owner': 'automation-runner',
        }


async def _connect_nats(nats_url: str, *, instance_id: str | None = None):
    import nats

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    return await nats.connect(
        servers=servers,
        name=f'{NATS_NAME}-automation-runner-{instance_id or "runtime"}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )


def _error_response(*, detail: str, status_code: int = 502) -> dict:
    return {
        'status': 'error',
        'status_code': status_code,
        'detail': detail,
    }
