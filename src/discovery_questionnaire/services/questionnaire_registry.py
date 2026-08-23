"""External YAML configuration loading for the discovery questionnaire."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from src.core.exceptions import (
    QuestionnaireConfigurationInvalid,
    QuestionnaireConfigurationNotFound,
)
from src.discovery_questionnaire.schemas.configuration import (
    QuestionnaireConfiguration,
)


class QuestionnaireRegistry:
    """Loads private questionnaire configuration from outside the source repository."""

    def __init__(self, registry_path: Path | None) -> None:
        self._registry_path = registry_path

    def load(self, questionnaire_identifier: str) -> QuestionnaireConfiguration:
        """Load and validate one questionnaire YAML file by its identifier."""
        configuration_file = self._find_configuration_file(questionnaire_identifier)
        try:
            raw_configuration = yaml.safe_load(
                configuration_file.read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError) as error:
            raise QuestionnaireConfigurationInvalid() from error

        if not isinstance(raw_configuration, dict):
            raise QuestionnaireConfigurationInvalid()

        try:
            configuration = QuestionnaireConfiguration.model_validate(
                raw_configuration
            )
        except ValidationError as error:
            raise QuestionnaireConfigurationInvalid() from error

        if configuration.identifier != questionnaire_identifier:
            raise QuestionnaireConfigurationInvalid()
        return configuration

    def _find_configuration_file(self, questionnaire_identifier: str) -> Path:
        """Return the configured YAML file without searching application source code."""
        if self._registry_path is None:
            raise QuestionnaireConfigurationNotFound()

        configuration_file = self._registry_path / f"{questionnaire_identifier}.yaml"
        if not configuration_file.is_file():
            raise QuestionnaireConfigurationNotFound()
        return configuration_file
