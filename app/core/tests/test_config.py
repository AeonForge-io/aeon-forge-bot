"""Tests for app.core.config module."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.shared.exceptions import ConfigError

REQUIRED_ENV = {
    "DISCORD_TOKEN": "discord_token",
    "ALCHEMY_API_KEY": "alchemy_key",
    "DB_PASSWORD": "db_password",
}


@pytest.fixture
def required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set only the three required env vars."""
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_settings_load_with_only_three_env_vars(required_env: None) -> None:
    """Settings load from DISCORD_TOKEN, ALCHEMY_API_KEY and DB_PASSWORD alone."""
    settings = Settings(_env_file=None)

    assert settings.discord_token == "discord_token"
    assert settings.alchemy_api_key == "alchemy_key"
    assert settings.db_password == "db_password"
    assert settings.log_level == "INFO"
    assert settings.db_name == "aeon_forge_bot"
    assert settings.db_user == "aeon_forge_bot"


@pytest.mark.parametrize("missing", sorted(REQUIRED_ENV))
def test_settings_missing_required_field(
    monkeypatch: pytest.MonkeyPatch, required_env: None, missing: str
) -> None:
    """Each of the three env vars is required."""
    monkeypatch.delenv(missing)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_log_level_validation_valid(
    monkeypatch: pytest.MonkeyPatch, required_env: None
) -> None:
    """Valid log levels are accepted, case-insensitively."""
    for level in ["DEBUG", "info", "WARNING", "ERROR", "CRITICAL"]:
        monkeypatch.setenv("LOG_LEVEL", level)
        settings = Settings(_env_file=None)
        assert settings.log_level == level.upper()


def test_settings_log_level_validation_invalid(
    monkeypatch: pytest.MonkeyPatch, required_env: None
) -> None:
    """An invalid log level raises ConfigError."""
    monkeypatch.setenv("LOG_LEVEL", "INVALID")

    with pytest.raises(ConfigError, match="Invalid log level"):
        Settings(_env_file=None)


def test_get_settings_caching(required_env: None) -> None:
    """get_settings() returns the cached instance."""
    settings1 = get_settings()
    settings2 = get_settings()

    assert settings1 is settings2
