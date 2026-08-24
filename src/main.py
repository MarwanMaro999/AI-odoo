"""Datum Engine FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.router import create_api_router
from src.api.demo import router as demo_router
from src.core.config import Settings, get_settings
from src.core.error_handlers import register_exception_handlers
from src.core.logging import configure_logging
from src.core.observability import RequestCorrelationMiddleware
from src.discovery_questionnaire.dependencies import (
    create_questionnaire_container,
)
from src.engine.dependencies import create_engine_container


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application without starting workers or model providers."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await application.state.questionnaire_container.queue.start()
        await application.state.engine_container.queue.start()
        yield
        await application.state.engine_container.queue.stop()
        await application.state.questionnaire_container.queue.stop()

    application = FastAPI(
        title="Datum Engine",
        version="0.1.0",
        description="Internal asynchronous AI document execution service.",
        lifespan=lifespan,
    )
    application.add_middleware(RequestCorrelationMiddleware)
    application.state.settings = settings
    application.state.questionnaire_container = create_questionnaire_container(settings)
    application.state.engine_container = create_engine_container(settings)
    register_exception_handlers(application)

    @application.get("/health", include_in_schema=False)
    async def health_check() -> dict[str, str]:
        """Lightweight liveness endpoint that never waits for a worker or provider."""
        return {"status": "ok"}

    application.include_router(create_api_router())
    application.include_router(demo_router)
    return application


app = create_application()
