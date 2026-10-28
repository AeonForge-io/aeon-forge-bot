"""PostgreSQL database client with connection pooling."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import TracebackType

# TYPE_CHECKING import to avoid circular imports
from typing import TYPE_CHECKING, ClassVar

import asyncpg

from app.core.config import get_settings
from app.core.logging import get_logger
from app.shared.exceptions import DatabaseError

if TYPE_CHECKING:
    from app.nft.models import (
        NFTBurnEvent,
        NFTListingEvent,
        NFTMintEvent,
        NFTSaleEvent,
        NFTTransferEvent,
    )

logger = get_logger(__name__)


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert timezone-aware datetime to naive UTC datetime.

    PostgreSQL TIMESTAMP columns (without timezone) expect naive datetimes.
    This function converts timezone-aware datetimes to UTC and strips timezone info.

    Args:
        dt: Datetime object (timezone-aware or naive)

    Returns:
        Naive datetime in UTC
    """
    if dt.tzinfo is None:
        # Already naive, assume it's UTC
        return dt
    # Convert to UTC and remove timezone info
    return dt.astimezone(UTC).replace(tzinfo=None)


class DatabaseClient:
    """Async PostgreSQL client with connection pooling."""

    MAX_RETRIES: ClassVar[int] = 3
    RETRY_DELAYS: ClassVar[list[int]] = [2, 4, 8]

    def __init__(self) -> None:
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> "DatabaseClient":
        """Create connection pool with retry logic."""
        settings = get_settings()

        for attempt in range(self.MAX_RETRIES):
            try:
                self.pool = await asyncpg.create_pool(
                    host=settings.db_host,
                    port=settings.db_port,
                    database=settings.db_name,
                    user=settings.db_user,
                    password=settings.db_password,
                    min_size=2,
                    max_size=5,
                    timeout=60.0,
                )
                logger.info("database.pool.created", min_size=2, max_size=5)
                return self
            except (asyncpg.PostgresError, OSError) as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning("database.pool.retry", attempt=attempt + 1, error=str(e))
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                else:
                    logger.error("database.pool.failed", error=str(e), exc_info=True)
                    raise DatabaseError(f"Failed to create pool: {e}") from e
        raise DatabaseError("Unreachable")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("database.pool.closed")

    # ==================== NFT Operations ====================

    async def get_nft_collection_db_id(self, collection_id: str) -> int | None:
        """Get database ID for an NFT collection by its string identifier.

        Args:
            collection_id: Collection string identifier (e.g., "aeon-forge-genesis")

        Returns:
            Database ID or None if not found

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = "SELECT id FROM nft_collections WHERE collection_id = $1"

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, collection_id)
                return row["id"] if row else None
        except asyncpg.PostgresError as e:
            logger.error("database.get_nft_collection_id.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get NFT collection ID: {e}") from e

    async def insert_nft_mint(self, event: "NFTMintEvent") -> bool:
        """Insert NFT mint event.

        Args:
            event: NFTMintEvent object

        Returns:
            True if inserted, False if duplicate

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_mints (
                collection_id, token_id, to_address, chain, token_image_url,
                price_native, price_usd, transaction_hash, block_number, event_timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (collection_id, token_id, transaction_hash) DO NOTHING
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    event.collection_id,
                    event.token_id,
                    event.to_address,
                    event.chain,
                    event.token_image_url,
                    event.price_native,
                    event.price_usd,
                    event.transaction_hash,
                    event.block_number,
                    _to_naive_utc(event.event_timestamp),
                )
                return row is not None
        except asyncpg.PostgresError as e:
            logger.error("database.insert_nft_mint.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to insert NFT mint: {e}") from e

    async def insert_nft_transfer(self, event: "NFTTransferEvent") -> bool:
        """Insert NFT transfer event.

        Args:
            event: NFTTransferEvent object

        Returns:
            True if inserted, False if duplicate

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_transfers (
                collection_id, token_id, from_address, to_address, chain, token_image_url,
                transaction_hash, block_number, event_timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (collection_id, token_id, transaction_hash) DO NOTHING
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    event.collection_id,
                    event.token_id,
                    event.from_address,
                    event.to_address,
                    event.chain,
                    event.token_image_url,
                    event.transaction_hash,
                    event.block_number,
                    _to_naive_utc(event.event_timestamp),
                )
                return row is not None
        except asyncpg.PostgresError as e:
            logger.error("database.insert_nft_transfer.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to insert NFT transfer: {e}") from e

    async def insert_nft_burn(self, event: "NFTBurnEvent") -> bool:
        """Insert NFT burn event.

        Args:
            event: NFTBurnEvent object

        Returns:
            True if inserted, False if duplicate

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_burns (
                collection_id, token_id, from_address, chain, token_image_url,
                transaction_hash, block_number, event_timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (collection_id, token_id, transaction_hash) DO NOTHING
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    event.collection_id,
                    event.token_id,
                    event.from_address,
                    event.chain,
                    event.token_image_url,
                    event.transaction_hash,
                    event.block_number,
                    _to_naive_utc(event.event_timestamp),
                )
                return row is not None
        except asyncpg.PostgresError as e:
            logger.error("database.insert_nft_burn.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to insert NFT burn: {e}") from e

    async def insert_nft_listing(self, event: "NFTListingEvent") -> bool:
        """Insert NFT listing event.

        Args:
            event: NFTListingEvent object

        Returns:
            True if inserted, False if duplicate

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_listings (
                collection_id, token_id, token_name, token_image_url, seller_address,
                marketplace, price_native, price_usd, floor_price_native, rarity_rank,
                listing_id, event_timestamp, is_active
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (collection_id, marketplace, listing_id) DO NOTHING
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    event.collection_id,
                    event.token_id,
                    event.token_name,
                    event.token_image_url,
                    event.seller_address,
                    event.marketplace,
                    event.price_native,
                    event.price_usd,
                    event.floor_price_native,
                    event.rarity_rank,
                    event.listing_id,
                    _to_naive_utc(event.event_timestamp),
                    event.is_active,
                )
                return row is not None
        except asyncpg.PostgresError as e:
            logger.error("database.insert_nft_listing.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to insert NFT listing: {e}") from e

    async def insert_nft_sale(self, event: "NFTSaleEvent") -> bool:
        """Insert NFT sale event.

        Args:
            event: NFTSaleEvent object

        Returns:
            True if inserted, False if duplicate

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_sales (
                collection_id, token_id, token_name, token_image_url, seller_address,
                buyer_address, marketplace, price_native, price_usd, floor_price_native,
                rarity_rank, sale_id, event_timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (collection_id, marketplace, sale_id) DO NOTHING
            RETURNING id
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    query,
                    event.collection_id,
                    event.token_id,
                    event.token_name,
                    event.token_image_url,
                    event.seller_address,
                    event.buyer_address,
                    event.marketplace,
                    event.price_native,
                    event.price_usd,
                    event.floor_price_native,
                    event.rarity_rank,
                    event.sale_id,
                    _to_naive_utc(event.event_timestamp),
                )
                return row is not None
        except asyncpg.PostgresError as e:
            logger.error("database.insert_nft_sale.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to insert NFT sale: {e}") from e

    async def mark_nft_mint_posted(
        self, collection_id: int, token_id: str, transaction_hash: str | None
    ) -> None:
        """Mark NFT mint as posted to Discord.

        Args:
            collection_id: Database collection ID
            token_id: NFT token ID
            transaction_hash: Transaction hash

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            UPDATE nft_mints
            SET posted_to_discord = TRUE, posted_at = NOW()
            WHERE collection_id = $1 AND token_id = $2 AND transaction_hash = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, token_id, transaction_hash)
        except asyncpg.PostgresError as e:
            logger.error("database.mark_nft_mint_posted.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to mark NFT mint posted: {e}") from e

    async def mark_nft_transfer_posted(
        self, collection_id: int, token_id: str, transaction_hash: str | None
    ) -> None:
        """Mark NFT transfer as posted to Discord.

        Args:
            collection_id: Database collection ID
            token_id: NFT token ID
            transaction_hash: Transaction hash

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            UPDATE nft_transfers
            SET posted_to_discord = TRUE, posted_at = NOW()
            WHERE collection_id = $1 AND token_id = $2 AND transaction_hash = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, token_id, transaction_hash)
        except asyncpg.PostgresError as e:
            logger.error("database.mark_nft_transfer_posted.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to mark NFT transfer posted: {e}") from e

    async def mark_nft_burn_posted(
        self, collection_id: int, token_id: str, transaction_hash: str | None
    ) -> None:
        """Mark NFT burn as posted to Discord.

        Args:
            collection_id: Database collection ID
            token_id: NFT token ID
            transaction_hash: Transaction hash

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            UPDATE nft_burns
            SET posted_to_discord = TRUE, posted_at = NOW()
            WHERE collection_id = $1 AND token_id = $2 AND transaction_hash = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, token_id, transaction_hash)
        except asyncpg.PostgresError as e:
            logger.error("database.mark_nft_burn_posted.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to mark NFT burn posted: {e}") from e

    async def mark_nft_listing_posted(
        self, collection_id: int, marketplace: str, listing_id: str
    ) -> None:
        """Mark NFT listing as posted to Discord.

        Args:
            collection_id: Database collection ID
            marketplace: Marketplace name
            listing_id: Listing ID

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            UPDATE nft_listings
            SET posted_to_discord = TRUE, posted_at = NOW()
            WHERE collection_id = $1 AND marketplace = $2 AND listing_id = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, marketplace, listing_id)
        except asyncpg.PostgresError as e:
            logger.error("database.mark_nft_listing_posted.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to mark NFT listing posted: {e}") from e

    async def mark_nft_sale_posted(
        self, collection_id: int, marketplace: str, sale_id: str
    ) -> None:
        """Mark NFT sale as posted to Discord.

        Args:
            collection_id: Database collection ID
            marketplace: Marketplace name
            sale_id: Sale ID

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            UPDATE nft_sales
            SET posted_to_discord = TRUE, posted_at = NOW()
            WHERE collection_id = $1 AND marketplace = $2 AND sale_id = $3
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, marketplace, sale_id)
        except asyncpg.PostgresError as e:
            logger.error("database.mark_nft_sale_posted.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to mark NFT sale posted: {e}") from e

    async def get_nft_marketplace_state(
        self, collection_id: int, marketplace: str
    ) -> datetime | None:
        """Get last poll timestamp for a collection/marketplace pair.

        Args:
            collection_id: Database collection ID
            marketplace: Marketplace name

        Returns:
            Last poll timestamp or None if never polled

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            SELECT last_poll_timestamp FROM nft_marketplace_state
            WHERE collection_id = $1 AND marketplace = $2
        """

        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(query, collection_id, marketplace)
                if row and row["last_poll_timestamp"]:
                    # Add UTC timezone to naive datetime
                    last_poll: datetime = row["last_poll_timestamp"]
                    return last_poll.replace(tzinfo=UTC)
                return None
        except asyncpg.PostgresError as e:
            logger.error("database.get_nft_marketplace_state.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get marketplace state: {e}") from e

    async def set_nft_marketplace_state(
        self, collection_id: int, marketplace: str, event_id: str | None = None
    ) -> None:
        """Update marketplace polling state.

        Args:
            collection_id: Database collection ID
            marketplace: Marketplace name
            event_id: Optional last event ID for cursor pagination

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        query = """
            INSERT INTO nft_marketplace_state (collection_id, marketplace, last_poll_timestamp, last_event_id)
            VALUES ($1, $2, NOW(), $3)
            ON CONFLICT (collection_id, marketplace)
            DO UPDATE SET last_poll_timestamp = NOW(), last_event_id = $3, updated_at = NOW()
        """

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(query, collection_id, marketplace, event_id)
        except asyncpg.PostgresError as e:
            logger.error("database.set_nft_marketplace_state.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to set marketplace state: {e}") from e

    async def get_unposted_nft_mints(
        self, max_age_hours: int = 12
    ) -> list[tuple[int, "NFTMintEvent", str, int]]:
        """Get unposted NFT mint events for recovery.

        Args:
            max_age_hours: Maximum age of events to retrieve

        Returns:
            List of tuples: (db_id, NFTMintEvent, collection_name, discord_channel_id)

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        from app.nft.models import NFTMintEvent

        query = """
            SELECT m.*, c.name as collection_name, c.discord_channel_id, c.chain
            FROM nft_mints m
            JOIN nft_collections c ON m.collection_id = c.id
            WHERE m.posted_to_discord = FALSE
              AND m.created_at > NOW() - $1::interval
              AND c.is_active = TRUE
            ORDER BY m.event_timestamp ASC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, timedelta(hours=max_age_hours))
                results = []
                for row in rows:
                    event = NFTMintEvent(
                        collection_id=row["collection_id"],
                        token_id=row["token_id"],
                        to_address=row["to_address"],
                        chain=row["chain"],
                        token_image_url=row.get("token_image_url"),
                        price_native=row["price_native"],
                        price_usd=row["price_usd"],
                        transaction_hash=row["transaction_hash"],
                        block_number=row["block_number"],
                        event_timestamp=row["event_timestamp"].replace(tzinfo=UTC),
                    )
                    results.append(
                        (
                            row["id"],
                            event,
                            row["collection_name"],
                            row["discord_channel_id"],
                        )
                    )
                return results
        except asyncpg.PostgresError as e:
            logger.error("database.get_unposted_nft_mints.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get unposted NFT mints: {e}") from e

    async def get_unposted_nft_transfers(
        self, max_age_hours: int = 12
    ) -> list[tuple[int, "NFTTransferEvent", str, int]]:
        """Get unposted NFT transfer events for recovery.

        Args:
            max_age_hours: Maximum age of events to retrieve

        Returns:
            List of tuples: (db_id, NFTTransferEvent, collection_name, discord_channel_id)

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        from app.nft.models import NFTTransferEvent

        query = """
            SELECT t.*, c.name as collection_name, c.discord_channel_id, c.chain
            FROM nft_transfers t
            JOIN nft_collections c ON t.collection_id = c.id
            WHERE t.posted_to_discord = FALSE
              AND t.created_at > NOW() - $1::interval
              AND c.is_active = TRUE
            ORDER BY t.event_timestamp ASC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, timedelta(hours=max_age_hours))
                results = []
                for row in rows:
                    event = NFTTransferEvent(
                        collection_id=row["collection_id"],
                        token_id=row["token_id"],
                        from_address=row["from_address"],
                        to_address=row["to_address"],
                        chain=row["chain"],
                        token_image_url=row.get("token_image_url"),
                        transaction_hash=row["transaction_hash"],
                        block_number=row["block_number"],
                        event_timestamp=row["event_timestamp"].replace(tzinfo=UTC),
                    )
                    results.append(
                        (
                            row["id"],
                            event,
                            row["collection_name"],
                            row["discord_channel_id"],
                        )
                    )
                return results
        except asyncpg.PostgresError as e:
            logger.error("database.get_unposted_nft_transfers.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get unposted NFT transfers: {e}") from e

    async def get_unposted_nft_burns(
        self, max_age_hours: int = 12
    ) -> list[tuple[int, "NFTBurnEvent", str, int]]:
        """Get unposted NFT burn events for recovery.

        Args:
            max_age_hours: Maximum age of events to retrieve

        Returns:
            List of tuples: (db_id, NFTBurnEvent, collection_name, discord_channel_id)

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        from app.nft.models import NFTBurnEvent

        query = """
            SELECT b.*, c.name as collection_name, c.discord_channel_id, c.chain
            FROM nft_burns b
            JOIN nft_collections c ON b.collection_id = c.id
            WHERE b.posted_to_discord = FALSE
              AND b.created_at > NOW() - $1::interval
              AND c.is_active = TRUE
            ORDER BY b.event_timestamp ASC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, timedelta(hours=max_age_hours))
                results = []
                for row in rows:
                    event = NFTBurnEvent(
                        collection_id=row["collection_id"],
                        token_id=row["token_id"],
                        from_address=row["from_address"],
                        chain=row["chain"],
                        token_image_url=row.get("token_image_url"),
                        transaction_hash=row["transaction_hash"],
                        block_number=row["block_number"],
                        event_timestamp=row["event_timestamp"].replace(tzinfo=UTC),
                    )
                    results.append(
                        (
                            row["id"],
                            event,
                            row["collection_name"],
                            row["discord_channel_id"],
                        )
                    )
                return results
        except asyncpg.PostgresError as e:
            logger.error("database.get_unposted_nft_burns.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get unposted NFT burns: {e}") from e

    async def get_unposted_nft_listings(
        self, max_age_hours: int = 12
    ) -> list[tuple[int, "NFTListingEvent", str, int, str, str]]:
        """Get unposted NFT listing events for recovery.

        Args:
            max_age_hours: Maximum age of events to retrieve

        Returns:
            List of tuples: (db_id, NFTListingEvent, collection_name, discord_channel_id,
                           chain, contract_address)

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        from app.nft.models import NFTListingEvent

        query = """
            SELECT l.*, c.name as collection_name, c.discord_channel_id,
                   c.chain, c.contract_address
            FROM nft_listings l
            JOIN nft_collections c ON l.collection_id = c.id
            WHERE l.posted_to_discord = FALSE
              AND l.created_at > NOW() - $1::interval
              AND c.is_active = TRUE
            ORDER BY l.event_timestamp ASC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, timedelta(hours=max_age_hours))
                results = []
                for row in rows:
                    event = NFTListingEvent(
                        collection_id=row["collection_id"],
                        token_id=row["token_id"],
                        token_name=row["token_name"],
                        token_image_url=row["token_image_url"],
                        seller_address=row["seller_address"],
                        marketplace=row["marketplace"],
                        price_native=row["price_native"],
                        price_usd=row["price_usd"],
                        floor_price_native=row["floor_price_native"],
                        rarity_rank=row["rarity_rank"],
                        listing_id=row["listing_id"],
                        event_timestamp=row["event_timestamp"].replace(tzinfo=UTC),
                        is_active=row["is_active"],
                    )
                    results.append(
                        (
                            row["id"],
                            event,
                            row["collection_name"],
                            row["discord_channel_id"],
                            row["chain"],
                            row["contract_address"],
                        )
                    )
                return results
        except asyncpg.PostgresError as e:
            logger.error("database.get_unposted_nft_listings.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get unposted NFT listings: {e}") from e

    async def get_unposted_nft_sales(
        self, max_age_hours: int = 12
    ) -> list[tuple[int, "NFTSaleEvent", str, int, str]]:
        """Get unposted NFT sale events for recovery.

        Args:
            max_age_hours: Maximum age of events to retrieve

        Returns:
            List of tuples: (db_id, NFTSaleEvent, collection_name, discord_channel_id, chain)

        Raises:
            DatabaseError: If connection pool is not initialized or query fails
        """
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")

        from app.nft.models import NFTSaleEvent

        query = """
            SELECT s.*, c.name as collection_name, c.discord_channel_id, c.chain
            FROM nft_sales s
            JOIN nft_collections c ON s.collection_id = c.id
            WHERE s.posted_to_discord = FALSE
              AND s.created_at > NOW() - $1::interval
              AND c.is_active = TRUE
            ORDER BY s.event_timestamp ASC
        """

        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(query, timedelta(hours=max_age_hours))
                results = []
                for row in rows:
                    event = NFTSaleEvent(
                        collection_id=row["collection_id"],
                        token_id=row["token_id"],
                        token_name=row["token_name"],
                        token_image_url=row["token_image_url"],
                        seller_address=row["seller_address"],
                        buyer_address=row["buyer_address"],
                        marketplace=row["marketplace"],
                        price_native=row["price_native"],
                        price_usd=row["price_usd"],
                        floor_price_native=row["floor_price_native"],
                        rarity_rank=row["rarity_rank"],
                        sale_id=row["sale_id"],
                        event_timestamp=row["event_timestamp"].replace(tzinfo=UTC),
                    )
                    results.append(
                        (
                            row["id"],
                            event,
                            row["collection_name"],
                            row["discord_channel_id"],
                            row["chain"],
                        )
                    )
                return results
        except asyncpg.PostgresError as e:
            logger.error("database.get_unposted_nft_sales.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"Failed to get unposted NFT sales: {e}") from e
