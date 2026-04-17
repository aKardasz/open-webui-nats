from types import SimpleNamespace

import pytest

from open_webui.routers.configs import get_runtime_registry_config


@pytest.mark.asyncio
async def test_get_runtime_registry_config_filters_records():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                RUNTIME_SERVICE_REGISTRY=[
                    {
                        'service_id': 'terminal.term-1',
                        'service_type': 'terminal',
                        'status': 'healthy',
                        'observed_at': '2026-04-17T18:59:45Z',
                    },
                    {
                        'service_id': 'tool-executor.tool-1',
                        'service_type': 'tool-executor',
                        'status': 'degraded',
                        'observed_at': '2026-04-17T18:59:45Z',
                    },
                ]
            )
        )
    )

    result = await get_runtime_registry_config(
        request,
        service_type='terminal',
        include_unhealthy=False,
        freshness_seconds=None,
        user=SimpleNamespace(id='admin-1', role='admin'),
    )

    assert result == {
        'RUNTIME_SERVICE_REGISTRY': [
            {
                'service_id': 'terminal.term-1',
                'service_type': 'terminal',
                'status': 'healthy',
                'observed_at': '2026-04-17T18:59:45Z',
            }
        ]
    }
