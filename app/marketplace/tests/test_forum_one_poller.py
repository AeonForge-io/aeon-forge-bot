"""Forum One listings through the poller: forumone.io pages in, Discord messages out."""

from dataclasses import replace

from app.chain.tests.conftest import MAIN_CHANNEL
from app.core.store import PostStatus
from app.marketplace.tests.conftest import LE_CONTRACT, SELLER, Poller, listing

HASH_A = "0x" + "a1" * 32
HASH_B = "0x" + "b2" * 32
HASH_C = "0x" + "c3" * 32


async def test_first_poll_posts_nothing_and_a_new_order_hash_posts_once(poller: Poller) -> None:
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    assert poller.discord.sent == {}
    assert poller.statuses() == [PostStatus.SKIPPED]

    poller.forum_one.listings = [listing(24, HASH_A), listing(25, HASH_B)]
    await poller.poller.poll_once()
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "DragonZ Limited Edition #25" in card.text
    assert card.values("Price") == ["0.02 ETH"]
    assert card.values("Seller") == [f"{SELLER[:6]}...{SELLER[-4:]}"]
    assert card.images == ["https://img.test/25.webp"]
    assert ("View on Forum One", f"https://forumone.io/token/8453/{LE_CONTRACT}/25") in card.buttons

    await poller.poller.poll_once()
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 1


async def test_pages_are_read_until_has_more_is_false(poller: Poller) -> None:
    poller.forum_one.listings = [listing(n, f"0x{n:064x}") for n in range(1, 121)]
    await poller.poller.poll_once()
    assert [offset for _, offset in poller.forum_one.requests] == [0, 50, 100]
    assert poller.statuses() == [PostStatus.SKIPPED] * 120

    poller.forum_one.listings.append(listing(121, HASH_A))
    await poller.poller.poll_once()
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 1


async def test_image_falls_back_to_the_collection_image_template(poller: Poller) -> None:
    await poller.poller.poll_once()
    poller.forum_one.listings = [listing(7, HASH_A, imageUrl=None)]
    await poller.poller.poll_once()

    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert card.images == ["https://images.test/le/7.jpg"]


async def test_post_listings_off_records_skipped_and_turning_on_posts_nothing_old(
    poller: Poller,
) -> None:
    await poller.poller.poll_once()
    [collection] = poller.store.collections
    poller.store.update_collection(replace(collection, post_listings=False))
    await poller.reloader.reload()

    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    assert poller.statuses() == [PostStatus.SKIPPED]

    poller.store.update_collection(collection)
    await poller.reloader.reload()
    await poller.poller.poll_once()
    await poller.publisher.retry_pending()
    assert poller.discord.sent == {}


async def test_a_relisting_with_a_new_order_hash_posts_again(poller: Poller) -> None:
    await poller.poller.poll_once()
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    poller.forum_one.listings = []
    await poller.poller.poll_once()
    poller.forum_one.listings = [listing(24, HASH_B)]
    await poller.poller.poll_once()

    assert len(poller.discord.messages(MAIN_CHANNEL)) == 2


async def test_a_failed_post_stays_pending_and_the_retry_posts_it(poller: Poller) -> None:
    await poller.poller.poll_once()
    poller.discord.missing_channels = frozenset({MAIN_CHANNEL})
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    assert poller.statuses() == [PostStatus.PENDING]

    poller.discord.missing_channels = frozenset()
    await poller.publisher.retry_pending()
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 1
    assert poller.statuses() == [PostStatus.POSTED]


async def test_collections_without_forum_one_tracking_are_not_polled(poller: Poller) -> None:
    [collection] = poller.store.collections
    poller.store.update_collection(replace(collection, track_marketplace=False))
    await poller.reloader.reload()

    await poller.poller.poll_once()
    assert poller.forum_one.requests == []
