"""Configuration read from environment variables (CLAUDE.md rule 13).

Secrets are `SecretStr`, validation errors never echo values, and in production a secret that
still carries the development marker of docker-compose.yml stops the process at startup.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# docker-compose.yml defaults every secret to a value containing this marker, so a local
# `docker compose up` needs no setup; production must replace all of them.
DEV_SECRET_MARKER = "dev-insecure"  # noqa: S105 (a marker, not a secret)


class _Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    env: Literal["development", "production"] = Field(
        default="development", validation_alias="ESFAKE_ENV"
    )

    @model_validator(mode="after")
    def _no_development_secrets_in_production(self) -> Self:
        if self.env == "production":
            for name, value in self:
                if isinstance(value, SecretStr) and DEV_SECRET_MARKER in value.get_secret_value():
                    raise ValueError(f"{name} still uses a development default")
        return self


class MigrationSettings(_Settings):
    """Schema work done as esfake_owner: migrations and catalogue seeding."""

    migrations_database_url: SecretStr


class ModelSettings(_Settings):
    """Where the versioned configuration and the downloaded model weights live (ADR-0003)."""

    config_dir: Path = Field(default=Path("../config"), validation_alias="ESFAKE_CONFIG_DIR")
    models_dir: Path = Field(
        default=Path.home() / ".cache" / "esfake" / "models", validation_alias="ESFAKE_MODELS_DIR"
    )
    # Containers set it so a missing model fails fast instead of reaching the network.
    models_offline: bool = Field(default=False, validation_alias="ESFAKE_MODELS_OFFLINE")


class ApiSettings(ModelSettings):
    internal_secret: SecretStr = Field(validation_alias="ESFAKE_INTERNAL_SECRET")
    # Containers listen on every interface; Docker Compose decides what is published.
    host: str = Field(default="0.0.0.0", validation_alias="ESFAKE_HOST")  # noqa: S104
    public_port: int = Field(default=8000, validation_alias="ESFAKE_PUBLIC_PORT")
    internal_port: int = Field(default=8001, validation_alias="ESFAKE_INTERNAL_PORT")
    # Comma-separated proxy addresses allowed to set X-Forwarded-For. Empty: trust nobody, so
    # the client IP is the socket peer (CLAUDE.md rule 9).
    trusted_proxies: str = Field(default="", validation_alias="ESFAKE_TRUSTED_PROXIES")

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [proxy.strip() for proxy in self.trusted_proxies.split(",") if proxy.strip()]


class ChannelWorkerSettings(_Settings):
    # Never a pooler: LISTEN needs a session (ADR-0002 §3).
    database_direct_url: SecretStr
