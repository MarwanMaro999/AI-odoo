"""Top-level versioned HTTP routing."""

from fastapi import APIRouter

from src.discovery_questionnaire.controller import router as questionnaire_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(questionnaire_router)
