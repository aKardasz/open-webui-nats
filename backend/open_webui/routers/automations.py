import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import AsyncSessionLocal, get_async_session, get_db_context
from open_webui.models.automations import (
    AutomationForm,
    AutomationListResponse,
    AutomationResponse,
    AutomationRunModel,
    AutomationRuns,
    Automations,
)
from open_webui.utils.access_control import has_permission
from open_webui.utils.auth import get_verified_user
from open_webui.utils.automations import (
    next_n_runs_ns,
    next_run_ns,
    rrule_interval_seconds,
    validate_rrule,
)
from open_webui.utils.automation_runner import request_automation_run

log = logging.getLogger(__name__)

router = APIRouter()
PAGE_ITEM_COUNT = 30
AutomationDbSession = AsyncSession | Session


def _is_async_db(db) -> bool:
    return isinstance(db, AsyncSession)


async def get_automation_session():
    if AsyncSessionLocal is None:
        with get_db_context() as db:
            yield db
        return

    async for db in get_async_session():
        yield db


def check_automations_permission(request, user):
    if not getattr(request.app.state.config, 'ENABLE_AUTOMATIONS', False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.UNAUTHORIZED)
    if user.role != 'admin' and not has_permission(
        user.id, 'features.automations', request.app.state.config.USER_PERMISSIONS
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.UNAUTHORIZED)


def check_automation_access(automation, user):
    if not automation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_MESSAGES.NOT_FOUND)
    if user.role != 'admin' and user.id != automation.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ERROR_MESSAGES.UNAUTHORIZED)


async def check_automation_limits(request, user, rrule_str: str, db, is_create: bool = False):
    if user.role == 'admin':
        return

    if is_create:
        max_count = getattr(request.app.state.config, 'AUTOMATION_MAX_COUNT', '')
        if max_count:
            max_count = int(max_count)
            current_count = (
                await Automations.count_by_user_async(user.id, db=db)
                if _is_async_db(db)
                else Automations.count_by_user(user.id, db=db)
            )
            if max_count > 0 and current_count >= max_count:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=ERROR_MESSAGES.AUTOMATION_LIMIT_EXCEEDED(max_count),
                )

    min_interval = getattr(request.app.state.config, 'AUTOMATION_MIN_INTERVAL', '')
    if min_interval:
        min_interval = int(min_interval)
        if min_interval > 0:
            interval = rrule_interval_seconds(rrule_str)
            if interval is not None and interval < min_interval:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_MESSAGES.AUTOMATION_TOO_FREQUENT(min_interval),
                )


async def enrich_automation(automation, db, tz: str = None) -> AutomationResponse:
    last_run = (
        await AutomationRuns.get_latest_async(automation.id, db=db)
        if _is_async_db(db)
        else AutomationRuns.get_latest(automation.id, db=db)
    )
    return AutomationResponse(
        **automation.model_dump(),
        last_run=last_run,
        next_runs=next_n_runs_ns(automation.data['rrule'], tz=tz),
    )


@router.get('/list')
async def get_automation_items(
    request: Request,
    query: Optional[str] = None,
    status: Optional[str] = None,
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    limit = PAGE_ITEM_COUNT
    page = max(1, page)
    skip = (page - 1) * limit

    result: AutomationListResponse = (
        await Automations.search_automations_async(
            user_id=user.id,
            query=query,
            status=status,
            skip=skip,
            limit=limit,
            db=db,
        )
        if _is_async_db(db)
        else Automations.search_automations(
            user_id=user.id,
            query=query,
            status=status,
            skip=skip,
            limit=limit,
            db=db,
        )
    )
    ids = [item.id for item in result.items]
    latest_runs = (
        await AutomationRuns.get_latest_batch_async(ids, db=db)
        if ids and _is_async_db(db)
        else (AutomationRuns.get_latest_batch(ids, db=db) if ids else {})
    )

    return {
        'items': [
            AutomationResponse(**item.model_dump(), last_run=latest_runs.get(item.id))
            for item in result.items
        ],
        'total': result.total,
    }


@router.post('/create', response_model=AutomationResponse)
async def create_new_automation(
    request: Request,
    form_data: AutomationForm,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    validate_rrule(form_data.data.rrule, tz=user.timezone)
    await check_automation_limits(request, user, form_data.data.rrule, db, is_create=True)
    automation = (
        await Automations.insert_async(user.id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
        if _is_async_db(db)
        else Automations.insert(user.id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
    )
    return await enrich_automation(automation, db, tz=user.timezone)


@router.get('/{id}', response_model=AutomationResponse)
async def get_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    return await enrich_automation(automation, db, tz=user.timezone)


@router.post('/{id}/update', response_model=AutomationResponse)
async def update_automation_by_id(
    request: Request,
    id: str,
    form_data: AutomationForm,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    validate_rrule(form_data.data.rrule, tz=user.timezone)
    await check_automation_limits(request, user, form_data.data.rrule, db, is_create=False)
    updated = (
        await Automations.update_by_id_async(id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
        if _is_async_db(db)
        else Automations.update_by_id(id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
    )
    return await enrich_automation(updated, db, tz=user.timezone)


@router.post('/{id}/toggle', response_model=AutomationResponse)
async def toggle_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    toggled = (
        await Automations.toggle_async(id, next_run_ns(automation.data['rrule'], tz=user.timezone), db=db)
        if _is_async_db(db)
        else Automations.toggle(id, next_run_ns(automation.data['rrule'], tz=user.timezone), db=db)
    )
    return await enrich_automation(toggled, db, tz=user.timezone)


@router.post('/{id}/run')
async def run_automation_by_id(
    request: Request,
    id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    try:
        execution = await request_automation_run(request.app, automation, background_tasks=background_tasks)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return {
        'automation': await enrich_automation(automation, db, tz=user.timezone),
        'execution': execution,
    }


@router.delete('/{id}/delete')
async def delete_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    if _is_async_db(db):
        await AutomationRuns.delete_by_automation_async(id, db=db)
        return await Automations.delete_async(id, db=db)
    AutomationRuns.delete_by_automation(id, db=db)
    return Automations.delete(id, db=db)


@router.get('/{id}/runs', response_model=list[AutomationRunModel])
async def get_automation_runs(
    request: Request,
    id: str,
    skip: int = 0,
    limit: int = 50,
    user=Depends(get_verified_user),
    db: AutomationDbSession = Depends(get_automation_session),
):
    check_automations_permission(request, user)
    automation = (
        await Automations.get_by_id_async(id, db=db)
        if _is_async_db(db)
        else Automations.get_by_id(id, db=db)
    )
    check_automation_access(automation, user)
    return (
        await AutomationRuns.get_by_automation_async(id, skip=skip, limit=limit, db=db)
        if _is_async_db(db)
        else AutomationRuns.get_by_automation(id, skip=skip, limit=limit, db=db)
    )
