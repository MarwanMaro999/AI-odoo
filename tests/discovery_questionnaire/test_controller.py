from pathlib import Path

from fastapi.testclient import TestClient

from src.core.config import Settings
from src.main import create_application


def _create_client(registry_path: Path) -> TestClient:
    settings = Settings(registry_path=registry_path)
    return TestClient(create_application(settings))


def _write_questionnaire_configuration(registry_path: Path) -> None:
    registry_path.mkdir(exist_ok=True)
    (registry_path / "gen-discovery-questions.yaml").write_text(
        """identifier: gen-discovery-questions
version: '0.1-demo'
kind: generator
accepted_source_material:
  - type: prospect_context
    required: true
outputs:
  - document_type: discovery_questionnaire
    distribution_class: client_permitted
instruction: Private demo instruction.
""",
        encoding="utf-8",
    )


def _request_body(idempotency_key: str = "example-company-001") -> dict[str, object]:
    return {
        "questionnaire_identifier": "gen-discovery-questions",
        "idempotency_key": idempotency_key,
        "customer": {"name": "Example Company", "country": "Egypt"},
        "source_material": [
            {
                "source_id": "context-1",
                "type": "prospect_context",
                "text": "The customer needs a discovery meeting.",
            }
        ],
    }


def test_controller_creates_and_reads_queued_run(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)

    created = client.post("/api/v1/discovery-questionnaire/runs", json=_request_body())
    run_id = created.json()["questionnaire_run_id"]
    stored = client.get(f"/api/v1/discovery-questionnaire/runs/{run_id}")

    assert created.status_code == 202
    assert stored.status_code == 200
    assert stored.json()["state"] == "queued"
    assert stored.json()["questionnaire_version"] == "0.1-demo"


def test_controller_reuses_identical_idempotent_request(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)

    first = client.post("/api/v1/discovery-questionnaire/runs", json=_request_body())
    second = client.post("/api/v1/discovery-questionnaire/runs", json=_request_body())

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["questionnaire_run_id"] == second.json()["questionnaire_run_id"]


def test_controller_returns_not_found_for_unknown_run(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)

    response = client.get(
        "/api/v1/discovery-questionnaire/runs/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "questionnaire_run_not_found"


def test_controller_rejects_idempotency_key_reused_with_new_data(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)
    client.post("/api/v1/discovery-questionnaire/runs", json=_request_body())

    response = client.post(
        "/api/v1/discovery-questionnaire/runs",
        json=_request_body(idempotency_key="example-company-001")
        | {"customer": {"name": "Different Company"}},
    )

    assert response.status_code == 409


def test_controller_returns_safe_public_configuration(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)

    response = client.get(
        "/api/v1/discovery-questionnaire/configuration/gen-discovery-questions"
    )

    assert response.status_code == 200
    assert response.json()["identifier"] == "gen-discovery-questions"
    assert "instruction" not in response.json()


def test_demo_page_is_available(tmp_path: Path) -> None:
    _write_questionnaire_configuration(tmp_path)
    client = _create_client(tmp_path)

    response = client.get("/demo")

    assert response.status_code == 200
    assert "Datum Engine" in response.text
    assert "Generate Arabic + English questionnaire" in response.text
