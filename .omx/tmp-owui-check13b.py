from collections import defaultdict
from open_webui.main import app
routes = defaultdict(set)
for r in app.routes:
    path = getattr(r, 'path', None)
    if path:
        for m in (getattr(r, 'methods', None) or []):
            routes[path].add(m)
for k in [
    '/api/v1/automations/list',
    '/api/v1/calendars/events',
    '/api/v1/notes/pinned',
    '/api/v1/chats/shared/{id}/access',
    '/api/v1/chats/{id}/read',
    '/api/tasks/chat/{chat_id:path}/stop',
]:
    print(k, sorted(routes.get(k, [])))
