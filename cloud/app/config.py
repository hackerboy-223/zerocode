from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ZeroCode Cloud"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/v1"
    database_url: str = "sqlite:///./zerocode_cloud.db"
    jwt_secret_key: str = "development-only-change-this-secret-before-deploying"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    fernet_key: str = ""
    allow_public_signup: bool = False
    cors_origins: str = "http://localhost:1420,http://localhost:5173"
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    auto_create_schema: bool = False
    upstream_timeout_seconds: int = 120
    allow_local_provider_urls: bool = False
    client_min_version: str = "1.0.0"

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if len(value.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 bytes")
        return value

    @field_validator("access_token_minutes")
    @classmethod
    def validate_access_ttl(cls, value: int) -> int:
        if not 5 <= value <= 60:
            raise ValueError("ACCESS_TOKEN_MINUTES must be between 5 and 60")
        return value

    @field_validator("refresh_token_days")
    @classmethod
    def validate_refresh_ttl(cls, value: int) -> int:
        if not 1 <= value <= 90:
            raise ValueError("REFRESH_TOKEN_DAYS must be between 1 and 90")
        return value

    @property
    def origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    def validate_production(self) -> None:
        if self.app_env == "production":
            if "development-only" in self.jwt_secret_key:
                raise ValueError("Set a unique JWT_SECRET_KEY in production")
            if not self.fernet_key:
                raise ValueError("FERNET_KEY is required in production")
            if self.auto_create_schema:
                raise ValueError("AUTO_CREATE_SCHEMA must be false in production; use migrations")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
