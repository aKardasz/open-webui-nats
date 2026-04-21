from types import SimpleNamespace

from open_webui.utils.models import build_action_item, build_filter_item, get_module_execution_metadata


def _function():
    return SimpleNamespace(
        id='fn-1',
        name='Function One',
        meta=SimpleNamespace(
            description='desc',
            manifest={},
        ),
    )


def test_get_module_execution_metadata_defaults_to_request_reply():
    module = SimpleNamespace()

    assert get_module_execution_metadata(module) == {
        'execution_mode': 'request_reply',
    }


def test_get_module_execution_metadata_marks_durable_stage():
    module = SimpleNamespace(durable_stage=True)

    assert get_module_execution_metadata(module) == {
        'execution_mode': 'jetstream',
        'durable_stage': True,
    }


def test_build_action_item_includes_execution_metadata():
    item = build_action_item(
        _function(),
        SimpleNamespace(durable_stage=True),
        {'id': 'sub', 'name': 'Sub'},
    )

    assert item == {
        'id': 'fn-1.sub',
        'name': 'Sub',
        'description': 'desc',
        'icon': None,
        'execution_mode': 'jetstream',
        'durable_stage': True,
        'internal_executor_id': 'fn-1',
        'sub_action_id': 'sub',
    }


def test_build_filter_item_includes_execution_metadata_and_user_valves():
    item = build_filter_item(
        _function(),
        SimpleNamespace(UserValves=object, execution='internal'),
    )

    assert item == {
        'id': 'fn-1',
        'name': 'Function One',
        'description': 'desc',
        'icon': None,
        'has_user_valves': True,
        'execution_mode': 'internal',
        'internal_executor_id': 'fn-1',
    }
