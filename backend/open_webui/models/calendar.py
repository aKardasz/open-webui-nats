import logging
import time
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, Boolean, Column, Index, JSON, Text, UniqueConstraint, delete, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from open_webui.internal.db import Base, get_async_db_context, get_db_context
from open_webui.models.access_grants import AccessGrantModel, AccessGrants
from open_webui.models.groups import Groups
from open_webui.models.users import User, UserModel, UserResponse, Users

log = logging.getLogger(__name__)


class Calendar(Base):
    __tablename__ = 'calendar'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    color = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (Index('ix_calendar_user', 'user_id'),)


class CalendarEvent(Base):
    __tablename__ = 'calendar_event'

    id = Column(Text, primary_key=True)
    calendar_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    start_at = Column(BigInteger, nullable=False)
    end_at = Column(BigInteger, nullable=True)
    all_day = Column(Boolean, nullable=False, default=False)
    rrule = Column(Text, nullable=True)
    color = Column(Text, nullable=True)
    location = Column(Text, nullable=True)
    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        Index('ix_calendar_event_calendar', 'calendar_id', 'start_at'),
        Index('ix_calendar_event_user_date', 'user_id', 'start_at'),
    )


class CalendarEventAttendee(Base):
    __tablename__ = 'calendar_event_attendee'

    id = Column(Text, primary_key=True)
    event_id = Column(Text, nullable=False)
    user_id = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default='pending')
    meta = Column(JSON, nullable=True)
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint('event_id', 'user_id', name='uq_event_attendee'),
        Index('ix_calendar_event_attendee_user', 'user_id', 'status'),
    )


class CalendarModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    color: Optional[str] = None
    is_default: bool = False
    is_system: bool = False
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_grants: list[AccessGrantModel] = Field(default_factory=list)
    created_at: int
    updated_at: int


class CalendarEventAttendeeModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    user_id: str
    status: str = 'pending'
    meta: Optional[dict] = None
    created_at: int
    updated_at: int


class CalendarEventModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra='allow')

    id: str
    calendar_id: str
    user_id: str
    title: str
    description: Optional[str] = None
    start_at: int
    end_at: Optional[int] = None
    all_day: bool = False
    rrule: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    is_cancelled: bool = False
    attendees: list[CalendarEventAttendeeModel] = Field(default_factory=list)
    created_at: int
    updated_at: int


class CalendarEventUserResponse(CalendarEventModel):
    user: Optional[UserResponse] = None


class CalendarEventListResponse(BaseModel):
    items: list[CalendarEventUserResponse]
    total: int


class CalendarForm(BaseModel):
    name: str
    color: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_grants: Optional[list[dict]] = None


class CalendarUpdateForm(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    access_grants: Optional[list[dict]] = None


class CalendarEventForm(BaseModel):
    calendar_id: str
    title: str
    description: Optional[str] = None
    start_at: int
    end_at: Optional[int] = None
    all_day: bool = False
    rrule: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    attendees: Optional[list[dict]] = None


class CalendarEventUpdateForm(BaseModel):
    calendar_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    start_at: Optional[int] = None
    end_at: Optional[int] = None
    all_day: Optional[bool] = None
    rrule: Optional[str] = None
    color: Optional[str] = None
    location: Optional[str] = None
    data: Optional[dict] = None
    meta: Optional[dict] = None
    is_cancelled: Optional[bool] = None
    attendees: Optional[list[dict]] = None


class RSVPForm(BaseModel):
    status: str


class CalendarTable:
    def _get_access_grants(self, calendar_id: str, db: Optional[Session] = None) -> list[AccessGrantModel]:
        return AccessGrants.get_grants_by_resource('calendar', calendar_id, db=db)

    def _to_calendar_model(
        self,
        cal: Calendar,
        access_grants: Optional[list[AccessGrantModel]] = None,
        db: Optional[Session] = None,
    ) -> CalendarModel:
        cal_data = CalendarModel.model_validate(cal).model_dump(exclude={'access_grants'})
        cal_data['access_grants'] = (
            access_grants if access_grants is not None else self._get_access_grants(cal_data['id'], db=db)
        )
        return CalendarModel.model_validate(cal_data)

    def get_or_create_defaults(self, user_id: str, db: Optional[Session] = None) -> list[CalendarModel]:
        with get_db_context(db) as db:
            calendars = db.query(Calendar).filter(Calendar.user_id == user_id).order_by(Calendar.created_at.asc()).all()
            if calendars:
                return [self._to_calendar_model(c, db=db) for c in calendars]

            now = int(time.time_ns())
            cal = Calendar(
                id=str(uuid4()),
                user_id=user_id,
                name='Personal',
                color='#3b82f6',
                is_default=True,
                created_at=now,
                updated_at=now,
            )
            db.add(cal)
            db.commit()
            db.refresh(cal)
            return [self._to_calendar_model(cal, db=db)]

    def get_calendars_by_user(self, user_id: str, db: Optional[Session] = None) -> list[CalendarModel]:
        with get_db_context(db) as db:
            user_groups = Groups.get_groups_by_member_id(user_id, db=db)
            user_group_ids = [g.id for g in user_groups]

            query = db.query(Calendar)
            query = AccessGrants.has_permission_filter(
                db=db,
                query=query,
                DocumentModel=Calendar,
                filter={'user_id': user_id, 'group_ids': user_group_ids},
                resource_type='calendar',
                permission='read',
            ).order_by(Calendar.created_at.asc())

            calendars = query.all()
            if not calendars:
                return self.get_or_create_defaults(user_id, db=db)

            cal_ids = [c.id for c in calendars]
            grants_map = AccessGrants.get_grants_by_resources('calendar', cal_ids, db=db)
            return [self._to_calendar_model(c, access_grants=grants_map.get(c.id, []), db=db) for c in calendars]

    def get_calendar_by_id(self, id: str, db: Optional[Session] = None) -> Optional[CalendarModel]:
        with get_db_context(db) as db:
            cal = db.query(Calendar).filter(Calendar.id == id).first()
            return self._to_calendar_model(cal, db=db) if cal else None

    def insert_new_calendar(self, user_id: str, form_data: CalendarForm, db: Optional[Session] = None) -> Optional[CalendarModel]:
        with get_db_context(db) as db:
            now = int(time.time_ns())
            cal = Calendar(
                id=str(uuid4()),
                user_id=user_id,
                name=form_data.name,
                color=form_data.color,
                is_default=False,
                data=form_data.data,
                meta=form_data.meta,
                created_at=now,
                updated_at=now,
            )
            db.add(cal)
            db.commit()
            if form_data.access_grants is not None:
                AccessGrants.set_access_grants('calendar', cal.id, form_data.access_grants, db=db)
            db.refresh(cal)
            return self._to_calendar_model(cal, db=db)

    def update_calendar_by_id(self, id: str, form_data: CalendarUpdateForm, db: Optional[Session] = None) -> Optional[CalendarModel]:
        with get_db_context(db) as db:
            cal = db.query(Calendar).filter(Calendar.id == id).first()
            if not cal:
                return None
            update_data = form_data.model_dump(exclude_unset=True)
            if 'name' in update_data:
                cal.name = update_data['name']
            if 'color' in update_data:
                cal.color = update_data['color']
            if 'data' in update_data:
                cal.data = {**(cal.data or {}), **(update_data['data'] or {})}
            if 'meta' in update_data:
                cal.meta = {**(cal.meta or {}), **(update_data['meta'] or {})}
            if 'access_grants' in update_data:
                AccessGrants.set_access_grants('calendar', id, update_data['access_grants'], db=db)
            cal.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(cal)
            return self._to_calendar_model(cal, db=db)

    def set_default_calendar(self, user_id: str, calendar_id: str, db: Optional[Session] = None) -> Optional[CalendarModel]:
        with get_db_context(db) as db:
            db.query(Calendar).filter(Calendar.user_id == user_id, Calendar.is_default == True).update(  # noqa: E712
                {'is_default': False}, synchronize_session=False
            )
            cal = db.query(Calendar).filter(Calendar.id == calendar_id, Calendar.user_id == user_id).first()
            if not cal:
                return None
            cal.is_default = True
            cal.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(cal)
            return self._to_calendar_model(cal, db=db)

    def delete_calendar_by_id(self, id: str, db: Optional[Session] = None) -> bool:
        try:
            with get_db_context(db) as db:
                cal = db.query(Calendar).filter(Calendar.id == id).first()
                if not cal or cal.is_default:
                    return False

                event_ids = [r[0] for r in db.query(CalendarEvent.id).filter(CalendarEvent.calendar_id == id).all()]
                if event_ids:
                    db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id.in_(event_ids)).delete(
                        synchronize_session=False
                    )
                db.query(CalendarEvent).filter(CalendarEvent.calendar_id == id).delete(synchronize_session=False)
                AccessGrants.revoke_all_access('calendar', id, db=db)
                db.query(Calendar).filter(Calendar.id == id).delete(synchronize_session=False)
                db.commit()
                return True
        except Exception:
            return False

    async def get_or_create_defaults_async(self, user_id: str, db: Optional[AsyncSession] = None) -> list[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.get_or_create_defaults(user_id, db=sync_db))

    async def get_calendars_by_user_async(self, user_id: str, db: Optional[AsyncSession] = None) -> list[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.get_calendars_by_user(user_id, db=sync_db))

    async def get_calendar_by_id_async(self, id: str, db: Optional[AsyncSession] = None) -> Optional[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.get_calendar_by_id(id, db=sync_db))

    async def insert_new_calendar_async(
        self, user_id: str, form_data: CalendarForm, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.insert_new_calendar(user_id, form_data, db=sync_db))

    async def update_calendar_by_id_async(
        self, id: str, form_data: CalendarUpdateForm, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.update_calendar_by_id(id, form_data, db=sync_db))

    async def set_default_calendar_async(
        self, user_id: str, calendar_id: str, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.set_default_calendar(user_id, calendar_id, db=sync_db))

    async def delete_calendar_by_id_async(self, id: str, db: Optional[AsyncSession] = None) -> bool:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.delete_calendar_by_id(id, db=sync_db))


class CalendarEventAttendeeTable:
    def set_attendees(self, event_id: str, attendees: list[dict], db: Optional[Session] = None) -> list[CalendarEventAttendeeModel]:
        with get_db_context(db) as db:
            db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id == event_id).delete(
                synchronize_session=False
            )
            now = int(time.time_ns())
            models = []
            for att in attendees:
                row = CalendarEventAttendee(
                    id=str(uuid4()),
                    event_id=event_id,
                    user_id=att['user_id'],
                    status=att.get('status', 'pending'),
                    meta=att.get('meta'),
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                models.append(CalendarEventAttendeeModel.model_validate(row))
            db.commit()
            return models

    def update_rsvp(self, event_id: str, user_id: str, status: str, db: Optional[Session] = None) -> Optional[CalendarEventAttendeeModel]:
        with get_db_context(db) as db:
            att = db.query(CalendarEventAttendee).filter(
                CalendarEventAttendee.event_id == event_id,
                CalendarEventAttendee.user_id == user_id,
            ).first()
            if not att:
                return None
            att.status = status
            att.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(att)
            return CalendarEventAttendeeModel.model_validate(att)

    def get_attendees_by_event(self, event_id: str, db: Optional[Session] = None) -> list[CalendarEventAttendeeModel]:
        with get_db_context(db) as db:
            rows = db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id == event_id).all()
            return [CalendarEventAttendeeModel.model_validate(r) for r in rows]

    async def update_rsvp_async(
        self, event_id: str, user_id: str, status: str, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarEventAttendeeModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.update_rsvp(event_id, user_id, status, db=sync_db))


class CalendarEventTable:
    def _get_attendees(self, event_id: str, db: Optional[Session] = None) -> list[CalendarEventAttendeeModel]:
        return CalendarEventAttendees.get_attendees_by_event(event_id, db=db)

    def _to_event_model(
        self,
        event: CalendarEvent,
        attendees: Optional[list[CalendarEventAttendeeModel]] = None,
        db: Optional[Session] = None,
    ) -> CalendarEventModel:
        event_data = CalendarEventModel.model_validate(event).model_dump(exclude={'attendees'})
        event_data['attendees'] = attendees if attendees is not None else self._get_attendees(event_data['id'], db=db)
        return CalendarEventModel.model_validate(event_data)

    def insert_new_event(self, user_id: str, form_data: CalendarEventForm, db: Optional[Session] = None) -> Optional[CalendarEventModel]:
        with get_db_context(db) as db:
            now = int(time.time_ns())
            event = CalendarEvent(
                id=str(uuid4()),
                calendar_id=form_data.calendar_id,
                user_id=user_id,
                title=form_data.title,
                description=form_data.description,
                start_at=form_data.start_at,
                end_at=form_data.end_at,
                all_day=form_data.all_day,
                rrule=form_data.rrule,
                color=form_data.color,
                location=form_data.location,
                data=form_data.data,
                meta=form_data.meta,
                is_cancelled=False,
                created_at=now,
                updated_at=now,
            )
            db.add(event)
            db.commit()
            if form_data.attendees:
                CalendarEventAttendees.set_attendees(event.id, form_data.attendees, db=db)
            db.refresh(event)
            return self._to_event_model(event, db=db)

    def get_event_by_id(self, id: str, db: Optional[Session] = None) -> Optional[CalendarEventModel]:
        with get_db_context(db) as db:
            event = db.query(CalendarEvent).filter(CalendarEvent.id == id).first()
            return self._to_event_model(event, db=db) if event else None

    def get_events_by_range(
        self,
        user_id: str,
        start: int,
        end: int,
        calendar_ids: Optional[list[str]] = None,
        db: Optional[Session] = None,
    ) -> list[CalendarEventUserResponse]:
        with get_db_context(db) as db:
            user_groups = Groups.get_groups_by_member_id(user_id, db=db)
            user_group_ids = [g.id for g in user_groups]

            cal_query = db.query(Calendar.id)
            cal_query = AccessGrants.has_permission_filter(
                db=db,
                query=cal_query,
                DocumentModel=Calendar,
                filter={'user_id': user_id, 'group_ids': user_group_ids},
                resource_type='calendar',
                permission='read',
            )
            accessible_cal_ids = [r[0] for r in cal_query.all()]
            if calendar_ids:
                accessible_cal_ids = [c for c in accessible_cal_ids if c in calendar_ids]

            attendee_event_ids = [
                r[0] for r in db.query(CalendarEventAttendee.event_id).filter(CalendarEventAttendee.user_id == user_id).all()
            ]

            conditions = []
            if accessible_cal_ids:
                conditions.append(CalendarEvent.calendar_id.in_(accessible_cal_ids))
            if attendee_event_ids:
                conditions.append(CalendarEvent.id.in_(attendee_event_ids))
            if not conditions:
                return []

            items = (
                db.query(CalendarEvent, User)
                .outerjoin(User, User.id == CalendarEvent.user_id)
                .filter(
                    CalendarEvent.is_cancelled == False,  # noqa: E712
                    or_(*conditions),
                    or_(
                        (
                            CalendarEvent.rrule.is_(None)
                            & (CalendarEvent.start_at < end)
                            & or_(
                                CalendarEvent.end_at.is_(None) & (CalendarEvent.start_at >= start),
                                CalendarEvent.end_at.isnot(None) & (CalendarEvent.end_at > start),
                            )
                        ),
                        CalendarEvent.rrule.isnot(None),
                    ),
                )
                .order_by(CalendarEvent.start_at.asc())
                .all()
            )
            if not items:
                return []

            event_ids = [event.id for event, _user in items]
            att_rows = db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id.in_(event_ids)).all()
            att_map: dict[str, list[CalendarEventAttendeeModel]] = {}
            for a in att_rows:
                att_map.setdefault(a.event_id, []).append(CalendarEventAttendeeModel.model_validate(a))

            events = []
            for event, user in items:
                event_data = CalendarEventModel.model_validate(event).model_dump(exclude={'attendees'})
                event_data['attendees'] = att_map.get(event.id, [])
                events.append(
                    CalendarEventUserResponse(
                        **event_data,
                        user=(UserResponse(**UserModel.model_validate(user).model_dump()) if user else None),
                    )
                )
            return events

    def search_events(
        self,
        user_id: str,
        query: Optional[str] = None,
        skip: int = 0,
        limit: int = 30,
        db: Optional[Session] = None,
    ) -> CalendarEventListResponse:
        with get_db_context(db) as db:
            user_groups = Groups.get_groups_by_member_id(user_id, db=db)
            user_group_ids = [g.id for g in user_groups]

            cal_query = db.query(Calendar.id)
            cal_query = AccessGrants.has_permission_filter(
                db=db,
                query=cal_query,
                DocumentModel=Calendar,
                filter={'user_id': user_id, 'group_ids': user_group_ids},
                resource_type='calendar',
                permission='read',
            )
            accessible_cal_ids = [r[0] for r in cal_query.all()]
            if not accessible_cal_ids:
                return CalendarEventListResponse(items=[], total=0)

            q = (
                db.query(CalendarEvent, User)
                .outerjoin(User, User.id == CalendarEvent.user_id)
                .filter(CalendarEvent.is_cancelled == False, CalendarEvent.calendar_id.in_(accessible_cal_ids))  # noqa: E712
            )
            if query:
                search = f'%{query}%'
                q = q.filter(
                    or_(
                        CalendarEvent.title.ilike(search),
                        CalendarEvent.description.ilike(search),
                        CalendarEvent.location.ilike(search),
                    )
                )

            total = q.count()
            items = q.order_by(CalendarEvent.start_at.desc()).offset(skip).limit(limit).all()
            if not items:
                return CalendarEventListResponse(items=[], total=total)

            event_ids = [event.id for event, _user in items]
            att_rows = db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id.in_(event_ids)).all()
            att_map: dict[str, list[CalendarEventAttendeeModel]] = {}
            for a in att_rows:
                att_map.setdefault(a.event_id, []).append(CalendarEventAttendeeModel.model_validate(a))

            events = []
            for event, user in items:
                event_data = CalendarEventModel.model_validate(event).model_dump(exclude={'attendees'})
                event_data['attendees'] = att_map.get(event.id, [])
                events.append(
                    CalendarEventUserResponse(
                        **event_data,
                        user=(UserResponse(**UserModel.model_validate(user).model_dump()) if user else None),
                    )
                )
            return CalendarEventListResponse(items=events, total=total)

    def update_event_by_id(self, id: str, form_data: CalendarEventUpdateForm, db: Optional[Session] = None) -> Optional[CalendarEventModel]:
        with get_db_context(db) as db:
            event = db.query(CalendarEvent).filter(CalendarEvent.id == id).first()
            if not event:
                return None

            update_data = form_data.model_dump(exclude_unset=True)
            for field in [
                'calendar_id',
                'title',
                'description',
                'start_at',
                'end_at',
                'all_day',
                'rrule',
                'color',
                'location',
                'is_cancelled',
            ]:
                if field in update_data:
                    setattr(event, field, update_data[field])

            if 'data' in update_data and update_data['data'] is not None:
                event.data = {**(event.data or {}), **update_data['data']}
            if 'meta' in update_data and update_data['meta'] is not None:
                event.meta = {**(event.meta or {}), **update_data['meta']}
            if 'attendees' in update_data and update_data['attendees'] is not None:
                CalendarEventAttendees.set_attendees(id, update_data['attendees'], db=db)

            event.updated_at = int(time.time_ns())
            db.commit()
            db.refresh(event)
            return self._to_event_model(event, db=db)

    def delete_event_by_id(self, id: str, db: Optional[Session] = None) -> bool:
        try:
            with get_db_context(db) as db:
                db.query(CalendarEventAttendee).filter(CalendarEventAttendee.event_id == id).delete(
                    synchronize_session=False
                )
                db.query(CalendarEvent).filter(CalendarEvent.id == id).delete(synchronize_session=False)
                db.commit()
                return True
        except Exception:
            return False

    async def insert_new_event_async(
        self, user_id: str, form_data: CalendarEventForm, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarEventModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.insert_new_event(user_id, form_data, db=sync_db))

    async def get_event_by_id_async(self, id: str, db: Optional[AsyncSession] = None) -> Optional[CalendarEventModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.get_event_by_id(id, db=sync_db))

    async def get_events_by_range_async(
        self,
        user_id: str,
        start: int,
        end: int,
        calendar_ids: Optional[list[str]] = None,
        db: Optional[AsyncSession] = None,
    ) -> list[CalendarEventUserResponse]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(
                lambda sync_db: self.get_events_by_range(
                    user_id=user_id,
                    start=start,
                    end=end,
                    calendar_ids=calendar_ids,
                    db=sync_db,
                )
            )

    async def search_events_async(
        self,
        user_id: str,
        query: Optional[str] = None,
        skip: int = 0,
        limit: int = 30,
        db: Optional[AsyncSession] = None,
    ) -> CalendarEventListResponse:
        async with get_async_db_context(db) as db:
            return await db.run_sync(
                lambda sync_db: self.search_events(
                    user_id=user_id,
                    query=query,
                    skip=skip,
                    limit=limit,
                    db=sync_db,
                )
            )

    async def update_event_by_id_async(
        self, id: str, form_data: CalendarEventUpdateForm, db: Optional[AsyncSession] = None
    ) -> Optional[CalendarEventModel]:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.update_event_by_id(id, form_data, db=sync_db))

    async def delete_event_by_id_async(self, id: str, db: Optional[AsyncSession] = None) -> bool:
        async with get_async_db_context(db) as db:
            return await db.run_sync(lambda sync_db: self.delete_event_by_id(id, db=sync_db))


Calendars = CalendarTable()
CalendarEvents = CalendarEventTable()
CalendarEventAttendees = CalendarEventAttendeeTable()
