"""Top-level versioned HTTP routing."""

from fastapi import APIRouter

from src.discovery_questionnaire.controller import router as questionnaire_router
from src.engine.api import router as engine_router
from src.chatter_ai.api import router as chatter_ai_router

def create_api_router() -> APIRouter:
    """Expose the local asynchronous APIs used by Odoo."""
    router = APIRouter(prefix="/api/v1")
    router.include_router(questionnaire_router)
    router.include_router(engine_router)
    router.include_router(chatter_ai_router)
    return router


api_router = create_api_router()
