from open_webui.utils.retrieval_jobs import (
    RETRIEVAL_JOB_PAYLOAD_VERSION,
    build_retrieval_job,
    build_retrieval_job_record,
    get_retrieval_job_reply_subject,
)


def test_build_retrieval_job_uses_expected_contract_shape():
    job = build_retrieval_job(
        actor_id='user-1',
        resource_id='file-1',
        job_id='job-1',
        payload={
            'file_id': 'file-1',
            'collection_name': 'file-file-1',
        },
    )

    assert job == {
        'job_id': 'job-1',
        'tenant_id': None,
        'actor_id': 'user-1',
        'resource_id': 'file-1',
        'requested_at': job['requested_at'],
        'reply_to': 'owui.evt.retrieval.job.job-1',
        'trace_id': None,
        'payload_version': RETRIEVAL_JOB_PAYLOAD_VERSION,
        'payload': {
            'file_id': 'file-1',
            'collection_name': 'file-file-1',
        },
    }


def test_build_retrieval_job_record_preserves_envelope_and_status():
    job = build_retrieval_job(
        actor_id='user-1',
        resource_id='file-1',
        job_id='job-1',
        payload={'file_id': 'file-1'},
    )

    record = build_retrieval_job_record(job, status='completed', document_count=3)

    assert record['job_id'] == 'job-1'
    assert record['status'] == 'completed'
    assert record['document_count'] == 3
    assert record['requested_at'] == job['requested_at']
    assert record['payload_version'] == job['payload_version']


def test_get_retrieval_job_reply_subject_is_partitioned_by_job_id():
    assert get_retrieval_job_reply_subject('job-123') == 'owui.evt.retrieval.job.job-123'
