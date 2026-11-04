"""Grouped Forum One listing posts: when a held burst is due, posting it, and re-drawing it on close.

A collection with listing_group_minutes above 0 holds its new listings as pending. Once the oldest
one is older than the window, all pending listings of the collection post as one grouped post and
each stores that post's message id. When listings of a grouped post close, the post is drawn again
from the ones still live, or deleted when none is.
"""

from datetime import datetime, timedelta

from app.core.logging import get_logger
from app.core.store import Collection, EventKind, PostStatus, Store, StoredListing
from app.discord.listing_group_card import MAX_ROWS
from app.discord.nft_poster import NFTPoster
from app.nft.models import NFTListingEvent
from app.nft.wallet_names import WalletNames
from app.shared.exceptions import DiscordAPIError

logger = get_logger(__name__)


def group_is_due(
    collection: Collection, pending: list[tuple[int, NFTListingEvent]], now: datetime
) -> bool:
    """Whether the oldest pending listing has waited out the collection's window."""
    window = timedelta(minutes=collection.listing_group_minutes)
    return bool(pending) and now - min(event.event_timestamp for _, event in pending) > window


class ListingGroups:
    """Posts grouped listing posts and keeps them in line with the listings still live."""

    def __init__(self, store: Store, poster: NFTPoster, wallet_names: WalletNames) -> None:
        self.store = store
        self.poster = poster
        self.wallet_names = wallet_names

    async def post(
        self, collection: Collection, pending: list[tuple[int, NFTListingEvent]]
    ) -> None:
        """Post the pending listings as one post; a failed send leaves them pending."""
        events = [event for _, event in pending]
        names = await self.wallet_names.names(e.seller_address for e in events[:MAX_ROWS])
        try:
            message_id = await self.poster.post_listing_group(
                events,
                collection.name,
                collection.discord_channel_id,
                collection.chain,
                collection.contract_address,
                names,
            )
        except DiscordAPIError as e:
            logger.error(
                "post.listing_group.failed", collection=collection.collection_id, error=str(e)
            )
            return
        for event_id, _ in pending:
            await self.store.set_post_status(EventKind.LISTING, event_id, PostStatus.POSTED)
            await self.store.set_listing_message(
                event_id, collection.discord_channel_id, message_id
            )

    async def close(self, collection: Collection, closing: list[StoredListing]) -> None:
        """Mark listings no longer live (cancelled, expired or sold) and fix their posts.

        A post with listings left live is edited once for all that close; a post with none is
        deleted. A failed Discord call is logged and leaves its listings active for the next try.
        """
        by_post: dict[tuple[int, int], list[StoredListing]] = {}
        for stored in closing:
            if stored.channel_id is None or stored.message_id is None:
                if stored.status is PostStatus.PENDING:
                    # never posted: the retry must not post a listing that is gone
                    await self.store.set_post_status(
                        EventKind.LISTING, stored.id, PostStatus.SKIPPED
                    )
                await self.store.set_listing_inactive(stored.id)
            else:
                by_post.setdefault((stored.channel_id, stored.message_id), []).append(stored)
        for (channel_id, message_id), gone in by_post.items():
            gone_ids = {stored.id for stored in gone}
            live = [
                stored.event
                for stored in await self.store.list_active_listings_of_message(
                    channel_id, message_id
                )
                if stored.id not in gone_ids
            ]
            try:
                if live:
                    names = await self.wallet_names.names(e.seller_address for e in live[:MAX_ROWS])
                    await self.poster.edit_listing_group(
                        channel_id,
                        message_id,
                        live,
                        collection.name,
                        collection.chain,
                        collection.contract_address,
                        names,
                    )
                else:
                    await self.poster.delete_message(channel_id, message_id)
            except DiscordAPIError as e:
                logger.error(
                    "post.listing.close_failed",
                    collection=collection.collection_id,
                    message_id=message_id,
                    error=str(e),
                )
                continue
            for stored in gone:
                await self.store.set_listing_inactive(stored.id)
