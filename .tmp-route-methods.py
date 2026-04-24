from open_webui.main import app
interesting = {
    '/api/v1/automations/list',
    '/api/v1/calendars/',
    '/api/v1/calendars/events',
    '/api/tasks/chat/{chat_id:path}/stop',
    '/api/v1/chats/{id}/read',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
}
for route in app.routes:
    path = getattr(route, 'path', None)
    if path in interesting:
        print(path, sorted(getattr(route, 'methods', []) or []), getattr(route, 'include_in_schema', None))
