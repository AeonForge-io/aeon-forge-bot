"""The Store seam: both implementations record events once on the same unique keys.

Every test runs against the in-memory store and, when TEST_DATABASE_URL is set,
against a migrated throwaway Postgres, so the stand-in can't drift from the schema.
"""

from datetime import UTC, datetime
from decimal import Decimal

from app.core.database import DatabaseClient
from app.core.memory_store import MemoryStore
from app.core.store import EventKind, PostStatus, Store
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

TX_A = "0x" + "a" * 64
TX_B = "0x" + "b" * 64
WHEN = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
HOLDER = "0x1111111111111111111111111111111111111111"
OTHER = "0x2222222222222222222222222222222222222222"


def mint(collection_id: int, nft_id: str = "1", tx: str | None = TX_A) -> NFTMintEvent:
    return NFTMintEvent(
        collection_id=collection_id,
        token_id=nft_id,
        to_address=HOLDER,
        progress_number=212,
        max_supply=750,
        transaction_hash=tx,
        block_number=100,
        event_timestamp=WHEN,
    )


def sale(collection_id: int, sale_id: str, tx: str, marketplace: str = "Forum One") -> NFTSaleEvent:
    return NFTSaleEvent(
        collection_id=collection_id,
        token_id="7",
        seller_address=HOLDER,
        buyer_address=OTHER,
        marketplace=marketplace,
        price_native=Decimal("0.05"),
        currency="ETH",
        sale_id=sale_id,
        transaction_hash=tx,
        event_timestamp=WHEN,
    )


def listing(collection_id: int, order_hash: str) -> NFTListingEvent:
    return NFTListingEvent(
        collection_id=collection_id,
        token_id="7",
        seller_address=HOLDER,
        marketplace="forum_one",
        price_native=Decimal("0.1"),
        currency="ETH",
        listing_id=order_hash,
        event_timestamp=WHEN,
    )


async def test_same_mint_is_recorded_once(store_with_collection: tuple[Store, int]) -> None:
    store, cid = store_with_collection
    first = await store.insert_mint(mint(cid), PostStatus.PENDING)
    again = await store.insert_mint(mint(cid), PostStatus.PENDING)
    assert first is not None
    assert again is None


async def test_mints_differing_in_token_or_tx_are_both_recorded(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    assert await store.insert_mint(mint(cid, "1", TX_A), PostStatus.PENDING) is not None
    assert await store.insert_mint(mint(cid, "2", TX_A), PostStatus.PENDING) is not None
    assert await store.insert_mint(mint(cid, "1", TX_B), PostStatus.PENDING) is not None


async def test_mint_without_tx_hash_never_conflicts(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    assert await store.insert_mint(mint(cid, tx=None), PostStatus.PENDING) is not None
    assert await store.insert_mint(mint(cid, tx=None), PostStatus.PENDING) is not None


async def test_same_transfer_and_burn_are_recorded_once(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    transfer = NFTTransferEvent(
        collection_id=cid,
        token_id="3",
        from_address=HOLDER,
        to_address=OTHER,
        transaction_hash=TX_A,
        event_timestamp=WHEN,
    )
    burn = NFTBurnEvent(
        collection_id=cid,
        token_id="3",
        from_address=HOLDER,
        transaction_hash=TX_B,
        event_timestamp=WHEN,
    )
    assert await store.insert_transfer(transfer, PostStatus.SKIPPED) is not None
    assert await store.insert_transfer(transfer, PostStatus.SKIPPED) is None
    assert await store.insert_burn(burn, PostStatus.PENDING) is not None
    assert await store.insert_burn(burn, PostStatus.PENDING) is None


async def test_one_sale_seen_by_two_sources_is_recorded_once(
    store_with_collection: tuple[Store, int],
) -> None:
    """Same collection, transaction and token: a second source's sale is refused."""
    store, cid = store_with_collection
    assert await store.insert_sale(sale(cid, "receipt-1", TX_A), PostStatus.PENDING) is not None
    assert (
        await store.insert_sale(sale(cid, "other-1", TX_A, "OpenSea"), PostStatus.PENDING) is None
    )


async def test_same_marketplace_sale_id_is_recorded_once(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    assert await store.insert_sale(sale(cid, "s-1", TX_A), PostStatus.PENDING) is not None
    assert await store.insert_sale(sale(cid, "s-1", TX_B), PostStatus.PENDING) is None


async def test_same_listing_order_hash_is_recorded_once(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    assert await store.insert_listing(listing(cid, "0xorder1"), PostStatus.SKIPPED) is not None
    assert await store.insert_listing(listing(cid, "0xorder1"), PostStatus.PENDING) is None
    assert await store.insert_listing(listing(cid, "0xorder2"), PostStatus.PENDING) is not None


async def test_cursor_round_trip(store_with_collection: tuple[Store, int]) -> None:
    store, _ = store_with_collection
    assert await store.get_cursor("base") is None
    await store.set_cursor("base", 100, WHEN)
    await store.set_cursor("base", 101, WHEN)
    cursor = await store.get_cursor("base")
    assert cursor is not None
    assert cursor.last_block == 101
    assert cursor.last_block_time == WHEN


async def test_marketplace_baseline(store_with_collection: tuple[Store, int]) -> None:
    store, cid = store_with_collection
    assert not await store.has_marketplace_baseline(cid, "forum_one")
    await store.mark_marketplace_polled(cid, "forum_one")
    await store.mark_marketplace_polled(cid, "forum_one")
    assert await store.has_marketplace_baseline(cid, "forum_one")


async def test_set_post_status_changes_the_event_status(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    for kind, insert in (
        (EventKind.MINT, store.insert_mint(mint(cid), PostStatus.PENDING)),
        (EventKind.SALE, store.insert_sale(sale(cid, "s1", TX_A), PostStatus.PENDING)),
        (EventKind.LISTING, store.insert_listing(listing(cid, "h1"), PostStatus.PENDING)),
    ):
        event_id = await insert
        assert event_id is not None
        await store.set_post_status(kind, event_id, PostStatus.POSTED)
        if isinstance(store, MemoryStore):
            assert [e.status for e in store.events[kind]] == [PostStatus.POSTED]
        else:
            assert isinstance(store, DatabaseClient) and store.pool is not None
            async with store.pool.acquire() as conn:
                row = await conn.fetchrow(
                    f"SELECT post_status, posted_at FROM {kind.value} WHERE id = $1",  # noqa: S608
                    event_id,
                )
            assert row is not None
            assert row["post_status"] == "posted"
            assert row["posted_at"] is not None


async def test_pending_events_are_listed_oldest_first_and_only_while_pending(
    store_with_collection: tuple[Store, int],
) -> None:
    store, cid = store_with_collection
    later = NFTBurnEvent(
        collection_id=cid,
        token_id="2",
        from_address=HOLDER,
        transaction_hash=TX_B,
        event_timestamp=WHEN.replace(hour=13),
    )
    earlier = later.model_copy(
        update={"token_id": "1", "transaction_hash": TX_A, "event_timestamp": WHEN}
    )
    await store.insert_burn(later, PostStatus.PENDING)
    earlier_id = await store.insert_burn(earlier, PostStatus.PENDING)
    await store.insert_burn(later.model_copy(update={"token_id": "3"}), PostStatus.SKIPPED)
    assert await store.insert_mint(mint(cid), PostStatus.PENDING) is not None
    transfer = NFTTransferEvent(
        collection_id=cid,
        token_id="3",
        from_address=HOLDER,
        to_address=OTHER,
        transaction_hash=TX_A,
        event_timestamp=WHEN,
    )
    assert await store.insert_transfer(transfer, PostStatus.PENDING) is not None

    assert [b.token_id for _, b in await store.list_pending_burns()] == ["1", "2"]
    assert earlier_id is not None
    await store.set_post_status(EventKind.BURN, earlier_id, PostStatus.POSTED)
    assert [b.token_id for _, b in await store.list_pending_burns()] == ["2"]
    assert [m.token_id for _, m in await store.list_pending_mints()] == ["1"]
    assert [t.token_id for _, t in await store.list_pending_transfers()] == ["3"]
