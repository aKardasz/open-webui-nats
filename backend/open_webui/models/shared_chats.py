import logging
import time
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, ForeignKey, Text, JSON
from sqlalchemy.orm import Session

from open_webui.internal.db import Base, get_db_context

log = logging.getLogger(__name__)


class SharedChat(Base):
    __tablename__ = 'shared_chat'

    id = Column(Text, primary_key=True)
    chat_id = Column(Text, ForeignKey('chat.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Text, nullable=False)
    title = Column(Text)
    chat = Column(JSON)
    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class SharedChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    user_id: str
    title: str
    chat: dict
    created_at: int
    updated_at: int


class SharedChatsTable:
    def create(self, chat_id: str, user_id: str, db: Optional[Session] = None) -> Optional[SharedChatModel]:
        with get_db_context(db) as db:
            from open_webui.models.chats import Chat

            chat = db.get(Chat, chat_id)
            if not chat:
                return None

            now = int(time.time())
            shared_chat = SharedChat(
                id=str(uuid.uuid4()),
                chat_id=chat_id,
                user_id=user_id,
                title=chat.title,
                chat=chat.chat,
                created_at=now,
                updated_at=now,
            )
            db.add(shared_chat)
            db.commit()
            db.refresh(shared_chat)
            return SharedChatModel.model_validate(shared_chat)

    def update(self, share_id: str, db: Optional[Session] = None) -> Optional[SharedChatModel]:
        with get_db_context(db) as db:
            from open_webui.models.chats import Chat

            shared_chat = db.get(SharedChat, share_id)
            if not shared_chat:
                return None

            chat = db.get(Chat, shared_chat.chat_id)
            if not chat:
                return None

            shared_chat.title = chat.title
            shared_chat.chat = chat.chat
            shared_chat.updated_at = int(time.time())
            db.commit()
            db.refresh(shared_chat)
            return SharedChatModel.model_validate(shared_chat)

    def get_by_id(self, share_id: str, db: Optional[Session] = None) -> Optional[SharedChatModel]:
        with get_db_context(db) as db:
            shared_chat = db.get(SharedChat, share_id)
            return SharedChatModel.model_validate(shared_chat) if shared_chat else None

    def get_by_chat_id(self, chat_id: str, db: Optional[Session] = None) -> Optional[SharedChatModel]:
        with get_db_context(db) as db:
            shared_chat = (
                db.query(SharedChat)
                .filter_by(chat_id=chat_id)
                .order_by(SharedChat.updated_at.desc())
                .first()
            )
            return SharedChatModel.model_validate(shared_chat) if shared_chat else None

    def delete_by_id(self, share_id: str, db: Optional[Session] = None) -> bool:
        try:
            with get_db_context(db) as db:
                db.query(SharedChat).filter_by(id=share_id).delete()
                db.commit()
                return True
        except Exception:
            return False

    def delete_by_chat_id(self, chat_id: str, db: Optional[Session] = None) -> bool:
        try:
            with get_db_context(db) as db:
                db.query(SharedChat).filter_by(chat_id=chat_id).delete()
                db.commit()
                return True
        except Exception:
            return False


SharedChats = SharedChatsTable()
