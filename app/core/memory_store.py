"""In-memory Store for tests: same behaviour as Postgres on the unique keys."""

from dataclasses import dataclass, field, replace
from datetime import datetime

from pydantic import BaseModel

from app.core.store import (
    ChainCursor,
    Collection,
    CompanyWallet,
    EventKind,
    MarketplaceMark,
    MarkKind,
    PostStatus,
    StoredListing,
)
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)
from app.shared.exceptions import DatabaseError

# The UNIQUE constraints of each event table in migrations/001_schema.sql
UNIQUE_KEYS: dict[EventKind, list[tuple[str, ...]]] = {
    EventKind.MINT: [("collection_id", "token_id", "transaction_hash")],
    EventKind.TRANSFER: [("collection_id", "token_id", "transaction_hash")],
    EventKind.BURN: [("collection_id", "token_id", "transaction_hash")],
    EventKind.LISTING: [("collection_id", "marketplace", "listing_id")],
    EventKind.SALE: [
        ("collection_id", "marketplace", "sale_id"),
        ("collection_id", "transaction_hash", "token_id"),
    ],
}


def _require_lowercase(value: str) -> None:
    """The schema's CHECK (x = lower(x)): stored addresses and marks are lowercase."""
    if value != value.lower():
        raise DatabaseError(f"value must be lowercase: {value}")


@dataclass
class StoredEvent:
    """A recorded event with its post status."""

    id: int
    event: BaseModel
    status: PostStatus
    # listings only: the Discord message of the post, and whether the listing is still live
    channel_id: int | None = None
    message_id: int | None = None
    active: bool = True


@dataclass
class MemoryStore:
    """Store kept in dicts; refuses duplicates like the Postgres schema does."""

    collections: list[Collection] = field(default_factory=list)
    company_wallets: dict[str, CompanyWallet] = field(default_factory=dict)
    marketplace_marks: dict[tuple[str, str], MarketplaceMark] = field(default_factory=dict)
    cursors: dict[str, ChainCursor] = field(default_factory=dict)
    events: dict[EventKind, list[StoredEvent]] = field(
        default_factory=lambda: {kind: [] for kind in EventKind}
    )
    baselines: set[tuple[int, str]] = field(default_factory=set)
    _next_id: int = 1

    # ---- Setup helpers (tests stand in for Adminer edits) ----

    def add_collection(self, collection: Collection) -> Collection:
        """Add a collection under a new id; refuses what the schema's CHECKs refuse."""
        _require_lowercase(collection.contract_address)
        if any(c.collection_id == collection.collection_id for c in self.collections):
            raise DatabaseError(f"duplicate collection {collection.collection_id}")
        added = replace(
            collection,
            id=self._take_id(),
            contract_address=collection.contract_address.lower(),
        )
        self.collections.append(added)
        return added

    def update_collection(self, collection: Collection) -> None:
        """Replace the collection with the same id."""
        for i, c in enumerate(self.collections):
            if c.id == collection.id:
                self.collections[i] = collection
                return
        raise KeyError(collection.id)

    def add_company_wallet(self, address: str, label: str) -> None:
        """Add a company wallet; refuses a non-lowercase or already present address."""
        _require_lowercase(address)
        if address in self.company_wallets:
            raise DatabaseError(f"duplicate company wallet {address}")
        self.company_wallets[address] = CompanyWallet(address=address, label=label)

    def add_marketplace_mark(
        self, kind: MarkKind, value: str, marketplace: str, note: str | None = None
    ) -> None:
        """Add a mark; refuses a non-lowercase value or a (kind, value) already present."""
        _require_lowercase(value)
        if (kind, value) in self.marketplace_marks:
            raise DatabaseError(f"duplicate mark {kind} {value}")
        self.marketplace_marks[(kind, value)] = MarketplaceMark(
            kind=kind,
            value=value,
            marketplace=marketplace,
            note=note,
        )

    # ---- Store ----

    async def list_collections(self) -> list[Collection]:
        return list(self.collections)

    async def list_company_wallets(self) -> list[CompanyWallet]:
        return list(self.company_wallets.values())

    async def list_marketplace_marks(self) -> list[MarketplaceMark]:
        return list(self.marketplace_marks.values())

    async def get_cursor(self, chain: str) -> ChainCursor | None:
        return self.cursors.get(chain)

    async def set_cursor(
        self, chain: str, last_block: int, last_block_time: datetime | None
    ) -> None:
        self.cursors[chain] = ChainCursor(chain, last_block, last_block_time)

    async def insert_mint(self, event: NFTMintEvent, status: PostStatus) -> int | None:
        return self._insert(EventKind.MINT, event, status)

    async def insert_transfer(self, event: NFTTransferEvent, status: PostStatus) -> int | None:
        return self._insert(EventKind.TRANSFER, event, status)

    async def insert_burn(self, event: NFTBurnEvent, status: PostStatus) -> int | None:
        return self._insert(EventKind.BURN, event, status)

    async def insert_sale(self, event: NFTSaleEvent, status: PostStatus) -> int | None:
        return self._insert(EventKind.SALE, event, status)

    async def insert_listing(self, event: NFTListingEvent, status: PostStatus) -> int | None:
        return self._insert(EventKind.LISTING, event, status)

    async def list_pending_mints(self) -> list[tuple[int, NFTMintEvent]]:
        return [(i, e) for i, e in self._pending(EventKind.MINT) if isinstance(e, NFTMintEvent)]

    async def list_pending_transfers(self) -> list[tuple[int, NFTTransferEvent]]:
        return [
            (i, e) for i, e in self._pending(EventKind.TRANSFER) if isinstance(e, NFTTransferEvent)
        ]

    async def list_pending_burns(self) -> list[tuple[int, NFTBurnEvent]]:
        return [(i, e) for i, e in self._pending(EventKind.BURN) if isinstance(e, NFTBurnEvent)]

    async def list_pending_sales(self) -> list[tuple[int, NFTSaleEvent]]:
        return [(i, e) for i, e in self._pending(EventKind.SALE) if isinstance(e, NFTSaleEvent)]

    async def list_pending_listings(self) -> list[tuple[int, NFTListingEvent]]:
        return [
            (i, e) for i, e in self._pending(EventKind.LISTING) if isinstance(e, NFTListingEvent)
        ]

    async def set_listing_message(self, event_id: int, channel_id: int, message_id: int) -> None:
        for stored in self.events[EventKind.LISTING]:
            if stored.id == event_id:
                stored.channel_id, stored.message_id = channel_id, message_id
                return

    async def list_active_listings(
        self, collection_id: int, marketplace: str
    ) -> list[StoredListing]:
        return [
            listing
            for listing in self._active_listings()
            if listing.event.collection_id == collection_id
            and listing.event.marketplace == marketplace
        ]

    async def list_active_listings_of_token(
        self, collection_id: int, token_id: str, seller_address: str
    ) -> list[StoredListing]:
        return [
            listing
            for listing in self._active_listings()
            if listing.event.collection_id == collection_id
            and listing.event.token_id == token_id
            and listing.event.seller_address == seller_address
        ]

    async def set_listing_inactive(self, event_id: int) -> None:
        for stored in self.events[EventKind.LISTING]:
            if stored.id == event_id:
                stored.active = False
                return

    async def has_sale_since(
        self, collection_id: int, token_id: str, seller_address: str, since: datetime
    ) -> bool:
        return any(
            isinstance(s.event, NFTSaleEvent)
            and s.event.collection_id == collection_id
            and s.event.token_id == token_id
            and s.event.seller_address == seller_address
            and s.event.event_timestamp >= since
            for s in self.events[EventKind.SALE]
        )

    async def set_post_status(self, kind: EventKind, event_id: int, status: PostStatus) -> None:
        for stored in self.events[kind]:
            if stored.id == event_id:
                stored.status = status
                return

    async def has_marketplace_baseline(self, collection_id: int, marketplace: str) -> bool:
        return (collection_id, marketplace) in self.baselines

    async def mark_marketplace_polled(self, collection_id: int, marketplace: str) -> None:
        self.baselines.add((collection_id, marketplace))

    # ---- Internals ----

    def _take_id(self) -> int:
        next_id = self._next_id
        self._next_id += 1
        return next_id

    def _active_listings(self) -> list[StoredListing]:
        return [
            StoredListing(s.id, s.event, s.status, s.channel_id, s.message_id)
            for s in self.events[EventKind.LISTING]
            if s.active and isinstance(s.event, NFTListingEvent)
        ]

    def _pending(self, kind: EventKind) -> list[tuple[int, BaseModel]]:
        pending = [s for s in self.events[kind] if s.status is PostStatus.PENDING]
        # The same order as the Postgres queries: event time, then id
        pending.sort(key=lambda s: (getattr(s.event, "event_timestamp"), s.id))  # noqa: B009
        return [(s.id, s.event) for s in pending]

    def _insert(self, kind: EventKind, event: BaseModel, status: PostStatus) -> int | None:
        for key in UNIQUE_KEYS[kind]:
            values = tuple(getattr(event, column) for column in key)
            # Postgres never treats a NULL as equal, so a key with a NULL never conflicts
            if any(v is None for v in values):
                continue
            for stored in self.events[kind]:
                if tuple(getattr(stored.event, column) for column in key) == values:
                    return None
        event_id = self._take_id()
        self.events[kind].append(StoredEvent(event_id, event, status))
        return event_id
