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
                self._build_prompt(
                    run.request,
                    configuration.instruction,
                    research_text,
                    configuration.questions_per_section,
                )
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
        request: StartQuestionnaireRequest,
        instruction: str,
        research_text: str,
        questions_per_section: int,
    ) -> str:
        customer = request.customer
        materials = "\n\n".join(
            f"[{item.type}]\n{item.text}" for item in request.source_material
        )
        languages = ", ".join(request.options.languages)
        return f"""{instruction}

Create a practical discovery questionnaire for a live customer meeting in these
languages: {languages}. The consultant must be able to ask the questions naturally
and use the answers to define scope, estimate effort, identify risks, and agree on
next steps.

Use the supplied material as known context. Do not ask for facts already provided.
Do not invent facts, technical constraints, integrations, or regulations. Where
information is missing, ask a concise, open-ended, non-leading question. Prioritize
business value and the customer's current way of working before technical details.

Create exactly {questions_per_section} primary questions in each of these sections:
1. Business objectives, stakeholders, and success measures
2. Current process, pain points, and priorities
3. Required capabilities, users, roles, and reports
4. Data, integrations, security, and compliance
5. Delivery, adoption, acceptance criteria, timeline, and support

Each question must be specific to this project. Include practical details where
relevant, such as decision makers, exceptions, approval steps, volumes, ownership,
existing systems, data quality, training, and measurable acceptance criteria.

Bilingual equivalence is a hard requirement. First, create one canonical English
question list internally, with stable pairs S1Q1 through S5Q{questions_per_section}.
Then translate each canonical question faithfully into Arabic. Do not create the
Arabic and English questions independently.

For every matching Arabic/English pair, preserve the same intent, subject, scope,
entities, qualifiers, assumptions, and expected answer. Never add, remove, merge,
split, reorder, or substitute a question in either language. The Arabic question at
section N, position M must be the translation of the English question at section N,
position M. Keep the visible numbering identical, but do not print the internal IDs.

Before producing the response, silently verify that both languages have exactly five
sections, exactly {questions_per_section} questions in every section, and one
semantically equivalent pair at every matching position. Correct any mismatch before
returning the Markdown.

Return only clean Markdown in this exact order:
# Discovery Questionnaire
## اللغة العربية
### أهداف العمل وأصحاب المصلحة ومعايير النجاح
1. سؤال
### العملية الحالية ونقاط الألم والأولويات
1. سؤال
### القدرات المطلوبة والمستخدمون والأدوار والتقارير
1. سؤال
### البيانات والتكاملات والأمان والامتثال
1. سؤال
### التنفيذ والتبني والقبول والجدول الزمني والدعم
1. سؤال
## English
### Business Objectives, Stakeholders, and Success Measures
1. Question
### Current Process, Pain Points, and Priorities
1. Question
### Required Capabilities, Users, Roles, and Reports
1. Question
### Data, Integrations, Security, and Compliance
1. Question
### Delivery, Adoption, Acceptance Criteria, Timeline, and Support
1. Question

Do not add answers, explanations, sources, a summary, internal IDs, or a Markdown
table.

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
