from typing import Optional

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from open_webui.models.files import FileModel
from open_webui.utils.retrieval_transport import RetrievalSubmissionTransport, get_retrieval_transport


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
    transport = transport or get_retrieval_transport(request)
    return transport.submit_file_job(
        request,
        file_item=file_item,
        user_id=user_id,
        command=command,
        background_tasks=background_tasks,
        db=db,
    )
