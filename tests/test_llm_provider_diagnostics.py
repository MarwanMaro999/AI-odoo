from types import SimpleNamespace

from src.shared.llm.providers import GroqTextGenerator


def test_provider_failure_diagnostics_include_safe_tpm_numbers() -> None:
    error = SimpleNamespace(
        status_code=413,
        response=SimpleNamespace(
            headers={"x-request-id": "req_123"},
            json=lambda: {"error": {"message": "TPM limit 8000, requested 12441 tokens."}},
        ),
    )
    diagnostics = GroqTextGenerator._provider_error_diagnostics(error)
    assert diagnostics["http_status"] == 413
    assert diagnostics["provider_request_id"] == "req_123"
    assert diagnostics["provider_limit"] == 8000
    assert diagnostics["provider_requested"] == 12441
    assert diagnostics["provider_limit_kind"] == "tpm"
