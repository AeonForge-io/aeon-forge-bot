"""Tests for the Alchemy RPC URL used by the token-image lookup."""

import pytest

from app.nft.metadata import alchemy_rpc_url


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "d")
    monkeypatch.setenv("ALCHEMY_API_KEY", "key123")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setattr("app.core.config._settings", None)


@pytest.mark.parametrize(
    ("chain", "network"),
    [("base", "base-mainnet"), ("base-sepolia", "base-sepolia")],
)
def test_alchemy_rpc_url(chain: str, network: str) -> None:
    assert alchemy_rpc_url(chain) == f"https://{network}.g.alchemy.com/v2/key123"


def test_unknown_chain_has_no_url() -> None:
    assert alchemy_rpc_url("polygon") is None
