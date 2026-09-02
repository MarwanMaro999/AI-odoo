"""Tests for bounded document-source extraction."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from pydantic import SecretStr

from src.core.config import Settings
from src.main import create_application


class _NoopChatterQueue:
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def enqueue(self, _run_id) -> None:
        return None


class _HealthyDatabase:
    async def ping(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


class _UnavailableDatabase:
    async def ping(self) -> None:
        raise ConnectionError("database is unavailable")

    async def dispose(self) -> None:
        return None


def create_test_application(settings: Settings):
    app = create_application(settings)
    queue = _NoopChatterQueue()
    app.state.chatter_ai_container = replace(app.state.chatter_ai_container, queue=queue)
    app.state.engine_container = replace(app.state.engine_container, queue=queue)
    return app


@pytest.mark.asyncio
async def test_extract_source_file_returns_text_for_small_txt_upload() -> None:
    app = create_test_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
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
    app = create_test_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.exe", b"not a document", "application/octet-stream")},
            headers={"Authorization": "Bearer test-token"},
        )
    assert response.status_code == 422


def test_extraction_http_endpoint_accepts_a_text_file() -> None:
    app = create_test_application(Settings(datum_engine_api_auth_token=SecretStr("test-token")))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.txt", b"Ready for extraction", "text/plain")},
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "Ready for extraction"


def test_health_endpoint_confirms_neon_connectivity_without_ai_calls() -> None:
    app = create_test_application(Settings())
    app.state.database_runtime = _HealthyDatabase()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_endpoint_returns_503_when_neon_is_unavailable() -> None:
    app = create_test_application(Settings())
    app.state.database_runtime = _UnavailableDatabase()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["detail"] == "database_unavailable"
