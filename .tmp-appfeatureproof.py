from open_webui.main import app
paths = {
    '/api/v1/automations/list',
    '/api/v1/calendars/',
    '/api/v1/calendars/events',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
}
route_paths = {getattr(r, 'path', None) for r in app.routes}
flag_auto = app.state.config.ENABLE_AUTOMATIONS
flag_cal = app.state.config.ENABLE_CALENDAR
if hasattr(flag_auto, 'value'):
    flag_auto = flag_auto.value
if hasattr(flag_cal, 'value'):
    flag_cal = flag_cal.value
print('app_state_ENABLE_AUTOMATIONS', flag_auto)
print('app_state_ENABLE_CALENDAR', flag_cal)
print('runtime_provider_count', len(getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])))
for p in sorted(paths):
    print('route', p, p in route_paths)
