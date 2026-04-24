from open_webui.main import app
for r in app.routes:
    if getattr(r, 'path', None) == '/api/tasks/chat/{chat_id:path}/stop':
        print('path', r.path)
        print('methods', sorted(getattr(r, 'methods', []) or []))
        print('include_in_schema', getattr(r, 'include_in_schema', None))
        break
else:
    print('not_found')
