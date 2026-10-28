"""PostgreSQL implementation of the Store, with connection pooling."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from types import TracebackType
from typing import Any, ClassVar, TypeVar

import asyncpg

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.store import (
    ChainCursor,
    Collection,
    CompanyWallet,
    EventKind,
    MarketplaceMark,
    PostStatus,
)
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)
from app.shared.exceptions import DatabaseError

logger = get_logger(__name__)

T = TypeVar("T")


class DatabaseClient:
    """Async PostgreSQL client with connection pooling; implements Store."""

    MAX_RETRIES: ClassVar[int] = 3
    RETRY_DELAYS: ClassVar[list[int]] = [2, 4, 8]

    def __init__(self, dsn: str | None = None) -> None:
        """Connect with the settings' database values, or to dsn when given."""
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def __aenter__(self) -> "DatabaseClient":
        """Create connection pool with retry logic."""
        if self.dsn is not None:
            connect_args: dict[str, Any] = {"dsn": self.dsn}
        else:
            settings = get_settings()
            connect_args = {
                "host": settings.db_host,
                "port": settings.db_port,
                "database": settings.db_name,
                "user": settings.db_user,
                "password": settings.db_password,
            }

        for attempt in range(self.MAX_RETRIES):
            try:
                self.pool = await asyncpg.create_pool(
                    **connect_args,
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

    async def _run(self, name: str, work: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        """Run work on a pooled connection, turning Postgres errors into DatabaseError."""
        if not self.pool:
            raise DatabaseError("Connection pool not initialized")
        try:
            async with self.pool.acquire() as conn:
                return await work(conn)
        except asyncpg.PostgresError as e:
            logger.error(f"database.{name}.failed", error=str(e), exc_info=True)
            raise DatabaseError(f"{name} failed: {e}") from e

    # ==================== Settings ====================

    async def list_collections(self) -> list[Collection]:
        rows = await self._run(
            "list_collections",
            lambda conn: conn.fetch("SELECT * FROM nft_collections ORDER BY id"),
        )
        return [
            Collection(
                id=row["id"],
                collection_id=row["collection_id"],
                name=row["name"],
                chain=row["chain"],
                contract_address=row["contract_address"],
                discord_channel_id=row["discord_channel_id"],
                is_active=row["is_active"],
                track_onchain=row["track_onchain"],
                track_marketplace=row["track_marketplace"],
                marketplaces=tuple(row["marketplaces"]),
                post_mints=row["post_mints"],
                post_burns=row["post_burns"],
                post_sales=row["post_sales"],
                post_listings=row["post_listings"],
                transfer_mode=row["transfer_mode"],
                image_url_template=row["image_url_template"],
                mint_url=row["mint_url"],
            )
            for row in rows
        ]

    async def list_company_wallets(self) -> list[CompanyWallet]:
        rows = await self._run(
            "list_company_wallets",
            lambda conn: conn.fetch("SELECT address, label FROM company_wallets ORDER BY id"),
        )
        return [CompanyWallet(address=row["address"], label=row["label"]) for row in rows]

    async def list_marketplace_marks(self) -> list[MarketplaceMark]:
        rows = await self._run(
            "list_marketplace_marks",
            lambda conn: conn.fetch(
                "SELECT kind, value, marketplace, note FROM marketplace_marks ORDER BY id"
            ),
        )
        return [
            MarketplaceMark(
                kind=row["kind"],
                value=row["value"],
                marketplace=row["marketplace"],
                note=row["note"],
            )
            for row in rows
        ]

    # ==================== Chain cursors ====================

    async def get_cursor(self, chain: str) -> ChainCursor | None:
        row = await self._run(
            "get_cursor",
            lambda conn: conn.fetchrow(
                "SELECT last_block, last_block_time FROM chain_cursors WHERE chain = $1", chain
            ),
        )
        if row is None:
            return None
        return ChainCursor(chain, row["last_block"], row["last_block_time"])

    async def set_cursor(
        self, chain: str, last_block: int, last_block_time: datetime | None
    ) -> None:
        await self._run(
            "set_cursor",
            lambda conn: conn.execute(
                """
                INSERT INTO chain_cursors (chain, last_block, last_block_time, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (chain) DO UPDATE
                SET last_block = $2, last_block_time = $3, updated_at = NOW()
                """,
                chain,
                last_block,
                last_block_time,
            ),
        )

    # ==================== Events ====================

    async def _insert(self, name: str, query: str, *args: object) -> int | None:
        row = await self._run(name, lambda conn: conn.fetchrow(query, *args))
        return row["id"] if row else None

    async def insert_mint(self, event: NFTMintEvent, status: PostStatus) -> int | None:
        return await self._insert(
            "insert_mint",
            """
            INSERT INTO nft_mints (
                collection_id, token_id, to_address, chain, token_image_url,
                price_native, price_usd, progress_number, max_supply,
                transaction_hash, block_number, event_timestamp, post_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            event.collection_id,
            event.token_id,
            event.to_address,
            event.chain,
            event.token_image_url,
            event.price_native,
            event.price_usd,
            event.progress_number,
            event.max_supply,
            event.transaction_hash,
            event.block_number,
            event.event_timestamp,
            status.value,
        )

    async def insert_transfer(self, event: NFTTransferEvent, status: PostStatus) -> int | None:
        return await self._insert(
            "insert_transfer",
            """
            INSERT INTO nft_transfers (
                collection_id, token_id, from_address, to_address, chain, token_image_url,
                transaction_hash, block_number, event_timestamp, post_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            event.collection_id,
            event.token_id,
            event.from_address,
            event.to_address,
            event.chain,
            event.token_image_url,
            event.transaction_hash,
            event.block_number,
            event.event_timestamp,
            status.value,
        )

    async def insert_burn(self, event: NFTBurnEvent, status: PostStatus) -> int | None:
        return await self._insert(
            "insert_burn",
            """
            INSERT INTO nft_burns (
                collection_id, token_id, from_address, chain, token_image_url,
                transaction_hash, block_number, event_timestamp, post_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            event.collection_id,
            event.token_id,
            event.from_address,
            event.chain,
            event.token_image_url,
            event.transaction_hash,
            event.block_number,
            event.event_timestamp,
            status.value,
        )

    async def insert_sale(self, event: NFTSaleEvent, status: PostStatus) -> int | None:
        # ON CONFLICT with no target covers both unique keys of nft_sales
        return await self._insert(
            "insert_sale",
            """
            INSERT INTO nft_sales (
                collection_id, token_id, token_name, token_image_url, seller_address,
                buyer_address, marketplace, price_native, price_usd, currency,
                floor_price_native, rarity_rank, sale_id, transaction_hash,
                event_timestamp, post_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            event.collection_id,
            event.token_id,
            event.token_name,
            event.token_image_url,
            event.seller_address,
            event.buyer_address,
            event.marketplace,
            event.price_native,
            event.price_usd,
            event.currency,
            event.floor_price_native,
            event.rarity_rank,
            event.sale_id,
            event.transaction_hash,
            event.event_timestamp,
            status.value,
        )

    async def insert_listing(self, event: NFTListingEvent, status: PostStatus) -> int | None:
        return await self._insert(
            "insert_listing",
            """
            INSERT INTO nft_listings (
                collection_id, token_id, token_name, token_image_url, seller_address,
                marketplace, price_native, price_usd, currency, floor_price_native,
                rarity_rank, listing_id, expires_at, event_timestamp, is_active, post_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            event.collection_id,
            event.token_id,
            event.token_name,
            event.token_image_url,
            event.seller_address,
            event.marketplace,
            event.price_native,
            event.price_usd,
            event.currency,
            event.floor_price_native,
            event.rarity_rank,
            event.listing_id,
            event.expires_at,
            event.event_timestamp,
            event.is_active,
            status.value,
        )

    async def _pending(self, name: str, kind: EventKind) -> list[Any]:
        # kind is an EventKind member, never user input, so naming the table is safe
        query = f"""
            SELECT * FROM {kind.value}
            WHERE post_status = 'pending'
            ORDER BY event_timestamp, id
        """  # noqa: S608
        return await self._run(name, lambda conn: conn.fetch(query))

    async def list_pending_mints(self) -> list[tuple[int, NFTMintEvent]]:
        rows = await self._pending("list_pending_mints", EventKind.MINT)
        return [(r["id"], NFTMintEvent.model_validate(dict(r))) for r in rows]

    async def list_pending_transfers(self) -> list[tuple[int, NFTTransferEvent]]:
        rows = await self._pending("list_pending_transfers", EventKind.TRANSFER)
        return [(r["id"], NFTTransferEvent.model_validate(dict(r))) for r in rows]

    async def list_pending_burns(self) -> list[tuple[int, NFTBurnEvent]]:
        rows = await self._pending("list_pending_burns", EventKind.BURN)
        return [(r["id"], NFTBurnEvent.model_validate(dict(r))) for r in rows]

    async def set_post_status(self, kind: EventKind, event_id: int, status: PostStatus) -> None:
        # kind is an EventKind member, never user input, so naming the table is safe
        query = f"""
            UPDATE {kind.value}
            SET post_status = $2,
                posted_at = CASE WHEN $2 = 'posted' THEN NOW() ELSE posted_at END
            WHERE id = $1
        """  # noqa: S608
        await self._run("set_post_status", lambda conn: conn.execute(query, event_id, status.value))

    # ==================== Marketplace baseline ====================

    async def has_marketplace_baseline(self, collection_id: int, marketplace: str) -> bool:
        row = await self._run(
            "has_marketplace_baseline",
            lambda conn: conn.fetchrow(
                """
                SELECT 1 FROM nft_marketplace_state
                WHERE collection_id = $1 AND marketplace = $2
                """,
                collection_id,
                marketplace,
            ),
        )
        return row is not None

    async def mark_marketplace_polled(self, collection_id: int, marketplace: str) -> None:
        await self._run(
            "mark_marketplace_polled",
            lambda conn: conn.execute(
                """
                INSERT INTO nft_marketplace_state (collection_id, marketplace, last_poll_timestamp)
                VALUES ($1, $2, NOW())
                ON CONFLICT (collection_id, marketplace)
                DO UPDATE SET last_poll_timestamp = NOW(), updated_at = NOW()
                """,
                collection_id,
                marketplace,
            ),
        )
