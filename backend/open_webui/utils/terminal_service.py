import asyncio
import datetime as dt
import json
import logging

from fastapi import Request
from open_webui.env import (
    NATS_CONNECT_TIMEOUT,
    NATS_NAME,
    TERMINAL_CONTROL_REQUEST_TIMEOUT,
    VERSION,
)
from open_webui.utils.runtime_registry import build_custom_runtime_service_record
from open_webui.utils.task_messaging import (
    TERMINAL_SESSION_ATTACHED_SUBJECT,
    TERMINAL_SESSION_CREATED_SUBJECT,
    TERMINAL_SESSION_DISCONNECTED_SUBJECT,
    TERMINAL_SESSION_FAILED_SUBJECT,
)
from open_webui.utils.tools import set_terminal_servers
from starlette.datastructures import Headers

log = logging.getLogger(__name__)

TERMINAL_SERVICE_RETRY_DELAY = 5.0
TERMINAL_SESSION_CREATE_SUBJECT = 'owui.cmd.terminal.session.create'
TERMINAL_SESSION_ATTACH_SUBJECT = 'owui.cmd.terminal.session.attach'


def should_start_terminal_service(
    *,
    terminal_connections: list[dict],
    nats_url: str,
    enable_embedded_service: bool,
    terminal_service_only_mode: bool,
) -> bool:
    if not nats_url:
        return False
    if not terminal_connections and not terminal_service_only_mode:
        return False
    return terminal_service_only_mode or enable_embedded_service


async def start_terminal_service(app, nats_url: str):
    service = TerminalService(app, nats_url)
    started = await service.start()
    if started:
        return service
    return None


async def start_terminal_service_with_retry(
    app,
    nats_url: str,
    *,
    retry_delay: float = TERMINAL_SERVICE_RETRY_DELAY,
):
    supervisor = RetryingTerminalService(app, nats_url, retry_delay=retry_delay)
    await supervisor.start()
    return supervisor


class RetryingTerminalService:
    def __init__(self, app, nats_url: str, *, retry_delay: float = 5.0):
        self.app = app
        self.nats_url = nats_url
        self.retry_delay = retry_delay
        self._service = None
        self._task = None

    async def start(self):
        self._task = asyncio.create_task(self._run())
        return self

    async def close(self):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._service is not None:
            await self._service.close()
            self._service = None

    async def _run(self):
        while True:
            service = TerminalService(self.app, self.nats_url)
            started = await service.start()
            if started:
                self._service = service
                return

            await service.close()

            if not service.retryable_failure:
                return

            log.warning('Terminal service startup failed; retrying in %.1f seconds.', self.retry_delay)
            await asyncio.sleep(self.retry_delay)


class TerminalService:
    def __init__(self, app, nats_url: str):
        self.app = app
        self.nats_url = nats_url
        self.retryable_failure = False
        self._provider = None
        self._nc = None
        self._subscriptions = []
        self._session_registry: dict[str, dict] = {}
        self._session_registry_task = None

    async def start(self) -> bool:
        if not self.nats_url:
            self.retryable_failure = False
            return False

        disabled_types = set(getattr(self.app.state, 'RUNTIME_SERVICE_DISABLED_TYPES', set()))
        disabled_types.add('terminal')
        self.app.state.RUNTIME_SERVICE_DISABLED_TYPES = disabled_types

        providers = list(getattr(self.app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', []))
        self._provider = lambda: build_terminal_service_records(self.app)
        providers.append(self._provider)
        self.app.state.RUNTIME_SERVICE_RECORD_PROVIDERS = providers

        try:
            await set_terminal_servers(_build_internal_request(self.app))
            self._nc = await _connect_nats(self.nats_url, instance_id=getattr(self.app.state, 'instance_id', None))
            self._subscriptions = [
                await self._nc.subscribe(TERMINAL_SESSION_CREATE_SUBJECT, cb=self._handle_create_request),
                await self._nc.subscribe(TERMINAL_SESSION_ATTACH_SUBJECT, cb=self._handle_attach_request),
                await self._nc.subscribe(TERMINAL_SESSION_CREATED_SUBJECT, cb=self._handle_session_event_message),
                await self._nc.subscribe(TERMINAL_SESSION_ATTACHED_SUBJECT, cb=self._handle_session_event_message),
                await self._nc.subscribe(TERMINAL_SESSION_DISCONNECTED_SUBJECT, cb=self._handle_session_event_message),
                await self._nc.subscribe(TERMINAL_SESSION_FAILED_SUBJECT, cb=self._handle_session_event_message),
            ]
            self._session_registry_task = asyncio.create_task(self._run_session_registry_cleanup())
        except Exception:
            self.retryable_failure = True
            log.exception('Failed to initialize terminal service cache/registry state.')
            return False

        self.retryable_failure = False
        return True

    async def close(self):
        if self._session_registry_task is not None:
            self._session_registry_task.cancel()
            try:
                await self._session_registry_task
            except asyncio.CancelledError:
                pass
            self._session_registry_task = None

        for subscription in self._subscriptions:
            try:
                await subscription.unsubscribe()
            except Exception:
                log.debug('Failed to unsubscribe terminal service control subject.', exc_info=True)
        self._subscriptions = []

        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                log.debug('Failed to drain terminal service NATS connection.', exc_info=True)
            self._nc = None

        if self._provider is not None:
            providers = [
                provider
                for provider in getattr(self.app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])
                if provider is not self._provider
            ]
            self.app.state.RUNTIME_SERVICE_RECORD_PROVIDERS = providers
            self._provider = None

    async def _handle_create_request(self, message):
        response = self.handle_control_request('create', json.loads(message.data.decode('utf-8')))
        await message.respond(json.dumps(response).encode('utf-8'))

    async def _handle_attach_request(self, message):
        response = self.handle_control_request('attach', json.loads(message.data.decode('utf-8')))
        await message.respond(json.dumps(response).encode('utf-8'))

    async def _handle_session_event_message(self, message):
        try:
            event = json.loads(message.data.decode('utf-8'))
        except Exception:
            log.exception('Failed to decode terminal session event payload.')
            return

        self.record_session_event(event)

    async def _run_session_registry_cleanup(self) -> None:
        ttl_seconds = getattr(self.app.state.config, 'TERMINAL_SESSION_REGISTRY_TTL_SECONDS', 600)
        sleep_seconds = max(30, min(60, ttl_seconds // 2))
        while True:
            self.prune_session_registry(ttl_seconds=ttl_seconds)
            await asyncio.sleep(sleep_seconds)

    def handle_control_request(self, action: str, payload: dict) -> dict:
        server_id = payload.get('server_id')
        session_id = payload.get('session_id')
        if not server_id:
            return _error_response(detail='Missing terminal control field: server_id')

        terminal_connections = getattr(self.app.state.config, 'TERMINAL_SERVER_CONNECTIONS', []) or []
        connection = next(
            (c for c in terminal_connections if c.get('id') == server_id),
            None,
        )
        if connection is None:
            return _error_response(detail='Terminal server not found', status_code=404)

        if action == 'attach' and session_id:
            session_entry = self._session_registry.get(session_id)
            if session_entry is not None:
                if session_entry.get('server_id') != server_id:
                    return _error_response(
                        detail='Terminal session does not belong to the requested server',
                        status_code=409,
                    )
                if session_entry.get('status') in {'failed', 'disconnected'}:
                    return _error_response(detail='Terminal session is not active', status_code=409)

                resolved_url = session_entry.get('resolved_url')
                if resolved_url:
                    return {
                        'status': 'ok',
                        'data': {
                            'server_id': server_id,
                            'action': action,
                            'resolved_url': resolved_url.rstrip('/'),
                            'route_source': session_entry.get('route_source', 'runtime'),
                            'session_status': session_entry.get('status'),
                            'lifecycle_source': 'session_registry',
                        },
                    }

        cached_servers = {
            server.get('id'): server
            for server in getattr(self.app.state, 'TERMINAL_SERVERS', []) or []
        }
        cached_server = cached_servers.get(server_id, {})
        runtime = cached_server.get('runtime') or {}
        route_source = 'runtime' if runtime.get('route_eligible') else 'config_fallback'
        resolved_url = (
            cached_server.get('url')
            if route_source == 'runtime' and cached_server.get('url')
            else connection.get('url')
        )

        if not resolved_url:
            return _error_response(detail='Terminal server URL not configured', status_code=503)

        return {
            'status': 'ok',
            'data': {
                'server_id': server_id,
                'action': action,
                'resolved_url': resolved_url.rstrip('/'),
                'route_source': route_source,
                'session_status': self._session_registry.get(session_id, {}).get('status') if session_id else None,
                'lifecycle_source': 'routing_fallback',
            },
        }

    def record_session_event(self, event: dict) -> None:
        data = event.get('data') or {}
        session_id = data.get('session_id')
        if not session_id:
            return

        current = self._session_registry.get(session_id, {})
        self._session_registry[session_id] = {
            **current,
            'session_id': session_id,
            'server_id': data.get('server_id') or current.get('server_id'),
            'status': data.get('status') or current.get('status'),
            'route_source': data.get('route_source') or current.get('route_source'),
            'resolved_url': data.get('resolved_url') or current.get('resolved_url'),
            'event_type': event.get('event_type') or current.get('event_type'),
            'updated_at': event.get('occurred_at') or current.get('updated_at'),
        }
        self.app.state._TERMINAL_SESSION_REGISTRY = dict(self._session_registry)

    def prune_session_registry(
        self,
        *,
        ttl_seconds: int | None = None,
        now: dt.datetime | None = None,
    ) -> None:
        ttl = ttl_seconds or getattr(self.app.state.config, 'TERMINAL_SESSION_REGISTRY_TTL_SECONDS', 600)
        current = now or dt.datetime.now(dt.UTC)
        stale_session_ids = []
        for session_id, session in self._session_registry.items():
            updated_at = _parse_timestamp(session.get('updated_at'))
            if updated_at is None:
                stale_session_ids.append(session_id)
                continue
            if (current - updated_at).total_seconds() > ttl:
                stale_session_ids.append(session_id)

        for session_id in stale_session_ids:
            self._session_registry.pop(session_id, None)
        self.app.state._TERMINAL_SESSION_REGISTRY = dict(self._session_registry)


def build_terminal_service_records(app) -> list[dict]:
    session_registry = getattr(app.state, '_TERMINAL_SESSION_REGISTRY', {}) or {}
    active_session_count = sum(
        1
        for session in session_registry.values()
        if session.get('status') not in {'failed', 'disconnected'}
    )
    lifecycle_state = 'active' if active_session_count > 0 else 'idle'
    session_counts_by_server: dict[str, dict[str, int]] = {}
    for session in session_registry.values():
        server_id = session.get('server_id')
        if not server_id:
            continue
        bucket = session_counts_by_server.setdefault(
            server_id,
            {'session_registry_entries': 0, 'active_session_count': 0},
        )
        bucket['session_registry_entries'] += 1
        if session.get('status') not in {'failed', 'disconnected'}:
            bucket['active_session_count'] += 1
    records = [
        build_custom_runtime_service_record(
            service_id='terminal-service.default',
            service_type='terminal-service',
            instance_id=getattr(app.state, 'instance_id', 'unknown'),
            version=VERSION,
            status='healthy',
            subjects=[
                TERMINAL_SESSION_CREATE_SUBJECT,
                TERMINAL_SESSION_ATTACH_SUBJECT,
                TERMINAL_SESSION_CREATED_SUBJECT,
                TERMINAL_SESSION_ATTACHED_SUBJECT,
                TERMINAL_SESSION_DISCONNECTED_SUBJECT,
                TERMINAL_SESSION_FAILED_SUBJECT,
            ],
            capabilities={
                'terminal_service': True,
                'service_owner': 'terminal-service',
                'session_registry': True,
                'session_registry_entries': len(session_registry),
                'active_session_count': active_session_count,
                'lifecycle_state': lifecycle_state,
            },
            routing={
                'region': 'local',
                'workspace_scope': 'shared',
                'owner': 'terminal-service',
            },
        )
    ]

    cached_servers = {
        server.get('id'): server
        for server in getattr(app.state, 'TERMINAL_SERVERS', []) or []
    }
    for connection in getattr(app.state.config, 'TERMINAL_SERVER_CONNECTIONS', []) or []:
        server_id = connection.get('id') or connection.get('name') or 'unknown'
        server = cached_servers.get(server_id, {})
        specs = server.get('specs') or []
        session_counts = session_counts_by_server.get(
            server_id,
            {'session_registry_entries': 0, 'active_session_count': 0},
        )
        lifecycle_state = 'active' if session_counts['active_session_count'] > 0 else 'idle'
        records.append(
            build_custom_runtime_service_record(
                service_id=f'terminal.{server_id}',
                service_type='terminal',
                instance_id=getattr(app.state, 'instance_id', 'unknown'),
                version=VERSION,
                status='healthy' if connection.get('enabled', True) and connection.get('url') else 'degraded',
                subjects=[
                    'owui.cmd.terminal.session.create',
                    'owui.cmd.terminal.session.attach',
                ],
                capabilities={
                    'terminal': True,
                    'system_prompt': bool(server.get('system_prompt')),
                    'tool_count': len(specs),
                    'service_owner': 'terminal-service',
                    **session_counts,
                    'lifecycle_state': lifecycle_state,
                },
                routing={
                    'region': 'local',
                    'workspace_scope': 'shared',
                    'owner': 'terminal-service',
                },
            )
        )
    return records


def _build_internal_request(app) -> Request:
    return Request(
        {
            'type': 'http',
            'asgi.version': '3.0',
            'asgi.spec_version': '2.0',
            'method': 'GET',
            'path': '/internal',
            'query_string': b'',
            'headers': Headers({}).raw,
            'client': ('127.0.0.1', 12345),
            'server': ('127.0.0.1', 80),
            'scheme': 'http',
            'app': app,
        }
    )


async def request_terminal_lifecycle_control(
    app,
    *,
    server_id: str,
    action: str,
    session_id: str | None = None,
) -> dict | None:
    if not getattr(app.state.config, 'NATS_URL', ''):
        return None

    subject = TERMINAL_SESSION_CREATE_SUBJECT if action == 'create' else TERMINAL_SESSION_ATTACH_SUBJECT
    nc = await _connect_nats(
        getattr(app.state.config, 'NATS_URL', ''),
        instance_id=getattr(app.state, 'instance_id', None),
    )
    try:
        response = await nc.request(
            subject,
            json.dumps({'server_id': server_id, 'action': action, 'session_id': session_id}).encode('utf-8'),
            timeout=TERMINAL_CONTROL_REQUEST_TIMEOUT,
        )
        return json.loads(response.data.decode('utf-8'))
    except Exception:
        log.exception('Terminal lifecycle control request failed for %s (%s).', server_id, action)
        return None
    finally:
        await nc.drain()


async def _connect_nats(nats_url: str, *, instance_id: str | None = None):
    import nats

    servers = [server.strip() for server in nats_url.split(',') if server.strip()]
    return await nats.connect(
        servers=servers,
        name=f'{NATS_NAME}-terminal-service-{instance_id or "runtime"}',
        connect_timeout=NATS_CONNECT_TIMEOUT,
    )


def _error_response(*, detail: str, status_code: int = 502) -> dict:
    return {
        'status': 'error',
        'status_code': status_code,
        'detail': detail,
    }


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
