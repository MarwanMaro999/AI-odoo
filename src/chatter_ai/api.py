"""HTTP API used by the Odoo chatter integration."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from mimetypes import guess_type

from src.chatter_ai.dependencies import get_chatter_ai_service
from src.chatter_ai.schemas import ChatterAIRunStatus, ChatterAIStartRequest
from src.chatter_ai.service import ChatterAIService
from src.core.security import require_engine_token


router = APIRouter(prefix="/chatter-ai/runs", tags=["chatter-ai"], dependencies=[Depends(require_engine_token)])


@router.post("", response_model=ChatterAIRunStatus, status_code=status.HTTP_202_ACCEPTED)
async def start_run(payload: ChatterAIStartRequest, service: ChatterAIService = Depends(get_chatter_ai_service)) -> ChatterAIRunStatus:
    try:
        return await service.start(payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{run_id}", response_model=ChatterAIRunStatus)
async def get_run(run_id: UUID, service: ChatterAIService = Depends(get_chatter_ai_service)) -> ChatterAIRunStatus:
    try:
        return service.status(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Chat run not found") from error


@router.get("/{run_id}/outputs/{filename}")
async def get_output(
    run_id: UUID,
    filename: str,
    request: Request,
    service: ChatterAIService = Depends(get_chatter_ai_service),
) -> FileResponse:
    try:
        path = service.output_path(
            run_id,
            filename,
            request.app.state.chatter_ai_container.output_directory,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Output not found") from error
    return FileResponse(
        path,
        media_type=guess_type(path.name)[0] or "application/octet-stream",
        filename=filename,
    )
