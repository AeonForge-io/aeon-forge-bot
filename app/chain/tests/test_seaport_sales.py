"""Seaport sales read from OrderFulfilled in the receipt of a tracked Transfer."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.chain.seaport import ORDER_FULFILLED_TOPIC, SEAPORT_1_5, SEAPORT_1_6
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
    ETH_CURRENCY,
    SELLER,
    TX_A,
    USDC,
    address_word,
    dragonz_collection,
    read,
    sale_transfer,
    word,
)
from app.core.store import EventKind, PostStatus

OPENSEA_FEE_WALLET = "0x0000a26b00c1f0df003000390027140000faa719"
OPENSEA_ZONE = "0x000056f7000000ece9003ca63978907a00ffd100"
OKX_ZONE = "0xdf2d4bffec010debd302674c9fb9cda99bb5e852"
UNKNOWN_ZONE = "0x" + "77" * 20
ROYALTY_WALLET = "0x00000000000000000000000000000000000000c3"
NO_ZONE = "0x" + "00" * 20
OPENSEA_TAG = "360c6ebe"
BLUR_TAG = "332d1229"
GEM_TAG = "72db8c0b"
# The rows of migrations/003 and 007 these tests rely on
SEEDED_MARKS = [
    ("calldata_tag", "0x" + OPENSEA_TAG, "OpenSea"),
    ("fee_wallet", OPENSEA_FEE_WALLET, "OpenSea"),
    ("zone", OPENSEA_ZONE, "OpenSea"),
    ("zone", OKX_ZONE, "OKX"),
]
INPUT_BODY = "aa" * 40


def nft_item(token_id: int, recipient: str | None = None) -> list[str]:
    item = [word(2), address_word(DRAGONZ), word(token_id), word(1)]
    return item + ([address_word(recipient)] if recipient else [])


def coin_item(amount: int, coin: str = ETH_CURRENCY, recipient: str | None = None) -> list[str]:
    item_type = 0 if coin == ETH_CURRENCY else 1
    item = [word(item_type), address_word(coin), word(0), word(amount)]
    return item + ([address_word(recipient)] if recipient else [])


def order_fulfilled(
    offer: list[list[str]],
    consideration: list[list[str]],
    offerer: str,
    recipient: str,
    zone: str = NO_ZONE,
    address: str = SEAPORT_1_6,
) -> dict[str, Any]:
    """OrderFulfilled as a receipt holds it: head words, then the offer and consideration arrays."""
    offer_words = [word(len(offer))] + [w for item in offer for w in item]
    consideration_words = [word(len(consideration))] + [w for item in consideration for w in item]
    head = [word(9), address_word(recipient), word(4 * 32), word((4 + len(offer_words)) * 32)]
    return {
        "address": address,
        "topics": [
            ORDER_FULFILLED_TOPIC,
            "0x" + address_word(offerer),
            "0x" + address_word(zone),
        ],
        "data": "0x" + "".join(head + offer_words + consideration_words),
        "logIndex": "0x9",
    }


def listing_fill(
    token_id: int = 5, zone: str = NO_ZONE, fee_wallet: str = ROYALTY_WALLET, **kwargs: Any
) -> dict[str, Any]:
    """A listing fill: the seller offers the NFT, the buyer pays 0.1 ETH split three ways."""
    return order_fulfilled(
        offer=[nft_item(token_id)],
        consideration=[
            coin_item(94 * 10**15 - 1, recipient=SELLER),
            coin_item(5 * 10**15, recipient=ROYALTY_WALLET),
            coin_item(10**15 + 1, recipient=fee_wallet),
        ],
        offerer=SELLER,
        recipient=BUYER,
        zone=zone,
        **kwargs,
    )


def tagged_input(*tags: str) -> str:
    return "0x" + INPUT_BODY + "".join(tags)


@pytest.fixture
async def base_bot() -> Bot:
    bot = await build_bot("base", dragonz_collection())
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    for kind, value, name in SEEDED_MARKS:
        bot.store.add_marketplace_mark(kind, value, name)  # type: ignore[arg-type]  # kind literals
    await bot.reloader.reload()
    return bot


async def marketplace_of_the_one_sale(bot: Bot) -> str:
    [card] = bot.discord.messages(MAIN_CHANNEL)
    [name] = card.values("Marketplace")
    return name


async def test_a_fill_tagged_for_opensea_is_named_opensea(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill()]
    base_bot.alchemy.tx_inputs[TX_A] = tagged_input(OPENSEA_TAG)

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "OpenSea"
    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["0.1 ETH"]


async def test_an_untagged_fill_paying_a_seeded_fee_wallet_is_named_by_it(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(fee_wallet=OPENSEA_FEE_WALLET)]
    base_bot.alchemy.tx_inputs[TX_A] = "0x" + INPUT_BODY

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "OpenSea"


async def test_a_fill_through_an_account_abstraction_entry_point_is_named_by_its_zone(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=OKX_ZONE)]
    base_bot.alchemy.tx_inputs[TX_A] = "0x" + INPUT_BODY

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "OKX"


async def test_an_aggregator_double_tag_names_the_last_tag(base_bot: Bot) -> None:
    base_bot.store.add_marketplace_mark("calldata_tag", "0x" + BLUR_TAG, "Blur")
    base_bot.store.add_marketplace_mark("calldata_tag", "0x" + GEM_TAG, "Gem")
    await base_bot.reloader.reload()
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=OPENSEA_ZONE)]
    # the aggregator's own tag comes first, the site's tag is appended last
    base_bot.alchemy.tx_inputs[TX_A] = tagged_input(BLUR_TAG, OPENSEA_TAG)

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "OpenSea"


async def test_the_tag_before_the_last_one_is_used_when_the_last_is_unknown(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=UNKNOWN_ZONE)]
    base_bot.alchemy.tx_inputs[TX_A] = tagged_input(OPENSEA_TAG, "deadbeef")

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "OpenSea"


async def test_a_tag_hit_comes_before_a_zone_hit(base_bot: Bot) -> None:
    base_bot.store.add_marketplace_mark("calldata_tag", "0x" + GEM_TAG, "Gem")
    await base_bot.reloader.reload()
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=OPENSEA_ZONE)]
    base_bot.alchemy.tx_inputs[TX_A] = tagged_input(GEM_TAG)

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "Gem"


async def test_an_unmarked_fill_is_other_marketplace_with_the_transaction_link(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=UNKNOWN_ZONE)]
    base_bot.alchemy.tx_inputs[TX_A] = tagged_input("deadbeef")

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "Other marketplace (Seaport)"
    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.buttons[0] == ("Transaction", f"https://basescan.org/tx/{TX_A}")


async def test_seaport_1_5_fills_are_decoded_too(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(address=SEAPORT_1_5)]

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "Other marketplace (Seaport)"


async def test_the_price_sums_the_payment_items_of_one_erc20(base_bot: Bot) -> None:
    base_bot.alchemy.erc20s[USDC] = ("USDC", 6)
    base_bot.alchemy.receipts[TX_A] = [
        order_fulfilled(
            offer=[nft_item(5)],
            consideration=[
                coin_item(9_400_000, USDC, SELLER),
                coin_item(500_000, USDC, ROYALTY_WALLET),
                coin_item(100_000, USDC, OPENSEA_FEE_WALLET),
            ],
            offerer=SELLER,
            recipient=BUYER,
        )
    ]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["10 USDC"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]


async def test_an_offer_fill_swaps_seller_and_buyer_and_prices_the_offered_coin(
    base_bot: Bot,
) -> None:
    base_bot.alchemy.erc20s[USDC] = ("USDC", 6)
    # the buyer offered 10 USDC; the seller accepted and receives the offer's items
    base_bot.alchemy.receipts[TX_A] = [
        order_fulfilled(
            offer=[coin_item(10_000_000, USDC)],
            consideration=[
                nft_item(5, BUYER),
                coin_item(100_000, USDC, OPENSEA_FEE_WALLET),
            ],
            offerer=BUYER,
            recipient=SELLER,
        )
    ]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["10 USDC"]
    assert card.values("Seller") == ["0x0000...00a1"]
    assert card.values("Buyer") == ["0x0000...00b2"]
    assert card.values("Marketplace") == ["OpenSea"]


async def test_a_fill_for_another_token_is_not_this_transfers_sale(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(token_id=99)]

    await read(base_bot, sale_transfer(5))

    assert base_bot.discord.sent == {}
    assert base_bot.store.events[EventKind.SALE] == []


async def test_a_look_alike_event_from_another_contract_is_ignored(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(address="0x" + "ee" * 20)]

    await read(base_bot, sale_transfer())

    assert base_bot.store.events[EventKind.SALE] == []


async def test_a_mark_added_in_the_store_is_used_after_the_next_reload(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill(zone=UNKNOWN_ZONE)]
    base_bot.store.add_marketplace_mark("zone", UNKNOWN_ZONE, "NewMarket")
    await base_bot.reloader.reload()

    await read(base_bot, sale_transfer())

    assert await marketplace_of_the_one_sale(base_bot) == "NewMarket"


async def test_a_sale_seen_twice_posts_once(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill()]
    await read(base_bot, sale_transfer())

    await base_bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    await base_bot.reader.connect_once()

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1


async def test_a_seaport_sale_transfer_posts_only_as_the_sale(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [listing_fill()]
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, transfer_mode="all"))
    await base_bot.reloader.reload()

    await read(base_bot, sale_transfer())

    assert len(base_bot.discord.messages(MAIN_CHANNEL)) == 1
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.SKIPPED]


async def test_an_order_paying_in_two_coins_is_skipped_not_fatal(base_bot: Bot) -> None:
    base_bot.alchemy.receipts[TX_A] = [
        order_fulfilled(
            offer=[nft_item(5)],
            consideration=[
                coin_item(10**17, recipient=SELLER),
                coin_item(10, USDC, recipient=SELLER),
            ],
            offerer=SELLER,
            recipient=BUYER,
        )
    ]

    await read(base_bot, sale_transfer())

    assert base_bot.discord.messages(MAIN_CHANNEL) == []
    assert len(base_bot.store.events[EventKind.TRANSFER]) == 1


async def test_a_sale_is_not_decoded_when_marketplace_tracking_is_off() -> None:
    bot = await build_bot("base", replace(dragonz_collection(), track_marketplace=False))
    await bot.store.set_cursor("base", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [listing_fill()]

    await read(bot, sale_transfer())

    assert bot.alchemy.receipt_requests == []


async def test_a_bundle_order_splits_its_payment_across_its_nft_items(base_bot: Bot) -> None:
    bundle = order_fulfilled(
        offer=[nft_item(5), nft_item(6)],
        consideration=[coin_item(3 * 10**18, recipient=SELLER)],
        offerer=SELLER,
        recipient=BUYER,
    )
    base_bot.alchemy.receipts[TX_A] = [bundle]

    await read(base_bot, sale_transfer(5, log_index=0), sale_transfer(6, log_index=1))

    cards = base_bot.discord.messages(MAIN_CHANNEL)
    assert [c.values("Price") for c in cards] == [["1.5 ETH"], ["1.5 ETH"]]


async def test_a_bundle_with_an_untracked_item_still_splits_by_all_nft_items(
    base_bot: Bot,
) -> None:
    other_nft = [word(2), address_word("0x" + "99" * 20), word(1), word(1)]
    bundle = order_fulfilled(
        offer=[nft_item(5), other_nft],
        consideration=[coin_item(3 * 10**18, recipient=SELLER)],
        offerer=SELLER,
        recipient=BUYER,
    )
    base_bot.alchemy.receipts[TX_A] = [bundle]

    await read(base_bot, sale_transfer())

    [card] = base_bot.discord.messages(MAIN_CHANNEL)
    assert card.values("Price") == ["1.5 ETH"]


async def test_an_nft_swap_with_a_fee_item_is_not_a_sale(base_bot: Bot) -> None:
    [collection] = base_bot.store.collections
    base_bot.store.update_collection(replace(collection, transfer_mode="all"))
    await base_bot.reloader.reload()
    swap = order_fulfilled(
        offer=[nft_item(5)],
        consideration=[nft_item(9, recipient=SELLER), coin_item(10**15, USDC, ROYALTY_WALLET)],
        offerer=SELLER,
        recipient=BUYER,
    )
    base_bot.alchemy.receipts[TX_A] = [swap]

    await read(base_bot, sale_transfer())

    assert base_bot.store.events[EventKind.SALE] == []
    assert [s.status for s in base_bot.store.events[EventKind.TRANSFER]] == [PostStatus.POSTED]


async def test_seaport_orders_are_not_decoded_off_base() -> None:
    bot = await build_bot("base-sepolia", replace(sepolia_collection(), track_marketplace=True))
    await bot.store.set_cursor("base-sepolia", 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.receipts[TX_A] = [listing_fill()]

    await read(bot, transfer_log(TEST_CONTRACT, 5, 101, TX_A, 0, SELLER, BUYER))

    assert bot.alchemy.receipt_requests == []
    assert bot.store.events[EventKind.SALE] == []
