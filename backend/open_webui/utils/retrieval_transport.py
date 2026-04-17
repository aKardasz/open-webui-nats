import logging
from typing import Optional, Protocol

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.orm import Session

from open_webui.env import NATS_URL, RETRIEVAL_TRANSPORT
from open_webui.models.files import FileModel, Files
from open_webui.models.users import Users
from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.retrieval_execution import execute_retrieval_job
from open_webui.utils.retrieval_jobs import build_retrieval_job, build_retrieval_job_record
from open_webui.utils.retrieval_worker import publish_retrieval_job_sync
from open_webui.utils.task_messaging import (
    RETRIEVAL_JOB_QUEUED_SUBJECT,
    build_domain_event,
    publish_app_event_sync,
)

log = logging.getLogger(__name__)


class RetrievalSubmissionTransport(Protocol):
    def submit_file_job(
        self,
        request,
        *,
        file_item: FileModel,
        user_id: str,
        command: dict,
        background_tasks: Optional[BackgroundTasks] = None,
        db: Optional[Session] = None,
    ) -> tuple[FileModel, dict]: ...


class LocalRetrievalTransport:
    def submit_file_job(
        self,
        request,
        *,
        file_item: FileModel,
        user_id: str,
        command: dict,
        background_tasks: Optional[BackgroundTasks] = None,
        db: Optional[Session] = None,
    ) -> tuple[FileModel, dict]:
        _authorize_submission(file_item, user_id)
        retrieval_job = build_retrieval_job(
            actor_id=user_id,
            resource_id=file_item.id,
            payload=command,
        )

        queued_file = (
            Files.update_file_data_by_id(
                file_item.id,
                {
                    'status': 'pending',
                    'retrieval_job': build_retrieval_job_record(retrieval_job, status='queued'),
                },
                db=db,
            )
            or file_item
        )

        publish_app_event_sync(
            request.app,
            RETRIEVAL_JOB_QUEUED_SUBJECT,
            build_domain_event(
                event_type='retrieval.job.queued',
                resource_type='retrieval_job',
                resource_id=retrieval_job['job_id'],
                data={
                    'job_id': retrieval_job['job_id'],
                    'file_id': queued_file.id,
                    'status': 'queued',
                    'processing_mode': command.get('processing_mode'),
                },
            ),
        )

        if background_tasks is not None and command.get('processing_mode') == 'background_task':
            background_tasks.add_task(execute_retrieval_job, request, retrieval_job)
            return queued_file, retrieval_job

        execute_retrieval_job(request, retrieval_job, db=db)
        return Files.get_file_by_id(file_item.id, db=db) or queued_file, retrieval_job


class JetStreamRetrievalTransport:
    def __init__(self, nats_url: str = ''):
        self.nats_url = nats_url

    def submit_file_job(
        self,
        request,
        *,
        file_item: FileModel,
        user_id: str,
        command: dict,
        background_tasks: Optional[BackgroundTasks] = None,
        db: Optional[Session] = None,
    ) -> tuple[FileModel, dict]:
        _authorize_submission(file_item, user_id)
        retrieval_job = build_retrieval_job(
            actor_id=user_id,
            resource_id=file_item.id,
            payload={
                **command,
                'delivery_mode': 'jetstream',
            },
        )

        queued_file = (
            Files.update_file_data_by_id(
                file_item.id,
                {
                    'status': 'pending',
                    'retrieval_job': build_retrieval_job_record(retrieval_job, status='queued'),
                },
                db=db,
            )
            or file_item
        )

        publish_app_event_sync(
            request.app,
            RETRIEVAL_JOB_QUEUED_SUBJECT,
            build_domain_event(
                event_type='retrieval.job.queued',
                resource_type='retrieval_job',
                resource_id=retrieval_job['job_id'],
                data={
                    'job_id': retrieval_job['job_id'],
                    'file_id': queued_file.id,
                    'status': 'queued',
                    'processing_mode': retrieval_job['payload'].get('processing_mode'),
                    'delivery_mode': 'jetstream',
                },
            ),
        )

        if not self.nats_url:
            log.warning(
                'RETRIEVAL_TRANSPORT=jetstream selected without NATS_URL; '
                'falling back to local execution for retrieval job %s.',
                retrieval_job['job_id'],
            )
            return _execute_retrieval_job_locally(
                request,
                file_item=file_item,
                retrieval_job=retrieval_job,
                background_tasks=background_tasks,
                db=db,
                queued_file=queued_file,
            )

        try:
            publish_retrieval_job_sync(request.app, self.nats_url, retrieval_job)
            return queued_file, retrieval_job
        except Exception:
            log.exception(
                'JetStream retrieval submission failed for job %s; falling back to local execution.',
                retrieval_job['job_id'],
            )
            return _execute_retrieval_job_locally(
                request,
                file_item=file_item,
                retrieval_job=retrieval_job,
                background_tasks=background_tasks,
                db=db,
                queued_file=queued_file,
            )


def build_retrieval_transport(transport_name: str, nats_url: str) -> RetrievalSubmissionTransport:
    if transport_name == 'jetstream':
        return JetStreamRetrievalTransport(nats_url=nats_url)
    return LocalRetrievalTransport()


def get_retrieval_transport(request) -> RetrievalSubmissionTransport:
    return getattr(request.app.state, 'retrieval_transport', None) or LocalRetrievalTransport()


def _authorize_submission(file_item: FileModel, user_id: str) -> None:
    user = Users.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )
    if user.role != 'admin' and file_item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )


def _execute_retrieval_job_locally(
    request,
    *,
    file_item: FileModel,
    retrieval_job: dict,
    background_tasks: Optional[BackgroundTasks] = None,
    db: Optional[Session] = None,
    queued_file: Optional[FileModel] = None,
) -> tuple[FileModel, dict]:
    if background_tasks is not None and retrieval_job['payload'].get('processing_mode') == 'background_task':
        background_tasks.add_task(execute_retrieval_job, request, retrieval_job)
        return queued_file or file_item, retrieval_job

    execute_retrieval_job(request, retrieval_job, db=db)
    return Files.get_file_by_id(file_item.id, db=db) or queued_file or file_item, retrieval_job
