from open_webui import config as cfg
print('cfg_env_value_automations', getattr(cfg.ENABLE_AUTOMATIONS, 'env_value', None))
print('cfg_env_value_calendar', getattr(cfg.ENABLE_CALENDAR, 'env_value', None))
print('cfg_value_automations', getattr(cfg.ENABLE_AUTOMATIONS, 'value', None))
print('cfg_value_calendar', getattr(cfg.ENABLE_CALENDAR, 'value', None))
