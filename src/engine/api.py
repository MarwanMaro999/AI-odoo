"""Generic internal AI execution endpoints for Odoo."""

from uuid import UUID
from mimetypes import guess_type

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from src.engine.schemas import RunStatus, StartRunRequest
from src.engine.service import EngineService

router = APIRouter(prefix="/runs", tags=["runs"])


def get_engine_service(request: Request) -> EngineService:
    return request.app.state.engine_container.service


@router.post("", response_model=RunStatus, status_code=status.HTTP_202_ACCEPTED)
async def start_run(payload: StartRunRequest, service: EngineService = Depends(get_engine_service)) -> RunStatus:
    try:
        return await service.start(payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/{run_id}", response_model=RunStatus)
async def get_run(run_id: UUID, service: EngineService = Depends(get_engine_service)) -> RunStatus:
    try:
        return service.status(run_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Run not found") from error


@router.get("/{run_id}/outputs/{filename}")
async def get_output(run_id: UUID, filename: str, request: Request, service: EngineService = Depends(get_engine_service)) -> FileResponse:
    try:
        path = service.output_path(run_id, filename, request.app.state.engine_container.output_directory)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Output not found") from error
    media_type = guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=filename)
