from app.schemas.discovery_questionnaire.configuration import (
    PublicQuestionnaireConfiguration,
    QuestionnaireConfiguration,
)
from app.schemas.discovery_questionnaire.request import StartQuestionnaireRequest


def test_skill_summary_never_contains_instruction() -> None:
    configuration = QuestionnaireConfiguration.model_validate(
        {
            "identifier": "gen-discovery-questions",
            "version": "0.1-demo",
            "kind": "generator",
            "accepted_source_material": [
                {"type": "prospect_context", "required": True}
            ],
            "outputs": [
                {
                    "document_type": "discovery_questionnaire",
                    "distribution_class": "client_permitted",
                }
            ],
            "instruction": "Private placeholder instruction.",
        }
    )

    assert (
        "instruction"
        not in PublicQuestionnaireConfiguration.create_public_view(
            configuration
        ).model_dump()
    )


def test_run_request_accepts_arabic_and_english_context() -> None:
    request = StartQuestionnaireRequest.model_validate(
        {
            "questionnaire_identifier": "gen-discovery-questions",
            "idempotency_key": "example-company-001",
            "customer": {"name": "شركة المثال", "country": "Egypt"},
            "source_material": [
                {
                    "source_id": "context-1",
                    "type": "prospect_context",
                    "text": "شركة تقدم حلولاً رقمية. The company needs a discovery meeting.",
                }
            ],
            "options": {"languages": ["AR", "en"]},
        }
    )

    assert request.options.languages == ["ar", "en"]
