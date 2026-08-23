"""Validation for incoming discovery-questionnaire requests."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from src.discovery_questionnaire.schemas.configuration import (
    QuestionnaireInputType,
)


class QuestionnaireSourceOrigin(StrEnum):
    """Where questionnaire information came from."""

    STAFF_PROVIDED = "staff_provided"
    FILE_EXTRACTED = "file_extracted"
    WEB_RESEARCH = "web_research"
    MODEL_INFERENCE = "model_inference"


class CustomerInformation(BaseModel):
    """Customer details supplied by the staff member."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    website: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=10_000)


class QuestionnaireSource(BaseModel):
    """One text source provided for questionnaire generation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=100)
    type: QuestionnaireInputType
    origin: QuestionnaireSourceOrigin = QuestionnaireSourceOrigin.STAFF_PROVIDED
    text: str = Field(min_length=1, max_length=100_000)
    revision: str | None = Field(default=None, max_length=100)


class QuestionnaireOptions(BaseModel):
    """Non-secret options for one questionnaire request."""

    model_config = ConfigDict(extra="forbid")

    languages: list[str] = Field(default_factory=lambda: ["ar", "en"], min_length=1)
    web_research_enabled: bool = True
    research_country: str | None = Field(default=None, max_length=100)

    @field_validator("languages")
    @classmethod
    def normalize_and_validate_languages(cls, value: list[str]) -> list[str]:
        """Normalize language codes and prevent duplicate document sections."""
        normalised = [language.strip().lower() for language in value]
        if len(set(normalised)) != len(normalised):
            raise ValueError("languages must not contain duplicates")
        return normalised


class StartQuestionnaireRequest(BaseModel):
    """Request accepted from Postman to start questionnaire generation."""

    model_config = ConfigDict(extra="forbid")

    questionnaire_identifier: str = Field(pattern=r"^[a-z][a-z0-9-]{2,99}$")
    idempotency_key: str = Field(min_length=1, max_length=128)
    customer: CustomerInformation
    source_material: list[QuestionnaireSource] = Field(min_length=1, max_length=100)
    options: QuestionnaireOptions = Field(default_factory=QuestionnaireOptions)
