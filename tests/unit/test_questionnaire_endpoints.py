from uuid import UUID

from fastapi.testclient import TestClient

from app.main import create_application


def test_start_questionnaire_accepts_valid_request() -> None:
    client = TestClient(create_application())

    response = client.post(
        "/api/v1/discovery-questionnaire/runs",
        json={
            "questionnaire_identifier": "gen-discovery-questions",
            "idempotency_key": "example-company-001",
            "customer": {"name": "Example Company", "country": "Egypt"},
            "source_material": [
                {
                    "source_id": "context-1",
                    "type": "prospect_context",
                    "text": "The customer needs a discovery meeting.",
                }
            ],
        },
    )

    assert response.status_code == 202
    assert response.json()["state"] == "queued"
    UUID(response.json()["questionnaire_run_id"])


def test_start_questionnaire_rejects_invalid_request() -> None:
    client = TestClient(create_application())

    response = client.post("/api/v1/discovery-questionnaire/runs", json={})

    assert response.status_code == 422


def test_status_is_not_available_before_state_storage_is_added() -> None:
    client = TestClient(create_application())

    response = client.get("/api/v1/discovery-questionnaire/runs/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 501
