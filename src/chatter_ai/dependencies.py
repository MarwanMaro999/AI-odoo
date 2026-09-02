"""Application wiring for chatter AI."""

import asyncio
from dataclasses import dataclass

import httpx

from fastapi import Request

from src.chatter_ai.service import ChatProvider, ChatRunRepository, ChatterAIOrchestrator, ChatterAIService, StoredChatRun
from src.chatter_ai.durable_queue import CHATTER_JOB_TYPE, DurableChatterQueue, chatter_job_handler
from src.chatter_ai.sessions import ChatterSessionStore
from src.core.config import Settings
from src.db.database import DatabaseRuntime
from src.core.prompt_security import GroqPromptInjectionScanner, PromptSecurityGate
from src.core.logging import get_logger
from src.engine.service import DatumDocxRenderer
from src.shared.queue.durable_jobs import DurableJobRepository, DurableJobWorker
from src.core.model_profiles import ModelResponsibility
from src.shared.llm.runtime import build_runtime_model_router
from src.shared.llm.quota import NeonModelQuotaGuard
from src.shared.embeddings import HuggingFaceEmbeddingProvider


@dataclass(frozen=True)
class ChatterAIContainer:
    service: ChatterAIService
    queue: DurableChatterQueue
    output_directory: object
    database: DatabaseRuntime


def create_chatter_ai_container(settings: Settings) -> ChatterAIContainer:
    database = DatabaseRuntime(settings)
    quota_guard = NeonModelQuotaGuard(database)
    router = build_runtime_model_router(settings, quota_guard=quota_guard)
    providers = [
        ChatProvider(
            "groq_with_qwen_fallback",
            router.bind(ModelResponsibility.ENGLISH_GENERATION),
            min(
                settings.chatter_ai_fallback_context_bytes,
                max(4_000, settings.ai_generation_source_bytes - 1_500),
            ),
        ),
    ]
    repository = ChatRunRepository(settings.chatter_ai_state_dir)
    security_gate = PromptSecurityGate(GroqPromptInjectionScanner(settings))
    sessions = ChatterSessionStore(
        database,
        settings,
        security_gate,
        HuggingFaceEmbeddingProvider(settings),
        router.bind(ModelResponsibility.SESSION_SUMMARY),
    )
    orchestrator = ChatterAIOrchestrator(
        repository,
        providers,
        DatumDocxRenderer(settings.engine_output_dir),
        _odoo_completion_callback(settings),
        sessions=sessions,
    )
    jobs = DurableJobRepository(database, settings)
    worker = DurableJobWorker(jobs, {CHATTER_JOB_TYPE: chatter_job_handler(orchestrator)}, settings)
    queue = DurableChatterQueue(repository, jobs, worker)
    return ChatterAIContainer(
        ChatterAIService(repository, queue, sessions), queue, settings.engine_output_dir, database,
    )


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
