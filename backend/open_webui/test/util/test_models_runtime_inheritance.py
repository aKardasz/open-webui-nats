from open_webui.utils.models import get_inherited_runtime_fields


def test_get_inherited_runtime_fields_copies_pipeline_runtime_fields():
    base_model = {
        'id': 'internal.pipe-1',
        'owned_by': 'openai',
        'connection_type': 'internal',
        'internal_executor_id': 'pipe-1',
        'pipeline': {'type': 'filter', 'priority': 0},
        'pipe': {'type': 'pipe'},
    }

    inherited = get_inherited_runtime_fields(base_model)

    assert inherited == {
        'owned_by': 'openai',
        'connection_type': 'internal',
        'internal_executor_id': 'pipe-1',
        'execution_mode': 'internal',
        'pipeline': {
            'type': 'filter',
            'priority': 0,
            'execution': 'internal',
        },
        'pipe': {'type': 'pipe'},
    }


def test_get_inherited_runtime_fields_returns_independent_copies():
    base_model = {
        'owned_by': 'openai',
        'connection_type': 'internal',
        'pipeline': {'type': 'filter'},
    }

    inherited = get_inherited_runtime_fields(base_model)
    inherited['pipeline']['type'] = 'changed'

    assert base_model['pipeline']['type'] == 'filter'


def test_get_inherited_runtime_fields_preserves_explicit_jetstream_execution():
    base_model = {
        'owned_by': 'openai',
        'connection_type': 'internal',
        'pipeline': {
            'type': 'filter',
            'execution': 'jetstream',
            'durable_stage': True,
        },
    }

    inherited = get_inherited_runtime_fields(base_model)

    assert inherited == {
        'owned_by': 'openai',
        'connection_type': 'internal',
        'execution_mode': 'jetstream',
        'pipeline': {
            'type': 'filter',
            'execution': 'jetstream',
            'durable_stage': True,
        },
    }
