"""FastAPI controller for the discovery-questionnaire module."""

from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.discovery_questionnaire.dependencies import get_questionnaire_service
from src.discovery_questionnaire.schemas.configuration import (
    PublicQuestionnaireConfiguration,
)
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.schemas.response import (
    QuestionnaireAcceptedResponse,
    QuestionnaireStatusResponse,
)
from src.discovery_questionnaire.services.questionnaire_service import QuestionnaireService

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
