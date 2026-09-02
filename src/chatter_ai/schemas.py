"""Public Odoo-to-FastAPI contracts for shared chatter AI runs."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatCommand(StrEnum):
    CHAT = "chat"
    QUESTION = "question"
    STRS = "strs"
    SOW = "sow"


class ChatRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ContextMode(StrEnum):
    BASELINE = "baseline"
    DELTA = "delta"


class ContextUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=4_000_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatterAIStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    record_model: str = Field(pattern=r"^[a-z][a-z0-9_.]+$")
    record_id: int = Field(gt=0)
    requester_id: int = Field(gt=0)
    session_id: UUID | None = None
    workflow: str = Field(default="chatter", pattern=r"^[a-z][a-z0-9_]{0,63}$")
    context_mode: ContextMode = ContextMode.BASELINE
    command: ChatCommand = ChatCommand.CHAT
    user_message: str = Field(min_length=1, max_length=100_000)
    context: list[ContextUnit] = Field(default_factory=list, max_length=2_000)


class ProviderAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    outcome: str
    reason: str | None = None


class ChatterAIRunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    session_id: UUID | None = None
    state: ChatRunState
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    command: ChatCommand
    reply_markdown: str | None = None
    artifact_filename: str | None = None
    artifact_document_type: str | None = None
    artifact_media_type: str | None = None
    artifact_download_url: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    context_source_count: int | None = None
    provider_attempts: list[ProviderAttempt] = Field(default_factory=list)
