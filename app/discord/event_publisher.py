"""Posts recorded events and retries the ones still pending.

An event stays pending when Discord fails; the 60-second settings loop posts it again
until it is more than 6 hours past its event time, then marks it expired.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, EventKind, PostStatus, Store, StoredListing
from app.discord.listing_groups import ListingGroups, group_is_due
from app.discord.nft_poster import MAX_EMBEDS_PER_MESSAGE, NFTPoster
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)
from app.nft.wallet_names import WalletNames
from app.shared.exceptions import DiscordAPIError

logger = get_logger(__name__)

EXPIRY_AFTER = timedelta(hours=6)


class EventPublisher:
    """Posts mints, transfers, burns, sales and listings, and records that they were posted."""

    def __init__(
        self,
        store: Store,
        reloader: SettingsReloader,
        poster: NFTPoster,
        wallet_names: WalletNames,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.reloader = reloader
        self.poster = poster
        self.wallet_names = wallet_names
        self.clock = clock
        self.groups = ListingGroups(store, poster, wallet_names)
        # Events whose post is under way in this process; retry_pending leaves them alone.
        self._in_flight: set[tuple[EventKind, int]] = set()

    async def _guarded(
        self, kind: EventKind, event_ids: list[int], work: Callable[[], Awaitable[None]]
    ) -> None:
        """Run a send-and-record unit with its ids in flight, shielded from cancellation.

        The ids are marked before the first await and cleared only when the unit is done,
        even if the caller is cancelled, so a sent message is never left pending.
        """
        keys = {(kind, event_id) for event_id in event_ids}
        self._in_flight |= keys

        async def run() -> None:
            try:
                await work()
            finally:
                self._in_flight -= keys

        await asyncio.shield(asyncio.ensure_future(run()))

    def _busy(self, kind: EventKind, event_id: int) -> bool:
        return (kind, event_id) in self._in_flight

    async def post_mints(
        self, collection: Collection, recorded: list[tuple[int, NFTMintEvent]]
    ) -> None:
        """Post mints of one collection: a message per transaction, 10 tokens to a message."""
        by_transaction: dict[str | None, list[tuple[int, NFTMintEvent]]] = defaultdict(list)
        for entry in recorded:
            by_transaction[entry[1].transaction_hash].append(entry)

        async def work() -> None:
            for entries in by_transaction.values():
                for first in range(0, len(entries), MAX_EMBEDS_PER_MESSAGE):
                    chunk = entries[first : first + MAX_EMBEDS_PER_MESSAGE]
                    events = [event for _, event in chunk]
                    names = await self.wallet_names.names(e.to_address for e in events)
                    try:
                        await self.poster.post_mints(
                            events,
                            collection.name,
                            collection.discord_channel_id,
                            collection.mint_url,
                            names,
                        )
                    except DiscordAPIError as e:
                        logger.error(
                            "post.mint.failed", collection=collection.collection_id, error=str(e)
                        )
                        continue
                    for event_id, _ in chunk:
                        await self.store.set_post_status(
                            EventKind.MINT, event_id, PostStatus.POSTED
                        )

        await self._guarded(EventKind.MINT, [event_id for event_id, _ in recorded], work)

    async def post_transfer(
        self, collection: Collection, event_id: int, event: NFTTransferEvent
    ) -> None:
        """Post a transfer; a company sender shows its wallet label."""

        async def work() -> None:
            from_label = self.reloader.current.company_label(event.from_address)
            # A company sender shows its label, so only the other wallets need a name
            names = await self.wallet_names.names(
                [event.to_address] if from_label else [event.from_address, event.to_address]
            )
            try:
                await self.poster.post_transfer(
                    event,
                    collection.name,
                    collection.discord_channel_id,
                    collection.contract_address,
                    from_label,
                    names,
                )
            except DiscordAPIError as e:
                logger.error(
                    "post.transfer.failed", collection=collection.collection_id, error=str(e)
                )
                return
            await self.store.set_post_status(EventKind.TRANSFER, event_id, PostStatus.POSTED)

        await self._guarded(EventKind.TRANSFER, [event_id], work)

    async def post_burn(self, collection: Collection, event_id: int, event: NFTBurnEvent) -> None:
        """Post a burn."""

        async def work() -> None:
            names = await self.wallet_names.names([event.from_address])
            try:
                await self.poster.post_burn(
                    event,
                    collection.name,
                    collection.discord_channel_id,
                    collection.contract_address,
                    names,
                )
            except DiscordAPIError as e:
                logger.error("post.burn.failed", collection=collection.collection_id, error=str(e))
                return
            await self.store.set_post_status(EventKind.BURN, event_id, PostStatus.POSTED)

        await self._guarded(EventKind.BURN, [event_id], work)

    async def post_sale(self, collection: Collection, event_id: int, event: NFTSaleEvent) -> None:
        """Post a sale."""

        async def work() -> None:
            names = await self.wallet_names.names([event.seller_address, event.buyer_address])
            try:
                await self.poster.post_sale(
                    event,
                    collection.name,
                    collection.discord_channel_id,
                    collection.chain,
                    collection.contract_address,
                    names,
                )
            except DiscordAPIError as e:
                logger.error("post.sale.failed", collection=collection.collection_id, error=str(e))
                return
            await self.store.set_post_status(EventKind.SALE, event_id, PostStatus.POSTED)

        await self._guarded(EventKind.SALE, [event_id], work)

    async def post_listing(
        self, collection: Collection, event_id: int, event: NFTListingEvent
    ) -> None:
        """Post a marketplace listing."""

        async def work() -> None:
            names = await self.wallet_names.names([event.seller_address])
            try:
                message_id = await self.poster.post_listing(
                    event,
                    collection.name,
                    collection.discord_channel_id,
                    collection.chain,
                    collection.contract_address,
                    names,
                )
            except DiscordAPIError as e:
                logger.error(
                    "post.listing.failed", collection=collection.collection_id, error=str(e)
                )
                return
            await self.store.set_post_status(EventKind.LISTING, event_id, PostStatus.POSTED)
            await self.store.set_listing_message(
                event_id, collection.discord_channel_id, message_id
            )

        await self._guarded(EventKind.LISTING, [event_id], work)

    async def post_due_listings(
        self, collection: Collection, pending: list[tuple[int, NFTListingEvent]]
    ) -> None:
        """Post a collection's held listings once the oldest has waited out its window.

        One listing posts as the single card, two or more as one grouped post.
        """
        oldest = self.clock() - EXPIRY_AFTER
        pending = [
            (event_id, event)
            for event_id, event in pending
            if not self._busy(EventKind.LISTING, event_id) and event.event_timestamp >= oldest
        ]
        if not group_is_due(collection, pending, self.clock()):
            return
        if len(pending) == 1:
            await self.post_listing(collection, *pending[0])
            return
        await self._guarded(
            EventKind.LISTING,
            [event_id for event_id, _ in pending],
            lambda: self.groups.post(collection, pending),
        )

    async def close_listings(self, collection: Collection, closing: list[StoredListing]) -> None:
        """Mark listings no longer live (cancelled, expired or sold) and delete or edit their posts."""
        await self.groups.close(collection, closing)

    async def settle_sale(self, collection: Collection, sale: NFTSaleEvent) -> None:
        """A sale was recorded: close the seller's live listings of that token now, not at the next poll."""
        await self.close_listings(
            collection,
            [
                stored
                for stored in await self.store.list_active_listings_of_token(
                    sale.collection_id, sale.token_id, sale.seller_address
                )
                if stored.event.event_timestamp <= sale.event_timestamp
            ],
        )

    async def retry_pending(self) -> None:
        """Expire pending events past 6 hours, post the rest again."""
        oldest = self.clock() - EXPIRY_AFTER
        mints = await self.store.list_pending_mints()
        transfers = await self.store.list_pending_transfers()
        burns = await self.store.list_pending_burns()
        sales = await self.store.list_pending_sales()
        listings = await self.store.list_pending_listings()

        live_mints: dict[int, list[tuple[int, NFTMintEvent]]] = defaultdict(list)
        for event_id, mint in mints:
            if self._busy(EventKind.MINT, event_id):
                continue
            if mint.event_timestamp < oldest:
                await self._expire(EventKind.MINT, event_id, mint.token_id)
            else:
                live_mints[mint.collection_id].append((event_id, mint))
        for collection_id, entries in live_mints.items():
            collection = self._collection(collection_id, "mint")
            # Re-check: awaits above may have let a live post start since the list was read.
            entries = [entry for entry in entries if not self._busy(EventKind.MINT, entry[0])]
            if collection is not None and entries:
                await self.post_mints(collection, entries)

        for event_id, transfer in transfers:
            if self._busy(EventKind.TRANSFER, event_id):
                continue
            if transfer.event_timestamp < oldest:
                await self._expire(EventKind.TRANSFER, event_id, transfer.token_id)
            elif (collection := self._collection(transfer.collection_id, "transfer")) is not None:
                await self.post_transfer(collection, event_id, transfer)

        for event_id, burn in burns:
            if self._busy(EventKind.BURN, event_id):
                continue
            if burn.event_timestamp < oldest:
                await self._expire(EventKind.BURN, event_id, burn.token_id)
            elif (collection := self._collection(burn.collection_id, "burn")) is not None:
                await self.post_burn(collection, event_id, burn)

        for event_id, sale in sales:
            if self._busy(EventKind.SALE, event_id):
                continue
            if sale.event_timestamp < oldest:
                await self._expire(EventKind.SALE, event_id, sale.token_id)
            elif (collection := self._collection(sale.collection_id, "sale")) is not None:
                await self.post_sale(collection, event_id, sale)

        await self._retry_listings(listings, oldest)

    async def _retry_listings(
        self, listings: list[tuple[int, NFTListingEvent]], oldest: datetime
    ) -> None:
        """Expire pending listings past 6 hours; post the rest singly, or grouped by window."""
        held: dict[int, list[tuple[int, NFTListingEvent]]] = defaultdict(list)
        for event_id, listing in listings:
            if self._busy(EventKind.LISTING, event_id):
                continue
            if listing.event_timestamp < oldest:
                await self._expire(EventKind.LISTING, event_id, listing.token_id)
            else:
                held[listing.collection_id].append((event_id, listing))
        for collection_id, entries in held.items():
            collection = self._collection(collection_id, "listing")
            if collection is None:
                continue
            if collection.listing_group_minutes:
                await self.post_due_listings(collection, entries)
                continue
            for event_id, listing in entries:
                await self.post_listing(collection, event_id, listing)

    async def _expire(self, kind: EventKind, event_id: int, token_id: str) -> None:
        await self.store.set_post_status(kind, event_id, PostStatus.EXPIRED)
        logger.warning("post.expired", kind=kind.value, event_id=event_id, token_id=token_id)

    def _collection(self, collection_id: int, kind: str) -> Collection | None:
        for collection in self.reloader.current.collections:
            if collection.id == collection_id:
                return collection
        logger.warning("post.retry.collection_missing", kind=kind, collection_id=collection_id)
        return None
