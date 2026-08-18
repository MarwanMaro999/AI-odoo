from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import (
    QuestionnaireConfigurationNotFound,
    register_questionnaire_exception_handlers,
)
from app.core.logging import redact_private_fields


def test_log_processor_redacts_private_values() -> None:
    event = redact_private_fields(
        None,
        "info",
        {
            "event": "questionnaire_started",
            "instruction": "Never return this text.",
            "provider": {"api_key": "private-key"},
        },
    )

    assert event["instruction"] == "[REDACTED]"
    assert event["provider"]["api_key"] == "[REDACTED]"


def test_questionnaire_error_does_not_expose_private_message() -> None:
    app = FastAPI()
    register_questionnaire_exception_handlers(app)

    @app.get("/test-error")
    async def test_error() -> None:
        raise QuestionnaireConfigurationNotFound("Private prompt text")

    response = TestClient(app).get("/test-error")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "questionnaire_configuration_not_found"
    assert "Private prompt text" not in response.text
