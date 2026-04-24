from open_webui.main import app
schema = app.openapi()
checks = [
    '/api/v1/automations/list',
    '/api/v1/calendars/events',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
    '/api/v1/chats/{id}/read',
    '/api/tasks/chat/{chat_id}/stop',
]
for path in checks:
    print(path, path in schema.get('paths', {}))
