import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from uuid import uuid4

from src.core.config import Settings
from src.engine.callbacks import OdooRunStatusCallback
from src.engine.schemas import RunState, RunStatus, SkillReference
from src.shared.text import html_to_plain_text


def test_html_to_plain_text_removes_ai_markup() -> None:
    assert html_to_plain_text("<p>Please confirm <strong>the date</strong>.</p>") == "Please confirm the date."


def test_document_callback_is_signed_and_contains_lifecycle_snapshot(monkeypatch) -> None:
    captured = {}

    class Response:
        is_success = True
        status_code = 200

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, content, headers):
            captured.update(url=url, content=content, headers=headers)
            return Response()

    monkeypatch.setattr("src.engine.callbacks.httpx.AsyncClient", Client)
    settings = Settings(
        datum_engine_api_auth_token="token",
        odoo_callback_signing_secret="secret",
        odoo_run_callback_url="http://odoo/datum-engine/run/callback",
    )
    status = RunStatus(
        run_id=uuid4(),
        state=RunState.RUNNING,
        skill=SkillReference(identifier="gen-sow", version="1.0.0"),
        engagement_id="12",
        source_set_revision="1",
        submitted_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        status_revision=3,
        progress_stage="reviewing",
        progress_message="Reviewing quality.",
    )
    run = SimpleNamespace(
        status=status,
        request=SimpleNamespace(record_model="datum.engagement", record_id=12),
    )

    asyncio.run(OdooRunStatusCallback(settings)(run))

    payload = json.loads(captured["content"])
    assert payload["event_id"].endswith(":3")
    assert payload["progress_stage"] == "reviewing"
    signed = captured["headers"]["X-Datum-Timestamp"].encode("ascii") + b"." + captured["content"]
    assert captured["headers"]["X-Datum-Signature"] == hmac.new(
        b"secret", signed, hashlib.sha256,
    ).hexdigest()
