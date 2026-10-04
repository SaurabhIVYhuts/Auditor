"""Central settings for the Auditor Agent.

Values can be overridden by environment variables or a .env file,
so nothing (URLs, limits, thresholds) is hard-coded in the code.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Konnective Tissue - Auditor Agent"
    api_prefix: str = "/api/v1"


settings = Settings()
