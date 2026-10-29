"""Rarible sales read from the transaction receipt of a tracked Transfer."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.chain.abi import TRANSFER_TOPIC
from app.chain.rarible import EXCHANGE_META_V2, MATCH_TOPIC
from app.chain.tests.conftest import (
    MAIN_CHANNEL,
    TEST_CONTRACT,
    Bot,
    block_time,
    build_bot,
    sepolia_collection,
    transfer_log,
)
from app.chain.tests.test_forum_one_sales import (
    BUYER,
    DRAGONZ,
    SELLER,
    TX_A,
    address_word,
    dragonz_collection,
    word,
)
from app.core.store import EventKind, PostStatus

WETH = "0x4200000000000000000000000000000000000006"
CANCEL_TOPIC = "0xe8d9861dbc9c664c3a2ef9bb3a1ec3f3a9a2e2b0b8d6a1e7a7ec7ef1b1e0f3c1"


def match_log(
    left_fill: int, right_fill: int, address: str = EXCHANGE_META_V2, log_index: int = 9
) -> dict[str, Any]:
    """A Match as a receipt holds it: four data words, nothing indexed."""
    return {
        "address": address,
        "topics": [MATCH_TOPIC],
        "data": "0x" + word(0x11) + word(0x22) + word(left_fill) + word(right_fill),
        "logIndex": hex(log_index),
    }


def payout_log(coin: str, to: str, amount: int) -> dict[str, Any]:
    """An ERC-20 Transfer: 3 topics, the amount in data."""
    return {
        "address": coin,
        "topics": [TRANSFER_TOPIC, "0x" + address_word(BUYER), "0x" + address_word(to)],
        "data": "0x" + word(amount),
        "logIndex": "0x8",
    }


@pytest.fixture
async def base_bot() -> Bot:
    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.erc20s[WETH] = ("WETH", 18)
    return bot


async def read(bot: Bot) -> None:
    bot.alchemy.logs = [transfer_log(DRAGONZ, 5, 101, TX_A, 0, SELLER, BUYER)]
    await bot.reader.connect_once()


async def test_a_match_with_weth_payouts_posts_one_rarible_sale(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        payout_log(WETH, SELLER, 98 * 10**12),
        payout_log(WETH, "0x" + "75" * 20, 2 * 10**12),
        match_log(1, 10**14),
    ]

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Rarible"]
    assert card.values("Price") == ["0.0001 WETH"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]
    assert card.buttons[0] == ("Transaction", f"https://basescan.org/tx/{TX_A}")
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.SKIPPED]


async def test_each_transfer_takes_the_price_of_its_own_match(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        match_log(1, 10**14, log_index=3),
        match_log(1, 3 * 10**14, log_index=7),
    ]
    base_bot.alchemy.logs = [
        transfer_log(DRAGONZ, 5, 101, TX_A, 1, SELLER, BUYER),
        transfer_log(DRAGONZ, 6, 101, TX_A, 5, SELLER, BUYER),
    ]

    await base_bot.reader.connect_once()

    prices = sorted(card.values("Price")[0] for card in base_bot.discord.messages(MAIN_CHANNEL))
    assert prices == ["0.0001 ETH", "0.0003 ETH"]


async def test_a_transfer_after_the_last_match_is_not_a_rarible_sale(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [match_log(1, 10**14, log_index=3)]
    base_bot.alchemy.logs = [transfer_log(DRAGONZ, 5, 101, TX_A, 5, SELLER, BUYER)]

    await base_bot.reader.connect_once()

    assert base_bot.store.events[EventKind.SALE] == []


async def test_a_match_without_an_erc20_payout_is_priced_in_eth(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [match_log(10**14, 1)]

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["0.0001 ETH"]


async def test_a_cancel_alone_posts_nothing(base_bot: Bot) -> None:
    cancel = {**match_log(1, 1), "topics": [CANCEL_TOPIC]}
    base_bot.alchemy.receipts[TX_A] = [cancel]

    await read(base_bot)

    assert base_bot.store.events[EventKind.SALE] == []
    assert base_bot.discord.sent == {}


async def test_a_match_from_another_contract_is_ignored(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [match_log(1, 10**14, address="0x" + "ee" * 20)]

    await read(base_bot)

    assert base_bot.store.events[EventKind.SALE] == []


async def test_the_same_sale_seen_twice_posts_once(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [match_log(1, 10**14)]
    await read(base_bot)

    await base_bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    await base_bot.reader.connect_once()

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1


async def test_post_sales_off_records_the_rarible_sale_as_skipped(base_bot: Bot) -> None:
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, post_sales=False))
    await base_bot.reloader.reload()
    base_bot.alchemy.receipts[TX_A] = [match_log(1, 10**14)]

    await read(base_bot)

    assert base_bot.discord.sent == {}
    assert [s.status for s in base_bot.store.events[EventKind.SALE]] == [PostStatus.SKIPPED]


async def test_test_contract_sales_are_never_decoded() -> None:
    bot = await build_bot("base-sepolia", sepolia_collection())
    await bot.store.set_cursor("base-sepolia", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [match_log(1, 10**14)]
    bot.alchemy.logs = [transfer_log(TEST_CONTRACT, 5, 101, TX_A, 0, SELLER, BUYER)]

    await bot.reader.connect_once()

    assert bot.alchemy.receipt_requests == []
    assert bot.store.events[EventKind.SALE] == []
