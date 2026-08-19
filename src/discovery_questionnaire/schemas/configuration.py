"""Validation rules for the external discovery-questionnaire YAML file."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class QuestionnaireOutputAccess(StrEnum):
    """Who may receive the generated questionnaire."""

    CLIENT_PERMITTED = "client_permitted"


class QuestionnaireInputType(StrEnum):
    """Information the questionnaire generator can use."""

    PROSPECT_CONTEXT = "prospect_context"
    ATTACHMENT = "attachment"
    WEB_RESEARCH = "web_research"


class QuestionnaireInputRequirement(BaseModel):
    """One input type declared in the external questionnaire configuration."""

    model_config = ConfigDict(extra="forbid")

    type: QuestionnaireInputType
    required: bool


class QuestionnaireOutputDefinition(BaseModel):
    """The document produced by the questionnaire generator."""

    model_config = ConfigDict(extra="forbid")

    document_type: str = Field(min_length=1, max_length=100)
    distribution_class: QuestionnaireOutputAccess


class QuestionnaireConfiguration(BaseModel):
    """Private configuration loaded from the external questionnaire YAML file."""

    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(pattern=r"^[a-z][a-z0-9-]{2,99}$")
    version: str = Field(min_length=1, max_length=50)
    kind: str = Field(pattern=r"^generator$")
    accepted_source_material: list[QuestionnaireInputRequirement] = Field(
        min_length=1
    )
    outputs: list[QuestionnaireOutputDefinition] = Field(min_length=1)
    instruction: str = Field(min_length=1, repr=False, exclude=True)


class PublicQuestionnaireConfiguration(BaseModel):
    """Safe questionnaire metadata that can be returned to API clients."""

    model_config = ConfigDict(extra="forbid")

    identifier: str
    version: str
    kind: str
    accepted_source_material: list[QuestionnaireInputRequirement]
    outputs: list[QuestionnaireOutputDefinition]

    @classmethod
    def create_public_view(
        cls, configuration: QuestionnaireConfiguration
    ) -> "PublicQuestionnaireConfiguration":
        """Create public metadata without exposing the private instruction."""
        return cls(
            identifier=configuration.identifier,
            version=configuration.version,
            kind=configuration.kind,
            accepted_source_material=configuration.accepted_source_material,
            outputs=configuration.outputs,
        )
