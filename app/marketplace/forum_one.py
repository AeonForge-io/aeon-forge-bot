"""Forum One listings: the forumone.io public API and the 60-second poller over it.

The first successful poll of a collection stores every live listing as skipped and sets
the baseline; later polls insert new orderHashes and post them. Listings that vanish are
ignored.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

import aiohttp
from pydantic import BaseModel, ConfigDict

from app.core.logging import get_logger
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, PostStatus, Store
from app.discord.event_publisher import EventPublisher
from app.nft.metadata import token_image_url
from app.nft.models import NFTListingEvent
from app.shared.exceptions import AeonForgeBotError

logger = get_logger(__name__)

MARKETPLACE = "forum_one"
POLL_INTERVAL_SECONDS = 60
PAGE_SIZE = 50
FORUM_ONE_API = "https://forumone.io/api"
# Forum One serves Base only among the chains this bot tracks
FORUM_ONE_CHAIN_IDS: dict[str, int] = {"base": 8453}


class ForumOneError(AeonForgeBotError):
    """forumone.io could not be read or answered something unexpected."""


class ListingsApi(Protocol):
    """The HTTP boundary: one page of a collection's live listings, as JSON."""

    async def listings_page(self, chain: str, contract: str, offset: int) -> dict[str, Any]: ...


class ForumOneApi:
    """forumone.io over HTTP."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str = FORUM_ONE_API) -> None:
        self._session = session
        self._base_url = base_url

    async def listings_page(self, chain: str, contract: str, offset: int) -> dict[str, Any]:
        chain_id = FORUM_ONE_CHAIN_IDS.get(chain)
        if chain_id is None:
            raise ForumOneError(f"Forum One does not serve chain {chain}")
        url = f"{self._base_url}/collection/{chain_id}/{contract}/listings"
        try:
            async with self._session.get(url, params={"all": 1, "offset": offset}) as response:
                response.raise_for_status()
                page: dict[str, Any] = await response.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise ForumOneError(f"Listings request failed: {type(e).__name__}: {e}") from e
        return page


class ForumOneListing(BaseModel):
    """The fields of one forumone.io listing the bot uses."""

    model_config = ConfigDict(extra="ignore")

    orderHash: str  # forumone.io's JSON field name
    tokenId: str
    sellerAddress: str
    unitPrice: Decimal
    currencySymbol: str
    createdAt: datetime
    expiresAt: datetime | None = None
    tokenName: str | None = None
    imageUrl: str | None = None


class ListingsPage(BaseModel):
    """One page of the listings response."""

    model_config = ConfigDict(extra="ignore")

    listings: list[ForumOneListing]
    hasMore: bool


class ForumOnePoller:
    """Polls Forum One for each collection that tracks it and posts new listings."""

    def __init__(
        self,
        api: ListingsApi,
        store: Store,
        reloader: SettingsReloader,
        publisher: EventPublisher,
    ) -> None:
        self.api = api
        self.store = store
        self.reloader = reloader
        self.publisher = publisher

    async def run(self, interval: float = POLL_INTERVAL_SECONDS) -> None:
        """Poll forever; a failed store or Discord call raises and stops the bot."""
        while True:
            await self.poll_once()
            await asyncio.sleep(interval)

    async def poll_once(self) -> None:
        """Poll every collection tracking Forum One; a Forum One outage waits for the next poll."""
        for collection in self.reloader.current.collections:
            if (
                collection.is_active
                and collection.track_marketplace
                and (MARKETPLACE in collection.marketplaces)
            ):
                try:
                    await self._poll_collection(collection)
                except ForumOneError as e:
                    logger.error(
                        "forum_one.poll.failed", collection=collection.collection_id, error=str(e)
                    )

    async def _poll_collection(self, collection: Collection) -> None:
        live = await self._fetch_all(collection)
        has_baseline = await self.store.has_marketplace_baseline(collection.id, MARKETPLACE)
        status = (
            PostStatus.PENDING if has_baseline and collection.post_listings else PostStatus.SKIPPED
        )
        for listing in live:
            event = self._event(collection, listing)
            event_id = await self.store.insert_listing(event, status)
            if event_id is not None and status is PostStatus.PENDING:
                await self.publisher.post_listing(collection, event_id, event)
        if not has_baseline:
            await self.store.mark_marketplace_polled(collection.id, MARKETPLACE)

    async def _fetch_all(self, collection: Collection) -> list[ForumOneListing]:
        listings: list[ForumOneListing] = []
        offset = 0
        while True:
            raw = await self.api.listings_page(
                collection.chain, collection.contract_address, offset
            )
            try:
                page = ListingsPage.model_validate(raw)
            except ValueError as e:
                raise ForumOneError(f"Unexpected listings page at offset {offset}: {e}") from e
            listings.extend(page.listings)
            if not page.hasMore:
                return listings
            offset += PAGE_SIZE

    @staticmethod
    def _event(collection: Collection, listing: ForumOneListing) -> NFTListingEvent:
        return NFTListingEvent(
            collection_id=collection.id,
            token_id=listing.tokenId,
            token_name=listing.tokenName,
            token_image_url=listing.imageUrl or token_image_url(collection, listing.tokenId),
            seller_address=listing.sellerAddress,
            marketplace=MARKETPLACE,
            price_native=listing.unitPrice,
            currency=listing.currencySymbol,
            listing_id=listing.orderHash,
            expires_at=listing.expiresAt,
            event_timestamp=listing.createdAt,
        )
