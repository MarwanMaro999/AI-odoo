"""Background execution for a questionnaire run."""

from uuid import UUID, uuid4

from src.core.logging import get_logger
from src.discovery_questionnaire.repositories.run_repository import (
    InMemoryQuestionnaireRunRepository,
    StoredQuestionnaireRun,
)
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.schemas.response import QuestionnaireOutput
from src.discovery_questionnaire.services.questionnaire_registry import QuestionnaireRegistry
from src.shared.llm.contracts import TextGenerator
from src.shared.rendering.questionnaire_pdf_renderer import QuestionnairePdfRenderer
from src.shared.web_research.research_service import CompanyResearchService


class QuestionnaireProcessor:
    """Assemble safe context, generate content, and render its output."""

    def __init__(
        self,
        repository: InMemoryQuestionnaireRunRepository,
        registry: QuestionnaireRegistry,
        generator: TextGenerator,
        research: CompanyResearchService,
        renderer: QuestionnairePdfRenderer,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._generator = generator
        self._research = research
        self._renderer = renderer
        self._logger = get_logger()

    async def process(self, questionnaire_run_id: UUID) -> None:
        """Execute one queued run and persist only safe status metadata."""
        run = self._repository.mark_running(questionnaire_run_id)
        try:
            configuration = self._registry.load(run.questionnaire_identifier)
            research_text = await self._get_research(run)
            generated = await self._generator.generate(
                self._build_prompt(run.request, configuration.instruction, research_text)
            )
            output_path = self._renderer.render(questionnaire_run_id, generated.text)
            output = QuestionnaireOutput(
                output_id=uuid4(),
                document_type=configuration.outputs[0].document_type,
                distribution_class=configuration.outputs[0].distribution_class,
                media_type="application/pdf",
                filename=output_path.name,
                download_url=f"/api/v1/discovery-questionnaire/runs/{questionnaire_run_id}/output",
            )
            self._repository.mark_succeeded(questionnaire_run_id, [output])
        except Exception as error:
            failure_code = self._failure_code(error)
            self._logger.error(
                "questionnaire_processing_failed",
                questionnaire_run_id=str(questionnaire_run_id),
                failure_code=failure_code,
                error_type=type(error).__name__,
            )
            self._repository.mark_failed(questionnaire_run_id, failure_code)

    async def _get_research(self, run: StoredQuestionnaireRun) -> str:
        request = run.request
        if not request.options.web_research_enabled:
            return ""
        customer = request.customer
        query = " ".join(
            value for value in [customer.name, customer.industry, customer.country, str(customer.website or "")] if value
        )
        result = await self._research.research(query)
        return result.text if result else ""

    @staticmethod
    def _build_prompt(
        request: StartQuestionnaireRequest, instruction: str, research_text: str
    ) -> str:
        customer = request.customer
        materials = "\n\n".join(
            f"[{item.type}]\n{item.text}" for item in request.source_material
        )
        languages = ", ".join(request.options.languages)
        return f"""{instruction}

Create a professional discovery questionnaire in these languages: {languages}.
Do not invent facts. Ask questions where information is missing.

Return only clean Markdown in this exact structure:
# Discovery Questionnaire
## اللغة العربية
### معلومات عامة عن المشروع
1. سؤال واضح
### المتطلبات الوظيفية
2. سؤال واضح
### التكامل والبيانات
3. سؤال واضح
### الأمان والخصوصية
4. سؤال واضح
### التنفيذ والقبول
5. سؤال واضح
## English
### General Project Information
1. Clear question
### Functional Requirements
2. Clear question
### Integration and Data
3. Clear question
### Security and Privacy
4. Clear question
### Delivery and Acceptance
5. Clear question

Use the same complete set of questions in Arabic and English. Do not add commentary,
answers, source material, or a Markdown table.

CUSTOMER
Name: {customer.name}
Website: {customer.website or 'Not provided'}
Industry: {customer.industry or 'Not provided'}
Country: {customer.country or 'Not provided'}
Notes: {customer.notes or 'Not provided'}

STAFF AND ATTACHMENT MATERIAL
{materials}

PUBLIC WEB RESEARCH (may be empty; treat as unverified background)
{research_text or 'No research was available.'}
"""

    @staticmethod
    def _failure_code(error: Exception) -> str:
        name = type(error).__name__.lower()
        if "provider" in name:
            return "generation_unavailable"
        if "document" in name or "pdf" in name:
            return "rendering_failed"
        return "processing_failed"
