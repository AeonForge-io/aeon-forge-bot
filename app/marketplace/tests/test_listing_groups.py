"""Forum One listings held per collection and posted as one grouped post."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.chain.tests.conftest import MAIN_CHANNEL
from app.core.store import EventKind, PostStatus
from app.marketplace.tests.conftest import NOW, Poller, listing
from app.nft.models import NFTSaleEvent


def _hash(n: int) -> str:
    return f"0x{n:064x}"


async def _held(poller: Poller, count: int, minutes: int = 15) -> None:
    """A baseline poll, then `count` new listings seen in one poll under a window."""
    await poller.poller.poll_once()
    [collection] = poller.store.collections
    poller.store.update_collection(replace(collection, listing_group_minutes=minutes))
    await poller.reloader.reload()
    poller.forum_one.listings = [listing(n, _hash(n)) for n in range(1, count + 1)]
    await poller.poller.poll_once()


async def _pass_window(poller: Poller, minutes: int = 16) -> None:
    poller.clock.current = NOW + timedelta(minutes=minutes)
    await poller.poller.poll_once()


def _message_ids(poller: Poller) -> list[int | None]:
    return [stored.message_id for stored in poller.store.events[EventKind.LISTING]]


async def _vanish(poller: Poller, *numbers: int) -> None:
    poller.forum_one.listings = [
        x for x in poller.forum_one.listings if int(x["tokenId"]) not in numbers
    ]
    await poller.poller.poll_once()


async def test_a_burst_is_held_then_posts_as_one_grouped_post(poller: Poller) -> None:
    await _held(poller, 3)
    assert poller.discord.sent == {}
    assert poller.statuses() == [PostStatus.PENDING] * 3

    poller.clock.current = NOW + timedelta(minutes=14)
    await poller.poller.poll_once()
    assert poller.discord.sent == {}

    await _pass_window(poller)
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "## 3 new listings: DragonZ Limited Edition" in card.text
    assert len(card.thumbnails) == 3
    assert poller.statuses() == [PostStatus.POSTED] * 3
    assert len(set(_message_ids(poller))) == 1
    assert None not in _message_ids(poller)


async def test_a_window_ending_with_one_listing_posts_the_single_card(poller: Poller) -> None:
    await _held(poller, 1)
    await _pass_window(poller)
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert card.values("Seller")
    assert ("View on Forum One", card.buttons[0][1]) == card.buttons[0]


async def test_a_retry_after_a_failed_send_folds_in_newer_listings(poller: Poller) -> None:
    await _held(poller, 2)
    poller.discord.missing_channels = frozenset({MAIN_CHANNEL})
    await _pass_window(poller)
    assert poller.statuses() == [PostStatus.PENDING] * 2

    poller.discord.missing_channels = frozenset()
    poller.forum_one.listings.append(listing(3, _hash(3)))
    await poller.poller.poll_once()  # the new listing is inserted, the old ones are due
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "## 3 new listings" in card.text
    assert len(set(_message_ids(poller))) == 1


async def test_retry_pending_posts_a_due_group(poller: Poller) -> None:
    await _held(poller, 2)
    poller.clock.current = NOW + timedelta(minutes=16)
    await poller.publisher.retry_pending()
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "## 2 new listings" in card.text


async def test_a_listing_that_closes_while_held_is_never_posted(poller: Poller) -> None:
    await _held(poller, 3)
    await _vanish(poller, 2)
    await _pass_window(poller)
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert "## 2 new listings" in card.text
    assert poller.statuses() == [PostStatus.POSTED, PostStatus.SKIPPED, PostStatus.POSTED]


async def test_25_listings_show_10_rows_and_closing_one_moves_the_next_up(poller: Poller) -> None:
    await _held(poller, 25)
    await _pass_window(poller)
    [card] = poller.discord.messages(MAIN_CHANNEL)
    assert len(card.thumbnails) == 10
    assert "and 15 more listed" in card.text

    await _vanish(poller, 1)
    [(_, _, edited)] = poller.discord.edited
    assert "## 24 new listings" in edited.text
    assert "[DragonZ Limited Edition #11]" in edited.text
    assert "[DragonZ Limited Edition #1]" not in edited.text
    assert "and 14 more listed" in edited.text


async def test_listings_vanishing_together_give_one_edit_and_the_last_one_deletes(
    poller: Poller,
) -> None:
    await _held(poller, 4)
    await _pass_window(poller)
    await _vanish(poller, 1, 2, 3)
    [(_, _, edited)] = poller.discord.edited
    assert "## 1 new listing: " in edited.text
    assert len(edited.thumbnails) == 1
    assert poller.discord.deleted == []

    await _vanish(poller, 4)
    assert len(poller.discord.deleted) == 1
    assert len(poller.discord.edited) == 1


async def test_a_recorded_sale_edits_the_grouped_post(poller: Poller) -> None:
    await _held(poller, 3)
    await _pass_window(poller)
    sale = NFTSaleEvent(
        collection_id=1,
        token_id="2",
        seller_address=poller.forum_one.listings[1]["sellerAddress"],
        buyer_address="0x" + "bb" * 20,
        marketplace="forum_one",
        price_native=Decimal("0.02"),
        currency="ETH",
        sale_id="0xtx:2",
        transaction_hash="0xtx",
        event_timestamp=poller.clock.current,
    )
    await poller.publisher.settle_sale(poller.reloader.current.collections[0], sale)
    [(_, _, edited)] = poller.discord.edited
    assert "## 2 new listings" in edited.text
    assert "[DragonZ Limited Edition #2]" not in edited.text


async def test_a_failed_edit_leaves_the_listings_active_and_the_next_poll_edits_again(
    poller: Poller,
) -> None:
    await _held(poller, 3)
    await _pass_window(poller)
    poller.discord.missing_channels = frozenset({MAIN_CHANNEL})
    await _vanish(poller, 1)
    assert len(await poller.store.list_active_listings(1, "forum_one")) == 3

    poller.discord.missing_channels = frozenset()
    await poller.poller.poll_once()
    [(_, _, edited)] = poller.discord.edited
    assert "## 2 new listings" in edited.text
    assert len(await poller.store.list_active_listings(1, "forum_one")) == 2


async def test_window_zero_posts_each_listing_at_once(poller: Poller) -> None:
    await _held(poller, 3, minutes=0)
    assert len(poller.discord.messages(MAIN_CHANNEL)) == 3
