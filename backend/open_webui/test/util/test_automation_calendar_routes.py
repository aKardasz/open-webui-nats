from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from open_webui.models.automations import AutomationForm, AutomationModel, AutomationData
from open_webui.models.calendar import CalendarEventForm, CalendarEventModel, CalendarForm, CalendarModel
from open_webui.routers import automations as automations_router
from open_webui.routers import chats as chats_router
from open_webui.routers import calendar as calendar_router


def _request(*, enable_automations=True, enable_calendar=True, user_permissions=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    ENABLE_AUTOMATIONS=enable_automations,
                    ENABLE_CALENDAR=enable_calendar,
                    USER_PERMISSIONS=user_permissions or {},
                    AUTOMATION_MAX_COUNT='',
                    AUTOMATION_MIN_INTERVAL='',
                )
            )
        )
    )


def _user(role='user'):
    return SimpleNamespace(id='user-1', role=role, timezone='UTC')


@pytest.mark.asyncio
async def test_create_new_automation_returns_enriched_response():
    request = _request()
    user = _user()
    db = object()
    form = AutomationForm(
        name='Daily summary',
        data=AutomationData(prompt='hello', model_id='model-1', rrule='RRULE:FREQ=DAILY;INTERVAL=1'),
    )
    created = AutomationModel(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'prompt': 'hello', 'model_id': 'model-1', 'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1'},
        meta=None,
        is_active=True,
        last_run_at=None,
        next_run_at=123,
        created_at=1,
        updated_at=1,
    )

    with (
        patch.object(automations_router, 'has_permission', return_value=True),
        patch.object(automations_router, 'validate_rrule', return_value=True),
        patch.object(automations_router, 'next_run_ns', return_value=123),
        patch.object(automations_router, 'next_n_runs_ns', return_value=[123, 456]),
        patch.object(automations_router.Automations, 'insert', return_value=created),
        patch.object(automations_router.AutomationRuns, 'get_latest', return_value=None),
    ):
        response = await automations_router.create_new_automation(request, form, user=user, db=db)

    assert response.id == 'auto-1'
    assert response.next_runs == [123, 456]


@pytest.mark.asyncio
async def test_run_automation_by_id_schedules_background_task():
    request = _request()
    user = _user()
    db = object()
    background_tasks = BackgroundTasks()
    automation = AutomationModel(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'prompt': 'hello', 'model_id': 'model-1', 'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1'},
        meta=None,
        is_active=True,
        last_run_at=None,
        next_run_at=123,
        created_at=1,
        updated_at=1,
    )

    with (
        patch.object(automations_router, 'has_permission', return_value=True),
        patch.object(automations_router.Automations, 'get_by_id', return_value=automation),
        patch.object(automations_router.AutomationRuns, 'get_latest', return_value=None),
        patch.object(automations_router, 'next_n_runs_ns', return_value=[123]),
    ):
        response = await automations_router.run_automation_by_id(
            request, 'auto-1', background_tasks, user=user, db=db
        )

    assert response.id == 'auto-1'
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_check_automations_permission_rejects_when_disabled():
    request = _request(enable_automations=False)
    user = _user()

    with pytest.raises(HTTPException) as exc:
        automations_router.check_automations_permission(request, user)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_get_calendars_appends_scheduled_tasks_calendar_when_automations_enabled():
    request = _request(enable_calendar=True, enable_automations=True)
    user = _user()
    db = object()
    calendars = [
        CalendarModel(
            id='cal-1',
            user_id='user-1',
            name='Personal',
            color='#3b82f6',
            is_default=True,
            is_system=False,
            data=None,
            meta=None,
            access_grants=[],
            created_at=1,
            updated_at=1,
        )
    ]

    with (
        patch.object(calendar_router, 'has_permission', return_value=True),
        patch.object(calendar_router.Calendars, 'get_calendars_by_user', return_value=calendars),
    ):
        result = await calendar_router.get_calendars(request, user=user, db=db)

    assert len(result) == 2
    assert any(cal.id == calendar_router.SCHEDULED_TASKS_CALENDAR_ID for cal in result)


@pytest.mark.asyncio
async def test_create_calendar_event_uses_calendar_event_table():
    request = _request(enable_calendar=True)
    user = _user()
    db = object()
    form = CalendarEventForm(
        calendar_id='cal-1',
        title='Meeting',
        start_at=100,
        end_at=200,
    )
    event = CalendarEventModel(
        id='evt-1',
        calendar_id='cal-1',
        user_id='user-1',
        title='Meeting',
        description=None,
        start_at=100,
        end_at=200,
        all_day=False,
        rrule=None,
        color=None,
        location=None,
        data=None,
        meta=None,
        is_cancelled=False,
        attendees=[],
        created_at=1,
        updated_at=1,
    )

    with (
        patch.object(calendar_router, 'has_permission', return_value=True),
        patch.object(
            calendar_router,
            '_check_calendar_access',
            return_value=CalendarModel(
                id='cal-1',
                user_id='user-1',
                name='Personal',
                color='#3b82f6',
                is_default=True,
                is_system=False,
                data=None,
                meta=None,
                access_grants=[],
                created_at=1,
                updated_at=1,
            ),
        ),
        patch.object(calendar_router.CalendarEvents, 'insert_new_event', return_value=event) as insert_event,
    ):
        response = await calendar_router.create_event(request, form, user=user, db=db)

    assert response.id == 'evt-1'
    insert_event.assert_called_once()


@pytest.mark.asyncio
async def test_set_default_calendar_returns_calendar():
    request = _request(enable_calendar=True)
    user = _user()
    db = object()
    calendar = CalendarModel(
        id='cal-1',
        user_id='user-1',
        name='Personal',
        color='#3b82f6',
        is_default=True,
        is_system=False,
        data=None,
        meta=None,
        access_grants=[],
        created_at=1,
        updated_at=1,
    )

    with (
        patch.object(calendar_router, 'has_permission', return_value=True),
        patch.object(calendar_router.Calendars, 'set_default_calendar', return_value=calendar),
    ):
        response = await calendar_router.set_default_calendar(request, 'cal-1', user=user, db=db)

    assert response.id == 'cal-1'
    assert response.is_default is True


@pytest.mark.asyncio
async def test_get_events_includes_virtual_automation_and_run_entries():
    request = _request(enable_calendar=True, enable_automations=True)
    user = _user()
    db = object()
    start = '2026-04-21T00:00:00'
    end = '2026-04-22T00:00:00'
    start_ns = int(__import__('datetime').datetime.fromisoformat(start).timestamp() * 1000) * 1_000_000
    automation = AutomationModel(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'prompt': 'hello', 'model_id': 'model-1', 'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1'},
        meta=None,
        is_active=True,
        last_run_at=None,
        next_run_at=start_ns,
        created_at=1,
        updated_at=1,
    )
    run = SimpleNamespace(id='run-1', created_at=start_ns + 500, status='success', error=None, chat_id='chat-1')

    with (
        patch.object(calendar_router, 'has_permission', return_value=True),
        patch.object(calendar_router.CalendarEvents, 'get_events_by_range', return_value=[]),
        patch.object(
            calendar_router.Automations,
            'search_automations',
            return_value=SimpleNamespace(items=[automation]),
        ),
        patch.object(calendar_router.AutomationRuns, 'get_by_automation', return_value=[run]),
        patch.object(
            calendar_router,
            'expand_recurring_event',
            return_value=[
                {
                    'id': 'auto_auto-1',
                    'calendar_id': calendar_router.SCHEDULED_TASKS_CALENDAR_ID,
                    'user_id': 'user-1',
                    'title': 'Daily summary',
                    'description': 'hello',
                    'start_at': 1_000_000_000,
                    'end_at': None,
                    'all_day': False,
                    'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1',
                    'color': None,
                    'location': None,
                    'data': None,
                    'meta': {'automation_id': 'auto-1'},
                    'is_cancelled': False,
                    'attendees': [],
                    'created_at': 1,
                    'updated_at': 1,
                    'instance_id': 'auto_auto-1_1000000000',
                }
            ],
        ),
        patch('open_webui.routers.calendar.time.time_ns', return_value=start_ns),
    ):
        result = await calendar_router.get_events(request, start, end, None, user=user, db=db)

    assert any(item['meta'].get('automation_id') == 'auto-1' for item in result)
    assert any(item['meta'].get('run_id') == 'run-1' for item in result)


@pytest.mark.asyncio
async def test_mark_chat_read_by_id_updates_persisted_chat():
    user = _user()
    db = object()
    chat = SimpleNamespace(id='chat-1', user_id='user-1')

    with (
        patch.object(chats_router.Chats, 'get_chat_by_id', return_value=chat),
        patch.object(chats_router.Chats, 'update_chat_last_read_at_by_id', return_value=True) as update_read,
    ):
        result = await chats_router.mark_chat_read_by_id('chat-1', user=user, db=db)

    assert result is True
    update_read.assert_called_once_with('chat-1', 'user-1', db=db)


@pytest.mark.asyncio
async def test_mark_chat_read_by_id_allows_local_chat_ids():
    result = await chats_router.mark_chat_read_by_id('local:socket-1', user=_user(), db=object())
    assert result is True
