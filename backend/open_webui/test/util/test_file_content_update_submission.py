from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from open_webui.routers.files import ContentForm, update_file_data_content_by_id


def _file():
    return SimpleNamespace(id='file-1', user_id='user-1', meta={'content_type': 'text/plain'}, data={'content': 'x'})


def _user():
    return SimpleNamespace(id='user-1', role='user')


def test_update_file_data_content_by_id_returns_400_when_submission_fails():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    with (
        patch('open_webui.routers.files.Files.get_file_by_id', return_value=_file()),
        patch('open_webui.routers.files.submit_file_retrieval', side_effect=Exception('boom')),
    ):
        with pytest.raises(HTTPException) as exc:
            update_file_data_content_by_id(request, 'file-1', ContentForm(content='hello'), _user(), db=Mock())

    assert exc.value.status_code == 400
    assert exc.value.detail == 'boom'
