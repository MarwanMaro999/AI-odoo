"""Datum Engine FastAPI application."""

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_questionnaire_exception_handlers
from app.core.logging import configure_logging


def create_application() -> FastAPI:
    """Create the HTTP application without starting workers or model providers."""
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title="Datum Engine",
        version="0.1.0",
        description="Internal discovery-questionnaire generation service.",
    )
    register_questionnaire_exception_handlers(application)
    application.include_router(api_router)
    return application


app = create_application()
