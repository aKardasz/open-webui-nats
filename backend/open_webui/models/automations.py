import logging
import time
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, Index, JSON, String, Text, cast, func, or_
from sqlalchemy.orm import Session

from open_webui.internal.db import Base, get_db_context

log = logging.getLogger(__name__)


class Automation(Base):
    __tablename__ = 'automation'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    data = Column(JSON, nullable=False)
    meta = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(BigInteger, nullable=True)
    next_run_at = Column(BigInteger, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_automation_next_run', 'next_run_at'),)


class AutomationRun(Base):
    __tablename__ = 'automation_run'

    id = Column(Text, primary_key=True)
    automation_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    error = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('ix_automation_run_automation_id', 'automation_id'),
        Index('ix_automation_run_aid_created', 'automation_id', 'created_at'),
    )


class AutomationTerminalConfig(BaseModel):
    server_id: str
    cwd: Optional[str] = None


class AutomationData(BaseModel):
    prompt: str
    model_id: str
    rrule: str
    terminal: Optional[AutomationTerminalConfig] = None


class AutomationModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    data: dict
    meta: Optional[dict] = None
    is_active: bool
    last_run_at: Optional[int] = None
    next_run_at: Optional[int] = None
    created_at: int
    updated_at: int


class AutomationRunModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_id: str
    chat_id: Optional[str] = None
    status: str
    error: Optional[str] = None
    created_at: int


class AutomationForm(BaseModel):
    name: str
    data: AutomationData
    meta: Optional[dict] = None
    is_active: Optional[bool] = True


class AutomationResponse(AutomationModel):
    last_run: Optional[AutomationRunModel] = None
    next_runs: Optional[list[int]] = None


class AutomationListResponse(BaseModel):
    items: list[AutomationModel]
    total: int


class AutomationTable:
    def insert(
        self,
        user_id: str,
        form: AutomationForm,
        next_run_at: int,
        db: Optional[Session] = None,
    ) -> AutomationModel:
        with get_db_context(db) as db:
            now = int(time.time_ns())
            row = Automation(
                id=str(uuid4()),
                user_id=user_id,
                name=form.name,
                data=form.data.model_dump(),
                meta=form.meta,
                is_active=form.is_active,
                next_run_at=next_run_at,
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return AutomationModel.model_validate(row)

    def count_by_user(self, user_id: str, db: Optional[Session] = None) -> int:
        with get_db_context(db) as db:
            return db.query(Automation).filter_by(user_id=user_id).count()

    def get_by_id(self, id: str, db: Optional[Session] = None) -> Optional[AutomationModel]:
        with get_db_context(db) as db:
            row = db.get(Automation, id)
            return AutomationModel.model_validate(row) if row else None

    def get_active_by_user(self, user_id: str, db: Optional[Session] = None) -> list[AutomationModel]:
        with get_db_context(db) as db:
            rows = (
                db.query(Automation)
                .filter_by(user_id=user_id, is_active=True)
                .order_by(Automation.created_at.desc())
                .all()
            )
            return [AutomationModel.model_validate(r) for r in rows]

    def search_automations(
        self,
        user_id: str,
        query: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 30,
        db: Optional[Session] = None,
    ) -> AutomationListResponse:
        with get_db_context(db) as db:
            q = db.query(Automation).filter_by(user_id=user_id)

            if query:
                search = f'%{query}%'
                q = q.filter(
                    or_(
                        Automation.name.ilike(search),
                        cast(Automation.data, String).ilike(search),
                    )
                )

            if status == 'active':
                q = q.filter(Automation.is_active == True)  # noqa: E712
            elif status == 'paused':
                q = q.filter(Automation.is_active == False)  # noqa: E712

            total = q.count()
            rows = q.order_by(Automation.created_at.desc()).offset(skip).limit(limit).all()
            return AutomationListResponse(items=[AutomationModel.model_validate(r) for r in rows], total=total)

    def update_by_id(
        self,
        id: str,
        form: AutomationForm,
        next_run_at: int,
        db: Optional[Session] = None,
    ) -> Optional[AutomationModel]:
        with get_db_context(db) as db:
            row = db.get(Automation, id)
            if not row:
                return None
            row.name = form.name
            row.data = form.data.model_dump()
            row.meta = form.meta
            if form.is_active is not None:
                row.is_active = form.is_active
            row.next_run_at = next_run_at
            row.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(row)
            return AutomationModel.model_validate(row)

    def toggle(self, id: str, next_run_at: Optional[int], db: Optional[Session] = None) -> Optional[AutomationModel]:
        with get_db_context(db) as db:
            row = db.get(Automation, id)
            if not row:
                return None
            row.is_active = not row.is_active
            row.next_run_at = next_run_at if row.is_active else None
            row.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(row)
            return AutomationModel.model_validate(row)

    def delete(self, id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            row = db.get(Automation, id)
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def claim_due(self, now_ns: int, limit: int = 10, db: Optional[Session] = None) -> list[AutomationModel]:
        from open_webui.utils.automations import next_run_ns

        with get_db_context(db) as db:
            rows = (
                db.query(Automation)
                .filter(
                    Automation.is_active == True,  # noqa: E712
                    Automation.next_run_at.isnot(None),
                    Automation.next_run_at <= now_ns,
                )
                .order_by(Automation.next_run_at.asc())
                .limit(limit)
                .all()
            )

            claimed: list[AutomationModel] = []
            for row in rows:
                row.last_run_at = now_ns
                row.next_run_at = next_run_ns(row.data.get('rrule', ''), tz=None)
                claimed.append(AutomationModel.model_validate(row))

            if rows:
                db.commit()

            return claimed


class AutomationRunTable:
    def insert(
        self,
        automation_id: str,
        status: str,
        chat_id: Optional[str] = None,
        error: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> AutomationRunModel:
        with get_db_context(db) as db:
            row = AutomationRun(
                id=str(uuid4()),
                automation_id=automation_id,
                chat_id=chat_id,
                status=status,
                error=error,
                created_at=int(time.time_ns()),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return AutomationRunModel.model_validate(row)

    def get_latest(self, automation_id: str, db: Optional[Session] = None) -> Optional[AutomationRunModel]:
        with get_db_context(db) as db:
            row = (
                db.query(AutomationRun)
                .filter_by(automation_id=automation_id)
                .order_by(AutomationRun.created_at.desc())
                .first()
            )
            return AutomationRunModel.model_validate(row) if row else None

    def get_latest_batch(self, automation_ids: list[str], db: Optional[Session] = None) -> dict[str, AutomationRunModel]:
        if not automation_ids:
            return {}
        with get_db_context(db) as db:
            rows = (
                db.query(AutomationRun)
                .filter(AutomationRun.automation_id.in_(automation_ids))
                .order_by(AutomationRun.automation_id, AutomationRun.created_at.desc())
                .all()
            )
            result = {}
            for row in rows:
                if row.automation_id not in result:
                    result[row.automation_id] = AutomationRunModel.model_validate(row)
            return result

    def get_by_automation(
        self,
        automation_id: str,
        skip: int = 0,
        limit: int = 50,
        db: Optional[Session] = None,
    ) -> list[AutomationRunModel]:
        with get_db_context(db) as db:
            rows = (
                db.query(AutomationRun)
                .filter_by(automation_id=automation_id)
                .order_by(AutomationRun.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
            return [AutomationRunModel.model_validate(r) for r in rows]

    def delete_by_automation(self, automation_id: str, db: Optional[Session] = None) -> bool:
        with get_db_context(db) as db:
            db.query(AutomationRun).filter_by(automation_id=automation_id).delete()
            db.commit()
            return True


Automations = AutomationTable()
AutomationRuns = AutomationRunTable()
