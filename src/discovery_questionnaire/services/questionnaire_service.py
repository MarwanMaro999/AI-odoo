"""Business logic for discovery-questionnaire requests."""

from uuid import UUID

from src.discovery_questionnaire.repositories.run_repository import (
    InMemoryQuestionnaireRunRepository,
)
from src.discovery_questionnaire.schemas.configuration import (
    PublicQuestionnaireConfiguration,
)
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.schemas.response import (
    QuestionnaireAcceptedResponse,
    QuestionnaireStatusResponse,
)
from src.discovery_questionnaire.services.questionnaire_registry import (
    QuestionnaireRegistry,
)


class QuestionnaireService:
    """Coordinates configuration validation and temporary questionnaire run state."""

    def __init__(
        self,
        repository: InMemoryQuestionnaireRunRepository,
        registry: QuestionnaireRegistry,
    ) -> None:
        self._repository = repository
        self._registry = registry

    async def start(
        self, request: StartQuestionnaireRequest
    ) -> QuestionnaireAcceptedResponse:
        """Validate configuration and create or reuse a queued questionnaire run."""
        configuration = self._registry.load(request.questionnaire_identifier)
        run, _ = self._repository.create_or_get(request, configuration.version)
        return QuestionnaireAcceptedResponse(
            questionnaire_run_id=run.questionnaire_run_id,
            state=run.state,
        )

    async def get_status(self, questionnaire_run_id: UUID) -> QuestionnaireStatusResponse:
        """Return the current temporary state of a questionnaire run."""
        return self._repository.get(questionnaire_run_id).to_status_response()

    async def get_public_configuration(
        self, questionnaire_identifier: str
    ) -> PublicQuestionnaireConfiguration:
        """Return configuration metadata without the private instruction."""
        configuration = self._registry.load(questionnaire_identifier)
        return PublicQuestionnaireConfiguration.create_public_view(configuration)
