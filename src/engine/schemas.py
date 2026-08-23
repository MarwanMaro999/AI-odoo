"""Provider-neutral contracts for Odoo and the Datum Engine."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SkillKind(StrEnum):
    GENERATOR = "generator"
    AUDITOR = "auditor"


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DistributionClass(StrEnum):
    CLIENT_PERMITTED = "client_permitted"
    INTERNAL_ONLY = "internal_only"


class Verdict(StrEnum):
    CLEARED = "cleared"
    NOT_CLEARED = "not_cleared"


class SourceMaterial(BaseModel):
    """Immutable Odoo source-artifact revision supplied to one execution."""

    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=128)
    revision: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=500_000)
    content_uri: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    mime_type: str | None = Field(default=None, max_length=255)


class SkillReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str = Field(pattern=r"^[a-z][a-z0-9-]{2,99}$")
    version: str = Field(min_length=1, max_length=50)


class StartRunRequest(BaseModel):
    """The entire Odoo-to-AI contract; it intentionally contains no prompt text."""

    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    engagement_id: str = Field(min_length=1, max_length=128)
    source_set_revision: str = Field(min_length=1, max_length=128)
    skill: SkillReference
    source_material: list[SourceMaterial] = Field(min_length=1, max_length=100)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_type: str
    distribution_class: DistributionClass


class PublicSkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str
    version: str
    kind: SkillKind
    accepted_source_material: list[str]
    outputs: list[OutputDefinition]
    prerequisite_document_types: list[str] = Field(default_factory=list)
    issues_verdict: bool = False


class RunOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_id: UUID
    document_type: str
    distribution_class: DistributionClass
    filename: str
    media_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    download_url: str
    preview_url: str
    source_references: list[str] = Field(default_factory=list)
    skill_version: str | None = None
    template_version: str | None = None
    validation_summary: dict[str, Any] = Field(default_factory=dict)
    source_text: str | None = None


class FindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_key: str
    severity: str
    category: str
    location: str
    summary: str
    resolution_route: str
    evidence: str = Field(min_length=1, max_length=4_000)
    prior_outcome: str | None = None


class RunLogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occurred_at: datetime
    step: str
    outcome: str
    duration_ms: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    state: RunState
    skill: SkillReference
    engagement_id: str
    source_set_revision: str
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_count: int = 0
    outputs: list[RunOutput] = Field(default_factory=list)
    verdict: Verdict | None = None
    findings: list[FindingPayload] = Field(default_factory=list)
    failure_code: str | None = None
    log: list[RunLogEntry] = Field(default_factory=list)
