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
from src.discovery_questionnaire.services.questionnaire_processor import QuestionnaireProcessor
from src.shared.llm.providers import FallbackTextGenerator, GroqTextGenerator, HuggingFaceTextGenerator, OpenAITextGenerator
from src.shared.queue.in_memory_queue import InMemoryRunQueue
from src.shared.rendering.questionnaire_pdf_renderer import QuestionnairePdfRenderer
from src.shared.web_research.research_service import CompanyResearchService


@dataclass(frozen=True)
class QuestionnaireContainer:
    """The questionnaire components shared by every request in one application."""

    service: QuestionnaireService
    queue: InMemoryRunQueue


def create_questionnaire_container(settings: Settings) -> QuestionnaireContainer:
    """Build local development dependencies; Odoo replaces repository later."""
    repository = InMemoryQuestionnaireRunRepository()
    registry = QuestionnaireRegistry(settings.registry_path)
    processor = QuestionnaireProcessor(
        repository=repository,
        registry=registry,
        generator=FallbackTextGenerator([
            GroqTextGenerator(settings),
            HuggingFaceTextGenerator(settings),
        ]),
        research=CompanyResearchService(settings),
        renderer=QuestionnairePdfRenderer(settings.dev_output_dir),
    )
    queue = InMemoryRunQueue(processor.process, settings.worker_concurrency)
    return QuestionnaireContainer(
        service=QuestionnaireService(repository, registry, queue, settings.dev_output_dir), queue=queue
    )


def get_questionnaire_service(request: Request) -> QuestionnaireService:
    """Retrieve the application-wide questionnaire service for a controller call."""
    return request.app.state.questionnaire_container.service
