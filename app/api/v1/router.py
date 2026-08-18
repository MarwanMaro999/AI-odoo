"""Version 1 API routing."""

from fastapi import APIRouter

from app.api.v1.endpoints.discovery_questionnaire import router as questionnaire_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(questionnaire_router)
