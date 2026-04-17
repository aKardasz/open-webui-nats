from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_transport import (
    LocalRetrievalTransport,
    RetrievalSubmissionTransport,
    get_retrieval_transport,
)


def resolve_retrieval_transport(
    request,
    *,
    command: dict,
    transport: Optional[RetrievalSubmissionTransport] = None,
) -> RetrievalSubmissionTransport:
    # Inline flows still depend on synchronous completion semantics, so they
    # stay local until worker-backed behavior is explicitly designed.
    if command.get('processing_mode') == 'inline':
        return LocalRetrievalTransport()

    if transport is not None:
        return transport

    return get_retrieval_transport(request)


def submit_file_retrieval(
    request,
    *,
    file_item: FileModel,
    user_id: str,
    command: dict,
    background_tasks: Optional[BackgroundTasks] = None,
    db: Optional[Session] = None,
    transport: Optional[RetrievalSubmissionTransport] = None,
) -> tuple[FileModel, dict]:
    transport = resolve_retrieval_transport(
        request,
        command=command,
        transport=transport,
    )
    return transport.submit_file_job(
        request,
        file_item=file_item,
        user_id=user_id,
        command=command,
        background_tasks=background_tasks,
        db=db,
    )
