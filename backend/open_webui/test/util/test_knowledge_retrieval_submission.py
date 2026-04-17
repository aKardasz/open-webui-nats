from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from open_webui.routers.knowledge import add_file_to_knowledge_by_id, reindex_knowledge_files, update_file_from_knowledge_by_id
from open_webui.utils.retrieval_transport import LocalRetrievalTransport


class _Knowledge:
    def __init__(self, knowledge_id='knowledge-1', user_id='user-1'):
        self.id = knowledge_id
        self.user_id = user_id

    def model_dump(self):
        return {'id': self.id, 'user_id': self.user_id}


def _file():
    return SimpleNamespace(id='file-1', user_id='user-1', meta={'content_type': 'text/plain'}, data={'content': 'x'})


def _user():
    return SimpleNamespace(id='user-1', role='user')


def _form():
    return SimpleNamespace(file_id='file-1')


def test_add_file_to_knowledge_by_id_returns_400_when_submission_fails():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    knowledge = _Knowledge()

    with (
        patch('open_webui.routers.knowledge.Knowledges.get_knowledge_by_id', return_value=knowledge),
        patch('open_webui.routers.knowledge.Files.get_file_by_id', return_value=_file()),
        patch('open_webui.routers.knowledge.submit_file_retrieval', side_effect=Exception('boom')),
        patch('open_webui.routers.knowledge.Knowledges.add_file_to_knowledge_by_id') as add_file,
    ):
        with pytest.raises(HTTPException) as exc:
            add_file_to_knowledge_by_id(request, 'knowledge-1', _form(), _user(), db=Mock())

    assert exc.value.status_code == 400
    add_file.assert_not_called()


def test_update_file_from_knowledge_by_id_returns_400_when_submission_fails():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    knowledge = _Knowledge()

    with (
        patch('open_webui.routers.knowledge.Knowledges.get_knowledge_by_id', return_value=knowledge),
        patch('open_webui.routers.knowledge.Files.get_file_by_id', return_value=_file()),
        patch('open_webui.routers.knowledge.Knowledges.has_file', return_value=True),
        patch('open_webui.routers.knowledge.VECTOR_DB_CLIENT.delete'),
        patch('open_webui.routers.knowledge.submit_file_retrieval', side_effect=Exception('boom')),
    ):
        with pytest.raises(HTTPException) as exc:
            update_file_from_knowledge_by_id(request, 'knowledge-1', _form(), _user(), db=Mock())

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reindex_knowledge_files_forces_local_transport_for_inline_reindex():
    app_transport = Mock()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(retrieval_transport=app_transport)))
    knowledge = _Knowledge()
    user = SimpleNamespace(id='admin-1', role='admin')
    db = Mock()

    async def run_inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with (
        patch('open_webui.routers.knowledge.Knowledges.get_knowledge_bases', return_value=[knowledge]),
        patch('open_webui.routers.knowledge.Knowledges.get_files_by_id', return_value=[_file()]),
        patch('open_webui.routers.knowledge.VECTOR_DB_CLIENT.has_collection', return_value=False),
        patch('open_webui.routers.knowledge.run_in_threadpool', side_effect=run_inline),
        patch.object(LocalRetrievalTransport, 'submit_file_job', return_value=(_file(), {'job_id': 'job-1'})) as submit_local,
    ):
        result = await reindex_knowledge_files(request, user=user, db=db)

    assert result is True
    app_transport.submit_file_job.assert_not_called()
    submit_local.assert_called_once()
