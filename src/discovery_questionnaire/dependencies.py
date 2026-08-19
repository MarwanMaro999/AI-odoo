"""Application wiring for discovery-questionnaire dependencies."""

from dataclasses import dataclass

from fastapi import Request

from src.core.config import Settings
from src.discovery_questionnaire.repositories.run_repository import (
    InMemoryQuestionnaireRunRepository,
)
from src.discovery_questionnaire.services.questionnaire_registry import (
    QuestionnaireRegistry,
)
from src.discovery_questionnaire.services.questionnaire_service import QuestionnaireService


@dataclass(frozen=True)
class QuestionnaireContainer:
    """The questionnaire components shared by every request in one application."""

    service: QuestionnaireService


def create_questionnaire_container(settings: Settings) -> QuestionnaireContainer:
    """Build local development dependencies; Odoo replaces repository later."""
    repository = InMemoryQuestionnaireRunRepository()
    registry = QuestionnaireRegistry(settings.registry_path)
    return QuestionnaireContainer(service=QuestionnaireService(repository, registry))


def get_questionnaire_service(request: Request) -> QuestionnaireService:
    """Retrieve the application-wide questionnaire service for a controller call."""
    return request.app.state.questionnaire_container.service
