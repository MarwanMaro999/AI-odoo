"""Authenticated lifecycle callbacks from document runs to Odoo."""

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from src.core.config import Settings
from src.core.logging import get_logger


class OdooRunStatusCallback:
    """Deliver idempotent run snapshots; polling remains the recovery path."""

    def __init__(self, settings: Settings) -> None:
        self._url = settings.odoo_run_callback_url
        self._token = settings.datum_engine_api_auth_token
        self._secret = settings.odoo_callback_signing_secret or self._token
        self._timeout = settings.odoo_chatter_callback_timeout_seconds

    async def __call__(self, run: Any) -> None:
        if not self._url or self._token is None or self._secret is None:
            return
        payload = run.status.model_dump(mode="json")
        payload.update({
            "event_id": "%s:%s" % (run.status.run_id, run.status.status_revision),
            "record_model": run.request.record_model,
            "record_id": run.request.record_id,
        })
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self._secret.get_secret_value().encode("utf-8"),
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "Authorization": "Bearer %s" % self._token.get_secret_value(),
            "Content-Type": "application/json",
            "X-Datum-Timestamp": timestamp,
            "X-Datum-Signature": signature,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for delay in (0, 0.25, 0.75, 1.5):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await client.post(self._url, content=body, headers=headers)
                    if response.is_success:
                        get_logger().info(
                            "odoo_run_callback_delivered",
                            run_id=str(run.status.run_id),
                            stage=run.status.progress_stage,
                        )
                        return
                    if response.status_code in {400, 401, 403}:
                        break
                except httpx.HTTPError:
                    continue
        get_logger().warning(
            "odoo_run_callback_failed",
            run_id=str(run.status.run_id),
            stage=run.status.progress_stage,
        )
