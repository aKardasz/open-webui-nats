from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
    APIRouter,
)
import aiohttp
import os
import logging
import shutil
from pydantic import BaseModel
from starlette.responses import FileResponse
from typing import Optional

from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.config import CACHE_DIR
from open_webui.constants import ERROR_MESSAGES
from open_webui.utils.pipeline_adapter import HttpPipelineAdapter, PipelineAdapterError


from open_webui.routers.openai import get_all_models_responses

from open_webui.utils.auth import get_admin_user

log = logging.getLogger(__name__)


##################################
#
# Pipeline Middleware
# Every hand this passes through can corrupt it or
# improve it. Let each stage leave it better than it found.
#
##################################


def get_sorted_filters(model_id, models):
    filters = [
        model
        for model in models.values()
        if 'pipeline' in model
        and 'type' in model['pipeline']
        and model['pipeline']['type'] == 'filter'
        and (
            model['pipeline']['pipelines'] == ['*']
            or any(model_id == target_model_id for target_model_id in model['pipeline']['pipelines'])
        )
    ]
    sorted_filters = sorted(filters, key=lambda x: x['pipeline']['priority'])
    return sorted_filters


async def process_pipeline_inlet_filter(request, payload, user, models):
    user = {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role}
    model_id = payload['model']
    sorted_filters = get_sorted_filters(model_id, models)
    model = models[model_id]
    adapter = HttpPipelineAdapter(request)

    if 'pipeline' in model:
        sorted_filters.append(model)

    for filter in sorted_filters:
        try:
            payload = await adapter.invoke_filter(filter, 'inlet', user=user, payload=payload)
        except PipelineAdapterError as e:
            raise Exception(e.status_code, e.detail)
        except Exception as e:
            log.exception(f'Connection error: {e}')

    return payload


async def process_pipeline_outlet_filter(request, payload, user, models):
    user = {'id': user.id, 'email': user.email, 'name': user.name, 'role': user.role}
    model_id = payload['model']
    sorted_filters = get_sorted_filters(model_id, models)
    model = models[model_id]
    adapter = HttpPipelineAdapter(request)

    if 'pipeline' in model:
        sorted_filters = [model] + sorted_filters

    for filter in sorted_filters:
        try:
            payload = await adapter.invoke_filter(filter, 'outlet', user=user, payload=payload)
        except PipelineAdapterError as e:
            raise Exception(e.status_code, e.detail)
        except Exception as e:
            log.exception(f'Connection error: {e}')

    return payload


##################################
#
# Pipelines Endpoints
#
##################################

router = APIRouter()


@router.get('/list')
async def get_pipelines_list(request: Request, user=Depends(get_admin_user)):
    responses = await get_all_models_responses(request, user)
    log.debug(f'get_pipelines_list: get_openai_models_responses returned {responses}')

    urlIdxs = [idx for idx, response in enumerate(responses) if response is not None and 'pipelines' in response]

    return {
        'data': [
            {
                'url': request.app.state.config.OPENAI_API_BASE_URLS[urlIdx],
                'idx': urlIdx,
            }
            for urlIdx in urlIdxs
        ]
    }


@router.post('/upload')
async def upload_pipeline(
    request: Request,
    urlIdx: int = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_admin_user),
):
    log.info(f'upload_pipeline: urlIdx={urlIdx}, filename={file.filename}')
    filename = os.path.basename(file.filename)
    adapter = HttpPipelineAdapter(request)

    # Check if the uploaded file is a python file
    if not (filename and filename.endswith('.py')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Only Python (.py) files are allowed.',
        )

    upload_folder = f'{CACHE_DIR}/pipelines'
    os.makedirs(upload_folder, exist_ok=True)
    file_path = os.path.join(upload_folder, filename)

    try:
        # Save the uploaded file
        with open(file_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)

        return await adapter.upload_file(urlIdx, 'pipelines/upload', file_path=file_path, filename=filename)
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')
    finally:
        # Ensure the file is deleted after the upload is completed or on failure
        if os.path.exists(file_path):
            os.remove(file_path)


class AddPipelineForm(BaseModel):
    url: str
    urlIdx: int


@router.post('/add')
async def add_pipeline(request: Request, form_data: AddPipelineForm, user=Depends(get_admin_user)):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.post_json(form_data.urlIdx, 'pipelines/add', {'url': form_data.url})
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')


class DeletePipelineForm(BaseModel):
    id: str
    urlIdx: int


@router.delete('/delete')
async def delete_pipeline(request: Request, form_data: DeletePipelineForm, user=Depends(get_admin_user)):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.delete_json(form_data.urlIdx, 'pipelines/delete', {'id': form_data.id})
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')


@router.get('/')
async def get_pipelines(request: Request, urlIdx: Optional[int] = None, user=Depends(get_admin_user)):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.get_json(urlIdx, 'pipelines')
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')


@router.get('/{pipeline_id}/valves')
async def get_pipeline_valves(
    request: Request,
    urlIdx: Optional[int],
    pipeline_id: str,
    user=Depends(get_admin_user),
):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.get_json(urlIdx, f'{pipeline_id}/valves')
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')


@router.get('/{pipeline_id}/valves/spec')
async def get_pipeline_valves_spec(
    request: Request,
    urlIdx: Optional[int],
    pipeline_id: str,
    user=Depends(get_admin_user),
):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.get_json(urlIdx, f'{pipeline_id}/valves/spec')
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')


@router.post('/{pipeline_id}/valves/update')
async def update_pipeline_valves(
    request: Request,
    urlIdx: Optional[int],
    pipeline_id: str,
    form_data: dict,
    user=Depends(get_admin_user),
):
    adapter = HttpPipelineAdapter(request)
    try:
        return await adapter.post_json(urlIdx, f'{pipeline_id}/valves/update', {**form_data})
    except PipelineAdapterError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.exception(f'Connection error: {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Pipeline not found')
