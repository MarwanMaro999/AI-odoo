from pathlib import Path

import pytest

from src.core.exceptions import QuestionnaireConfigurationNotFound
from src.discovery_questionnaire.services.questionnaire_registry import QuestionnaireRegistry


def test_registry_raises_not_found_for_missing_configuration(tmp_path: Path) -> None:
    registry = QuestionnaireRegistry(tmp_path)

    with pytest.raises(QuestionnaireConfigurationNotFound):
        registry.load("gen-discovery-questions")
