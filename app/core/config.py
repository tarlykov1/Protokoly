from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
PRODUCTION_LIKE_ENVIRONMENTS = {"prod", "production", "stage", "staging"}


class Settings(BaseSettings):
    app_name: str = "Protocol Management System"
    database_url: str = "sqlite:///./protocols.db"
    demo_mode: bool = False
    environment: str = "development"
    ai_enabled: bool = False
    ai_provider: str = "rule_based"
    ai_allow_external: bool = False
    ai_model: str = ""
    ai_api_key: str = ""
    import_session_ttl_hours: int = 24
    allow_wildcard_hosts: bool = False
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: DEFAULT_ALLOWED_HOSTS.copy()
    )
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return DEFAULT_ALLOWED_HOSTS.copy()

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return DEFAULT_ALLOWED_HOSTS.copy()
            if stripped.startswith("["):
                try:
                    value = json.loads(stripped)
                except json.JSONDecodeError:
                    value = stripped
            if isinstance(value, str):
                value = value.split(",")

        if isinstance(value, (list, tuple, set)):
            return [item for item in (str(item).strip() for item in value) if item]

        return DEFAULT_ALLOWED_HOSTS.copy()

    @field_validator("allowed_hosts")
    @classmethod
    def reject_wildcard_in_production_like_mode(cls, value: list[str], info) -> list[str]:
        environment = str(info.data.get("environment", "")).lower()
        allow_wildcard = bool(info.data.get("allow_wildcard_hosts", False))
        if "*" in value and environment in PRODUCTION_LIKE_ENVIRONMENTS and not allow_wildcard:
            msg = "ALLOWED_HOSTS='*' is not allowed in production-like environments"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
