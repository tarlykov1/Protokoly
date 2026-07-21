from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET_KEYS = {"", "change-me", "dev-secret", "secret", "changeme"}


class Settings(BaseSettings):
    app_name: str = "Protocol Management System"
    app_env: str = "dev"
    app_version: str = "0.5.0-demo"
    git_commit: str = "local"
    build_date: str = "local"
    database_url: str = "sqlite:///./protocols.db"
    demo_mode: bool = False
    demo_basic_auth_enabled: bool = True
    secret_key: str = "dev-secret"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 20
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    public_base_url: str = "http://localhost:8000"
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver"])
    forwarded_allow_ips: str = "127.0.0.1"
    log_level: str = "INFO"
    session_max_age_seconds: int = 60 * 60 * 8
    ai_enabled: bool = False
    ai_provider: str = "rule_based"
    ai_allow_external: bool = False
    ai_model: str = ""
    ai_api_key: str = ""
    import_session_ttl_hours: int = 24
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def split_hosts(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def production_like(self) -> bool:
        return self.app_env.lower() in {"demo", "prod", "production"}

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://") and self.production_like

    def validate_runtime_security(self) -> None:
        if self.production_like and self.secret_key in INSECURE_SECRET_KEYS:
            raise RuntimeError(
                "SECRET_KEY must be set to a unique high-entropy value for demo/production deployments"
            )
        if self.production_like and self.forwarded_allow_ips.strip() in {"*", "0.0.0.0/0"}:
            raise RuntimeError("FORWARDED_ALLOW_IPS must not trust arbitrary proxies in demo/production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_runtime_security()
    return settings
