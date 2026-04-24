from open_webui.main import app
paths = [
    '/api/v1/automations/list',
    '/api/v1/calendars/events',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
    '/api/v1/chats/{id}/read',
    '/api/tasks/chat/{chat_id:path}/stop',
]
route_paths = {getattr(r, 'path', None): sorted(getattr(r, 'methods', []) or []) for r in app.routes}
for p in paths:
    print(p, route_paths.get(p))
print('runtime_provider_count', len(getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])))
