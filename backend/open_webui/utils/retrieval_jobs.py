from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


RETRIEVAL_JOB_PAYLOAD_VERSION = 'v1'


def build_retrieval_job(
    *,
    actor_id: str,
    resource_id: str,
    payload: dict,
    tenant_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    job_id: Optional[str] = None,
    requested_at: Optional[str] = None,
    payload_version: str = RETRIEVAL_JOB_PAYLOAD_VERSION,
) -> dict:
    resolved_job_id = job_id or f'job_{uuid4().hex}'
    return {
        'job_id': resolved_job_id,
        'tenant_id': tenant_id,
        'actor_id': actor_id,
        'resource_id': resource_id,
        'requested_at': requested_at or _utc_now(),
        'reply_to': get_retrieval_job_reply_subject(resolved_job_id),
        'trace_id': trace_id,
        'payload_version': payload_version,
        'payload': payload,
    }


def build_retrieval_job_record(job: dict, *, status: str, error: Optional[str] = None, **extra) -> dict:
    return {
        'job_id': job['job_id'],
        'requested_at': job['requested_at'],
        'payload_version': job['payload_version'],
        'status': status,
        **{key: value for key, value in extra.items() if value is not None},
        **({'error': error} if error is not None else {}),
    }


def get_retrieval_job_reply_subject(job_id: str) -> str:
    return f'owui.evt.retrieval.job.{job_id}'


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
