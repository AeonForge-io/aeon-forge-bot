"""The fallback: a tracked transfer paid for outside every named marketplace posts as a sale."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.chain.abi import TRANSFER_TOPIC
from app.chain.tests.conftest import (
    MAIN_CHANNEL,
    Bot,
    block_time,
    build_bot,
    transfer_log,
)
from app.chain.tests.test_forum_one_sales import (
    BUYER,
    DRAGONZ,
    SELLER,
    SIGNED_LISTING_FILLED_TOPIC,
    TX_A,
    USDC,
    address_word,
    dragonz_collection,
    forum_one_log,
    word,
)
from app.core.store import EventKind, PostStatus

TX_B = "0x" + "b2" * 32
SMART_WALLET = "0x00000000000000000000000000000000000000c3"
RELAYER = "0x00000000000000000000000000000000000000d4"
FEE_WALLET = "0x00000000000000000000000000000000000000e5"
ETH = 10**18


def erc20_transfer(coin: str, sender: str, recipient: str, amount: int) -> dict[str, Any]:
    return {
        "address": coin,
        "topics": [TRANSFER_TOPIC, "0x" + address_word(sender), "0x" + address_word(recipient)],
        "data": "0x" + word(amount),
        "logIndex": "0x8",
    }


def call(
    sender: str, to: str, value: int, calls: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"from": sender, "to": to, "value": hex(value), "calls": calls or []}


@pytest.fixture
async def base_bot() -> Bot:
    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.erc20s[USDC] = ("USDC", 6)
    return bot


async def read(bot: Bot, *token_ids: int, tx: str = TX_A) -> None:
    bot.alchemy.logs = [
        transfer_log(DRAGONZ, token_id, 101, tx, index, SELLER, BUYER)
        for index, token_id in enumerate(token_ids or (5,))
    ]
    await bot.reader.connect_once()


def transfer_statuses(bot: Bot) -> list[PostStatus]:
    return [stored.status for stored in bot.store.events[EventKind.TRANSFER]]


async def test_an_erc20_payment_to_the_seller_posts_the_buyers_gross_amount(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        erc20_transfer(USDC, BUYER, SELLER, 90 * 10**6),
        erc20_transfer(USDC, BUYER, FEE_WALLET, 10 * 10**6),
    ]

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Other marketplace"]
    assert card.values("Price") == ["100 USDC"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]
    assert card.buttons[0] == ("Transaction", f"https://basescan.org/tx/{TX_A}")
    assert transfer_statuses(base_bot) == [PostStatus.SKIPPED]


async def test_an_erc20_paid_by_someone_else_shows_what_the_seller_received(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.receipts[TX_A] = [erc20_transfer(USDC, RELAYER, SELLER, 90 * 10**6)]

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Other marketplace"]
    assert card.values("Seller received") == ["90 USDC"]
    assert base_bot.discord.messages(MAIN_CHANNEL)[0].values("Price") == []


async def test_a_direct_eth_buy_posts_the_transaction_value(base_bot: Bot) -> None:
    base_bot.alchemy.tx_values_wei[TX_A] = ETH // 10
    base_bot.alchemy.tx_senders[TX_A] = BUYER

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Other marketplace"]
    assert card.values("Price") == ["0.1 ETH"]
    assert "debug_traceTransaction" not in base_bot.alchemy.calls


async def test_two_tokens_in_one_direct_buy_split_the_value(base_bot: Bot) -> None:
    base_bot.alchemy.tx_values_wei[TX_A] = ETH // 10
    base_bot.alchemy.tx_senders[TX_A] = BUYER

    await read(base_bot, 5, 6)

    cards = base_bot.discord.messages(MAIN_CHANNEL)
    assert [c.values("Price") for c in cards] == [["0.05 ETH"], ["0.05 ETH"]]


async def test_a_smart_wallet_buy_is_found_in_the_trace(base_bot: Bot) -> None:
    base_bot.alchemy.tx_senders[TX_A] = RELAYER
    base_bot.alchemy.tx_targets[TX_A] = SMART_WALLET
    base_bot.alchemy.traces[TX_A] = call(
        RELAYER,
        SMART_WALLET,
        0,
        [
            call(BUYER, SELLER, 9 * ETH // 100),
            call(BUYER, FEE_WALLET, ETH // 100),
        ],
    )

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Other marketplace"]
    assert card.values("Price") == ["0.1 ETH"]


async def test_a_plain_transfer_with_no_payment_is_not_a_sale(base_bot: Bot) -> None:
    base_bot.alchemy.tx_senders[TX_A] = RELAYER
    base_bot.alchemy.tx_targets[TX_A] = SMART_WALLET
    base_bot.alchemy.traces[TX_A] = call(RELAYER, SMART_WALLET, 0, [call(BUYER, FEE_WALLET, 1)])

    await read(base_bot)

    assert base_bot.discord.messages(MAIN_CHANNEL) == []
    assert transfer_statuses(base_bot) == [PostStatus.SKIPPED]  # company mode, sender not company
    assert base_bot.alchemy.calls.count("debug_traceTransaction") == 1


async def test_no_trace_is_called_when_the_tx_called_the_nft_contract(base_bot: Bot) -> None:
    base_bot.alchemy.tx_senders[TX_A] = SELLER
    base_bot.alchemy.tx_targets[TX_A] = DRAGONZ

    await read(base_bot)

    assert base_bot.discord.messages(MAIN_CHANNEL) == []
    assert "debug_traceTransaction" not in base_bot.alchemy.calls


async def test_a_sale_a_named_decoder_recorded_does_not_post_again(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        forum_one_log(SIGNED_LISTING_FILLED_TOPIC, 5, ETH // 10),
        erc20_transfer(USDC, BUYER, SELLER, 90 * 10**6),
    ]

    await read(base_bot)

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Forum One"]
    assert len(base_bot.store.events[EventKind.SALE]) == 1


async def test_the_same_fallback_sale_seen_twice_posts_once(base_bot: Bot) -> None:
    base_bot.alchemy.tx_values_wei[TX_A] = ETH // 10
    base_bot.alchemy.tx_senders[TX_A] = BUYER

    await read(base_bot)
    await read(base_bot)

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1


async def test_a_switched_off_sales_post_is_recorded_as_skipped() -> None:
    bot = await build_bot("base", dragonz_collection(post_sales=False))
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.tx_values_wei[TX_A] = ETH // 10
    bot.alchemy.tx_senders[TX_A] = BUYER

    await read(bot)

    assert bot.discord.messages(MAIN_CHANNEL) == []
    assert [s.status for s in bot.store.events[EventKind.SALE]] == [PostStatus.SKIPPED]
