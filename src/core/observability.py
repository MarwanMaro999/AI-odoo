"""Small local request-correlation middleware."""

import time
from uuid import uuid4

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Add a correlation identifier without logging source material or prompts."""

    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        started = time.perf_counter()
        response_status = 500
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            structlog.get_logger("datum_engine").info(
                "http_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response_status,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            structlog.contextvars.unbind_contextvars("correlation_id")
