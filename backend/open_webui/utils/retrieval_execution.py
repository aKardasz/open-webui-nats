import logging
from typing import Optional

from sqlalchemy.orm import Session

from open_webui.internal.db import SessionLocal
from open_webui.models.files import Files
from open_webui.models.users import Users
from open_webui.routers.audio import transcribe
from open_webui.storage.provider import Storage
from open_webui.utils.misc import strict_match_mime_type
from open_webui.utils.retrieval_jobs import build_retrieval_job_record
from open_webui.utils.retrieval_service import ProcessFileForm, process_file as process_file_service
from open_webui.utils.task_messaging import (
    RETRIEVAL_JOB_FAILED_SUBJECT,
    build_domain_event,
    publish_app_event_sync,
)

log = logging.getLogger(__name__)


def execute_retrieval_job(request, retrieval_job: dict, db: Optional[Session] = None):
    def _execute(db_session: Session):
        payload = retrieval_job.get('payload', {})
        file_item = None
        processing_started = False
        try:
            command_type = payload.get('command_type')
            if command_type != 'process_file':
                raise ValueError(f'Unsupported retrieval command type: {command_type}')

            file_item = Files.get_file_by_id(payload['file_id'], db=db_session)
            if not file_item:
                raise ValueError(f"File not found for retrieval command: {payload['file_id']}")

            if _is_completed_duplicate(file_item, retrieval_job['job_id']):
                log.info('Skipping duplicate completed retrieval job %s for file %s', retrieval_job['job_id'], file_item.id)
                return

            user = Users.get_user_by_id(retrieval_job['actor_id'])
            if user is None:
                raise ValueError(f"User not found for retrieval job: {retrieval_job['actor_id']}")

            inline_content = payload.get('inline_content')
            collection_name = payload.get('collection_name')

            if inline_content is not None:
                processing_started = True
                process_file_service(
                    request,
                    ProcessFileForm(
                        file_id=file_item.id,
                        content=inline_content,
                        collection_name=collection_name,
                        job_id=retrieval_job['job_id'],
                    ),
                    user=user,
                    db=db_session,
                )
                return

            content_type = payload.get('content_type')
            if content_type and content_type.startswith(('image/', 'video/')):
                if _is_text_file(file_item.path):
                    content_type = 'text/plain'

            if content_type:
                stt_supported_content_types = getattr(request.app.state.config, 'STT_SUPPORTED_CONTENT_TYPES', [])
                if strict_match_mime_type(stt_supported_content_types, content_type):
                    file_path_processed = Storage.get_file(file_item.path)
                    file_metadata = file_item.meta.get('data', {}) if file_item.meta else {}
                    result = transcribe(request, file_path_processed, file_metadata, user)

                    processing_started = True
                    process_file_service(
                        request,
                        ProcessFileForm(
                            file_id=file_item.id,
                            content=result.get('text', ''),
                            job_id=retrieval_job['job_id'],
                        ),
                        user=user,
                        db=db_session,
                    )
                    return

                if (not content_type.startswith(('image/', 'video/'))) or (
                    request.app.state.config.CONTENT_EXTRACTION_ENGINE == 'external'
                ):
                    processing_started = True
                    process_file_service(
                        request,
                        ProcessFileForm(
                            file_id=file_item.id,
                            collection_name=collection_name,
                            job_id=retrieval_job['job_id'],
                        ),
                        user=user,
                        db=db_session,
                    )
                    return

                raise Exception(f'File type {content_type} is not supported for processing')

            log.info(f'File type for {file_item.id} is not provided, but trying to process anyway')
            processing_started = True
            process_file_service(
                request,
                ProcessFileForm(
                    file_id=file_item.id,
                    collection_name=collection_name,
                    job_id=retrieval_job['job_id'],
                ),
                user=user,
                db=db_session,
            )

        except Exception as e:
            file_id = file_item.id if file_item is not None else payload.get('file_id')
            log.error(f'Error processing retrieval job for file: {file_id}')
            if file_item is not None:
                Files.update_file_data_by_id(
                    file_item.id,
                    {
                        'status': 'failed',
                        'retrieval_job': build_retrieval_job_record(
                            retrieval_job,
                            status='failed',
                            error=(str(e.detail) if hasattr(e, 'detail') else str(e)),
                        ),
                        'error': str(e.detail) if hasattr(e, 'detail') else str(e),
                    },
                    db=db_session,
                )
            if not processing_started:
                publish_app_event_sync(
                    request.app,
                    RETRIEVAL_JOB_FAILED_SUBJECT,
                    build_domain_event(
                        event_type='retrieval.job.failed',
                        resource_type='retrieval_job',
                        resource_id=retrieval_job['job_id'],
                        data={
                            'job_id': retrieval_job['job_id'],
                            'file_id': file_id,
                            'collection_name': payload.get('collection_name') or f'file-{file_id}',
                            'status': 'failed',
                            'error_code': 'retrieval_failed',
                        },
                    ),
                )
            if payload.get('processing_mode') == 'inline' or payload.get('delivery_mode') == 'jetstream':
                raise

    if db is not None:
        _execute(db)
    else:
        with SessionLocal() as db_session:
            _execute(db_session)


def _is_completed_duplicate(file_item, job_id: str) -> bool:
    existing_job = file_item.data.get('retrieval_job') if file_item.data else None
    if not existing_job:
        return False
    return existing_job.get('job_id') == job_id and existing_job.get('status') == 'completed'


def _is_text_file(file_path: str, chunk_size: int = 8192) -> bool:
    try:
        resolved = Storage.get_file(file_path)
        with open(resolved, 'rb') as f:
            chunk = f.read(chunk_size)
        if not chunk:
            return False
        if b'\x00' in chunk:
            return False
        chunk.decode('utf-8')
        return True
    except (UnicodeDecodeError, Exception):
        return False
