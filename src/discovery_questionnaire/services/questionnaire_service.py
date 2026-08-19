"""Business logic for discovery-questionnaire requests."""

from pathlib import Path
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
from src.shared.queue.in_memory_queue import InMemoryRunQueue


class QuestionnaireService:
    """Coordinates configuration validation and temporary questionnaire run state."""

    def __init__(
        self,
        repository: InMemoryQuestionnaireRunRepository,
        registry: QuestionnaireRegistry,
        queue: InMemoryRunQueue,
        output_directory: Path,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._queue = queue
        self._output_directory = output_directory

    async def start(
        self, request: StartQuestionnaireRequest
    ) -> QuestionnaireAcceptedResponse:
        """Validate configuration and create or reuse a queued questionnaire run."""
        configuration = self._registry.load(request.questionnaire_identifier)
        run, created = self._repository.create_or_get(request, configuration.version)
        if created:
            await self._queue.enqueue(run.questionnaire_run_id)
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

    async def get_output_file(self, questionnaire_run_id: UUID) -> Path:
        """Resolve a completed local PDF without exposing arbitrary file paths."""
        run = self._repository.get(questionnaire_run_id)
        if not run.outputs:
            raise FileNotFoundError("Questionnaire output is not ready")
        output_path = self._output_directory / run.outputs[0].filename
        if not output_path.is_file():
            raise FileNotFoundError("Questionnaire output file is not available")
        return output_path
