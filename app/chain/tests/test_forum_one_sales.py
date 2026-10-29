"""Forum One sales read from the transaction receipt of a tracked Transfer."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.chain.forum_one import FORUM_ONE_PROXY
from app.chain.tests.conftest import (
    MAIN_CHANNEL,
    TEST_CONTRACT,
    Bot,
    block_time,
    build_bot,
    sepolia_collection,
    transfer_log,
)
from app.core.store import Collection, EventKind, PostStatus

DRAGONZ = "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
SELLER = "0x00000000000000000000000000000000000000a1"
BUYER = "0x00000000000000000000000000000000000000b2"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TX_A = "0x" + "a1" * 32
ORDER_HASH = "0x" + "99" * 32

SALE_TOPIC = "0x57922c657d2aa8c0407bcb047bc5a483d91c0f7e28188f214b14a84eab893be8"
OFFER_ACCEPTED_TOPIC = "0xf88935f945a788a879b9adf2f3f28f1500f1ccce23c42b83efbedb913fb87dca"
SIGNED_LISTING_FILLED_TOPIC = "0x78a483c83edb347901adcedb783f01dc2e4d71ee9039ff4cb66b869109e8e4b5"
SIGNED_OFFER_ACCEPTED_TOPIC = "0x3a4038ed4cc3e7ca35508d12ec6915481d30ca4b831828aed2355b4533de1a50"

ETH_CURRENCY = "0x" + "00" * 20


def word(value: int) -> str:
    return f"{value:064x}"


def address_word(address: str) -> str:
    return address[2:].rjust(64, "0")


def forum_one_log(
    topic: str,
    token_id: int,
    total_price: int,
    currency: str = ETH_CURRENCY,
    asset_contract: str = DRAGONZ,
    address: str = FORUM_ONE_PROXY,
) -> dict[str, Any]:
    """A Forum One proxy event as a receipt holds it."""
    signed = topic in (SIGNED_LISTING_FILLED_TOPIC, SIGNED_OFFER_ACCEPTED_TOPIC)
    words = [address_word(asset_contract), word(token_id), word(1)]
    if signed:
        words.append(word(1))  # filledToDate
    words += [word(total_price), address_word(currency), word(0), word(0), address_word(SELLER)]
    return {
        "address": address,
        "topics": [
            topic,
            ORDER_HASH if signed else "0x" + word(7),
            "0x" + address_word(SELLER),
            "0x" + address_word(BUYER),
        ],
        "data": "0x" + "".join(words),
        "logIndex": "0x9",
    }


def dragonz_collection(**overrides: Any) -> Collection:
    return replace(
        sepolia_collection(
            collection_id="dragonz-limited-edition",
            name="DragonZ Limited Edition",
            chain="base",
            contract_address=DRAGONZ,
            discord_channel_id=MAIN_CHANNEL,
            track_marketplace=True,
            marketplaces=("forum_one",),
        ),
        **overrides,
    )


@pytest.fixture
async def base_bot() -> Bot:
    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    return bot


async def read(bot: Bot, *logs: dict[str, Any]) -> None:
    bot.alchemy.logs = list(logs)
    await bot.reader.connect_once()


def sale_transfer(token_id: int = 5, tx: str = TX_A, log_index: int = 0) -> dict[str, Any]:
    return transfer_log(DRAGONZ, token_id, 101, tx, log_index, SELLER, BUYER)


@pytest.mark.parametrize(
    "topic",
    [
        SALE_TOPIC,
        OFFER_ACCEPTED_TOPIC,
        SIGNED_LISTING_FILLED_TOPIC,
        SIGNED_OFFER_ACCEPTED_TOPIC,
    ],
)
async def test_each_forum_one_event_posts_one_sale_with_price_and_coin(
    base_bot: Bot, topic: str
) -> None:
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(topic, 5, 45 * 10**15)]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["0.045 ETH"]
    assert card.values("Marketplace") == ["Forum One"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]
    assert "#5" in card.text
    assert card.buttons[0] == ("Transaction", f"https://basescan.org/tx/{TX_A}")


async def test_erc20_sale_shows_the_token_symbol_and_decimals(base_bot: Bot) -> None:
    base_bot.alchemy.erc20s[USDC] = ("USDC", 6)
    base_bot.alchemy.receipts[TX_A] = [
        forum_one_log(SIGNED_OFFER_ACCEPTED_TOPIC, 5, 12_500_000, currency=USDC)
    ]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["12.5 USDC"]


async def test_the_sale_transfer_posts_only_as_the_sale(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18)]
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, transfer_mode="all"))
    await base_bot.reloader.reload()

    await read(base_bot, sale_transfer())

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.SKIPPED]


async def test_a_sale_seen_again_by_catch_up_posts_once(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18)]
    await read(base_bot, sale_transfer())

    await base_bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    await base_bot.reader.connect_once()

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1


async def test_two_tokens_sold_in_one_transaction_fetch_the_receipt_once(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        forum_one_log(SALE_TOPIC, 5, 10**18),
        forum_one_log(SALE_TOPIC, 6, 2 * 10**18),
    ]

    await read(base_bot, sale_transfer(5, log_index=0), sale_transfer(6, log_index=1))

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 2
    assert base_bot.alchemy.receipt_requests == [TX_A]


async def test_post_sales_off_records_the_sale_as_skipped(base_bot: Bot) -> None:
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, post_sales=False))
    await base_bot.reloader.reload()
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18)]

    await read(base_bot, sale_transfer())

    assert base_bot.discord.sent == {}
    assert [s.status for s in base_bot.store.events[EventKind.SALE]] == [PostStatus.SKIPPED]


async def test_a_forum_one_event_for_another_token_is_not_this_transfers_sale(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 99, 10**18)]

    await read(base_bot, sale_transfer(5))

    assert base_bot.discord.sent == {}
    assert base_bot.store.events[EventKind.SALE] == []


async def test_a_look_alike_sale_event_from_another_contract_is_ignored(base_bot: Bot) -> None:
    fake = "0x" + "ee" * 20
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18, address=fake)]

    await read(base_bot, sale_transfer())

    assert base_bot.store.events[EventKind.SALE] == []
    assert base_bot.discord.sent == {}


async def test_a_transfer_without_a_sale_event_is_a_plain_transfer(base_bot: Bot) -> None:
    await read(base_bot, sale_transfer())

    assert base_bot.discord.sent == {}
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.SKIPPED]


async def test_a_failed_sale_post_is_retried_by_the_loop(base_bot: Bot) -> None:
    from app.chain.tests.test_transfers_and_retries import run_loop_once

    base_bot.discord.missing_channels = frozenset({MAIN_CHANNEL})
    base_bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18)]
    await read(base_bot, sale_transfer())
    assert [s.status for s in base_bot.store.events[EventKind.SALE]] == [PostStatus.PENDING]

    base_bot.discord.missing_channels = frozenset()
    await run_loop_once(base_bot)

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1
    assert [s.status for s in base_bot.store.events[EventKind.SALE]] == [PostStatus.POSTED]


async def test_test_contract_sales_are_never_decoded() -> None:
    bot = await build_bot("base-sepolia", sepolia_collection())
    await bot.store.set_cursor("base-sepolia", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [
        forum_one_log(SALE_TOPIC, 5, 10**18, asset_contract=TEST_CONTRACT)
    ]

    await read(bot, transfer_log(TEST_CONTRACT, 5, 101, TX_A, 0, SELLER, BUYER))

    assert bot.alchemy.receipt_requests == []
    assert bot.store.events[EventKind.SALE] == []


async def test_a_pending_sale_expires_after_six_hours() -> None:
    from app.chain.tests.test_transfers_and_retries import run_loop_once

    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.discord.missing_channels = frozenset({MAIN_CHANNEL})
    bot.alchemy.receipts[TX_A] = [forum_one_log(SALE_TOPIC, 5, 10**18)]
    await read(bot, sale_transfer())
    event_time = datetime.fromtimestamp(block_time(101), UTC)

    bot.discord.missing_channels = frozenset()
    bot.clock.current = event_time + timedelta(hours=6, seconds=1)
    await run_loop_once(bot)

    assert [s.status for s in bot.store.events[EventKind.SALE]] == [PostStatus.EXPIRED]
    assert bot.discord.messages(MAIN_CHANNEL) == []


async def test_forum_one_sales_are_not_decoded_off_base() -> None:
    bot = await build_bot(
        "base-sepolia",
        replace(sepolia_collection(), track_marketplace=True, marketplaces=("forum_one",)),
    )
    await bot.store.set_cursor("base-sepolia", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [
        forum_one_log(SALE_TOPIC, 5, 10**18, asset_contract=TEST_CONTRACT)
    ]

    await read(bot, transfer_log(TEST_CONTRACT, 5, 101, TX_A, 0, SELLER, BUYER))

    assert bot.alchemy.receipt_requests == []
    assert bot.store.events[EventKind.SALE] == []
