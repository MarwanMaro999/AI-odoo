from pathlib import Path
from uuid import uuid4

import pytest

from src.core.config import Settings
from src.discovery_questionnaire.repositories.run_repository import InMemoryQuestionnaireRunRepository
from src.discovery_questionnaire.schemas.request import StartQuestionnaireRequest
from src.discovery_questionnaire.services.questionnaire_processor import QuestionnaireProcessor
from src.discovery_questionnaire.services.questionnaire_registry import QuestionnaireRegistry
from pypdf import PdfReader

from src.shared.document_processing.text_extractor import extract_text
from src.shared.llm.contracts import GeneratedText
from src.shared.rendering.questionnaire_pdf_renderer import QuestionnairePdfRenderer
from src.shared.web_research.research_service import CompanyResearchService


class WorkingGenerator:
    async def generate(self, prompt: str) -> GeneratedText:
        assert "Example Company" in prompt
        return GeneratedText(text="الأسئلة الاستكشافية\n1. ما هي أهداف المشروع؟\n\nDiscovery Questions\n1. What are the project goals?", provider="test", model="test-model")


def _request() -> StartQuestionnaireRequest:
    return StartQuestionnaireRequest.model_validate({
        "questionnaire_identifier": "gen-discovery-questions",
        "idempotency_key": "pipeline-test",
        "customer": {"name": "Example Company", "country": "Egypt"},
        "source_material": [{"source_id": "context", "type": "prospect_context", "text": "Needs a CRM."}],
        "options": {"web_research_enabled": False},
    })


def _write_configuration(path: Path) -> None:
    path.mkdir(exist_ok=True)
    (path / "gen-discovery-questions.yaml").write_text("""identifier: gen-discovery-questions
version: '0.1-demo'
kind: generator
accepted_source_material:
  - type: prospect_context
    required: true
outputs:
  - document_type: discovery_questionnaire
    distribution_class: client_permitted
instruction: Generate a bilingual questionnaire.
""", encoding="utf-8")


@pytest.mark.asyncio
async def test_processor_generates_a_bilingual_pdf(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry"
    _write_configuration(registry_path)
    repository = InMemoryQuestionnaireRunRepository()
    run, _ = repository.create_or_get(_request(), "0.1-demo")
    processor = QuestionnaireProcessor(
        repository=repository,
        registry=QuestionnaireRegistry(registry_path),
        generator=WorkingGenerator(),
        research=CompanyResearchService(Settings()),
        renderer=QuestionnairePdfRenderer(tmp_path / "outputs"),
    )

    await processor.process(run.questionnaire_run_id)

    completed = repository.get(run.questionnaire_run_id)
    assert completed.state == "succeeded"
    assert completed.outputs
    assert (tmp_path / "outputs" / completed.outputs[0].filename).read_bytes().startswith(b"%PDF")


def test_extract_text_accepts_plain_text() -> None:
    assert extract_text("context.txt", b"Customer context") == "Customer context"


def test_renderer_removes_markdown_markers(tmp_path: Path) -> None:
    output = QuestionnairePdfRenderer(tmp_path).render(
        uuid4(),
        "# Discovery Questionnaire\n## English\n### General Project Information\n1. What are the project goals?\n---",
    )

    extracted = PdfReader(str(output)).pages[0].extract_text()
    assert "#" not in extracted
    assert "Discovery Questionnaire" in extracted
