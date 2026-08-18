"""HTTP endpoints for discovery-questionnaire requests."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

from app.schemas.discovery_questionnaire.request import StartQuestionnaireRequest
from app.schemas.discovery_questionnaire.response import (
    QuestionnaireAcceptedResponse,
    QuestionnaireStatusResponse,
)

router = APIRouter(prefix="/discovery-questionnaire", tags=["discovery-questionnaire"])


@router.post(
    "/runs",
    response_model=QuestionnaireAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_questionnaire(
    request: StartQuestionnaireRequest,
) -> QuestionnaireAcceptedResponse:
    """Validate a questionnaire request and accept it for later processing."""
    del request
    return QuestionnaireAcceptedResponse(questionnaire_run_id=uuid4())


@router.get("/runs/{questionnaire_run_id}", response_model=QuestionnaireStatusResponse)
async def get_questionnaire_status(
    questionnaire_run_id: UUID,
) -> QuestionnaireStatusResponse:
    """Reserve the status endpoint until temporary run-state storage is added."""
    del questionnaire_run_id
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Questionnaire run status is not available until state storage is configured.",
    )


@router.get("/configuration")
async def get_questionnaire_configuration() -> None:
    """Reserve the public configuration endpoint until registry loading is added."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Questionnaire configuration is not available until registry loading is configured.",
    )
