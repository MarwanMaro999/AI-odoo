"""Application settings for Datum Engine."""

from functools import lru_cache
from pathlib import Path
import re
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: SecretStr | None = Field(default=None, repr=False)
    groq_fallback_api_key: SecretStr | None = Field(default=None, repr=False)
    # Legacy generic calls default to the same GPT-OSS primary. Responsibilities
    # use the explicit profiles below; Compound is never an implicit primary.
    groq_model: str = "qwen/qwen3.8-27b"
    groq_max_completion_tokens: int = Field(default=2048, ge=512, le=16_384)
    groq_timeout_seconds: float = Field(default=90.0, ge=10.0, le=300.0)
    groq_research_model: str = "groq/compound"
    hf_token: SecretStr | None = Field(default=None, repr=False)
    # Hugging Face is only a resilience path after Groq fails.  Llama is used
    # deliberately; do not silently substitute another vendor/model family.
    hf_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    hf_provider: str = "auto"
    hf_automatic_fallback_enabled: bool = False
    hf_max_completion_tokens: int = Field(default=2_000, ge=128, le=16_384)
    hf_timeout_seconds: float = Field(default=90.0, ge=10.0, le=300.0)
    database_url: SecretStr | None = Field(default=None, repr=False)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    # Provider-profile settings. Every routed responsibility carries an
    # independent input/output budget rather than sharing one broad limit.
    ai_prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    ai_prompt_guard_source_bytes: int = Field(default=1_000, ge=256, le=100_000)
    ai_prompt_guard_max_input_tokens: int = Field(default=384, ge=1, le=512)
    ai_prompt_guard_max_output_tokens: int = Field(default=16, ge=1, le=128)
    ai_prompt_guard_rpm: int = Field(default=30, ge=1)
    ai_prompt_guard_tpm: int = Field(default=15_000, ge=1)
    ai_prompt_guard_rpd: int = Field(default=14_400, ge=1)
    ai_prompt_guard_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    ai_prompt_guard_max_retries: int = Field(default=0, ge=0, le=5)

    ai_review_model: str = "qwen/qwen3.8-27b"
    ai_review_source_bytes: int = Field(default=12_000, ge=256, le=1_000_000)
    ai_review_max_input_tokens: int = Field(default=4_000, ge=1)
    ai_review_max_output_tokens: int = Field(default=750, ge=1)
    ai_review_rpm: int = Field(default=30, ge=1)
    ai_review_tpm: int = Field(default=8_000, ge=1)
    ai_review_rpd: int = Field(default=1_000, ge=1)
    ai_review_timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    ai_review_max_retries: int = Field(default=1, ge=0, le=5)

    ai_summary_model: str = "qwen/qwen3.6-27b"
    ai_summary_source_bytes: int = Field(default=6_000, ge=256, le=1_000_000)
    ai_summary_max_input_tokens: int = Field(default=2_000, ge=1)
    ai_summary_max_output_tokens: int = Field(default=256, ge=1)
    ai_summary_rpm: int = Field(default=30, ge=1)
    ai_summary_tpm: int = Field(default=8_000, ge=1)
    ai_summary_rpd: int = Field(default=1_000, ge=1)
    ai_summary_timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    ai_summary_max_retries: int = Field(default=1, ge=0, le=5)

    # GPT-OSS is the primary document model. Compound is a deliberately
    # separate fallback with its own admission and completion budgets.
    ai_generation_model: str = "qwen/qwen3.8-27b"
    ai_generation_enabled: bool = True
    ai_generation_source_bytes: int = Field(default=14_000, ge=256, le=1_000_000)
    ai_generation_max_input_tokens: int = Field(default=7_000, ge=1)
    ai_generation_max_output_tokens: int = Field(default=2_000, ge=1)
    ai_generation_rpm: int = Field(default=30, ge=1)
    ai_generation_tpm: int = Field(default=70_000, ge=1)
    ai_generation_rpd: int = Field(default=250, ge=1)
    ai_generation_timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    ai_generation_max_retries: int = Field(default=2, ge=0, le=5)
    ai_generation_fallback_enabled: bool = True
    ai_generation_fallback_model: str = "qwen/qwen3.6-27b"
    ai_generation_fallback_source_bytes: int = Field(default=8_000, ge=256, le=1_000_000)
    ai_generation_fallback_max_input_tokens: int = Field(default=4_000, ge=1)
    ai_generation_fallback_max_output_tokens: int = Field(default=1_500, ge=1)
    ai_generation_fallback_rpm: int = Field(default=30, ge=1)
    ai_generation_fallback_tpm: int = Field(default=8_000, ge=1)
    ai_generation_fallback_rpd: int = Field(default=1_000, ge=1)
    ai_generation_fallback_timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    ai_generation_fallback_max_retries: int = Field(default=1, ge=0, le=5)
    ai_review_fallback_enabled: bool = True
    ai_review_fallback_model: str = "qwen/qwen3.6-27b"
    ai_review_fallback_source_bytes: int = Field(default=6_000, ge=256, le=1_000_000)
    ai_review_fallback_max_input_tokens: int = Field(default=3_000, ge=1)
    ai_review_fallback_max_output_tokens: int = Field(default=750, ge=1)
    ai_review_fallback_rpm: int = Field(default=30, ge=1)
    ai_review_fallback_tpm: int = Field(default=8_000, ge=1)
    ai_review_fallback_rpd: int = Field(default=1_000, ge=1)
    ai_review_fallback_timeout_seconds: float = Field(default=90.0, ge=1.0, le=300.0)
    ai_review_fallback_max_retries: int = Field(default=1, ge=0, le=5)
    # HF auto-routing has no fixed account quota. These are Datum's own
    # conservative circuit-breaker caps for the Llama fallback path.
    hf_fallback_source_bytes: int = Field(default=12_000, ge=256, le=1_000_000)
    hf_fallback_max_input_tokens: int = Field(default=6_000, ge=1)
    hf_fallback_rpm: int = Field(default=5, ge=1)
    hf_fallback_tpm: int = Field(default=40_000, ge=1)
    hf_fallback_rpd: int = Field(default=100, ge=1)
    hf_fallback_max_retries: int = Field(default=0, ge=0, le=5)
    ai_embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    ai_embedding_chunk_bytes: int = Field(default=1_000, ge=128, le=8_000)
    ai_embedding_timeout_seconds: float = Field(default=45.0, ge=5.0, le=300.0)
    chatter_ai_embedding_max_chunks_per_run: int = Field(default=4, ge=0, le=100)
    chatter_ai_embedding_concurrency: int = Field(default=4, ge=1, le=16)
    ai_summary_min_new_sources: int = Field(default=3, ge=1, le=100)
    ai_summary_max_new_sources_per_run: int = Field(default=12, ge=1, le=500)
    datum_engine_api_auth_token: SecretStr | None = Field(default=None, repr=False)
    odoo_chatter_callback_url: str | None = None
    odoo_run_callback_url: str | None = None
    odoo_callback_signing_secret: SecretStr | None = Field(default=None, repr=False)
    odoo_chatter_callback_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    tavily_api_key: SecretStr | None = Field(default=None, repr=False)
    registry_path: Path | None = None
    log_level: str = "INFO"
    log_format: str = Field(default="console", pattern=r"^(console|json)$")
    worker_concurrency: int = Field(default=2, ge=1, le=32)
    dev_output_dir: Path = Path("./.runtime/outputs")
    engine_state_dir: Path = Path("./.runtime/engine-state")
    chatter_ai_state_dir: Path = Path("./.runtime/chatter-ai-state")
    engine_output_dir: Path = Path("./.runtime/engine-outputs")
    engine_demo_registry_path: Path = Path("C:/ProgramData/OdooTec/datum-engine-registry")
    prompt_registry_path: Path = Path("C:/ProgramData/OdooTec/datum-engine-prompts")
    engine_allow_demo_outputs: bool = False
    # Keep Groq free-tier requests below its TPM admission limit after prompt
    # overhead and the reserved completion are included.
    engine_max_source_bytes: int = Field(default=14_000, ge=4_000, le=2_000_000)
    engine_quality_attempts: int = Field(default=3, ge=1, le=5)
    engine_session_retrieval_max_sources: int = Field(default=24, ge=1, le=500)
    engine_session_retrieval_max_bytes: int = Field(default=40_000, ge=1_000, le=1_000_000)
    # Compound needs prompt headroom for its answer.  A compact Chatter context
    # keeps normal conversations under its input limit and avoids slow fallback.
    # Groq Compound counts the full rendered prompt, not just retained record
    # context.  Keep the context budget at the minimum so system instructions
    # and a normal Log Note stay below its request-size limit.
    chatter_ai_groq_context_bytes: int = Field(default=256, ge=256, le=1_000_000)
    chatter_ai_fallback_context_bytes: int = Field(default=28_000, ge=4_000, le=1_000_000)
    chatter_ai_groq_max_completion_tokens: int = Field(default=256, ge=128, le=4_096)
    chatter_ai_retrieval_max_sources: int = Field(default=40, ge=1, le=500)
    chatter_ai_retrieval_max_bytes: int = Field(default=48_000, ge=1_000, le=1_000_000)
    ai_job_lease_seconds: int = Field(default=120, ge=30, le=900)
    ai_job_poll_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    ai_job_max_attempts: int = Field(default=3, ge=1, le=10)
    max_upload_size_mb: int = Field(default=20, ge=1, le=100)
    max_upload_files: int = Field(default=5, ge=1, le=20)
    document_extraction_timeout_seconds: float = Field(default=30.0, ge=5.0, le=120.0)
    document_extraction_max_pdf_pages: int = Field(default=100, ge=1, le=1_000)
    document_extraction_max_text_bytes: int = Field(default=500_000, ge=10_000, le=5_000_000)
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

    @property
    def async_database_url(self) -> str | None:
        """Return a SQLAlchemy Psycopg URL without exposing credentials."""
        if self.database_url is None:
            return None
        return re.sub(
            r"^(postgres|postgresql):",
            "postgresql+psycopg:",
            self.database_url.get_secret_value(),
            count=1,
        )

@lru_cache
def get_settings() -> Settings:
    return Settings()
