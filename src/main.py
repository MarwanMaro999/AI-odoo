"""Datum Engine FastAPI application."""

from fastapi import FastAPI

from src.api.router import api_router
from src.core.config import Settings, get_settings
from src.core.error_handlers import register_exception_handlers
from src.core.logging import configure_logging
from src.discovery_questionnaire.dependencies import (
    create_questionnaire_container,
)


def create_application(settings: Settings | None = None) -> FastAPI:
    """Create the HTTP application without starting workers or model providers."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Datum Engine",
        version="0.1.0",
        description="Internal discovery-questionnaire generation service.",
    )
    application.state.questionnaire_container = create_questionnaire_container(settings)
    register_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_application()
