from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from open_webui.models.notes import NoteModel
from open_webui.routers import chats as chats_router
from open_webui.routers import notes as notes_router


class _DumpableUser:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return dict(self.__dict__)


def _request(*, permissions=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    USER_PERMISSIONS=permissions or {},
                )
            )
        )
    )


def _user(role='user'):
    return SimpleNamespace(id='user-1', role=role, timezone='UTC')


@pytest.mark.asyncio
async def test_get_pinned_notes_returns_note_list():
    request = _request()
    user = _user()
    db = object()
    note = NoteModel(
        id='note-1',
        user_id='user-1',
        title='Pinned note',
        data={'content': {'md': 'hello'}},
        meta=None,
        is_pinned=True,
        access_grants=[],
        created_at=1,
        updated_at=1,
    )
    db_user = _DumpableUser(
        id='user-1',
        name='User One',
        email='user@example.com',
        profile_image_url='/u.png',
        role='user',
    )

    with (
        patch.object(notes_router, 'has_permission', return_value=True),
        patch.object(notes_router.Notes, 'get_pinned_notes_by_user_id', return_value=[note]),
        patch.object(notes_router.Users, 'get_users_by_user_ids', return_value=[db_user]),
    ):
        result = await notes_router.get_pinned_notes(request, user=user, db=db)

    assert len(result) == 1
    assert result[0].id == 'note-1'
    assert result[0].is_pinned is True


@pytest.mark.asyncio
async def test_pin_note_by_id_toggles_note_for_owner():
    request = _request()
    user = _user()
    db = object()
    note = NoteModel(
        id='note-1',
        user_id='user-1',
        title='Pinned note',
        data={'content': {'md': 'hello'}},
        meta=None,
        is_pinned=False,
        access_grants=[],
        created_at=1,
        updated_at=1,
    )
    toggled = note.model_copy(update={'is_pinned': True})

    with (
        patch.object(notes_router, 'has_permission', return_value=True),
        patch.object(notes_router.Notes, 'get_note_by_id', return_value=note),
        patch.object(notes_router.Notes, 'toggle_note_pinned_by_id', return_value=toggled) as toggle_note,
    ):
        result = await notes_router.pin_note_by_id(request, 'note-1', user=user, db=db)

    assert result.is_pinned is True
    toggle_note.assert_called_once_with('note-1', db=db)


@pytest.mark.asyncio
async def test_get_shared_chat_by_id_rejects_when_access_grant_missing():
    user = _user()
    db = object()
    shared_chat = SimpleNamespace(
        id='share-1',
        user_id='user-1',
        title='Shared chat',
        chat={'messages': []},
        created_at=1,
        updated_at=1,
        share_id='share-1',
    )
    shared_snapshot = SimpleNamespace(id='share-1', chat_id='chat-1')

    with (
        patch.object(chats_router.Chats, 'get_chat_by_share_id', return_value=shared_chat),
        patch('open_webui.models.shared_chats.SharedChats.get_by_id', return_value=shared_snapshot),
        patch.object(chats_router.AccessGrants, 'has_access', return_value=False),
    ):
        with pytest.raises(HTTPException) as exc:
            await chats_router.get_shared_chat_by_id('share-1', user=user, db=db)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_shared_chat_access_routes_round_trip():
    request = _request()
    user = _user()
    db = object()
    chat = SimpleNamespace(
        id='chat-1',
        user_id='user-1',
        model_dump=lambda: {
            'id': 'chat-1',
            'user_id': 'user-1',
            'title': 'Chat 1',
            'chat': {'messages': []},
            'updated_at': 1,
            'created_at': 1,
            'archived': False,
        },
    )
    grants = [SimpleNamespace(id='g1', principal_type='user', principal_id='*', permission='read')]

    with (
        patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', return_value=chat),
        patch.object(chats_router, 'filter_allowed_access_grants', return_value=[{'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]),
        patch.object(chats_router.AccessGrants, 'set_access_grants', return_value=[]),
    ):
        updated = await chats_router.update_shared_chat_access_by_id(
            request,
            'chat-1',
            chats_router.ChatAccessGrantsForm(access_grants=[{'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]),
            user=user,
            db=db,
        )

    assert updated.id == 'chat-1'

    with (
        patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', return_value=chat),
        patch.object(chats_router.AccessGrants, 'get_grants_by_resource', return_value=grants),
    ):
        result = await chats_router.get_shared_chat_access_by_id('chat-1', user=user, db=db)

    assert result == [{'id': 'g1', 'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]
