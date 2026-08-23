"""Response contracts for discovery-questionnaire processing."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.discovery_questionnaire.schemas.configuration import (
    QuestionnaireOutputAccess,
)


class QuestionnaireRunState(StrEnum):
    """Visible state of an asynchronous questionnaire request."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QuestionnaireAcceptedResponse(BaseModel):
    """Immediate response after a questionnaire request is accepted."""

    questionnaire_run_id: UUID
    state: QuestionnaireRunState = QuestionnaireRunState.QUEUED


class QuestionnaireOutput(BaseModel):
    """Metadata for a completed questionnaire document."""

    model_config = ConfigDict(extra="forbid")

    output_id: UUID
    document_type: str
    distribution_class: QuestionnaireOutputAccess
    media_type: str
    filename: str
    download_url: str | None = None


class QuestionnaireProcessingLog(BaseModel):
    """Safe processing metadata, with no private instruction field."""

    model_config = ConfigDict(extra="forbid")

    occurred_at: datetime
    step: str
    outcome: str
    duration_ms: int | None = Field(default=None, ge=0)
    provider: str | None = None
    model: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class QuestionnaireStatusResponse(BaseModel):
    """Current questionnaire state and safe output metadata."""

    model_config = ConfigDict(extra="forbid")

    questionnaire_run_id: UUID
    state: QuestionnaireRunState
    questionnaire_identifier: str
    questionnaire_version: str | None = None
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    outputs: list[QuestionnaireOutput] = Field(default_factory=list)
    failure_code: str | None = None
