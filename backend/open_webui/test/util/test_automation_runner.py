from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from open_webui.utils.automation_runner import (
    AutomationRunner,
    request_automation_run,
    should_start_automation_runner,
)


def _app(*, nats_url=''):
    return SimpleNamespace(
        state=SimpleNamespace(
            instance_id='instance-1',
            config=SimpleNamespace(
                NATS_URL=nats_url,
                AUTOMATION_NATS_SUBJECT='owui.cmd.automation.run',
                AUTOMATION_NATS_REQUEST_TIMEOUT=5.0,
                ENABLE_AUTOMATIONS=True,
            ),
        )
    )


def _automation():
    return SimpleNamespace(id='auto-1')


def test_should_start_automation_runner_requires_enablement_and_nats():
    assert should_start_automation_runner(
        enable_automations=True,
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        automation_runner_only_mode=False,
    )
    assert should_start_automation_runner(
        enable_automations=True,
        nats_url='nats://nats:4222',
        enable_embedded_runner=False,
        automation_runner_only_mode=True,
    )
    assert not should_start_automation_runner(
        enable_automations=False,
        nats_url='nats://nats:4222',
        enable_embedded_runner=True,
        automation_runner_only_mode=False,
    )
    assert not should_start_automation_runner(
        enable_automations=True,
        nats_url='',
        enable_embedded_runner=True,
        automation_runner_only_mode=False,
    )


@pytest.mark.asyncio
async def test_request_automation_run_falls_back_to_local_background_task_without_nats():
    app = _app(nats_url='')
    background_tasks = SimpleNamespace(tasks=[], add_task=lambda fn, *args, **kwargs: background_tasks.tasks.append((fn, args, kwargs)))

    result = await request_automation_run(app, _automation(), background_tasks=background_tasks)

    assert result['status'] == 'accepted'
    assert result['owner'] == 'web-local'
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_request_automation_run_uses_nats_request_when_available():
    app = _app(nats_url='nats://nats:4222')
    response = SimpleNamespace(data=b'{"status":"accepted","request_id":"req-1","owner":"automation-runner"}')
    nc = SimpleNamespace(request=AsyncMock(return_value=response), drain=AsyncMock())

    with patch('open_webui.utils.automation_runner._connect_nats', AsyncMock(return_value=nc)):
        result = await request_automation_run(app, _automation())

    assert result['owner'] == 'automation-runner'
    nc.request.assert_awaited_once()
    nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_automation_run_does_not_fallback_locally_when_nats_runner_unavailable():
    app = _app(nats_url='nats://nats:4222')
    background_tasks = SimpleNamespace(tasks=[], add_task=lambda fn, *args, **kwargs: background_tasks.tasks.append((fn, args, kwargs)))
    nc = SimpleNamespace(request=AsyncMock(side_effect=TimeoutError('no responders')), drain=AsyncMock())

    with (
        patch('open_webui.utils.automation_runner._connect_nats', AsyncMock(return_value=nc)),
        patch('open_webui.utils.automation_runner.execute_automation') as execute_automation,
    ):
        with pytest.raises(RuntimeError, match='Automation runner unavailable'):
            await request_automation_run(app, _automation(), background_tasks=background_tasks)

    assert background_tasks.tasks == []
    execute_automation.assert_not_called()
    nc.request.assert_awaited_once()
    nc.drain.assert_awaited_once()


@pytest.mark.asyncio
async def test_automation_runner_request_payload_accepts_valid_job():
    app = _app(nats_url='nats://nats:4222')
    runner = AutomationRunner(app, 'nats://nats:4222', 'instance-1')
    scheduled = []

    def fake_create_task(task):
        scheduled.append(task)
        try:
            task.close()
        except Exception:
            pass
        return SimpleNamespace()

    with (
        patch('open_webui.models.automations.Automations.get_by_id', return_value=_automation()),
        patch('open_webui.utils.automation_runner.asyncio.create_task', side_effect=fake_create_task),
    ):
        result = await runner.handle_request_payload(b'{"automation_id":"auto-1","request_id":"req-1"}')

    assert result['status'] == 'accepted'
    assert result['request_id'] == 'req-1'
    assert len(scheduled) == 1
