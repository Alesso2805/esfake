"""Configuration read from environment variables (CLAUDE.md rule 13).

Connection strings embed passwords, so they are `SecretStr` and validation errors never echo
their values.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class MigrationSettings(BaseSettings):
    """Settings for schema work done as esfake_owner: migrations and catalogue seeding."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    migrations_database_url: SecretStr
