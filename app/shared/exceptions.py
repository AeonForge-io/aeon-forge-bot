"""Custom exception hierarchy for the Aeon Forge bot."""


class AeonForgeBotError(Exception):
    """Base exception for all bot errors."""


class ConfigError(AeonForgeBotError):
    """Raised when configuration validation fails."""


class DiscordAPIError(AeonForgeBotError):
    """Raised when Discord API requests fail."""


class DatabaseError(AeonForgeBotError):
    """Raised when database operations fail."""
