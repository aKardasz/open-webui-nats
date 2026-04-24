from open_webui.main import app
schema = app.openapi()
for p in sorted(schema.get('paths', {})):
    if '/api/tasks/chat/' in p or '/api/v1/chats/' in p:
        print(p)
