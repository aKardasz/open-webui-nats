from open_webui.main import app
schema = app.openapi()
checks = {
    '/api/v1/automations/list': 'get',
    '/api/v1/calendars/events': 'get',
    '/api/v1/notes/pinned': 'get',
    '/api/v1/chats/shared/{id}/access': 'get',
    '/api/v1/chats/{id}/read': 'post',
    '/api/tasks/chat/{chat_id}/stop': 'post',
}
print('runtime_provider_count', len(getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])))
for path, method in checks.items():
    print(path, method, method in schema.get('paths', {}).get(path, {}))
