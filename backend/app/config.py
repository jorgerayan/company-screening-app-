from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str

    # Gemini — NEVER expose this value outside backend
    gemini_api_key: str
    gemini_model: str = "gemini-2.0-flash"

    # OpenAI — second-pass analysis validator (optional; validation skipped if absent)
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"

    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: List[str] = ["http://localhost:3000"]

    # Pipeline
    scrape_timeout_seconds: int = 30
    llm_timeout_seconds: int = 60
    max_website_pages: int = 8

    # Experiment kill-switch — set DISABLE_CALIBRATION=1 in .env to run mode B
    # (no deterministic risk filters, no executive injection, no scoring guardrails).
    # Default: False (mode A — calibration active).
    disable_calibration: bool = False


settings = Settings()