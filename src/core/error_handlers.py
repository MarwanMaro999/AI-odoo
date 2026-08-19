"""Safe HTTP error handlers for Datum Engine."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.exceptions import QuestionnaireError
from src.core.logging import get_logger


async def questionnaire_error_handler(
    _: Request, error: QuestionnaireError
) -> JSONResponse:
    """Return the explicitly safe fields of a known questionnaire error."""
    get_logger().warning(
        "questionnaire_request_failed",
        error_code=error.error_code,
        status_code=error.status_code,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={"error": {"code": error.error_code, "message": error.public_message}},
    )


async def unexpected_error_handler(_: Request, error: Exception) -> JSONResponse:
    """Hide unexpected implementation details from API clients."""
    get_logger().error(
        "unexpected_questionnaire_error", error_type=type(error).__name__
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


def register_exception_handlers(app: FastAPI) -> None:
    """Attach safe application-wide error handlers."""
    app.add_exception_handler(QuestionnaireError, questionnaire_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
