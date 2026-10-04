"""Central settings for the Auditor Agent.

Values can be overridden by environment variables or a .env file,
so nothing (URLs, limits, thresholds) is hard-coded in the code.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Konnective Tissue - Auditor Agent"
    api_prefix: str = "/api/v1"

    # Fail safe: if ENVIRONMENT is not set, assume production (dev login disabled).
    environment: str = "production"

    # The real value comes from .env (never committed).
    # This placeholder has no real password on purpose.
    database_url: str = "postgresql+psycopg://auditor_app:change_me@localhost:5432/auditor_db"


settings = Settings()
