from open_webui.main import app
flag_auto = app.state.config.ENABLE_AUTOMATIONS
flag_cal = app.state.config.ENABLE_CALENDAR
if hasattr(flag_auto, 'value'):
    flag_auto = flag_auto.value
if hasattr(flag_cal, 'value'):
    flag_cal = flag_cal.value
print('app_state_ENABLE_AUTOMATIONS', flag_auto)
print('app_state_ENABLE_CALENDAR', flag_cal)
print('runtime_provider_count', len(getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])))
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
