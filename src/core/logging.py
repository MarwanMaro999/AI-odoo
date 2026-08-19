"""Structured logging that prevents private questionnaire instructions leaking."""

import logging
from collections.abc import Mapping
from typing import Any

import structlog


_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key",
        "authorization",
        "instruction",
        "prompt",
        "system_prompt",
        "token",
    }
)
_REDACTED_VALUE = "[REDACTED]"


def redact_private_fields(
    _: Any, __: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """Redact private values recursively before an event reaches a log sink."""
    return _redact_mapping(event_data)


def _redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in values.items():
        if key.lower() in _SENSITIVE_FIELD_NAMES:
            redacted[key] = _REDACTED_VALUE
        elif isinstance(value, Mapping):
            redacted[key] = _redact_mapping(value)
        elif isinstance(value, list):
            redacted[key] = [
                _redact_mapping(item) if isinstance(item, Mapping) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def configure_logging(log_level: str = "INFO") -> None:
    """Configure JSON logs with instruction and credential redaction."""
    resolved_log_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=resolved_log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_private_fields,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(resolved_log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return the shared logger used for safe operational metadata only."""
    return structlog.get_logger("datum_engine")
