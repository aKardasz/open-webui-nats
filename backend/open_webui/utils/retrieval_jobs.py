import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from open_webui.env import RETRIEVAL_JOB_SIGNING_SECRET


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
    job = {
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
    job['signature'] = sign_retrieval_job(job)
    return job


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


def sign_retrieval_job(job: dict) -> str:
    signing_secret = RETRIEVAL_JOB_SIGNING_SECRET.encode('utf-8')
    return hmac.new(signing_secret, _canonical_retrieval_job_payload(job).encode('utf-8'), hashlib.sha256).hexdigest()


def verify_retrieval_job(job: dict) -> bool:
    signature = job.get('signature')
    if not signature:
        return False
    expected = sign_retrieval_job({key: value for key, value in job.items() if key != 'signature'})
    return hmac.compare_digest(signature, expected)


def _canonical_retrieval_job_payload(job: dict) -> str:
    payload = {key: value for key, value in job.items() if key != 'signature'}
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
