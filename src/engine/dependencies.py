"""Datum Engine application wiring."""

from dataclasses import dataclass

from src.core.config import Settings
from src.engine.registry import SkillRegistry
from src.engine.service import DatumDocxRenderer, DatumOrchestrator, EngineService, InProcessRunQueue, PersistentRunRepository
from src.shared.llm.providers import GroqTextGenerator
from src.shared.web_research.research_service import CompanyResearchService


@dataclass(frozen=True)
class EngineContainer:
    service: EngineService
    queue: InProcessRunQueue
    output_directory: object


def create_engine_container(settings: Settings) -> EngineContainer:
    repository = PersistentRunRepository(settings.engine_state_dir)
    registry = SkillRegistry(settings.registry_path or settings.engine_demo_registry_path)
    renderer = DatumDocxRenderer(settings.engine_output_dir)
    orchestrator = DatumOrchestrator(
        repository,
        registry,
        renderer,
        settings.run_max_attempts,
        CompanyResearchService(settings),
        GroqTextGenerator(settings),
    )
    queue = InProcessRunQueue(orchestrator.process, settings.worker_concurrency)
    return EngineContainer(EngineService(repository, queue), queue, settings.engine_output_dir)
