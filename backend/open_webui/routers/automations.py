import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from open_webui.constants import ERROR_MESSAGES
from open_webui.internal.db import get_session
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
    execute_automation,
    next_n_runs_ns,
    next_run_ns,
    rrule_interval_seconds,
    validate_rrule,
)

log = logging.getLogger(__name__)

router = APIRouter()
PAGE_ITEM_COUNT = 30


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


def check_automation_limits(request, user, rrule_str: str, db, is_create: bool = False):
    if user.role == 'admin':
        return

    if is_create:
        max_count = getattr(request.app.state.config, 'AUTOMATION_MAX_COUNT', '')
        if max_count:
            max_count = int(max_count)
            if max_count > 0 and Automations.count_by_user(user.id, db=db) >= max_count:
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


def enrich_automation(automation, db, tz: str = None) -> AutomationResponse:
    last_run = AutomationRuns.get_latest(automation.id, db=db)
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
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    limit = PAGE_ITEM_COUNT
    page = max(1, page)
    skip = (page - 1) * limit

    result: AutomationListResponse = Automations.search_automations(
        user_id=user.id,
        query=query,
        status=status,
        skip=skip,
        limit=limit,
        db=db,
    )
    ids = [item.id for item in result.items]
    latest_runs = AutomationRuns.get_latest_batch(ids, db=db) if ids else {}

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
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    validate_rrule(form_data.data.rrule, tz=user.timezone)
    check_automation_limits(request, user, form_data.data.rrule, db, is_create=True)
    automation = Automations.insert(user.id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
    return enrich_automation(automation, db, tz=user.timezone)


@router.get('/{id}', response_model=AutomationResponse)
async def get_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    return enrich_automation(automation, db, tz=user.timezone)


@router.post('/{id}/update', response_model=AutomationResponse)
async def update_automation_by_id(
    request: Request,
    id: str,
    form_data: AutomationForm,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    validate_rrule(form_data.data.rrule, tz=user.timezone)
    check_automation_limits(request, user, form_data.data.rrule, db, is_create=False)
    updated = Automations.update_by_id(id, form_data, next_run_ns(form_data.data.rrule, tz=user.timezone), db=db)
    return enrich_automation(updated, db, tz=user.timezone)


@router.post('/{id}/toggle', response_model=AutomationResponse)
async def toggle_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    toggled = Automations.toggle(id, next_run_ns(automation.data['rrule'], tz=user.timezone), db=db)
    return enrich_automation(toggled, db, tz=user.timezone)


@router.post('/{id}/run')
async def run_automation_by_id(
    request: Request,
    id: str,
    background_tasks: BackgroundTasks,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    background_tasks.add_task(execute_automation, request.app, automation)
    return enrich_automation(automation, db, tz=user.timezone)


@router.delete('/{id}/delete')
async def delete_automation_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    AutomationRuns.delete_by_automation(id, db=db)
    return Automations.delete(id, db=db)


@router.get('/{id}/runs', response_model=list[AutomationRunModel])
async def get_automation_runs(
    request: Request,
    id: str,
    skip: int = 0,
    limit: int = 50,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    check_automations_permission(request, user)
    automation = Automations.get_by_id(id, db=db)
    check_automation_access(automation, user)
    return AutomationRuns.get_by_automation(id, skip=skip, limit=limit, db=db)
