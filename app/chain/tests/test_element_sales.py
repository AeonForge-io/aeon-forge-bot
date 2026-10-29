"""Element sales read from the transaction receipt of a tracked Transfer."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.chain.element import ELEMENT_EX
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
    DRAGONZ,
    TX_A,
    address_word,
    dragonz_collection,
    word,
)
from app.core.store import EventKind, PostStatus

MAKER = "0x00000000000000000000000000000000000000a1"
TAKER = "0x00000000000000000000000000000000000000b2"
WETH = "0x4200000000000000000000000000000000000006"
ETH_COIN = "0x" + "ee" * 20

ERC721_SELL = "0x9c248aa1a265aa616f707b979d57f4529bb63a4fc34dc7fc61fdddc18410f74e"
ERC721_BUY = "0xd90a5c60975c6ff8eafcf02088e7b50ae5d9e156a79206ba553df1c4fb4594c2"
ERC1155_SELL = "0xfcde121a3f6a9b14a3ce266d61fc00940de86c4d8c1d733fe62d503ae5d99ff9"
ERC1155_BUY = "0x105616901449a64554ca9246a5bbcaca973b40b3c0055e5070c6fa191618d9f3"


def element_log(
    topic: str,
    token_id: int,
    amount: int,
    coin: str = ETH_COIN,
    nft: str = DRAGONZ,
    address: str = ELEMENT_EX,
) -> dict[str, Any]:
    """An ElementEx fill as a receipt holds it: every field in data, none indexed."""
    words = [
        word(0x77),  # orderHash
        address_word(MAKER),
        address_word(TAKER),
        word(7),  # nonce
        address_word(coin),
        word(amount),
        word(0x120),  # offset of the fees array
        address_word(nft),
        word(token_id),
    ]
    if topic in (ERC1155_SELL, ERC1155_BUY):
        words.append(word(1))  # fill quantity
    words += [word(1), address_word("0x" + "75" * 20), word(amount // 10), word(0x60), word(0)]
    return {
        "address": address,
        "topics": [topic],
        "data": "0x" + "".join(words),
        "logIndex": "0x9",
    }


@pytest.fixture
async def base_bot() -> Bot:
    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    return bot


async def read(bot: Bot, *logs: dict[str, Any]) -> None:
    bot.alchemy.logs = list(logs)
    await bot.reader.connect_once()


def sale_transfer(token_id: int = 5, log_index: int = 0) -> dict[str, Any]:
    return transfer_log(DRAGONZ, token_id, 101, TX_A, log_index, MAKER, TAKER)


@pytest.mark.parametrize("topic", [ERC721_SELL, ERC1155_SELL])
async def test_a_bought_listing_posts_one_element_sale_maker_selling_to_taker(
    base_bot: Bot, topic: str
) -> None:
    base_bot.alchemy.receipts[TX_A] = [element_log(topic, 5, 250_000_000_000_000)]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Element"]
    assert card.values("Price") == ["0.00025 ETH"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]
    assert card.buttons[0] == ("Transaction", f"https://basescan.org/tx/{TX_A}")
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.SKIPPED]


@pytest.mark.parametrize("topic", [ERC721_BUY, ERC1155_BUY])
async def test_an_accepted_offer_swaps_buyer_and_seller_and_shows_the_erc20(
    base_bot: Bot, topic: str
) -> None:
    base_bot.alchemy.erc20s[WETH] = ("WETH", 18)
    base_bot.alchemy.receipts[TX_A] = [element_log(topic, 5, 5 * 10**17, coin=WETH)]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["0.5 WETH"]
    assert card.values("Seller") == ["0x0000...00b2"]
    assert card.values("Buyer") == ["0x0000...00a1"]


async def test_a_bulk_transaction_posts_only_the_tracked_tokens_fill(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        element_log(ERC721_BUY, 4, 10**18),
        element_log(ERC721_BUY, 5, 2 * 10**18, coin=WETH),
        element_log(ERC721_BUY, 5, 9 * 10**18, nft="0x" + "cd" * 20),
    ]
    base_bot.alchemy.erc20s[WETH] = ("WETH", 18)

    await read(base_bot, sale_transfer(5))

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["2 WETH"]


async def test_the_same_sale_seen_twice_posts_once(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [element_log(ERC721_SELL, 5, 10**18)]
    await read(base_bot, sale_transfer())

    await base_bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    await base_bot.reader.connect_once()

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1


async def test_post_sales_off_records_the_element_sale_as_skipped(base_bot: Bot) -> None:
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, post_sales=False))
    await base_bot.reloader.reload()
    base_bot.alchemy.receipts[TX_A] = [element_log(ERC721_SELL, 5, 10**18)]

    await read(base_bot, sale_transfer())

    assert base_bot.discord.sent == {}
    assert [s.status for s in base_bot.store.events[EventKind.SALE]] == [PostStatus.SKIPPED]


async def test_a_look_alike_event_from_another_contract_is_ignored(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        element_log(ERC721_SELL, 5, 10**18, address="0x" + "ee" * 20)
    ]

    await read(base_bot, sale_transfer())

    assert base_bot.store.events[EventKind.SALE] == []
    assert base_bot.discord.sent == {}


async def test_test_contract_sales_are_never_decoded() -> None:
    bot = await build_bot("base-sepolia", sepolia_collection())
    await bot.store.set_cursor("base-sepolia", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [element_log(ERC721_SELL, 5, 10**18, nft=TEST_CONTRACT)]

    await read(bot, transfer_log(TEST_CONTRACT, 5, 101, TX_A, 0, MAKER, TAKER))

    assert bot.alchemy.receipt_requests == []
    assert bot.store.events[EventKind.SALE] == []


async def test_a_log_with_no_topics_does_not_hide_the_element_sale(base_bot: Bot) -> None:
    junk = {"address": "0x" + "ab" * 20, "topics": [], "data": "0x", "logIndex": "0x1"}
    base_bot.alchemy.receipts[TX_A] = [junk, element_log(ERC721_SELL, 5, 10**18)]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Marketplace") == ["Element"]
