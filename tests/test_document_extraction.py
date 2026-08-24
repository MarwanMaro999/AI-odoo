"""Tests for bounded document-source extraction."""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from src.core.config import Settings
from src.discovery_questionnaire.controller import extract_source_file
from src.main import create_application


@pytest.mark.asyncio
async def test_extract_source_file_returns_text_for_small_txt_upload() -> None:
    upload = UploadFile(filename="brief.txt", file=BytesIO(b"Datum Engine project brief"))

    result = await extract_source_file(upload)

    assert result.type == "attachment"
    assert result.text == "Datum Engine project brief"


@pytest.mark.asyncio
async def test_extract_source_file_rejects_unsupported_upload() -> None:
    upload = UploadFile(filename="brief.exe", file=BytesIO(b"not a document"))

    with pytest.raises(HTTPException) as error:
        await extract_source_file(upload)

    assert error.value.status_code == 422


def test_extraction_http_endpoint_accepts_a_text_file() -> None:
    app = create_application(Settings())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/discovery-questionnaire/source-files/extract",
            files={"file": ("brief.txt", b"Ready for extraction", "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["text"] == "Ready for extraction"


def test_health_endpoint_does_not_depend_on_ai_providers() -> None:
    app = create_application(Settings())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
