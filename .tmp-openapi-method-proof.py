from open_webui.main import app
schema = app.openapi()
checks = {
    '/api/v1/automations/list': 'get',
    '/api/v1/calendars/': 'get',
    '/api/v1/calendars/events': 'get',
    '/api/v1/notes/pinned': 'get',
    '/api/v1/chats/shared/{id}/access': 'get',
    '/api/v1/chats/{id}/read': 'post',
    '/api/tasks/chat/{chat_id}/stop': 'post',
}
for path, method in checks.items():
    print(path, method, method in schema.get('paths', {}).get(path, {}))
