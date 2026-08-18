from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: str = "gemini-3.6-flash"
    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_model: str = "openai/gpt-oss-20b"
    llm_provider_order: str = "gemini,groq"
    tavily_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_research_model: str = "groq/compound"
    search_provider_order: str = "tavily,groq_compound"
    registry_path: Path | None = None
    log_level: str = "INFO"
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    dev_output_dir: Path = Path("./.runtime/outputs")
    max_upload_size_mb: int = Field(default=20, ge=1, le=100)
    max_upload_files: int = Field(default=5, ge=1, le=20)
    run_max_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator("registry_path")
    @classmethod
    def require_absolute_registry_path(cls, value: Path | None) -> Path | None:
        """Keep the real registry outside the application repository."""
        if value is not None and not value.is_absolute():
            raise ValueError("REGISTRY_PATH must be an absolute path")
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
