"""Mints through the chain reader: Alchemy in, Discord messages and event status out."""

from dataclasses import replace
from datetime import UTC, datetime

import discord
import pytest

from app.chain.reader import POLL_INTERVAL_SECONDS
from app.chain.rpc import SubscriptionError
from app.chain.tests.conftest import (
    MAIN_CHANNEL,
    SECOND_CONTRACT,
    TEST_CHANNEL,
    TEST_CONTRACT,
    Bot,
    StopTest,
    block_time,
    embed_field,
    mint_log,
    sepolia_collection,
)
from app.core.store import PostStatus

TX_A = "0x" + "a1" * 32
TX_B = "0x" + "b2" * 32


async def start_at(bot: Bot, block: int) -> None:
    """Put the cursor at a block, as if the bot had been running up to it."""
    await bot.store.set_cursor(
        "base-sepolia", block, datetime.fromtimestamp(block_time(block), UTC)
    )


def progress(message: list[discord.Embed]) -> list[str]:
    return [embed_field(embed, "Progress") for embed in message]


async def test_test_contract_mint_posts_in_test_channel_with_progress(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.initial_supply = 211
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [message] = bot.discord.messages(TEST_CHANNEL)
    [embed] = message
    assert embed_field(embed, "Progress") == "#212 of 750"
    assert embed.title.endswith("#7")
    assert embed.image.url == "https://images.test/7.png"
    assert bot.discord.messages(MAIN_CHANNEL) == []
    assert bot.mint_statuses() == [PostStatus.POSTED]


async def test_first_start_posts_nothing_old(bot: Bot) -> None:
    bot.alchemy.head = 100
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 90, TX_A, 0)]

    await bot.reader.connect_once()

    assert bot.discord.sent == {}
    cursor = await bot.store.get_cursor("base-sepolia")
    assert cursor is not None and cursor.last_block == 100


async def test_twelve_token_mint_splits_into_10_and_2_with_exact_progress(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 100 + i, 101, TX_A, i) for i in range(12)]

    await bot.reader.connect_once()

    first, second = bot.discord.messages(TEST_CHANNEL)
    assert (len(first), len(second)) == (10, 2)
    assert progress(first) + progress(second) == [f"#{n} of 750" for n in range(1, 13)]


async def test_two_mint_transactions_in_one_block_get_exact_progress(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.initial_supply = 40
    bot.alchemy.logs = [
        mint_log(TEST_CONTRACT, 1, 101, TX_A, 3),
        mint_log(TEST_CONTRACT, 2, 101, TX_A, 4),
        mint_log(TEST_CONTRACT, 3, 101, TX_B, 5),
    ]

    await bot.reader.connect_once()

    first, second = bot.discord.messages(TEST_CHANNEL)
    assert progress(first) == ["#41 of 750", "#42 of 750"]
    assert progress(second) == ["#43 of 750"]


async def test_paid_mint_shows_price_per_token(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, i, 101, TX_A, i) for i in range(3)]
    bot.alchemy.tx_values_wei = {TX_A: 150_000_000_000_000_000}

    await bot.reader.connect_once()

    [message] = bot.discord.messages(TEST_CHANNEL)
    assert [embed_field(embed, "Price") for embed in message] == ["0.05 ETH"] * 3


async def test_free_mint_shows_no_price(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [[embed]] = bot.discord.messages(TEST_CHANNEL)
    assert [f.name for f in embed.fields if f.name == "Price"] == []


async def test_log_seen_by_subscription_and_catch_up_posts_once(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 100
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]
    bot.alchemy.notifications = [bot.alchemy.logs[0]]

    await bot.reader.connect_once()  # the subscription delivers the mint
    assert len(bot.discord.messages(TEST_CHANNEL)) == 1

    await start_at(bot, 100)  # a reconnect that catches up over the same block
    bot.alchemy.head = 101
    bot.alchemy.notifications = []
    await bot.reader.connect_once()

    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
    assert bot.mint_statuses() == [PostStatus.POSTED]


async def test_removed_log_is_ignored(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 100
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]
    bot.alchemy.notifications = [{**bot.alchemy.logs[0], "removed": True}]

    await bot.reader.connect_once()

    assert bot.discord.sent == {}
    assert bot.mint_statuses() == []


async def test_catch_up_stops_at_six_hours(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 100 + 12_000  # 6 hours 40 minutes of 2-second blocks
    bot.alchemy.logs = [
        mint_log(TEST_CONTRACT, 1, 1_000, TX_A, 0),  # 6 hours 17 minutes before the head
        mint_log(TEST_CONTRACT, 2, 11_000, TX_B, 0),  # 33 minutes before the head
    ]

    await bot.reader.connect_once()

    [[embed]] = bot.discord.messages(TEST_CHANNEL)
    assert embed.title.endswith("#2")
    cursor = await bot.store.get_cursor("base-sepolia")
    assert cursor is not None and cursor.last_block == 12_100


async def test_post_mints_off_records_skipped_and_turning_on_posts_nothing_old(bot: Bot) -> None:
    await start_at(bot, 100)
    [collection] = bot.store.collections
    bot.store.update_collection(replace(collection, post_mints=False))
    await bot.reloader.reload()
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    await bot.reader.connect_once()
    assert bot.discord.sent == {}
    assert bot.mint_statuses() == [PostStatus.SKIPPED]

    bot.store.update_collection(replace(collection, post_mints=True))
    await bot.reloader.reload()
    bot.alchemy.head = 102
    bot.alchemy.logs.append(mint_log(TEST_CONTRACT, 2, 102, TX_B, 0))
    await start_at(bot, 100)  # re-reading block 101 must not post the skipped mint
    await bot.reader.connect_once()

    [[embed]] = bot.discord.messages(TEST_CHANNEL)
    assert embed.title.endswith("#2")
    assert bot.mint_statuses() == [PostStatus.SKIPPED, PostStatus.POSTED]


async def test_failed_post_stays_pending(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    await bot.reader.connect_once()

    assert bot.mint_statuses() == [PostStatus.PENDING]


async def test_collection_added_later_is_tracked_from_the_current_block(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(SECOND_CONTRACT, 1, 101, TX_A, 0)]  # before it is tracked
    bot.store.add_collection(
        sepolia_collection(collection_id="second", name="Second", contract_address=SECOND_CONTRACT)
    )
    await bot.reloader.reload()
    bot.reader.replace_contracts(bot.reloader.current.tracked_contracts["base-sepolia"])

    await bot.reader.connect_once()
    assert bot.discord.sent == {}

    bot.alchemy.head = 102
    bot.alchemy.logs.append(mint_log(SECOND_CONTRACT, 2, 102, TX_B, 0))
    await bot.reader.connect_once()

    [[embed]] = bot.discord.messages(TEST_CHANNEL)
    assert embed.title.endswith("#2")
    assert bot.alchemy.subscription_filters[-1]["address"] == sorted(
        [TEST_CONTRACT, SECOND_CONTRACT]
    )


async def test_reconnect_backs_off_between_failures(bot: Bot) -> None:
    bot.alchemy.failing_requests = 100

    with pytest.raises(StopTest):
        await bot.reader.run()

    assert bot.sleeps == [2.0, 4.0, 8.0]


async def test_base_sepolia_polls_when_the_subscription_is_refused(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.subscription_error = SubscriptionError("no logs subscription")
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    with pytest.raises(StopTest):
        await bot.reader.run()

    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
    assert bot.sleeps[0] == POLL_INTERVAL_SECONDS
