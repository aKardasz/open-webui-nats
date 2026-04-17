import asyncio
import logging
import uuid
from typing import Optional

import tiktoken
from fastapi import Request, status
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
    TokenTextSplitter,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session

from open_webui.config import RAG_EMBEDDING_CONTENT_PREFIX
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import RAG_EMBEDDING_TIMEOUT
from open_webui.internal.db import get_db
from open_webui.models.files import FileModel, Files
from open_webui.retrieval.loaders.main import Loader
from open_webui.retrieval.utils import get_embedding_function
from open_webui.retrieval.vector.factory import VECTOR_DB_CLIENT
from open_webui.retrieval.vector.utils import filter_metadata
from open_webui.storage.provider import Storage
from open_webui.utils.misc import calculate_sha256_string, sanitize_text_for_db
from open_webui.utils.retrieval_commands import build_process_file_command
from open_webui.utils.retrieval_jobs import build_retrieval_job, build_retrieval_job_record
from open_webui.utils.task_messaging import (
    RETRIEVAL_JOB_COMPLETED_SUBJECT,
    RETRIEVAL_JOB_FAILED_SUBJECT,
    RETRIEVAL_JOB_PROGRESS_SUBJECT,
    RETRIEVAL_JOB_STARTED_SUBJECT,
    build_domain_event,
    publish_app_event_sync,
)

log = logging.getLogger(__name__)


class RetrievalServiceError(Exception):
    def __init__(self, detail: str, *, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class ProcessFileForm(BaseModel):
    file_id: str
    content: Optional[str] = None
    collection_name: Optional[str] = None
    job_id: Optional[str] = None


def can_merge_chunks(a: Document, b: Document) -> bool:
    if a.metadata.get('source') != b.metadata.get('source'):
        return False

    a_file_id = a.metadata.get('file_id')
    b_file_id = b.metadata.get('file_id')

    if a_file_id is not None and b_file_id is not None:
        return a_file_id == b_file_id

    return True


def merge_docs_to_target_size(
    request: Request,
    chunks: list[Document],
) -> list[Document]:
    min_chunk_size_target = request.app.state.config.CHUNK_MIN_SIZE_TARGET
    max_chunk_size = request.app.state.config.CHUNK_SIZE

    if min_chunk_size_target <= 0:
        return chunks

    measure_chunk_size = len
    if request.app.state.config.TEXT_SPLITTER == 'token':
        encoding = tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
        measure_chunk_size = lambda text: len(encoding.encode(text))

    processed_chunks: list[Document] = []
    current_chunk: Document | None = None
    current_content = ''

    for next_chunk in chunks:
        if current_chunk is None:
            current_chunk = next_chunk
            current_content = next_chunk.page_content
            continue

        proposed_content = f'{current_content}\n\n{next_chunk.page_content}'
        can_merge = (
            can_merge_chunks(current_chunk, next_chunk)
            and measure_chunk_size(current_content) < min_chunk_size_target
            and measure_chunk_size(proposed_content) <= max_chunk_size
        )

        if can_merge:
            current_content = proposed_content
            continue

        processed_chunks.append(
            Document(
                page_content=current_content,
                metadata={**current_chunk.metadata},
            )
        )
        current_chunk = next_chunk
        current_content = next_chunk.page_content

    if current_chunk is not None:
        processed_chunks.append(
            Document(
                page_content=current_content,
                metadata={**current_chunk.metadata},
            )
        )

    return processed_chunks


def save_docs_to_vector_db(
    request: Request,
    docs,
    collection_name,
    metadata: Optional[dict] = None,
    overwrite: bool = False,
    split: bool = True,
    add: bool = False,
    user=None,
) -> bool:
    def _get_docs_info(docs: list[Document]) -> str:
        docs_info = set()

        for doc in docs:
            doc_metadata = getattr(doc, 'metadata', {})
            doc_name = doc_metadata.get('name', '')
            if not doc_name:
                doc_name = doc_metadata.get('title', '')
            if not doc_name:
                doc_name = doc_metadata.get('source', '')
            if doc_name:
                docs_info.add(doc_name)

        return ', '.join(docs_info)

    log.debug(f'save_docs_to_vector_db: document {_get_docs_info(docs)} {collection_name}')

    if metadata and 'hash' in metadata:
        result = VECTOR_DB_CLIENT.query(
            collection_name=collection_name,
            filter={'hash': metadata['hash']},
        )

        if result is not None and result.ids and len(result.ids) > 0:
            existing_doc_ids = result.ids[0]
            if existing_doc_ids:
                existing_file_id = None
                if result.metadatas and result.metadatas[0]:
                    existing_file_id = result.metadatas[0][0].get('file_id')

                if existing_file_id != metadata.get('file_id'):
                    log.info(f'Document with hash {metadata["hash"]} already exists')
                    raise ValueError(ERROR_MESSAGES.DUPLICATE_CONTENT)

    if split:
        if request.app.state.config.ENABLE_MARKDOWN_HEADER_TEXT_SPLITTER:
            log.info('Using markdown header text splitter')
            markdown_splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=[
                    ('#', 'Header 1'),
                    ('##', 'Header 2'),
                    ('###', 'Header 3'),
                    ('####', 'Header 4'),
                    ('#####', 'Header 5'),
                    ('######', 'Header 6'),
                ],
                strip_headers=False,
            )

            split_docs = []
            for doc in docs:
                split_docs.extend(
                    [
                        Document(
                            page_content=split_chunk.page_content,
                            metadata={**doc.metadata},
                        )
                        for split_chunk in markdown_splitter.split_text(doc.page_content)
                    ]
                )

            docs = split_docs
            if request.app.state.config.CHUNK_MIN_SIZE_TARGET > 0:
                docs = merge_docs_to_target_size(request, docs)

        if request.app.state.config.TEXT_SPLITTER in ['', 'character']:
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=request.app.state.config.CHUNK_SIZE,
                chunk_overlap=request.app.state.config.CHUNK_OVERLAP,
                add_start_index=True,
            )
            docs = text_splitter.split_documents(docs)
        elif request.app.state.config.TEXT_SPLITTER == 'token':
            log.info(f'Using token text splitter: {request.app.state.config.TIKTOKEN_ENCODING_NAME}')
            tiktoken.get_encoding(str(request.app.state.config.TIKTOKEN_ENCODING_NAME))
            text_splitter = TokenTextSplitter(
                encoding_name=str(request.app.state.config.TIKTOKEN_ENCODING_NAME),
                chunk_size=request.app.state.config.CHUNK_SIZE,
                chunk_overlap=request.app.state.config.CHUNK_OVERLAP,
                add_start_index=True,
            )
            docs = text_splitter.split_documents(docs)
        else:
            raise ValueError(ERROR_MESSAGES.DEFAULT('Invalid text splitter'))

    if len(docs) == 0:
        raise ValueError(ERROR_MESSAGES.EMPTY_CONTENT)

    texts = [sanitize_text_for_db(doc.page_content) for doc in docs]
    metadatas = [
        {
            **doc.metadata,
            **(metadata if metadata else {}),
            'embedding_config': {
                'engine': request.app.state.config.RAG_EMBEDDING_ENGINE,
                'model': request.app.state.config.RAG_EMBEDDING_MODEL,
            },
        }
        for doc in docs
    ]

    try:
        if VECTOR_DB_CLIENT.has_collection(collection_name=collection_name):
            log.info(f'collection {collection_name} already exists')

            if overwrite:
                VECTOR_DB_CLIENT.delete_collection(collection_name=collection_name)
                log.info(f'deleting existing collection {collection_name}')
            elif add is False:
                log.info(f'collection {collection_name} already exists, overwrite is False and add is False')
                return True

        log.info(f'generating embeddings for {collection_name}')
        embedding_function = get_embedding_function(
            request.app.state.config.RAG_EMBEDDING_ENGINE,
            request.app.state.config.RAG_EMBEDDING_MODEL,
            request.app.state.ef,
            (
                request.app.state.config.RAG_OPENAI_API_BASE_URL
                if request.app.state.config.RAG_EMBEDDING_ENGINE == 'openai'
                else (
                    request.app.state.config.RAG_OLLAMA_BASE_URL
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == 'ollama'
                    else request.app.state.config.RAG_AZURE_OPENAI_BASE_URL
                )
            ),
            (
                request.app.state.config.RAG_OPENAI_API_KEY
                if request.app.state.config.RAG_EMBEDDING_ENGINE == 'openai'
                else (
                    request.app.state.config.RAG_OLLAMA_API_KEY
                    if request.app.state.config.RAG_EMBEDDING_ENGINE == 'ollama'
                    else request.app.state.config.RAG_AZURE_OPENAI_API_KEY
                )
            ),
            request.app.state.config.RAG_EMBEDDING_BATCH_SIZE,
            azure_api_version=(
                request.app.state.config.RAG_AZURE_OPENAI_API_VERSION
                if request.app.state.config.RAG_EMBEDDING_ENGINE == 'azure_openai'
                else None
            ),
            enable_async=request.app.state.config.ENABLE_ASYNC_EMBEDDING,
            concurrent_requests=request.app.state.config.RAG_EMBEDDING_CONCURRENT_REQUESTS,
        )

        future = asyncio.run_coroutine_threadsafe(
            embedding_function(
                list(map(lambda x: x.replace('\n', ' '), texts)),
                prefix=RAG_EMBEDDING_CONTENT_PREFIX,
                user=user,
            ),
            request.app.state.main_loop,
        )
        embeddings = future.result(timeout=RAG_EMBEDDING_TIMEOUT)
        log.info(f'embeddings generated {len(embeddings)} for {len(texts)} items')

        items = [
            {
                'id': str(uuid.uuid4()),
                'text': text,
                'vector': embeddings[idx],
                'metadata': metadatas[idx],
            }
            for idx, text in enumerate(texts)
        ]

        log.info(f'adding to collection {collection_name}')
        VECTOR_DB_CLIENT.insert(collection_name=collection_name, items=items)
        log.info(f'added {len(items)} items to collection {collection_name}')
        return True
    except Exception as e:
        log.exception(e)
        raise e


def process_file(request: Request, form_data: ProcessFileForm, *, user, db: Session):
    if user.role == 'admin':
        file = Files.get_file_by_id(form_data.file_id, db=db)
    else:
        file = Files.get_file_by_id_and_user_id(form_data.file_id, user.id, db=db)

    if not file:
        raise RetrievalServiceError(ERROR_MESSAGES.NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND)

    retrieval_job = None
    collection_name = form_data.collection_name or f'file-{file.id}'

    try:
        retrieval_job = _resolve_retrieval_job(file, user.id, collection_name, form_data)
        Files.update_file_data_by_id(
            file.id,
            {
                'status': 'processing',
                'retrieval_job': build_retrieval_job_record(
                    retrieval_job,
                    status='started',
                    collection_name=collection_name,
                ),
            },
            db=db,
        )

        publish_app_event_sync(
            request.app,
            RETRIEVAL_JOB_STARTED_SUBJECT,
            build_domain_event(
                event_type='retrieval.job.started',
                resource_type='retrieval_job',
                resource_id=retrieval_job['job_id'],
                data={
                    'job_id': retrieval_job['job_id'],
                    'file_id': file.id,
                    'status': 'started',
                    'collection_name': collection_name,
                },
            ),
        )

        docs, text_content = _prepare_documents(request, file, form_data, user)
        log.debug(f'text_content: {text_content}')
        Files.update_file_data_by_id(file.id, {'content': text_content}, db=db)
        content_hash = calculate_sha256_string(text_content)
        _publish_retrieval_progress(
            request,
            retrieval_job=retrieval_job,
            file_id=file.id,
            collection_name=collection_name,
            progress=50,
            step='content_extracted',
            document_count=len(docs),
        )

        if request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL:
            Files.update_file_data_by_id(
                file.id,
                {
                    'status': 'completed',
                    'retrieval_job': build_retrieval_job_record(
                        retrieval_job,
                        status='completed',
                        collection_name=None,
                        bypass_embedding=True,
                    ),
                },
                db=db,
            )
            Files.update_file_hash_by_id(file.id, content_hash, db=db)
            publish_app_event_sync(
                request.app,
                RETRIEVAL_JOB_COMPLETED_SUBJECT,
                build_domain_event(
                    event_type='retrieval.job.completed',
                    resource_type='retrieval_job',
                    resource_id=retrieval_job['job_id'],
                    data={
                        'job_id': retrieval_job['job_id'],
                        'file_id': file.id,
                        'collection_name': None,
                        'status': 'completed',
                        'bypass_embedding': True,
                    },
                ),
            )
            return {
                'status': True,
                'collection_name': None,
                'filename': file.filename,
                'content': text_content,
            }

        db.commit()
        result = save_docs_to_vector_db(
            request,
            docs=docs,
            collection_name=collection_name,
            metadata={
                'file_id': file.id,
                'name': file.filename,
                'hash': content_hash,
            },
            add=(True if form_data.collection_name else False),
            user=user,
        )
        log.info(f'added {len(docs)} items to collection {collection_name}')

        if not result:
            raise Exception('Error saving document to vector database')

        _publish_retrieval_progress(
            request,
            retrieval_job=retrieval_job,
            file_id=file.id,
            collection_name=collection_name,
            progress=90,
            step='indexed',
            document_count=len(docs),
        )

        with get_db() as session:
            Files.update_file_metadata_by_id(file.id, {'collection_name': collection_name}, db=session)
            Files.update_file_data_by_id(
                file.id,
                {
                    'status': 'completed',
                    'retrieval_job': build_retrieval_job_record(
                        retrieval_job,
                        status='completed',
                        collection_name=collection_name,
                        document_count=len(docs),
                    ),
                },
                db=session,
            )
            Files.update_file_hash_by_id(file.id, content_hash, db=session)

            publish_app_event_sync(
                request.app,
                RETRIEVAL_JOB_COMPLETED_SUBJECT,
                build_domain_event(
                    event_type='retrieval.job.completed',
                    resource_type='retrieval_job',
                    resource_id=retrieval_job['job_id'],
                    data={
                        'job_id': retrieval_job['job_id'],
                        'file_id': file.id,
                        'status': 'completed',
                        'collection_name': collection_name,
                        'document_count': len(docs),
                        'bypass_embedding': False,
                    },
                ),
            )

        return {
            'status': True,
            'collection_name': collection_name,
            'filename': file.filename,
            'content': text_content,
        }
    except Exception as e:
        log.exception(e)
        _mark_processing_failed(
            request,
            file,
            retrieval_job,
            form_data,
            str(e.detail) if hasattr(e, 'detail') else str(e),
        )

        if 'No pandoc was found' in str(e):
            raise RetrievalServiceError(ERROR_MESSAGES.PANDOC_NOT_INSTALLED)

        if isinstance(e, RetrievalServiceError):
            raise e

        raise RetrievalServiceError(str(e))


def _publish_retrieval_progress(
    request: Request,
    *,
    retrieval_job: dict,
    file_id: str,
    collection_name: Optional[str],
    progress: int,
    step: str,
    document_count: Optional[int] = None,
) -> None:
    publish_app_event_sync(
        request.app,
        RETRIEVAL_JOB_PROGRESS_SUBJECT,
        build_domain_event(
            event_type='retrieval.job.progress',
            resource_type='retrieval_job',
            resource_id=retrieval_job['job_id'],
            data={
                'job_id': retrieval_job['job_id'],
                'file_id': file_id,
                'status': 'in_progress',
                'collection_name': collection_name,
                'progress': progress,
                'step': step,
                **({'document_count': document_count} if document_count is not None else {}),
            },
        ),
    )


def _prepare_documents(request: Request, file: FileModel, form_data: ProcessFileForm, user) -> tuple[list[Document], str]:
    if form_data.content:
        try:
            VECTOR_DB_CLIENT.delete_collection(collection_name=f'file-{file.id}')
        except Exception:
            pass

        return (
            [
                Document(
                    page_content=form_data.content.replace('<br/>', '\n'),
                    metadata={
                        **file.meta,
                        'name': file.filename,
                        'created_by': file.user_id,
                        'file_id': file.id,
                        'source': file.filename,
                    },
                )
            ],
            form_data.content,
        )

    if form_data.collection_name:
        result = VECTOR_DB_CLIENT.query(collection_name=f'file-{file.id}', filter={'file_id': file.id})

        if result is not None and len(result.ids[0]) > 0:
            docs = [
                Document(
                    page_content=result.documents[0][idx],
                    metadata=result.metadatas[0][idx],
                )
                for idx, _ in enumerate(result.ids[0])
            ]
        else:
            docs = [
                Document(
                    page_content=file.data.get('content', ''),
                    metadata={
                        **file.meta,
                        'name': file.filename,
                        'created_by': file.user_id,
                        'file_id': file.id,
                        'source': file.filename,
                    },
                )
            ]

        return docs, file.data.get('content', '')

    file_path = file.path
    if file_path:
        file_path = Storage.get_file(file_path)
        loader = Loader(
            engine=request.app.state.config.CONTENT_EXTRACTION_ENGINE,
            user=user,
            DATALAB_MARKER_API_KEY=request.app.state.config.DATALAB_MARKER_API_KEY,
            DATALAB_MARKER_API_BASE_URL=request.app.state.config.DATALAB_MARKER_API_BASE_URL,
            DATALAB_MARKER_ADDITIONAL_CONFIG=request.app.state.config.DATALAB_MARKER_ADDITIONAL_CONFIG,
            DATALAB_MARKER_SKIP_CACHE=request.app.state.config.DATALAB_MARKER_SKIP_CACHE,
            DATALAB_MARKER_FORCE_OCR=request.app.state.config.DATALAB_MARKER_FORCE_OCR,
            DATALAB_MARKER_PAGINATE=request.app.state.config.DATALAB_MARKER_PAGINATE,
            DATALAB_MARKER_STRIP_EXISTING_OCR=request.app.state.config.DATALAB_MARKER_STRIP_EXISTING_OCR,
            DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION=request.app.state.config.DATALAB_MARKER_DISABLE_IMAGE_EXTRACTION,
            DATALAB_MARKER_FORMAT_LINES=request.app.state.config.DATALAB_MARKER_FORMAT_LINES,
            DATALAB_MARKER_USE_LLM=request.app.state.config.DATALAB_MARKER_USE_LLM,
            DATALAB_MARKER_OUTPUT_FORMAT=request.app.state.config.DATALAB_MARKER_OUTPUT_FORMAT,
            EXTERNAL_DOCUMENT_LOADER_URL=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_URL,
            EXTERNAL_DOCUMENT_LOADER_API_KEY=request.app.state.config.EXTERNAL_DOCUMENT_LOADER_API_KEY,
            TIKA_SERVER_URL=request.app.state.config.TIKA_SERVER_URL,
            DOCLING_SERVER_URL=request.app.state.config.DOCLING_SERVER_URL,
            DOCLING_API_KEY=request.app.state.config.DOCLING_API_KEY,
            DOCLING_PARAMS=request.app.state.config.DOCLING_PARAMS,
            PDF_EXTRACT_IMAGES=request.app.state.config.PDF_EXTRACT_IMAGES,
            PDF_LOADER_MODE=request.app.state.config.PDF_LOADER_MODE,
            DOCUMENT_INTELLIGENCE_ENDPOINT=request.app.state.config.DOCUMENT_INTELLIGENCE_ENDPOINT,
            DOCUMENT_INTELLIGENCE_KEY=request.app.state.config.DOCUMENT_INTELLIGENCE_KEY,
            DOCUMENT_INTELLIGENCE_MODEL=request.app.state.config.DOCUMENT_INTELLIGENCE_MODEL,
            MISTRAL_OCR_API_BASE_URL=request.app.state.config.MISTRAL_OCR_API_BASE_URL,
            MISTRAL_OCR_API_KEY=request.app.state.config.MISTRAL_OCR_API_KEY,
            MINERU_API_MODE=request.app.state.config.MINERU_API_MODE,
            MINERU_API_URL=request.app.state.config.MINERU_API_URL,
            MINERU_API_KEY=request.app.state.config.MINERU_API_KEY,
            MINERU_API_TIMEOUT=request.app.state.config.MINERU_API_TIMEOUT,
            MINERU_PARAMS=request.app.state.config.MINERU_PARAMS,
        )
        loaded_docs = loader.load(file.filename, file.meta.get('content_type'), file_path)
        docs = [
            Document(
                page_content=doc.page_content,
                metadata={
                    **filter_metadata(doc.metadata),
                    'name': file.filename,
                    'created_by': file.user_id,
                    'file_id': file.id,
                    'source': file.filename,
                },
            )
            for doc in loaded_docs
        ]
    else:
        docs = [
            Document(
                page_content=file.data.get('content', ''),
                metadata={
                    **file.meta,
                    'name': file.filename,
                    'created_by': file.user_id,
                    'file_id': file.id,
                    'source': file.filename,
                },
            )
        ]

    return docs, ' '.join([doc.page_content for doc in docs])


def _mark_processing_failed(
    request: Request,
    file: FileModel,
    retrieval_job: Optional[dict],
    form_data: ProcessFileForm,
    error_detail: str,
) -> None:
    if retrieval_job is None:
        return

    with get_db() as session:
        Files.update_file_data_by_id(
            file.id,
            {
                'status': 'failed',
                'retrieval_job': build_retrieval_job_record(
                    retrieval_job,
                    status='failed',
                    collection_name=form_data.collection_name or f'file-{file.id}',
                    error=error_detail,
                ),
            },
            db=session,
        )
        Files.update_file_hash_by_id(file.id, None, db=session)

    publish_app_event_sync(
        request.app,
        RETRIEVAL_JOB_FAILED_SUBJECT,
        build_domain_event(
            event_type='retrieval.job.failed',
            resource_type='retrieval_job',
            resource_id=retrieval_job['job_id'],
            data={
                'job_id': retrieval_job['job_id'],
                'file_id': file.id,
                'status': 'failed',
                'collection_name': form_data.collection_name or f'file-{file.id}',
                'error_code': 'retrieval_failed',
            },
        ),
    )


def _resolve_retrieval_job(file: FileModel, actor_id: str, collection_name: str, form_data: ProcessFileForm) -> dict:
    command = build_process_file_command(
        file_id=file.id,
        source='process_file',
        processing_mode='inline',
        content_type=file.meta.get('content_type') if file.meta else None,
        collection_name=collection_name,
        inline_content=form_data.content,
    )

    existing_job = file.data.get('retrieval_job') if file.data else None
    if existing_job and existing_job.get('job_id') == form_data.job_id:
        return build_retrieval_job(
            actor_id=actor_id,
            resource_id=file.id,
            job_id=existing_job['job_id'],
            requested_at=existing_job.get('requested_at'),
            payload_version=existing_job.get('payload_version', 'v1'),
            payload=command,
        )

    return build_retrieval_job(
        actor_id=actor_id,
        resource_id=file.id,
        job_id=form_data.job_id,
        payload=command,
    )
