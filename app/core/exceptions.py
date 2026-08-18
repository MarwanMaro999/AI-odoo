"""Safe questionnaire API errors that never expose private model instructions."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger


class QuestionnaireError(Exception):
    """Base exception with a safe public response."""

    status_code = 500
    error_code = "questionnaire_error"
    public_message = "The questionnaire request could not be completed."


class QuestionnaireConfigurationNotFound(QuestionnaireError):
    """Raised when the requested questionnaire configuration does not exist."""

    status_code = 404
    error_code = "questionnaire_configuration_not_found"
    public_message = "The requested questionnaire configuration was not found."


class QuestionnaireRequestConflict(QuestionnaireError):
    """Raised when a request conflicts with previously submitted data."""

    status_code = 409
    error_code = "questionnaire_request_conflict"
    public_message = "The questionnaire request conflicts with an existing request."


class QuestionnaireProviderUnavailable(QuestionnaireError):
    """Raised when all configured model providers are temporarily unavailable."""

    status_code = 503
    error_code = "questionnaire_provider_unavailable"
    public_message = "The questionnaire service is temporarily unavailable."


async def questionnaire_error_handler(
    _: Request, error: QuestionnaireError
) -> JSONResponse:
    """Return only the explicitly safe properties of a known questionnaire error."""
    get_logger().warning(
        "questionnaire_request_failed",
        error_code=error.error_code,
        status_code=error.status_code,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={
            "error": {
                "code": error.error_code,
                "message": error.public_message,
            }
        },
    )


async def unexpected_error_handler(_: Request, error: Exception) -> JSONResponse:
    """Hide unexpected implementation details from API clients."""
    get_logger().error(
        "unexpected_questionnaire_error",
        error_type=type(error).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected questionnaire service error occurred.",
            }
        },
    )


def register_questionnaire_exception_handlers(app: FastAPI) -> None:
    """Attach safe exception handlers when the FastAPI app is created."""
    app.add_exception_handler(QuestionnaireError, questionnaire_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
