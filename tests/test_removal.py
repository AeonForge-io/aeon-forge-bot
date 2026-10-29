"""Removal check: the app carries no GitHub, stats, Thirdweb or Magic Eden code."""

import importlib.util

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
    "app.discord.embeds",
    "app.discord.event_colors",
    "app.discord.event_embeds",
    "app.discord.event_grouping",
    "app.discord.stats_embeds",
    "app.discord.summaries",
    "app.discord.summary_embed",
    "app.github.client",
    "app.github.events",
    "app.github.polling",
    "app.stats.calculator",
    "app.stats.service",
    "app.nft.marketplaces.magic_eden",
    "app.nft.marketplaces.poller",
    "app.nft.thirdweb.handler",
]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_removed_module_is_gone(module: str) -> None:
    """Each removed module no longer exists."""
    try:
        spec = importlib.util.find_spec(module)
    except ModuleNotFoundError:  # a removed parent package makes its children unfindable too
        spec = None
    assert spec is None


def test_settings_have_no_github_or_global_channel_fields() -> None:
    """The settings carry nothing for the removed GitHub or global-channel features."""
    from app.core.config import Settings

    leftovers = [
        name
        for name in Settings.model_fields
        if any(word in name for word in ("github", "channel", "webhook", "thirdweb"))
    ]
    assert leftovers == []
