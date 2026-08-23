"""FastAPI controller for the discovery-questionnaire module."""

from uuid import UUID

from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from src.discovery_questionnaire.dependencies import get_questionnaire_service
from src.discovery_questionnaire.schemas.configuration import (
    PublicQuestionnaireConfiguration,
)
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.schemas.request import QuestionnaireSource, QuestionnaireSourceOrigin
from src.discovery_questionnaire.schemas.response import (
    QuestionnaireAcceptedResponse,
    QuestionnaireStatusResponse,
)
from src.discovery_questionnaire.services.questionnaire_service import QuestionnaireService
from src.core.config import get_settings
from src.shared.document_processing.text_extractor import UnsupportedDocumentError, extract_text

router = APIRouter(prefix="/discovery-questionnaire", tags=["discovery-questionnaire"])


@router.post(
    "/runs",
    response_model=QuestionnaireAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_questionnaire(
    request: StartQuestionnaireRequest,
    service: QuestionnaireService = Depends(get_questionnaire_service),
) -> QuestionnaireAcceptedResponse:
    """Accept a validated questionnaire request without performing model work."""
    return await service.start(request)


@router.get("/runs/{questionnaire_run_id}", response_model=QuestionnaireStatusResponse)
async def get_questionnaire_status(
    questionnaire_run_id: UUID,
    service: QuestionnaireService = Depends(get_questionnaire_service),
) -> QuestionnaireStatusResponse:
    """Return the currently stored development state for one questionnaire run."""
    return await service.get_status(questionnaire_run_id)


@router.get(
    "/configuration/{questionnaire_identifier}",
    response_model=PublicQuestionnaireConfiguration,
)
async def get_questionnaire_configuration(
    questionnaire_identifier: str,
    service: QuestionnaireService = Depends(get_questionnaire_service),
) -> PublicQuestionnaireConfiguration:
    """Return safe questionnaire configuration metadata without its instruction."""
    return await service.get_public_configuration(questionnaire_identifier)


@router.post("/source-files/extract", response_model=QuestionnaireSource)
async def extract_source_file(file: UploadFile = File(...)) -> QuestionnaireSource:
    """Extract PDF/DOCX/TXT content to use in a subsequent JSON run request."""
    content = await file.read()
    if len(content) > get_settings().max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="The uploaded file is too large")
    try:
        text = extract_text(file.filename or "upload", content)
    except UnsupportedDocumentError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return QuestionnaireSource(
        source_id=str(uuid4()),
        type="attachment",
        origin=QuestionnaireSourceOrigin.FILE_EXTRACTED,
        text=text,
    )


@router.get("/runs/{questionnaire_run_id}/output")
async def download_questionnaire_output(
    questionnaire_run_id: UUID,
    service: QuestionnaireService = Depends(get_questionnaire_service),
) -> FileResponse:
    """Download the generated PDF after the run has succeeded."""
    try:
        output_path = await service.get_output_file(questionnaire_run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="The questionnaire output is not ready") from error
    return FileResponse(output_path, media_type="application/pdf", filename=output_path.name)
