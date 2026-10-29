"""Configuration management using Pydantic Settings.

The env file holds only secrets and the log level; collections, channels,
switches and company wallets live in the database.
"""

from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.shared.exceptions import ConfigError

# Singleton instance
_settings: "Settings | None" = None


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # Secrets (required)
    discord_token: str
    alchemy_api_key: str
    db_password: str

    # Optional
    log_level: str = "INFO"

    # Fixed by docker-compose; not read from the env file in production
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "aeon_forge_bot"
    db_user: str = "aeon_forge_bot"

    # Valid log levels
    VALID_LOG_LEVELS: ClassVar[set[str]] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the allowed values."""
        v_upper = v.upper()
        if v_upper not in cls.VALID_LOG_LEVELS:
            raise ConfigError(
                f"Invalid log level: {v}. Must be one of {', '.join(cls.VALID_LOG_LEVELS)}"
            )
        return v_upper


def get_settings() -> Settings:
    """Get or create the global Settings instance (cached singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
