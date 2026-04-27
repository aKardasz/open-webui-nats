import asyncio
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from open_webui.models.automations import Automations
from open_webui.utils.automations import (
    AUTOMATION_RUN_FAILED_SUBJECT,
    AUTOMATION_RUN_COMPLETED_SUBJECT,
    AUTOMATION_RUN_STARTED_SUBJECT,
    build_automation_runner_service_record,
    execute_automation,
    next_n_runs_ns,
    register_automation_runtime_provider,
    rrule_interval_seconds,
    scheduler_worker_loop,
    should_start_local_automation_scheduler,
    validate_rrule,
)


def _app():
    return SimpleNamespace(
        state=SimpleNamespace(
            instance_id='instance-1',
            RUNTIME_SERVICE_RECORD_PROVIDERS=[],
            config=SimpleNamespace(
                ENABLE_AUTOMATIONS=True,
                ENABLE_CALENDAR=True,
                AUTOMATION_NATS_SUBJECT='owui.cmd.automation.run',
            ),
        )
    )


def test_validate_rrule_accepts_valid_daily_schedule():
    assert validate_rrule('RRULE:FREQ=DAILY;INTERVAL=1') is True


def test_validate_rrule_rejects_invalid_schedule():
    with pytest.raises(ValueError):
        validate_rrule('RRULE:NOT_A_REAL_RULE')


def test_next_runs_and_interval_are_derived_from_rrule():
    runs = next_n_runs_ns('RRULE:FREQ=HOURLY;INTERVAL=2', count=2)
    assert len(runs) == 2
    assert runs[1] > runs[0]
    assert rrule_interval_seconds('RRULE:FREQ=HOURLY;INTERVAL=2') == 7200


def test_register_automation_runtime_provider_adds_single_provider():
    app = _app()

    register_automation_runtime_provider(app)
    register_automation_runtime_provider(app)

    assert len(app.state.RUNTIME_SERVICE_RECORD_PROVIDERS) == 1
    record = app.state.RUNTIME_SERVICE_RECORD_PROVIDERS[0]()
    assert record[0]['service_id'] == 'automation-runner.default'
    assert record[0]['service_type'] == 'automation-runner'


def test_build_automation_runner_service_record_reports_service_owner_metadata():
    record = build_automation_runner_service_record(_app())
    assert record['service_id'] == 'automation-runner.default'
    assert record['capabilities']['execution_mode'] == 'transitional-local'
    assert record['capabilities']['service_owner'] == 'automation-runner'
    assert record['routing']['owner'] == 'automation-runner'
    assert 'owui.cmd.automation.run' in record['subjects']


def test_should_start_local_automation_scheduler_only_in_local_or_embedded_modes():
    assert should_start_local_automation_scheduler(
        enable_automations=True,
        nats_url='',
        enable_embedded_runner=False,
        automation_runner_present=False,
        worker_only_mode=False,
    )
    assert should_start_local_automation_scheduler(
        enable_automations=True,
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        automation_runner_present=False,
        worker_only_mode=False,
    )
    assert not should_start_local_automation_scheduler(
        enable_automations=True,
        nats_url='nats://nats:4222',
        enable_embedded_runner=False,
        automation_runner_present=False,
        worker_only_mode=False,
    )
    assert not should_start_local_automation_scheduler(
        enable_automations=True,
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        automation_runner_present=True,
        worker_only_mode=False,
    )


def test_claim_due_only_returns_rows_that_win_compare_and_swap_update():
    row = SimpleNamespace(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1'},
        meta=None,
        is_active=True,
        last_run_at=None,
        next_run_at=10,
        created_at=1,
        updated_at=1,
    )
    query = SimpleNamespace(
        filter=lambda *args, **kwargs: query,
        order_by=lambda *args, **kwargs: query,
        limit=lambda *args, **kwargs: query,
        all=lambda: [row],
    )
    db = SimpleNamespace(
        query=lambda *args, **kwargs: query,
        execute=lambda *args, **kwargs: SimpleNamespace(rowcount=1),
        commit=lambda: None,
    )

    @contextmanager
    def fake_db_context(_db):
        yield db

    with (
        patch('open_webui.models.automations.get_db_context', fake_db_context),
        patch('open_webui.utils.automations.next_run_ns', return_value=20),
    ):
        claimed = Automations.claim_due(10, db=db)

    assert len(claimed) == 1
    assert claimed[0].last_run_at == 10
    assert claimed[0].next_run_at == 20


def test_claim_due_skips_rows_that_lose_compare_and_swap_update():
    row = SimpleNamespace(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'rrule': 'RRULE:FREQ=DAILY;INTERVAL=1'},
        meta=None,
        is_active=True,
        last_run_at=None,
        next_run_at=10,
        created_at=1,
        updated_at=1,
    )
    query = SimpleNamespace(
        filter=lambda *args, **kwargs: query,
        order_by=lambda *args, **kwargs: query,
        limit=lambda *args, **kwargs: query,
        all=lambda: [row],
    )
    db = SimpleNamespace(
        query=lambda *args, **kwargs: query,
        execute=lambda *args, **kwargs: SimpleNamespace(rowcount=0),
        commit=lambda: None,
    )

    @contextmanager
    def fake_db_context(_db):
        yield db

    with (
        patch('open_webui.models.automations.get_db_context', fake_db_context),
        patch('open_webui.utils.automations.next_run_ns', return_value=20),
    ):
        claimed = Automations.claim_due(10, db=db)

    assert claimed == []


def test_execute_automation_records_failed_run_and_emits_events():
    app = _app()
    automation = SimpleNamespace(id='auto-1')

    with patch('open_webui.models.automations.AutomationRuns.insert') as insert_run, patch(
        'open_webui.utils.automations.publish_app_event_sync'
    ) as publish_event:
        execute_automation(app, automation)

    insert_run.assert_called_once()
    assert publish_event.call_count == 2
    assert publish_event.call_args_list[0].args[1] == AUTOMATION_RUN_STARTED_SUBJECT
    assert publish_event.call_args_list[1].args[1] == AUTOMATION_RUN_FAILED_SUBJECT
    assert publish_event.call_args_list[0].args[2]['data']['trigger'] == 'scheduled'


def test_execute_automation_success_creates_chat_and_emits_completed_event():
    app = _app()
    app.state.main_loop = None
    automation = SimpleNamespace(
        id='auto-1',
        user_id='user-1',
        name='Daily summary',
        data={'prompt': 'hello', 'model_id': 'model-1'},
    )
    user = SimpleNamespace(id='user-1')
    chat = SimpleNamespace(id='chat-1')

    with (
        patch('open_webui.models.users.Users.get_user_by_id', return_value=user),
        patch('open_webui.models.chats.Chats.insert_new_chat', return_value=chat),
        patch('open_webui.main.chat_completion', new=AsyncMock(return_value={'status': True})) as chat_completion,
        patch('open_webui.models.automations.AutomationRuns.insert') as insert_run,
        patch('open_webui.utils.automations.publish_app_event_sync') as publish_event,
    ):
        execute_automation(app, automation)

    chat_completion.assert_awaited_once()
    assert insert_run.call_args.kwargs['status'] == 'success'
    assert insert_run.call_args.kwargs['chat_id'] == 'chat-1'
    assert publish_event.call_count == 2
    assert publish_event.call_args_list[0].args[1] == AUTOMATION_RUN_STARTED_SUBJECT
    assert publish_event.call_args_list[1].args[1] == AUTOMATION_RUN_COMPLETED_SUBJECT
    assert publish_event.call_args_list[1].args[2]['data']['trigger'] == 'scheduled'


@pytest.mark.asyncio
async def test_scheduler_worker_loop_claims_due_automations_and_schedules_execution():
    app = _app()
    app.state.config.ENABLE_AUTOMATIONS = True
    automation = SimpleNamespace(id='auto-1')
    scheduled = []

    async def fake_sleep(_seconds):
        raise asyncio.CancelledError()

    def fake_create_task(task):
        scheduled.append(task)
        try:
            task.close()
        except Exception:
            pass
        class DummyTask:
            pass
        return DummyTask()

    with (
        patch('open_webui.models.automations.Automations.claim_due', return_value=[automation]) as claim_due,
        patch('open_webui.utils.automations.asyncio.sleep', side_effect=fake_sleep),
        patch('open_webui.utils.automations.asyncio.create_task', side_effect=fake_create_task),
    ):
        with pytest.raises(asyncio.CancelledError):
            await scheduler_worker_loop(app)

    claim_due.assert_called_once()
    assert len(scheduled) == 1
