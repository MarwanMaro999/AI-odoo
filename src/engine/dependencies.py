"""Datum Engine application wiring."""

from dataclasses import dataclass

from src.core.config import Settings
from src.core.prompt_security import GroqPromptInjectionScanner, PromptSecurityGate
from src.engine.registry import SkillRegistry
from src.engine.prompt_registry import PromptRegistry
from src.engine.service import DatumDocxRenderer, DatumOrchestrator, EngineService, PersistentRunRepository
from src.engine.durable_queue import ENGINE_JOB_TYPE, DurableEngineQueue, engine_job_handler
from src.core.model_profiles import ModelResponsibility
from src.db.database import DatabaseRuntime
from src.engine.sessions import EngineSessionStore
from src.engine.clarifications import ClarificationService
from src.engine.reviews import ReviewPersistenceService
from src.engine.callbacks import OdooRunStatusCallback
from src.shared.llm.runtime import build_runtime_model_router
from src.shared.llm.quota import NeonModelQuotaGuard
from src.shared.embeddings import HuggingFaceEmbeddingProvider
from src.shared.queue.durable_jobs import DurableJobRepository, DurableJobWorker
from src.shared.web_research.research_service import CompanyResearchService


@dataclass(frozen=True)
class EngineContainer:
    service: EngineService
    queue: DurableEngineQueue
    output_directory: object
    database: DatabaseRuntime
    clarifications: ClarificationService


def create_engine_container(settings: Settings) -> EngineContainer:
    database = DatabaseRuntime(settings)
    repository = PersistentRunRepository(settings.engine_state_dir)
    registry = SkillRegistry(settings.registry_path or settings.engine_demo_registry_path)
    renderer = DatumDocxRenderer(settings.engine_output_dir)
    router = build_runtime_model_router(
        settings, structured_generation=True, quota_guard=NeonModelQuotaGuard(database),
    )
    orchestrator = DatumOrchestrator(
        repository,
        registry,
        renderer,
        settings.run_max_attempts,
        CompanyResearchService(settings),
        router.bind(ModelResponsibility.ENGLISH_GENERATION),
        PromptRegistry(settings.prompt_registry_path),
        settings.engine_allow_demo_outputs,
        settings.engine_max_source_bytes,
        settings.engine_quality_attempts,
        PromptSecurityGate(GroqPromptInjectionScanner(settings)),
        router.bind(ModelResponsibility.STRUCTURED_REVIEW),
        router.bind(ModelResponsibility.ARABIC_GENERATION),
        ReviewPersistenceService(database),
        settings.ai_generation_source_bytes,
        min(
            settings.ai_review_source_bytes,
            settings.ai_review_max_input_tokens * 2,
        ),
        OdooRunStatusCallback(settings),
    )
    jobs = DurableJobRepository(database, settings)
    worker = DurableJobWorker(jobs, {ENGINE_JOB_TYPE: engine_job_handler(orchestrator)}, settings)
    queue = DurableEngineQueue(repository, jobs, worker)
    return EngineContainer(
        EngineService(
            repository,
            queue,
            EngineSessionStore(
                database,
                settings,
                HuggingFaceEmbeddingProvider(settings),
                router.bind(ModelResponsibility.SESSION_SUMMARY),
            ),
        ),
        queue,
        settings.engine_output_dir,
        database,
        ClarificationService(database),
    )
