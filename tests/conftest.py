"""Shared pytest fixtures for Aeon Forge bot tests."""

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache() -> Iterator[None]:
    """Reset the global settings cache before and after each test.

    This ensures tests don't interfere with each other via cached settings.
    """
    # Import here to avoid circular dependencies
    import app.core.config

    # Clear cache before test
    app.core.config._settings = None

    yield

    # Clear cache after test
    app.core.config._settings = None
