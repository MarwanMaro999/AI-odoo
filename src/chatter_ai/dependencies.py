"""Application wiring for chatter AI."""

import asyncio
from dataclasses import dataclass

import httpx

from fastapi import Request

from src.chatter_ai.service import ChatProvider, ChatRunRepository, ChatterAIOrchestrator, ChatterAIService, StoredChatRun
from src.core.config import Settings
from src.core.logging import get_logger
from src.engine.service import InProcessRunQueue
from src.engine.service import DatumDocxRenderer
from src.shared.llm.providers import GroqTextGenerator, HuggingFaceTextGenerator


@dataclass(frozen=True)
class ChatterAIContainer:
    service: ChatterAIService
    queue: InProcessRunQueue
    output_directory: object


def create_chatter_ai_container(settings: Settings) -> ChatterAIContainer:
    providers = [
        ChatProvider(
            "groq",
            GroqTextGenerator(settings, max_completion_tokens=settings.chatter_ai_groq_max_completion_tokens),
            settings.chatter_ai_groq_context_bytes,
        ),
        ChatProvider("huggingface", HuggingFaceTextGenerator(settings), settings.chatter_ai_fallback_context_bytes),
    ]
    repository = ChatRunRepository(settings.chatter_ai_state_dir)
    orchestrator = ChatterAIOrchestrator(
        repository,
        providers,
        DatumDocxRenderer(settings.engine_output_dir),
        _odoo_completion_callback(settings),
    )
    queue = InProcessRunQueue(orchestrator.process, settings.worker_concurrency)
    return ChatterAIContainer(ChatterAIService(repository, queue), queue, settings.engine_output_dir)


def get_chatter_ai_service(request: Request) -> ChatterAIService:
    return request.app.state.chatter_ai_container.service


def _odoo_completion_callback(settings: Settings):
    callback_url = settings.odoo_chatter_callback_url
    token = settings.datum_engine_api_auth_token
    logger = get_logger()

    async def notify(run: StoredChatRun) -> None:
        if not callback_url or token is None or not run.request.idempotency_key.startswith("odoo-chatter-"):
            return
        payload = run.status.model_dump(mode="json")
        headers = {"Authorization": "Bearer %s" % token.get_secret_value()}
        async with httpx.AsyncClient(timeout=settings.odoo_chatter_callback_timeout_seconds) as client:
            for delay in (0, 0.25, 0.75, 1.5):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    response = await client.post(callback_url, json=payload, headers=headers)
                    if response.is_success:
                        logger.info("odoo_chatter_callback_delivered", run_id=str(run.status.run_id))
                        return
                    logger.warning(
                        "odoo_chatter_callback_rejected",
                        run_id=str(run.status.run_id),
                        status_code=response.status_code,
                    )
                    if response.status_code in {400, 401, 403}:
                        break
                except httpx.HTTPError:
                    continue
        logger.warning("odoo_chatter_callback_failed", run_id=str(run.status.run_id))

    return notify
