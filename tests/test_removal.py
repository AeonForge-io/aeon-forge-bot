"""Removal check: the app carries no GitHub, stats, Thirdweb or Magic Eden code."""

import importlib
import importlib.util
import sys

import pytest

REMOVED_MODULES = [
    "app.github",
    "app.stats",
    "app.core.state",
    "app.shared.models",
    "app.discord.poster",
    "app.discord.commands",
    "app.discord.quotes",
    "app.discord.summary_scheduler",
    "app.nft.config",
    "app.nft.thirdweb",
    "app.nft.webhook_server",
    "app.nft.marketplaces",
]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_removed_module_is_gone(module: str) -> None:
    """Each removed module no longer exists."""
    assert importlib.util.find_spec(module) is None


def test_importing_app_loads_no_removed_code() -> None:
    """Importing the entry point pulls in none of the removed code."""
    importlib.import_module("app.main")

    loaded = [m for m in sys.modules if m.startswith(tuple(REMOVED_MODULES))]
    assert loaded == []
