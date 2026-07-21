from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Protocol Management System"
    database_url: str = "sqlite:///./protocols.db"
    ai_enabled: bool = False
    ai_provider: str = "rule_based"
    ai_allow_external: bool = False
    ai_model: str = ""
    ai_api_key: str = ""
    import_session_ttl_hours: int = 24
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
