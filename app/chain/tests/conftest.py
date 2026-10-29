"""The test entry point's fakes: Alchemy at the transport boundary, and Discord."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.chain.abi import TRANSFER_TOPIC
from app.chain.reader import (
    MAX_SUPPLY_SELECTOR,
    TOTAL_SUPPLY_SELECTOR,
    ChainReader,
)
from app.chain.rpc import (
    DECIMALS_SELECTOR,
    SYMBOL_SELECTOR,
    ChainConnectionError,
    ChainRpc,
    SubscriptionError,
)
from app.core.memory_store import MemoryStore
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, EventKind, PostStatus
from app.discord.event_publisher import EventPublisher
from app.discord.nft_poster import NFTPoster
from app.discord.tests.card_view import Card
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
            TRANSFER_TOPIC,
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


IMAGE_URL_TEMPLATE = "https://images.test/ipfs/cid/{token_id}.jpg"


def abi_string(text: str) -> str:
    """An ABI-encoded string return value."""
    raw = text.encode()
    return "0x" + f"{32:064x}" + f"{len(raw):064x}" + raw.hex().ljust(64, "0")


class StopTest(Exception):
    """Raised by a fake to end a run() loop."""


@dataclass
class FakeAlchemy:
    """Answers JSON-RPC calls the way Alchemy does, from a scripted chain."""

    head: int = 100
    logs: list[dict[str, Any]] = field(default_factory=list)
    tx_values_wei: dict[str, int] = field(default_factory=dict)
    receipts: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    erc20s: dict[str, tuple[str, int]] = field(default_factory=dict)
    tx_inputs: dict[str, str] = field(default_factory=dict)
    tx_senders: dict[str, str] = field(default_factory=dict)
    tx_targets: dict[str, str] = field(default_factory=dict)
    traces: dict[str, dict[str, Any]] = field(default_factory=dict)
    initial_supply: int = 0
    max_supply: int = 750
    notifications: list[dict[str, Any]] = field(default_factory=list)
    subscription_filters: list[dict[str, Any]] = field(default_factory=list)
    subscription_error: SubscriptionError | None = None
    failing_requests: int = 0
    calls: list[str] = field(default_factory=list)
    receipt_requests: list[str] = field(default_factory=list)

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
            if call["data"] == SYMBOL_SELECTOR:
                return abi_string(self.erc20s[call["to"]][0])
            if call["data"] == DECIMALS_SELECTOR:
                return hex(self.erc20s[call["to"]][1])
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
            return {
                "hash": params[0],
                "value": hex(self.tx_values_wei.get(params[0], 0)),
                "input": self.tx_inputs.get(params[0], "0x"),
                "from": self.tx_senders.get(params[0], ZERO_ADDRESS),
                "to": self.tx_targets.get(params[0], ZERO_ADDRESS),
            }
        if method == "debug_traceTransaction":
            assert params[1] == {"tracer": "callTracer"}
            return self.traces.get(
                params[0], {"from": ZERO_ADDRESS, "to": ZERO_ADDRESS, "value": "0x0"}
            )
        if method == "eth_getTransactionReceipt":
            self.receipt_requests.append(params[0])
            # A receipt holds the tx's tracked Transfer logs as well as the scripted ones
            transfers = [log for log in self.logs if log["transactionHash"] == params[0]]
            return {
                "transactionHash": params[0],
                "logs": [*self.receipts.get(params[0], []), *transfers],
            }
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
        self.sent: dict[int, list[Card]] = {}
        self.missing_channels = missing_channels
        self.client = MagicMock(spec=discord.Client)
        self.client.get_channel.side_effect = self._channel

    def _channel(self, channel_id: int) -> MagicMock | None:
        if channel_id in self.missing_channels:
            return None
        channel = MagicMock(spec=discord.TextChannel)

        async def send(**kwargs: Any) -> None:
            self.sent.setdefault(channel_id, []).append(Card(kwargs["view"]))

        channel.send = AsyncMock(side_effect=send)
        return channel

    def messages(self, channel_id: int) -> list[Card]:
        return self.sent.get(channel_id, [])


def transfer_log(
    contract: str, token_id: int, block: int, tx: str, log_index: int, sender: str, recipient: str
) -> dict[str, Any]:
    """An ERC-721 Transfer between two addresses, as eth_getLogs returns it."""
    log = mint_log(contract, token_id, block, tx, log_index, minter=recipient)
    log["topics"][1] = _topic_address(sender)
    return log


def sepolia_collection(**overrides: Any) -> Collection:
    values: dict[str, Any] = {
        "id": 0,
        "collection_id": "sepolia-test",
        "name": "Sepolia Test",
        "chain": "base-sepolia",
        "contract_address": TEST_CONTRACT,
        "discord_channel_id": TEST_CHANNEL,
        "image_url_template": IMAGE_URL_TEMPLATE,
    }
    return Collection(**{**values, **overrides})


@dataclass
class Clock:
    """The publisher's clock, moved by tests."""

    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass
class Bot:
    """Everything a test drives: the reader (entry point) and what it can observe."""

    reader: ChainReader
    alchemy: FakeAlchemy
    discord: FakeDiscord
    store: MemoryStore
    reloader: SettingsReloader
    sleeps: list[float]
    publisher: EventPublisher
    clock: "Clock"

    def mint_statuses(self) -> list[PostStatus]:
        return [stored.status for stored in self.store.events[EventKind.MINT]]


async def _no_change(chain: str, contracts: frozenset[str]) -> None:
    return None


async def build_bot(chain: str, collection: Collection) -> Bot:
    alchemy = FakeAlchemy()
    fake_discord = FakeDiscord()
    store = MemoryStore()
    store.add_collection(collection)
    reloader = SettingsReloader(store, _no_change)
    await reloader.reload()
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise StopTest

    clock = Clock(datetime.fromtimestamp(block_time(100), UTC))
    publisher = EventPublisher(
        store,
        reloader,
        NFTPoster(fake_discord),  # type: ignore[arg-type]  # FakeDiscord has the bot's client
        clock.now,
    )
    reader = ChainReader(
        chain,
        ChainRpc(alchemy),
        store,
        reloader,
        publisher,
        sleep=record_sleep,
    )
    return Bot(reader, alchemy, fake_discord, store, reloader, sleeps, publisher, clock)


@pytest.fixture
async def bot() -> Bot:
    return await build_bot("base-sepolia", sepolia_collection())
