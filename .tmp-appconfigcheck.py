from open_webui.main import app
flag_auto = app.state.config.ENABLE_AUTOMATIONS
flag_cal = app.state.config.ENABLE_CALENDAR
if hasattr(flag_auto, 'value'):
    flag_auto = flag_auto.value
if hasattr(flag_cal, 'value'):
    flag_cal = flag_cal.value
print('app_state_ENABLE_AUTOMATIONS', flag_auto)
print('app_state_ENABLE_CALENDAR', flag_cal)
providers = getattr(app.state, 'RUNTIME_SERVICE_RECORD_PROVIDERS', [])
print('runtime_provider_count', len(providers))
print('provider_names', [getattr(p, '__name__', type(p).__name__) for p in providers])
