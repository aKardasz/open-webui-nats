from open_webui.main import app
paths = {
    '/api/tasks/chat/{chat_id:path}/stop',
    '/api/v1/chats/{id}/read',
    '/api/v1/chats/shared/{id}/access',
    '/api/v1/notes/pinned',
}
route_paths = {getattr(r, 'path', None) for r in app.routes}
for p in sorted(paths):
    print('route', p, p in route_paths)
