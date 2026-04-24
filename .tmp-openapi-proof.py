from open_webui.main import app
schema = app.openapi()
for path in [
    '/api/v1/automations/list',
    '/api/v1/calendars/',
    '/api/v1/calendars/events',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
    '/api/tasks/chat/{chat_id:path}/stop',
    '/api/v1/chats/{id}/read',
]:
    print(path, path in schema.get('paths', {}))
