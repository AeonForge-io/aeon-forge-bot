"""The test entry point's fakes: Alchemy at the transport boundary, and Discord."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord
import pytest

from app.chain.reader import (
    ERC721_TRANSFER_TOPIC,
    MAX_SUPPLY_SELECTOR,
    TOTAL_SUPPLY_SELECTOR,
    ChainReader,
)
from app.chain.rpc import ChainConnectionError, ChainRpc, SubscriptionError
from app.core.memory_store import MemoryStore
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, EventKind, PostStatus
from app.discord.nft_poster import NFTPoster
from app.nft import metadata
from app.nft.metadata import fetch_token_image
from app.nft.models import ZERO_ADDRESS

TEST_CHANNEL = 1215729486994210897
MAIN_CHANNEL = 1445253310574755912
TEST_CONTRACT = "0xad1f02d8b22fed6798a6474b65a5778cc0918afc"
SECOND_CONTRACT = "0x1111111111111111111111111111111111111111"
MINTER = "0x00000000000000000000000000000000000000aa"
GENESIS_TIME = 1_800_000_000
BLOCK_SECONDS = 2


def block_time(number: int) -> int:
    return GENESIS_TIME + BLOCK_SECONDS * number


def _topic_address(address: str) -> str:
    return "0x" + address[2:].rjust(64, "0")


def mint_log(
    contract: str, token_id: int, block: int, tx: str, log_index: int, minter: str = MINTER
) -> dict[str, Any]:
    """An ERC-721 Transfer from the zero address, as eth_getLogs returns it."""
    return {
        "address": contract,
        "topics": [
            ERC721_TRANSFER_TOPIC,
            _topic_address(ZERO_ADDRESS),
            _topic_address(minter),
            f"0x{token_id:064x}",
        ],
        "data": "0x",
        "blockNumber": hex(block),
        "transactionHash": tx,
        "logIndex": hex(log_index),
        "removed": False,
    }


TOKEN_URI_SELECTOR = "0xc87b56dd"
METADATA_BASE = "https://metadata.test/"


def abi_string(text: str) -> str:
    """An ABI-encoded string return value, as eth_call gives it."""
    raw = text.encode()
    padded = raw.ljust((len(raw) + 31) // 32 * 32, b"\0")
    return "0x" + f"{32:064x}" + f"{len(raw):064x}" + padded.hex()


class StopTest(Exception):
    """Raised by a fake to end a run() loop."""


@dataclass
class FakeAlchemy:
    """Answers JSON-RPC calls the way Alchemy does, from a scripted chain."""

    head: int = 100
    logs: list[dict[str, Any]] = field(default_factory=list)
    tx_values_wei: dict[str, int] = field(default_factory=dict)
    initial_supply: int = 0
    max_supply: int = 750
    notifications: list[dict[str, Any]] = field(default_factory=list)
    subscription_filters: list[dict[str, Any]] = field(default_factory=list)
    subscription_error: SubscriptionError | None = None
    failing_requests: int = 0
    calls: list[str] = field(default_factory=list)

    async def request(self, method: str, params: list[Any]) -> Any:
        self.calls.append(method)
        if self.failing_requests:
            self.failing_requests -= 1
            raise ChainConnectionError("down")
        if method == "eth_getBlockByNumber":
            number = self.head if params[0] == "latest" else int(params[0], 16)
            return {"number": hex(number), "timestamp": hex(block_time(number))}
        if method == "eth_getLogs":
            wanted = params[0]
            low, high = int(wanted["fromBlock"], 16), int(wanted["toBlock"], 16)
            return [
                log
                for log in self.logs
                if low <= int(log["blockNumber"], 16) <= high
                and log["address"] in wanted["address"]
            ]
        if method == "eth_call":
            call, block_hex = params
            if call["data"].startswith(TOKEN_URI_SELECTOR):
                return abi_string(METADATA_BASE + str(int(call["data"][10:], 16)))
            if call["data"] == MAX_SUPPLY_SELECTOR:
                return hex(self.max_supply)
            assert call["data"] == TOTAL_SUPPLY_SELECTOR
            minted = sum(
                1
                for log in self.logs
                if log["address"] == call["to"]
                and int(log["blockNumber"], 16) <= int(block_hex, 16)
            )
            return hex(self.initial_supply + minted)
        if method == "eth_getTransactionByHash":
            return {"hash": params[0], "value": hex(self.tx_values_wei.get(params[0], 0))}
        raise AssertionError(f"unexpected RPC {method}")

    async def subscribe_logs(self, log_filter: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        self.subscription_filters.append(log_filter)
        if self.subscription_error:
            raise self.subscription_error
        for notification in self.notifications:
            yield notification


class FakeDiscord:
    """Stands in for DiscordBot: records every send, per channel."""

    def __init__(self, missing_channels: frozenset[int] = frozenset()) -> None:
        self.sent: dict[int, list[list[discord.Embed]]] = {}
        self.missing_channels = missing_channels
        self.client = MagicMock(spec=discord.Client)
        self.client.get_channel.side_effect = self._channel

    def _channel(self, channel_id: int) -> MagicMock | None:
        if channel_id in self.missing_channels:
            return None
        channel = MagicMock(spec=discord.TextChannel)

        async def send(**kwargs: Any) -> None:
            self.sent.setdefault(channel_id, []).append(kwargs["embeds"])

        channel.send = AsyncMock(side_effect=send)
        return channel

    def messages(self, channel_id: int) -> list[list[discord.Embed]]:
        return self.sent.get(channel_id, [])


class FakeResponse:
    """An aiohttp response with a status and a JSON body."""

    def __init__(self, body: Any, status: int = 200) -> None:  # JSON body
        self.body = body
        self.status = status

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def json(self) -> Any:  # JSON body
        return self.body


class FakeSession:
    """Stands in for aiohttp.ClientSession in the token-image lookup: eth_call goes to the fake
    Alchemy, and the tokenURI metadata is served from METADATA_BASE.
    """

    def __init__(self, alchemy: FakeAlchemy) -> None:
        self.alchemy = alchemy

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def post(self, _url: str, json: dict[str, Any]) -> FakeResponse:
        alchemy = self.alchemy

        class RpcResponse(FakeResponse):
            async def json(self) -> Any:  # JSON body
                return {"result": await alchemy.request(json["method"], json["params"])}

        return RpcResponse(None)

    def get(self, url: str, **_: Any) -> FakeResponse:
        token_id = url.removeprefix(METADATA_BASE)
        return FakeResponse({"image": f"ipfs://images/{token_id}.png"})


def embed_field(embed: discord.Embed, name: str) -> str:
    return str(next(f.value for f in embed.fields if f.name == name))


def sepolia_collection(**overrides: Any) -> Collection:
    values: dict[str, Any] = {
        "id": 0,
        "collection_id": "sepolia-test",
        "name": "Sepolia Test",
        "chain": "base-sepolia",
        "contract_address": TEST_CONTRACT,
        "discord_channel_id": TEST_CHANNEL,
    }
    return Collection(**{**values, **overrides})


@dataclass
class Bot:
    """Everything a test drives: the reader (entry point) and what it can observe."""

    reader: ChainReader
    alchemy: FakeAlchemy
    discord: FakeDiscord
    store: MemoryStore
    reloader: SettingsReloader
    sleeps: list[float]

    def mint_statuses(self) -> list[PostStatus]:
        return [stored.status for stored in self.store.events[EventKind.MINT]]


async def _no_change(chain: str, contracts: frozenset[str]) -> None:
    return None


@pytest.fixture
async def bot(monkeypatch: pytest.MonkeyPatch) -> Bot:
    alchemy = FakeAlchemy()
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: FakeSession(alchemy))
    monkeypatch.setattr(metadata, "alchemy_rpc_url", lambda _chain: "https://alchemy.test/")
    fake_discord = FakeDiscord()
    store = MemoryStore()
    store.add_collection(sepolia_collection())
    reloader = SettingsReloader(store, _no_change)
    await reloader.reload()
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise StopTest

    reader = ChainReader(
        "base-sepolia",
        ChainRpc(alchemy),
        store,
        reloader,
        NFTPoster(fake_discord),  # type: ignore[arg-type]  # FakeDiscord has the bot's client
        fetch_token_image,
        sleep=record_sleep,
    )
    return Bot(reader, alchemy, fake_discord, store, reloader, sleeps)
