"""Tests for bounded document-source extraction."""

import pytest
from fastapi.testclient import TestClient

from pydantic import SecretStr

from src.core.config import Settings
from src.main import create_application


@pytest.mark.asyncio
async def test_extract_source_file_returns_text_for_small_txt_upload() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.txt", b"Datum Engine project brief", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    result = type("Extracted", (), response.json())()

    assert result.type == "attachment"
    assert result.text == "Datum Engine project brief"


@pytest.mark.asyncio
async def test_extract_source_file_rejects_unsupported_upload() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.exe", b"not a document", "application/octet-stream")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 422


def test_extraction_http_endpoint_accepts_a_text_file() -> None:
    app = create_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.txt", b"Ready for extraction", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "Ready for extraction"


def test_health_endpoint_does_not_depend_on_ai_providers() -> None:
    app = create_application(Settings())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
