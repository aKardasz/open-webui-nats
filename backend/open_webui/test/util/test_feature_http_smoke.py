from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.internal.db import Base, SessionLocal, engine
from open_webui.models.access_grants import AccessGrant
from open_webui.models.automations import Automation, AutomationRun
from open_webui.models.calendar import Calendar, CalendarEvent, CalendarEventAttendee
from open_webui.models.chats import Chat
from open_webui.models.notes import Note
from open_webui.models.users import Users, User
from open_webui.routers import automations as automations_router
from open_webui.routers import calendar as calendar_router
from open_webui.routers import chats as chats_router
from open_webui.routers import notes as notes_router
from open_webui.utils.auth import get_verified_user


def _permissions():
    return {
        'chat': {
            'share': True,
        },
        'features': {
            'automations': True,
            'calendar': True,
            'notes': True,
        }
    }


def _user():
    return SimpleNamespace(id='smoke-user', role='admin', timezone='UTC', permissions=_permissions())


def _build_app():
    app = FastAPI()
    app.state.config = SimpleNamespace(
        ENABLE_AUTOMATIONS=True,
        ENABLE_CALENDAR=True,
        ENABLE_NOTES=True,
        ENABLE_ADMIN_CHAT_ACCESS=True,
        USER_PERMISSIONS=_permissions(),
        AUTOMATION_MAX_COUNT='',
        AUTOMATION_MIN_INTERVAL='',
    )
    app.include_router(automations_router.router, prefix='/api/v1/automations')
    app.include_router(calendar_router.router, prefix='/api/v1/calendars')
    app.include_router(chats_router.router, prefix='/api/v1/chats')
    app.include_router(notes_router.router, prefix='/api/v1/notes')
    app.dependency_overrides[get_verified_user] = lambda: _user()
    return app


def _reset_tables():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        db.query(AutomationRun).delete()
        db.query(Automation).delete()
        db.query(CalendarEventAttendee).delete()
        db.query(CalendarEvent).delete()
        db.query(Calendar).delete()
        db.query(AccessGrant).delete()
        db.query(Note).delete()
        db.query(Chat).delete()
        db.query(User).filter(User.id == 'smoke-user').delete()
        db.commit()
        Users.insert_new_user(
            id='smoke-user',
            name='Smoke User',
            email='smoke@example.com',
            role='admin',
            db=db,
        )
    finally:
        db.close()


def test_automation_routes_http_smoke():
    _reset_tables()
    app = _build_app()
    client = TestClient(app)

    create = client.post(
        '/api/v1/automations/create',
        json={
            'name': 'Smoke automation',
            'data': {
                'prompt': 'hello',
                'model_id': 'model-1',
                'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1',
            },
        },
    )
    assert create.status_code == 200
    created = create.json()
    assert created['name'] == 'Smoke automation'

    listing = client.get('/api/v1/automations/list?page=1')
    assert listing.status_code == 200
    body = listing.json()
    assert body['total'] >= 1
    assert any(item['id'] == created['id'] for item in body['items'])

    run_response = client.post(f"/api/v1/automations/{created['id']}/run")
    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body['automation']['id'] == created['id']
    assert run_body['execution']['status'] == 'accepted'


def test_calendar_routes_http_smoke():
    _reset_tables()
    app = _build_app()
    client = TestClient(app)

    create_cal = client.post(
        '/api/v1/calendars/create',
        json={
            'name': 'Smoke calendar',
            'color': '#3b82f6',
        },
    )
    assert create_cal.status_code == 200
    calendar = create_cal.json()
    assert calendar['name'] == 'Smoke calendar'

    calendars = client.get('/api/v1/calendars/')
    assert calendars.status_code == 200
    calendar_items = calendars.json()
    assert any(item['id'] == calendar['id'] for item in calendar_items)

    create_event = client.post(
        '/api/v1/calendars/events/create',
        json={
            'calendar_id': calendar['id'],
            'title': 'Smoke event',
            'start_at': 1_800_000_000_000_000_000,
            'end_at': 1_800_000_003_600_000_000,
        },
    )
    assert create_event.status_code == 200
    event = create_event.json()
    assert event['title'] == 'Smoke event'

    fetched = client.get(f"/api/v1/calendars/events/{event['id']}")
    assert fetched.status_code == 200
    assert fetched.json()['id'] == event['id']


def test_note_pin_and_shared_chat_http_smoke():
    _reset_tables()
    app = _build_app()
    client = TestClient(app)

    note_create = client.post(
        '/api/v1/notes/create',
        json={
            'title': 'Smoke note',
            'data': {'content': {'md': 'hello'}},
            'meta': None,
            'access_grants': [],
        },
    )
    assert note_create.status_code == 200
    note = note_create.json()

    note_pin = client.post(f"/api/v1/notes/{note['id']}/pin")
    assert note_pin.status_code == 200
    assert note_pin.json()['is_pinned'] is True

    pinned = client.get('/api/v1/notes/pinned')
    assert pinned.status_code == 200
    assert any(item['id'] == note['id'] for item in pinned.json())

    chat_create = client.post(
        '/api/v1/chats/new',
        json={
            'chat': {
                'title': 'Smoke chat',
                'messages': [{'role': 'user', 'content': 'hi'}],
                'history': {'currentId': None, 'messages': {}},
            }
        },
    )
    assert chat_create.status_code == 200
    chat = chat_create.json()

    shared = client.post(f"/api/v1/chats/{chat['id']}/share")
    assert shared.status_code == 200
    shared_chat = shared.json()
    assert shared_chat['share_id']

    access_update = client.post(
        f"/api/v1/chats/shared/{chat['id']}/access/update",
        json={'access_grants': [{'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]},
    )
    assert access_update.status_code == 200

    access_list = client.get(f"/api/v1/chats/shared/{chat['id']}/access")
    assert access_list.status_code == 200
    assert any(item['principal_id'] == '*' for item in access_list.json())
