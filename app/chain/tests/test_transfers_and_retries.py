"""Burns, company-wallet transfers, retries and expiry through the chain reader."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.chain.tests.conftest import (
    TEST_CHANNEL,
    TEST_CONTRACT,
    Bot,
    block_time,
    transfer_log,
)
from app.core.store import EventKind, PostStatus
from app.nft.models import ZERO_ADDRESS

TX_A = "0x" + "a1" * 32
TX_B = "0x" + "b2" * 32
TREASURY = "0x00000000000000000000000000000000000000c1"
HOLDER = "0x00000000000000000000000000000000000000d2"
OTHER = "0x00000000000000000000000000000000000000e3"


async def start_at(bot: Bot, block: int) -> None:
    await bot.store.set_cursor(
        "base-sepolia", block, datetime.fromtimestamp(block_time(block), UTC)
    )


async def set_mode(bot: Bot, mode: str) -> None:
    [collection] = bot.store.collections
    bot.store.update_collection(replace(collection, transfer_mode=mode))  # type: ignore[arg-type]
    await bot.reloader.reload()


def statuses(bot: Bot, kind: EventKind) -> list[PostStatus]:
    return [stored.status for stored in bot.store.events[kind]]


async def read_transfers(bot: Bot, *logs: dict) -> None:  # type: ignore[type-arg]
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = list(logs)
    await bot.reader.connect_once()


async def test_company_mode_posts_only_company_senders_with_their_label(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await bot.reloader.reload()

    await read_transfers(
        bot,
        transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER),
        transfer_log(TEST_CONTRACT, 2, 101, TX_B, 1, HOLDER, OTHER),
    )

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("From") == ["Aeon Forge (Treasury)"]
    assert "#1" in card.text


async def test_empty_wallet_table_posts_no_transfers(bot: Bot) -> None:
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, HOLDER, OTHER))

    assert bot.discord.sent == {}


async def test_off_mode_posts_no_transfers_even_from_a_company_wallet(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await set_mode(bot, "off")

    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER))

    assert bot.discord.sent == {}


async def test_all_mode_posts_every_transfer_and_marks_company_senders(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await set_mode(bot, "all")

    await read_transfers(
        bot,
        transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER),
        transfer_log(TEST_CONTRACT, 2, 101, TX_B, 1, HOLDER, OTHER),
    )

    company, plain = bot.discord.messages(TEST_CHANNEL)
    assert company.values("From") == ["Aeon Forge (Treasury)"]
    assert plain.values("From") == ["0x0000...00d2"]


async def test_wallet_added_in_the_store_is_picked_up_on_the_next_reload(bot: Bot) -> None:
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER))
    assert bot.discord.sent == {}

    bot.store.add_company_wallet(TREASURY, "Treasury")
    await bot.reloader.reload()
    bot.alchemy.head = 102
    bot.alchemy.logs.append(transfer_log(TEST_CONTRACT, 2, 102, TX_B, 0, TREASURY, HOLDER))
    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("From") == ["Aeon Forge (Treasury)"]


async def test_burn_posts(bot: Bot) -> None:
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS))

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert "#9" in card.text
    assert card.values("Burned by") == ["0x0000...00d2"]
    assert statuses(bot, EventKind.BURN) == [PostStatus.POSTED]


async def test_post_burns_off_records_skipped(bot: Bot) -> None:
    [collection] = bot.store.collections
    bot.store.update_collection(replace(collection, post_burns=False))
    await bot.reloader.reload()

    await read_transfers(bot, transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS))

    assert bot.discord.sent == {}
    assert statuses(bot, EventKind.BURN) == [PostStatus.SKIPPED]


async def test_failed_post_is_retried_on_the_next_loop(bot: Bot) -> None:
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS))
    assert statuses(bot, EventKind.BURN) == [PostStatus.PENDING]

    bot.discord.missing_channels = frozenset()
    bot.clock.current = datetime.fromtimestamp(block_time(101), UTC) + timedelta(seconds=60)
    await bot.publisher.retry_pending()

    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
    assert statuses(bot, EventKind.BURN) == [PostStatus.POSTED]


@pytest.mark.parametrize("kind", ["mint", "burn", "transfer"])
async def test_pending_post_expires_after_six_hours(bot: Bot, kind: str) -> None:
    bot.store.add_company_wallet(HOLDER, "Holder")
    await bot.reloader.reload()
    logs = {
        "mint": transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, ZERO_ADDRESS, HOLDER),
        "burn": transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS),
        "transfer": transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, OTHER),
    }
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    await read_transfers(bot, logs[kind])
    event_time = datetime.fromtimestamp(block_time(101), UTC)
    event_kind = {"mint": EventKind.MINT, "burn": EventKind.BURN, "transfer": EventKind.TRANSFER}[
        kind
    ]

    bot.discord.missing_channels = frozenset()
    bot.clock.current = event_time + timedelta(hours=6)  # exactly 6 hours is still retried
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    await bot.publisher.retry_pending()
    assert statuses(bot, event_kind) == [PostStatus.PENDING]

    bot.discord.missing_channels = frozenset()
    bot.clock.current = event_time + timedelta(hours=6, seconds=1)
    await bot.publisher.retry_pending()

    assert statuses(bot, event_kind) == [PostStatus.EXPIRED]
    assert bot.discord.sent == {}
