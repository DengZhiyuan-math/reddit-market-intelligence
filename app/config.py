"""Runtime settings for the Reddit Market Intelligence System."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.compliance.policies import AccessMode


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reddit_access_mode: AccessMode = AccessMode.PERSONAL
    reddit_commercial_approval_reference: str | None = None
    reddit_retention_policy_days: int = Field(default=2, ge=0)
    reddit_delete_removed_content: bool = True
    reddit_allow_business_context_without_approval: bool = False
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str | None = None
    reddit_ratelimit_seconds: int = Field(default=5, ge=0)
    reddit_min_remaining: float = Field(default=5.0, ge=0)
    reddit_retry_attempts: int = Field(default=3, ge=1)
    reddit_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    reddit_api_enabled: bool = True
    web_fallback_enabled: bool = False
    web_fallback_mode: str = "static"
    web_fallback_proxy_rotation_enabled: bool = False
    web_fallback_captcha_bypass_enabled: bool = False
    web_fallback_login_enabled: bool = False
    web_fallback_fake_user_agent_enabled: bool = False
    google_custom_search_api_key: str | None = None
    google_custom_search_engine_id: str | None = None
    project_registry_path: Path = Path("outputs/projects/projects.json")
    default_run_limit: int = Field(default=100, ge=1)
    database_url: str = "postgresql+psycopg://reddit_market_intel:reddit_market_intel@localhost:5432/reddit_market_intel"
    database_echo: bool = False
    embedding_provider: str = "codex-gpt-5.2"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=64, ge=1)
    relevance_accept_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    relevance_reject_threshold: float = Field(default=0.35, ge=0.0, le=1.0)
    llm_review_provider: str = "codex-local"
    llm_review_model: str = "gpt-5.2-codex"
    llm_review_max_retries: int = Field(default=1, ge=0)
    llm_review_default_limit: int = Field(default=25, ge=1)
    signal_extraction_provider: str = "codex-local"
    signal_extraction_model: str = "gpt-5.2-codex"
    signal_extraction_max_retries: int = Field(default=1, ge=0)
    signal_extraction_default_limit: int = Field(default=25, ge=1)
    signal_extraction_confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
