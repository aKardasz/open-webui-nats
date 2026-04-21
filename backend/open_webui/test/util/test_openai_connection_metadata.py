from open_webui.routers.openai import apply_api_connection_metadata


def test_apply_api_connection_metadata_marks_internal_pipeline_execution():
    model = {
        'id': 'pipe-1',
        'name': 'Pipe One',
        'pipeline': {'type': 'filter', 'pipelines': ['*'], 'priority': 0},
    }
    api_config = {
        'connection_type': 'internal',
        'prefix_id': 'internal',
    }

    result = apply_api_connection_metadata(model, api_config)

    assert result == {
        'id': 'internal.pipe-1',
        'name': 'Pipe One',
        'pipeline': {
            'type': 'filter',
            'pipelines': ['*'],
            'priority': 0,
            'execution': 'internal',
        },
        'connection_type': 'internal',
        'internal_executor_id': 'pipe-1',
        'execution_mode': 'internal',
    }


def test_apply_api_connection_metadata_respects_explicit_internal_executor_id():
    model = {
        'id': 'pipe-1',
        'pipeline': {'type': 'filter'},
    }
    api_config = {
        'connection_type': 'internal',
        'internal_executor_id': 'filter-fn-1',
    }

    result = apply_api_connection_metadata(model, api_config)

    assert result['internal_executor_id'] == 'filter-fn-1'
    assert result['pipeline']['execution'] == 'internal'
    assert result['execution_mode'] == 'internal'


def test_apply_api_connection_metadata_can_seed_pipeline_metadata_from_config():
    model = {
        'id': 'pipe-1',
        'name': 'Pipe One',
    }
    api_config = {
        'connection_type': 'internal',
        'pipeline': {
            'type': 'filter',
            'pipelines': ['*'],
            'priority': 5,
        },
    }

    result = apply_api_connection_metadata(model, api_config)

    assert result == {
        'id': 'pipe-1',
        'name': 'Pipe One',
        'connection_type': 'internal',
        'internal_executor_id': 'pipe-1',
        'execution_mode': 'internal',
        'pipeline': {
            'type': 'filter',
            'pipelines': ['*'],
            'priority': 5,
            'execution': 'internal',
        },
    }


def test_apply_api_connection_metadata_preserves_explicit_jetstream_execution():
    model = {
        'id': 'pipe-1',
        'pipeline': {
            'type': 'filter',
            'execution': 'jetstream',
            'durable_stage': True,
        },
    }
    api_config = {
        'connection_type': 'internal',
    }

    result = apply_api_connection_metadata(model, api_config)

    assert result == {
        'id': 'pipe-1',
        'execution_mode': 'jetstream',
        'pipeline': {
            'type': 'filter',
            'execution': 'jetstream',
            'durable_stage': True,
        },
        'connection_type': 'internal',
        'internal_executor_id': 'pipe-1',
    }


def test_apply_api_connection_metadata_keeps_external_models_unchanged_except_standard_fields():
    model = {
        'id': 'pipe-1',
        'pipeline': {'type': 'filter'},
    }
    api_config = {
        'connection_type': 'external',
        'tags': ['alpha'],
    }

    result = apply_api_connection_metadata(model, api_config)

    assert result == {
        'id': 'pipe-1',
        'pipeline': {'type': 'filter'},
        'connection_type': 'external',
        'tags': ['alpha'],
    }
