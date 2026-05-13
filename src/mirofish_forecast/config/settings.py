from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="MIROFISH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # FRED API
    fred_api_key: str

    # Upstash Redis
    redis_url: str
    redis_token: str

    # Databento
    databento_api_key: str = ""

    # IB Market Internals Relay
    ib_relay_url: str = "http://localhost:5001"

    # OpenAI
    openai_api_key: str = ""
    openai_model_parse: str = "gpt-4o-2024-08-06"  # For NLP parsing (structured output)
    openai_model_synthesis: str = "gpt-4o-2024-08-06"  # For forecast synthesis (Phase 4)
    openai_model_agents: str = "gpt-4o-mini-2024-07-18"  # For simulation agents (Phase 4)
    openai_max_rpm: int = 500  # Rate limit (requests per minute)

    # App settings
    debug: bool = False

    # GCS bucket for forecast tracking
    gcs_bucket: str = "total-now-339022-mirofish-results"

    # Fast path (Phase 7)
    fast_path_enabled: bool = True
    fast_path_auto_route: bool = True

    # Calibration
    calibration_enabled: bool = True

    # Upstash Vector (Brooks RAG)
    upstash_vector_url: str = ""
    upstash_vector_token: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton settings instance. Fails fast if required env vars missing."""
    return Settings()  # type: ignore[call-arg]
