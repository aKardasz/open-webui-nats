"""Reverse proxy for admin-configured terminal servers.

Routes:
  GET  /                         — list terminals the user has access to
  *    /{server_id}/{path:path}  — proxy request to terminal server
"""

import asyncio
import json
import logging
import posixpath
from types import SimpleNamespace
from urllib.parse import unquote

import aiohttp
from fastapi import APIRouter, Depends, Request, Response, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from open_webui.models.groups import Groups
from open_webui.models.users import Users
from open_webui.utils.access_control import has_connection_access
from open_webui.utils.auth import decode_token, get_verified_user, is_valid_token
from open_webui.utils.task_messaging import (
    TERMINAL_SESSION_ATTACHED_SUBJECT,
    TERMINAL_SESSION_CREATED_SUBJECT,
    TERMINAL_SESSION_DISCONNECTED_SUBJECT,
    TERMINAL_SESSION_FAILED_SUBJECT,
    build_domain_event,
    publish_app_event,
)
from open_webui.utils.terminal_service import request_terminal_lifecycle_control
from open_webui.utils.tools import get_terminal_servers as get_cached_terminal_servers
from starlette.background import BackgroundTask

log = logging.getLogger(__name__)

router = APIRouter()

STREAMING_CONTENT_TYPES = ('application/octet-stream', 'image/', 'application/pdf')
STRIPPED_RESPONSE_HEADERS = frozenset(('transfer-encoding', 'connection', 'content-encoding', 'content-length'))


def _sanitize_proxy_path(path: str) -> str | None:
    """Sanitize a proxy path to prevent directory traversal / SSRF.

    Returns the cleaned path, or None if the path is invalid.
    Trailing slashes are preserved — many upstream frameworks treat
    ``/path`` and ``/path/`` differently.
    """
    decoded = unquote(path)
    had_trailing_slash = decoded.endswith('/')
    normalized = posixpath.normpath(decoded)
    # Remove any leading slashes that would reset the base
    cleaned = normalized.lstrip('/')
    # Reject if normpath resolved to parent traversal or current-dir only
    if cleaned.startswith('..') or cleaned == '.':
        return None
    # Restore trailing slash if the original path had one
    if had_trailing_slash and cleaned and not cleaned.endswith('/'):
        cleaned += '/'
    return cleaned


def _extract_terminal_session_id_from_path(path: str) -> str | None:
    cleaned = _sanitize_proxy_path(path)
    if not cleaned:
        return None

    parts = cleaned.rstrip('/').split('/')
    if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'terminals':
        session_id = parts[2]
        return session_id or None
    return None


async def _resolve_terminal_connection(request: Request, user, server_id: str):
    """Resolve the configured connection plus any registry-aware runtime route hint."""
    connections = request.app.state.config.TERMINAL_SERVER_CONNECTIONS or []
    connection = next((c for c in connections if c.get('id') == server_id), None)

    if connection is None:
        return None

    user_group_ids = {group.id for group in Groups.get_groups_by_member_id(user.id)}
    has_access = has_connection_access(user, connection, user_group_ids)

    terminal_servers = {
        server.get('id'): server
        for server in await get_cached_terminal_servers(request)
    }
    runtime_server = terminal_servers.get(server_id)
    runtime = runtime_server.get('runtime') if runtime_server else None
    route_source = 'runtime' if runtime and runtime.get('route_eligible') else 'config_fallback'
    resolved_url = (
        runtime_server.get('url')
        if route_source == 'runtime' and runtime_server and runtime_server.get('url')
        else connection.get('url')
    )

    return {
        'connection': connection,
        'has_access': has_access,
        'runtime': runtime,
        'route_source': route_source,
        'resolved_url': (resolved_url or '').rstrip('/'),
    }


async def _resolve_terminal_lifecycle_connection(
    request: Request,
    user,
    server_id: str,
    *,
    action: str,
    session_id: str | None = None,
):
    resolved = await _resolve_terminal_connection(request, user, server_id)
    if resolved is None or not resolved['has_access']:
        return resolved

    lifecycle = await request_terminal_lifecycle_control(
        request.app,
        server_id=server_id,
        action=action,
        session_id=session_id,
    )
    if lifecycle is not None:
        if lifecycle.get('status') == 'error':
            resolved['error_status'] = lifecycle.get('status_code', 502)
            resolved['error_detail'] = lifecycle.get('detail') or 'Terminal lifecycle control request failed'
            return resolved

        lifecycle_data = lifecycle.get('data') or {}
        if lifecycle_data.get('resolved_url'):
            resolved['route_source'] = lifecycle_data.get('route_source', resolved['route_source'])
            resolved['resolved_url'] = lifecycle_data['resolved_url'].rstrip('/')
            resolved['session_status'] = lifecycle_data.get('session_status')
            resolved['lifecycle_source'] = lifecycle_data.get('lifecycle_source', 'service_control')

    return resolved


@router.get('/')
async def list_terminal_servers(request: Request, user=Depends(get_verified_user)):
    """Return terminal servers the authenticated user has access to."""
    connections = request.app.state.config.TERMINAL_SERVER_CONNECTIONS or []
    user_group_ids = {group.id for group in Groups.get_groups_by_member_id(user.id)}
    terminal_servers = {
        server.get('id'): server
        for server in await get_cached_terminal_servers(request)
    }

    return [
        {
            'id': connection.get('id', ''),
            'url': connection.get('url', ''),
            'name': connection.get('name', ''),
            **(
                {'runtime': terminal_servers[connection.get('id')].get('runtime')}
                if connection.get('id') in terminal_servers and terminal_servers[connection.get('id')].get('runtime')
                else {}
            ),
            **(
                {'session_registry_entries': session_registry_entries}
                if session_registry_entries is not None
                else {}
            ),
            **(
                {'active_session_count': active_session_count}
                if active_session_count is not None
                else {}
            ),
            **(
                {'lifecycle_state': lifecycle_state}
                if lifecycle_state is not None
                else {}
            ),
            'route_source': (
                'runtime'
                if terminal_servers.get(connection.get('id'), {}).get('runtime', {}).get('route_eligible')
                else 'config_fallback'
            ),
        }
        for connection in connections
        if connection.get('enabled', True)
        and has_connection_access(user, connection, user_group_ids)
        for runtime in [terminal_servers.get(connection.get('id'), {}).get('runtime', {})]
        for capabilities in [runtime.get('capabilities', {})]
        for session_registry_entries in [capabilities.get('session_registry_entries')]
        for active_session_count in [capabilities.get('active_session_count')]
        for lifecycle_state in [capabilities.get('lifecycle_state')]
    ]


PROXY_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']


@router.api_route('/{server_id}/{path:path}', methods=PROXY_METHODS)
async def proxy_terminal(  # noqa: C901
    server_id: str,
    path: str,
    request: Request,
    user=Depends(get_verified_user),
):
    """Proxy a request to the admin terminal server identified by *server_id*."""
    lifecycle_action = 'create' if request.method == 'POST' and path == 'api/terminals' else 'attach'
    lifecycle_session_id = None if lifecycle_action == 'create' else _extract_terminal_session_id_from_path(path)
    resolved = await _resolve_terminal_lifecycle_connection(
        request,
        user,
        server_id,
        action=lifecycle_action,
        session_id=lifecycle_session_id,
    )
    if resolved is None:
        return JSONResponse({'error': f"Terminal server '{server_id}' not found"}, status_code=404)
    if not resolved['has_access']:
        return JSONResponse({'error': 'Access denied'}, status_code=403)
    if resolved.get('error_detail'):
        return JSONResponse({'error': resolved['error_detail']}, status_code=resolved.get('error_status', 502))

    connection = resolved['connection']
    route_source = resolved['route_source']
    base_url = resolved['resolved_url']
    lifecycle_source = resolved.get('lifecycle_source')
    session_status = resolved.get('session_status')
    if not base_url:
        return JSONResponse({'error': 'Terminal server URL not configured'}, status_code=503)

    safe_path = _sanitize_proxy_path(path)
    if safe_path is None:
        return JSONResponse({'error': 'Invalid path'}, status_code=400)

    target_url = f'{base_url}/{safe_path}'

    # Route through orchestrator policy endpoint if policy_id is set
    policy_id = connection.get('policy_id')
    if policy_id:
        target_url = f'{base_url}/p/{policy_id}/{safe_path}'

    if request.query_params:
        target_url += f'?{request.query_params}'

    headers = {'X-User-Id': user.id}
    cookies = {}
    auth_type = connection.get('auth_type', 'bearer')

    if auth_type == 'bearer':
        headers['Authorization'] = f'Bearer {connection.get("key", "")}'
    elif auth_type == 'session':
        cookies = request.cookies
        headers['Authorization'] = f'Bearer {request.state.token.credentials}'
    elif auth_type == 'system_oauth':
        cookies = request.cookies
        oauth_token = request.headers.get('x-oauth-access-token', '')
        if oauth_token:
            headers['Authorization'] = f'Bearer {oauth_token}'
    # auth_type == "none": no Authorization header

    content_type = request.headers.get('content-type')
    if content_type:
        headers['Content-Type'] = content_type

    body = await request.body()
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=300, connect=10),
        trust_env=True,
    )

    try:
        upstream_response = await session.request(
            method=request.method,
            url=target_url,
            headers=headers,
            cookies=cookies,
            data=body or None,
        )

        upstream_content_type = upstream_response.headers.get('content-type', '')
        filtered_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() not in STRIPPED_RESPONSE_HEADERS
        }
        filtered_headers['X-OWUI-Terminal-Route'] = route_source
        if resolved.get('lifecycle_source'):
            filtered_headers['X-OWUI-Terminal-Lifecycle'] = resolved['lifecycle_source']
        if resolved.get('session_status'):
            filtered_headers['X-OWUI-Terminal-Session-Status'] = str(resolved['session_status'])

        # Stream binary responses directly
        if any(t in upstream_content_type for t in STREAMING_CONTENT_TYPES):

            async def cleanup():
                await upstream_response.release()
                await session.close()

            return StreamingResponse(
                content=upstream_response.content.iter_any(),
                status_code=upstream_response.status,
                headers=filtered_headers,
                background=BackgroundTask(cleanup),
            )

        # Buffer text/JSON responses
        response_body = await upstream_response.read()
        status_code = upstream_response.status
        await upstream_response.release()
        await session.close()

        if status_code < 400:
            if request.method == 'POST' and safe_path == 'api/terminals':
                session_payload = {}
                if 'application/json' in upstream_content_type:
                    try:
                        session_payload = json.loads(response_body.decode('utf-8'))
                    except Exception:
                        session_payload = {}

                session_id = str(session_payload.get('name') or session_payload.get('id') or '')
                if session_id:
                    await publish_app_event(
                        TERMINAL_SESSION_CREATED_SUBJECT,
                        build_domain_event(
                            event_type='terminal.session.created',
                            resource_type='terminal_session',
                            resource_id=session_id,
                            data={
                                'session_id': session_id,
                                'server_id': server_id,
                                'status': 'created',
                                'route_source': route_source,
                                'resolved_url': base_url,
                                'lifecycle_source': lifecycle_source,
                                'session_status': session_status,
                            },
                        ),
                    )

        return Response(content=response_body, status_code=status_code, headers=filtered_headers)

    except Exception as error:
        await session.close()
        log.exception('Terminal proxy error: %s', error)
        return JSONResponse({'error': f'Terminal proxy error: {error}'}, status_code=502)


# ---------------------------------------------------------------------------
# WebSocket proxy for interactive terminal sessions
# ---------------------------------------------------------------------------


async def _resolve_authenticated_connection(ws: WebSocket, server_id: str, session_id: str):
    """Authenticate a WebSocket via first-message auth and resolve the terminal server.

    The client must send ``{"type": "auth", "token": "<jwt>"}`` as its first
    message after connecting.

    Returns ``(user, connection)`` on success, or ``None`` after closing *ws*
    with an appropriate error code.
    """
    # First-message authentication
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10.0)
        payload = json.loads(raw)
        if payload.get('type') != 'auth':
            await ws.close(code=4001, reason='Expected auth message')
            return None
        token = payload.get('token', '')
        data = decode_token(token)
        if data is None or 'id' not in data:
            await ws.close(code=4001, reason='Invalid token')
            return None
        if data.get('jti') and not await is_valid_token(ws, data):
            await ws.close(code=4001, reason='Invalid token')
            return None
        user = Users.get_user_by_id(data['id'])
        if user is None:
            await ws.close(code=4001, reason='User not found')
            return None
    except (TimeoutError, json.JSONDecodeError):
        await ws.close(code=4001, reason='Auth timeout or invalid payload')
        return None
    except Exception:
        await ws.close(code=4001, reason='Invalid token')
        return None

    # Resolve terminal server
    resolved = await _resolve_terminal_lifecycle_connection(
        SimpleNamespace(app=ws.app),
        user,
        server_id,
        action='attach',
        session_id=session_id,
    )
    if resolved is None:
        await ws.close(code=4004, reason='Terminal server not found')
        return None
    if not resolved['has_access']:
        await ws.close(code=4003, reason='Access denied')
        return None
    if resolved.get('error_detail'):
        await ws.close(code=4008, reason=resolved['error_detail'])
        return None

    return (
        user,
        resolved['connection'],
        resolved['route_source'],
        resolved['resolved_url'],
        resolved.get('lifecycle_source'),
        resolved.get('session_status'),
    )


@router.websocket('/{server_id}/api/terminals/{session_id}')
async def ws_terminal(  # noqa: C901
    ws: WebSocket,
    server_id: str,
    session_id: str,
):
    """Proxy an interactive WebSocket terminal session to a terminal server.

    Uses first-message auth: the client sends ``{"type": "auth", "token": "<jwt>"}``
    as its first message. The proxy validates the JWT, then connects to the
    upstream terminal server and authenticates with the server's API key.
    """
    await ws.accept()

    result = await _resolve_authenticated_connection(ws, server_id, session_id)
    if result is None:
        return
    user, connection, route_source, base_url, lifecycle_source, session_status = result

    if not base_url:
        await ws.close(code=4003, reason='Terminal server URL not configured')
        return

    # Build upstream WebSocket URL (no token in URL)
    ws_base = base_url.replace('https://', 'wss://').replace('http://', 'ws://')

    # Route through orchestrator policy endpoint if policy_id is set
    policy_id = connection.get('policy_id')
    upstream_params = {}
    # For orchestrator-backed servers, pass user_id
    upstream_params['user_id'] = user.id

    import urllib.parse

    if policy_id:
        upstream_url = f'{ws_base}/p/{policy_id}/api/terminals/{session_id}'
    else:
        upstream_url = f'{ws_base}/api/terminals/{session_id}'
    if upstream_params:
        upstream_url += f'?{urllib.parse.urlencode(upstream_params)}'

    session = aiohttp.ClientSession()
    attached = False
    try:
        async with session.ws_connect(upstream_url) as upstream:
            import asyncio
            import json as _json

            # First-message auth to upstream terminal server
            auth_type = connection.get('auth_type', 'bearer')
            if auth_type == 'bearer':
                key = connection.get('key', '')
                await upstream.send_str(_json.dumps({'type': 'auth', 'token': key}))

            async def _client_to_upstream():
                """Forward client → upstream."""
                try:
                    while True:
                        msg = await ws.receive()
                        if msg['type'] == 'websocket.disconnect':
                            break
                        elif 'bytes' in msg and msg['bytes']:
                            await upstream.send_bytes(msg['bytes'])
                        elif 'text' in msg and msg['text']:
                            await upstream.send_str(msg['text'])
                except Exception:
                    pass

            async def _upstream_to_client():
                """Forward upstream → client."""
                nonlocal attached
                try:
                    async for msg in upstream:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            if not attached:
                                await publish_app_event(
                                    TERMINAL_SESSION_ATTACHED_SUBJECT,
                                    build_domain_event(
                                        event_type='terminal.session.attached',
                                        resource_type='terminal_session',
                                        resource_id=session_id,
                                        data={
                                            'session_id': session_id,
                                            'server_id': server_id,
                                            'status': 'attached',
                                            'route_source': route_source,
                                            'resolved_url': base_url,
                                            'lifecycle_source': lifecycle_source,
                                            'session_status': session_status,
                                        },
                                    ),
                                )
                                attached = True
                            await ws.send_bytes(msg.data)
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            if not attached:
                                await publish_app_event(
                                    TERMINAL_SESSION_ATTACHED_SUBJECT,
                                    build_domain_event(
                                        event_type='terminal.session.attached',
                                        resource_type='terminal_session',
                                        resource_id=session_id,
                                        data={
                                            'session_id': session_id,
                                            'server_id': server_id,
                                            'status': 'attached',
                                            'route_source': route_source,
                                            'resolved_url': base_url,
                                            'lifecycle_source': lifecycle_source,
                                            'session_status': session_status,
                                        },
                                    ),
                                )
                                attached = True
                            await ws.send_text(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSE,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                except Exception:
                    pass

            await asyncio.gather(
                _client_to_upstream(),
                _upstream_to_client(),
                return_exceptions=True,
            )
    except Exception as e:
        await publish_app_event(
            TERMINAL_SESSION_FAILED_SUBJECT,
            build_domain_event(
                event_type='terminal.session.failed',
                resource_type='terminal_session',
                resource_id=session_id,
                data={
                    'session_id': session_id,
                    'server_id': server_id,
                    'status': 'failed',
                    'error_code': 'terminal_proxy_failed',
                    'route_source': route_source,
                    'resolved_url': base_url,
                    'lifecycle_source': lifecycle_source,
                    'session_status': session_status,
                },
            ),
        )
        log.exception('Terminal WebSocket proxy error: %s', e)
    finally:
        await session.close()
        if attached:
            await publish_app_event(
                TERMINAL_SESSION_DISCONNECTED_SUBJECT,
                build_domain_event(
                    event_type='terminal.session.disconnected',
                    resource_type='terminal_session',
                    resource_id=session_id,
                    data={
                        'session_id': session_id,
                        'server_id': server_id,
                        'status': 'disconnected',
                        'route_source': route_source,
                        'resolved_url': base_url,
                        'lifecycle_source': lifecycle_source,
                        'session_status': session_status,
                    },
                ),
            )
        try:
            await ws.close()
        except Exception:
            pass
