"""The bot's storage seam: settings rows, chain cursors and recorded NFT events.

The Postgres implementation lives in app.core.database; app.core.memory_store is
the in-memory stand-in tests use. Both refuse duplicates on the same unique keys.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

TransferMode = Literal["off", "company", "all"]
MarkKind = Literal["fee_wallet", "zone", "calldata_tag"]


class PostStatus(StrEnum):
    """Where a recorded event stands with Discord."""

    PENDING = "pending"
    POSTED = "posted"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class EventKind(StrEnum):
    """Event tables, named by the event they hold."""

    MINT = "nft_mints"
    TRANSFER = "nft_transfers"
    BURN = "nft_burns"
    SALE = "nft_sales"
    LISTING = "nft_listings"


@dataclass(frozen=True)
class Collection:
    """One nft_collections row."""

    id: int
    collection_id: str
    name: str
    chain: str
    contract_address: str
    discord_channel_id: int
    is_active: bool = True
    track_onchain: bool = True
    track_marketplace: bool = False
    marketplaces: tuple[str, ...] = ()
    post_mints: bool = True
    post_burns: bool = True
    post_sales: bool = True
    post_listings: bool = True
    transfer_mode: TransferMode = "company"
    image_url_template: str | None = None  # "{token_id}" is replaced by the token id


@dataclass(frozen=True)
class CompanyWallet:
    """One company_wallets row."""

    address: str
    label: str


@dataclass(frozen=True)
class MarketplaceMark:
    """One marketplace_marks row."""

    kind: MarkKind
    value: str
    marketplace: str
    note: str | None = None


@dataclass(frozen=True)
class ChainCursor:
    """The last block of a chain whose logs are stored."""

    chain: str
    last_block: int
    last_block_time: datetime | None


class Store(Protocol):
    """Everything the bot reads from and writes to its database."""

    # Settings, re-read by the 60-second reload
    async def list_collections(self) -> list[Collection]: ...

    async def list_company_wallets(self) -> list[CompanyWallet]: ...

    async def list_marketplace_marks(self) -> list[MarketplaceMark]: ...

    # Chain cursors
    async def get_cursor(self, chain: str) -> ChainCursor | None: ...

    async def set_cursor(
        self, chain: str, last_block: int, last_block_time: datetime | None
    ) -> None: ...

    # Events: insert-or-ignore on the table's unique keys.
    # Each returns the new row id, or None when the event is already recorded.
    async def insert_mint(self, event: NFTMintEvent, status: PostStatus) -> int | None: ...

    async def insert_transfer(self, event: NFTTransferEvent, status: PostStatus) -> int | None: ...

    async def insert_burn(self, event: NFTBurnEvent, status: PostStatus) -> int | None: ...

    async def insert_sale(self, event: NFTSaleEvent, status: PostStatus) -> int | None: ...

    async def insert_listing(self, event: NFTListingEvent, status: PostStatus) -> int | None: ...

    async def set_post_status(self, kind: EventKind, event_id: int, status: PostStatus) -> None: ...

    # Marketplace polling baseline, per collection and marketplace
    async def has_marketplace_baseline(self, collection_id: int, marketplace: str) -> bool: ...

    async def mark_marketplace_polled(self, collection_id: int, marketplace: str) -> None: ...
