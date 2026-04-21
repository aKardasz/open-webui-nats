from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_nats_overlay():
    compose_path = REPO_ROOT / 'docker-compose.nats.yaml'
    with compose_path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def _normalized_env(service):
    return {item.strip("'") for item in service.get('environment', [])}


def test_nats_overlay_provisions_transitional_stage_b_services():
    compose = _load_nats_overlay()

    services = compose.get('services', {})

    assert {'nats', 'open-webui', 'retrieval-worker', 'pipeline-runner', 'terminal-service'} <= set(services)


def test_nats_overlay_disables_embedded_services_in_web_lane():
    compose = _load_nats_overlay()

    web_env = _normalized_env(compose['services']['open-webui'])

    assert 'ENABLE_EMBEDDED_RETRIEVAL_WORKER=false' in web_env
    assert 'ENABLE_EMBEDDED_PIPELINE_RUNNER=false' in web_env
    assert 'ENABLE_EMBEDDED_TERMINAL_SERVICE=false' in web_env
    assert 'NATS_URL=nats://nats:4222' in web_env
    assert any(item.startswith('WEBUI_SECRET_KEY=') and item != 'WEBUI_SECRET_KEY=' for item in web_env)


def test_nats_overlay_worker_modes_are_explicit():
    compose = _load_nats_overlay()

    retrieval_env = _normalized_env(compose['services']['retrieval-worker'])
    pipeline_env = _normalized_env(compose['services']['pipeline-runner'])
    terminal_env = _normalized_env(compose['services']['terminal-service'])

    assert compose['services']['retrieval-worker']['command'] == ['python', '-m', 'open_webui', 'retrieval-worker']
    assert compose['services']['pipeline-runner']['command'] == ['python', '-m', 'open_webui', 'pipeline-runner']
    assert compose['services']['terminal-service']['command'] == ['python', '-m', 'open_webui', 'terminal-service']

    assert 'WORKER_ONLY_MODE=true' in retrieval_env
    assert 'RETRIEVAL_TRANSPORT=jetstream' in retrieval_env
    assert 'PIPELINE_RUNNER_ONLY_MODE=true' in pipeline_env
    assert 'PIPELINE_INTERNAL_TRANSPORT=nats' in pipeline_env
    assert 'TERMINAL_SERVICE_ONLY_MODE=true' in terminal_env

    assert any(item.startswith('WEBUI_SECRET_KEY=') and item != 'WEBUI_SECRET_KEY=' for item in retrieval_env)
    assert any(item.startswith('WEBUI_SECRET_KEY=') and item != 'WEBUI_SECRET_KEY=' for item in pipeline_env)
    assert any(item.startswith('WEBUI_SECRET_KEY=') and item != 'WEBUI_SECRET_KEY=' for item in terminal_env)


def test_nats_overlay_disables_http_healthchecks_for_worker_only_services():
    compose = _load_nats_overlay()

    for service_name in ['retrieval-worker', 'pipeline-runner', 'terminal-service']:
        assert compose['services'][service_name]['healthcheck'] == {'disable': True}


def test_nats_overlay_has_broker_healthcheck_and_persistent_jetstream_volume():
    compose = _load_nats_overlay()

    nats_service = compose['services']['nats']

    assert nats_service['command'] == ['-js', '-sd', '/data', '-m', '8222']
    assert nats_service['healthcheck']['test'] == ['CMD', 'wget', '-qO-', 'http://127.0.0.1:8222/healthz']
    assert 'nats-data:/data' in nats_service['volumes']
    assert 'nats-data' in compose['volumes']


def test_stage_b_smoke_runbook_tracks_runtime_promotion_gate():
    runbook_path = REPO_ROOT / 'docs' / 'architecture' / 'nats' / '07-stage-b-smoke-runbook.md'

    runbook = runbook_path.read_text(encoding='utf-8')

    assert 'docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml config --services' in runbook
    assert 'docker-compose -f docker-compose.yaml -f docker-compose.nats.yaml up -d' in runbook
    assert 'terminal-service.default' in runbook
    assert 'pipeline-runner.default' in runbook
    assert 'Failure And Rollback Checks' in runbook
