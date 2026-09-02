from src.core.config import Settings
from src.db.database import DatabaseRuntime
from src.db.models import AIClarification, AIContextChunk, AIFinding, AIJob, AIModelUsageWindow, AIReviewCycle, AISession, AISessionSource, AISessionTurn


def test_database_url_is_normalized_for_async_psycopg() -> None:
    settings = Settings(database_url="postgresql://user:password@example.test/neondb?sslmode=require")

    assert settings.async_database_url == "postgresql+psycopg://user:password@example.test/neondb?sslmode=require"


def test_ai_foundation_models_have_expected_table_names() -> None:
    assert [model.__tablename__ for model in (
        AISession,
        AISessionSource,
        AISessionTurn,
        AIContextChunk,
        AIJob,
        AIModelUsageWindow,
        AIReviewCycle,
        AIFinding,
        AIClarification,
    )] == [
        "ai_sessions",
        "ai_session_sources",
        "ai_session_turns",
        "ai_context_chunks",
        "ai_jobs",
        "ai_model_usage_windows",
        "ai_review_cycles",
        "ai_findings",
        "ai_clarifications",
    ]


def test_database_runtime_requires_a_database_url() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        DatabaseRuntime(Settings(database_url=None))
