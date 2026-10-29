"""Forum One listings through the poller: forumone.io pages in, Discord messages out."""

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import aiohttp
import pytest

from app.chain.tests.conftest import MAIN_CHANNEL
from app.core.store import EventKind, PostStatus
from app.marketplace.forum_one import ForumOneApi, ForumOneError
from app.marketplace.tests.conftest import LE_CONTRACT, NOW, SELLER, Poller, le_collection, listing
from app.nft.models import NFTListingEvent, NFTSaleEvent

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


async def test_pages_of_a_different_size_skip_nothing(poller: Poller) -> None:
    poller.forum_one.page_size = 20
    poller.forum_one.listings = [listing(n, f"0x{n:064x}") for n in range(1, 56)]
    await poller.poller.poll_once()
    assert [offset for _, offset in poller.forum_one.requests] == [0, 20, 40]
    assert poller.statuses() == [PostStatus.SKIPPED] * 55


async def test_a_forum_one_outage_sets_no_baseline_and_other_collections_still_poll(
    poller: Poller,
) -> None:
    other = "0x" + "9" * 40
    poller.store.add_collection(
        le_collection(collection_id="other", contract_address=other, name="Other")
    )
    await poller.reloader.reload()
    poller.forum_one.failing_contracts = frozenset({LE_CONTRACT})
    poller.forum_one.listings = [listing(1, HASH_A)]
    await poller.poller.poll_once()
    assert {contract for contract, _ in poller.forum_one.requests} == {LE_CONTRACT, other}
    assert poller.statuses() == [PostStatus.SKIPPED]  # only the other collection's baseline

    poller.forum_one.failing_contracts = frozenset()
    poller.forum_one.listings = [listing(1, HASH_A), listing(2, HASH_B)]
    await poller.poller.poll_once()
    # the other collection posts its new listing; LE's first successful poll is its baseline
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 1
    assert poller.statuses().count(PostStatus.PENDING) == 0


async def test_a_malformed_page_is_contained_and_sets_no_baseline(poller: Poller) -> None:
    poller.forum_one.malformed_contracts = frozenset({LE_CONTRACT})
    await poller.poller.poll_once()
    assert poller.statuses() == []
    assert poller.discord.sent == {}


async def test_one_bad_listing_is_skipped_and_the_rest_still_post(poller: Poller) -> None:
    await poller.poller.poll_once()
    poller.forum_one.listings = [
        listing(1, HASH_A, currencySymbol=None),
        {k: v for k, v in listing(2, HASH_B).items() if k != "createdAt"},
        listing(3, HASH_C, tokenId=3),
    ]
    await poller.poller.poll_once()
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "DragonZ Limited Edition #3" in card.text
    assert len(poller.statuses()) == 1


async def test_a_server_that_ignores_offset_stops_at_the_page_cap(poller: Poller) -> None:
    class _Stuck:
        calls = 0

        async def listings_page(self, _c: str, _a: str, _o: int) -> dict[str, object]:
            self.calls += 1
            return {"listings": [listing(1, HASH_A)], "hasMore": True}

    stuck = _Stuck()
    poller.poller.api = stuck
    await poller.poller.poll_once()
    assert stuck.calls == 100
    assert poller.statuses() == []


async def test_a_listing_older_than_six_hours_is_recorded_skipped_not_posted(
    poller: Poller,
) -> None:
    await poller.poller.poll_once()
    old = (NOW - timedelta(hours=6, seconds=1)).isoformat()
    poller.forum_one.listings = [listing(1, HASH_A, createdAt=old)]
    await poller.poller.poll_once()
    assert poller.statuses() == [PostStatus.SKIPPED]
    assert poller.discord.sent == {}


async def test_the_small_feed_image_is_rewritten_to_512(poller: Poller) -> None:
    await poller.poller.poll_once()
    url = f"https://cdn.test/storage/8453/{LE_CONTRACT}/64/9.webp"
    poller.forum_one.listings = [listing(9, HASH_A, imageUrl=url)]
    await poller.poller.poll_once()
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert card.images == [f"https://cdn.test/storage/8453/{LE_CONTRACT}/512/9.webp"]


async def test_a_pending_listing_expires_after_six_hours(poller: Poller) -> None:
    await poller.poller.poll_once()
    poller.discord.missing_channels = frozenset({MAIN_CHANNEL})
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    event = poller.store.events[EventKind.LISTING][0].event
    assert isinstance(event, NFTListingEvent)
    event_time = event.event_timestamp

    poller.clock.current = event_time + timedelta(hours=6)
    await poller.publisher.retry_pending()
    assert poller.statuses() == [PostStatus.PENDING]

    poller.discord.missing_channels = frozenset()
    poller.clock.current = event_time + timedelta(hours=6, seconds=1)
    await poller.publisher.retry_pending()
    assert poller.statuses() == [PostStatus.EXPIRED]
    assert poller.discord.sent == {}


class _Response:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientError(f"HTTP {self.status}")

    async def json(self) -> object:
        return json.loads(self._body)


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response

    def get(self, *_: object, **__: object) -> _Response:
        return self.response


@pytest.mark.parametrize(
    "response", [_Response(503, "{}"), _Response(200, "<html>not json")], ids=["5xx", "bad-json"]
)
async def test_api_faults_become_forum_one_errors(response: _Response) -> None:
    api = ForumOneApi(_Session(response))  # type: ignore[arg-type]
    with pytest.raises(ForumOneError):
        await api.listings_page("base", LE_CONTRACT, 0)


def _sale(token_id: int, at: datetime, seller: str = SELLER) -> NFTSaleEvent:
    return NFTSaleEvent(
        collection_id=1,
        token_id=str(token_id),
        seller_address=seller,
        buyer_address="0x" + "bb" * 20,
        marketplace="forum_one",
        price_native=Decimal("0.02"),
        currency="ETH",
        sale_id=f"0xtx:{token_id}",
        transaction_hash="0xtx",
        event_timestamp=at,
    )


async def _posted_listing(poller: Poller, token_id: int = 24, order_hash: str = HASH_A) -> None:
    await poller.poller.poll_once()
    poller.forum_one.listings = [listing(token_id, order_hash)]
    await poller.poller.poll_once()
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 1


async def test_a_listing_that_vanishes_with_no_sale_is_deleted(poller: Poller) -> None:
    await _posted_listing(poller)
    poller.forum_one.listings = []
    await poller.poller.poll_once()
    [(channel, _)] = poller.discord.deleted
    assert channel == MAIN_CHANNEL
    assert poller.discord.edited == []

    await poller.poller.poll_once()
    assert len(poller.discord.deleted) == 1


async def test_listing_and_unlisting_four_times_leaves_only_the_live_post(poller: Poller) -> None:
    await poller.poller.poll_once()
    for n in range(4):
        poller.forum_one.listings = [listing(24, f"0x{n:064x}")]
        await poller.poller.poll_once()
        poller.forum_one.listings = []
        await poller.poller.poll_once()
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 5
    assert len(poller.discord.deleted) == 4


async def test_a_sale_deletes_a_live_listing_and_a_later_vanish_does_nothing_more(
    poller: Poller,
) -> None:
    await _posted_listing(poller)
    sale = _sale(24, NOW + timedelta(minutes=1))
    await poller.store.insert_sale(sale, PostStatus.SKIPPED)
    await poller.publisher.settle_sale(poller.reloader.current.collections[0], sale)
    assert len(poller.discord.deleted) == 1
    assert poller.discord.edited == []

    poller.forum_one.listings = []
    await poller.poller.poll_once()
    assert len(poller.discord.deleted) == 1


async def test_a_sale_by_another_seller_leaves_the_listing_alone(poller: Poller) -> None:
    await _posted_listing(poller)
    sale = _sale(24, NOW + timedelta(minutes=1), seller="0x" + "cc" * 20)
    await poller.publisher.settle_sale(poller.reloader.current.collections[0], sale)
    assert poller.discord.deleted == []


async def test_a_forum_one_outage_deletes_nothing(poller: Poller) -> None:
    await _posted_listing(poller)
    poller.forum_one.failing_contracts = frozenset({LE_CONTRACT})
    await poller.poller.poll_once()
    assert poller.discord.deleted == []
    assert poller.discord.edited == []


async def test_a_vanished_listing_that_was_never_posted_touches_no_discord(poller: Poller) -> None:
    poller.forum_one.listings = [listing(24, HASH_A)]
    await poller.poller.poll_once()
    assert poller.statuses() == [PostStatus.SKIPPED]
    poller.forum_one.listings = []
    await poller.poller.poll_once()
    assert poller.discord.deleted == []
    assert poller.discord.edited == []
    assert await poller.store.list_active_listings(1, "forum_one") == []


async def test_a_failed_delete_is_retried_on_the_next_poll(poller: Poller) -> None:
    await _posted_listing(poller)
    poller.forum_one.listings = []
    poller.discord.missing_channels = frozenset({MAIN_CHANNEL})
    await poller.poller.poll_once()
    assert len(await poller.store.list_active_listings(1, "forum_one")) == 1

    poller.discord.missing_channels = frozenset()
    await poller.poller.poll_once()
    assert len(poller.discord.deleted) == 1
