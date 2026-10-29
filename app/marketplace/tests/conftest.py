"""The poller test entry point's fakes: forumone.io at the HTTP boundary, and Discord."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from app.chain.tests.conftest import MAIN_CHANNEL, Clock, FakeDiscord
from app.core.memory_store import MemoryStore
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, EventKind, PostStatus
from app.discord.event_publisher import EventPublisher
from app.discord.nft_poster import NFTPoster
from app.marketplace.forum_one import PAGE_SIZE, ForumOnePoller

LE_CONTRACT = "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
SELLER = "0x9195312b2dc49eee39c4c1bcf89c0ace287930fd"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
TEMPLATE_URL = "https://images.test/le/{token_id}.jpg"


def listing(token_id: int, order_hash: str, **overrides: Any) -> dict[str, Any]:
    """One entry of forumone.io's listings array, as the live API returns it."""
    values: dict[str, Any] = {
        "kind": "signed",
        "orderHash": order_hash,
        "chain": 8453,
        "contractAddress": LE_CONTRACT,
        "tokenId": str(token_id),
        "sellerAddress": SELLER,
        "unitPrice": 0.02,
        "currencyAddress": "0x0000000000000000000000000000000000000000",
        "currencySymbol": "ETH",
        "expiresAt": "2027-01-11T19:51:45+00:00",
        "createdAt": "2026-10-28T11:59:30.260561+00:00",
        "tokenName": f"DragonZ Limited Edition #{token_id}",
        "imageUrl": f"https://img.test/{token_id}.webp",
        "signature": "0x00",
    }
    return {**values, **overrides}


@dataclass
class FakeForumOne:
    """Answers pages the way forumone.io does, from a scripted listing set."""

    listings: list[dict[str, Any]] = field(default_factory=list)
    requests: list[tuple[str, int]] = field(default_factory=list)

    async def listings_page(self, _chain: str, contract: str, offset: int) -> dict[str, Any]:
        self.requests.append((contract, offset))
        page = self.listings[offset : offset + PAGE_SIZE]
        return {
            "listings": page,
            "hasMore": offset + PAGE_SIZE < len(self.listings),
            "offset": offset,
        }


@dataclass
class Poller:
    """Everything a test drives: the poller (entry point) and what it can observe."""

    poller: ForumOnePoller
    forum_one: FakeForumOne
    discord: FakeDiscord
    store: MemoryStore
    reloader: SettingsReloader
    publisher: EventPublisher
    clock: Clock

    def statuses(self) -> list[PostStatus]:
        return [stored.status for stored in self.store.events[EventKind.LISTING]]


def le_collection(**overrides: Any) -> Collection:
    values: dict[str, Any] = {
        "id": 0,
        "collection_id": "dragonz-limited-edition",
        "name": "DragonZ Limited Edition",
        "chain": "base",
        "contract_address": LE_CONTRACT,
        "discord_channel_id": MAIN_CHANNEL,
        "track_marketplace": True,
        "marketplaces": ("forum_one",),
        "image_url_template": TEMPLATE_URL,
    }
    return Collection(**{**values, **overrides})


async def _no_change(chain: str, contracts: frozenset[str]) -> None:
    return None


@pytest.fixture
async def poller() -> Poller:
    forum_one = FakeForumOne()
    fake_discord = FakeDiscord()
    store = MemoryStore()
    store.add_collection(le_collection())
    reloader = SettingsReloader(store, _no_change)
    await reloader.reload()
    clock = Clock(NOW)
    publisher = EventPublisher(
        store,
        reloader,
        NFTPoster(fake_discord),  # type: ignore[arg-type]  # FakeDiscord has the bot's client
        clock.now,
    )
    return Poller(
        ForumOnePoller(forum_one, store, reloader, publisher),
        forum_one,
        fake_discord,
        store,
        reloader,
        publisher,
        clock,
    )
