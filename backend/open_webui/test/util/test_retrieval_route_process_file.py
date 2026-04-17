from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException, status

from open_webui.routers.retrieval import ProcessFileForm, process_file
from open_webui.utils.retrieval_service import RetrievalServiceError


def test_route_process_file_delegates_to_shared_service():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = SimpleNamespace(id='user-1', role='user')
    db = Mock()
    form_data = ProcessFileForm(file_id='file-1', content='hello')

    with patch(
        'open_webui.routers.retrieval.process_file_service',
        return_value={'status': True, 'collection_name': None, 'filename': 'doc.txt', 'content': 'hello'},
    ) as process:
        result = process_file(request, form_data, user=user, db=db)

    process.assert_called_once_with(
        request,
        form_data,
        user=user,
        db=db,
    )
    assert result['status'] is True


def test_route_process_file_maps_service_errors_to_http():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = SimpleNamespace(id='user-1', role='user')
    db = Mock()

    with patch(
        'open_webui.routers.retrieval.process_file_service',
        side_effect=RetrievalServiceError('boom', status_code=status.HTTP_400_BAD_REQUEST),
    ):
        with pytest.raises(HTTPException) as exc_info:
            process_file(request, ProcessFileForm(file_id='file-1'), user=user, db=db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == 'boom'
