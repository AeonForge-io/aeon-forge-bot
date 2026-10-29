"""Burns, company-wallet transfers, retries and expiry through the chain reader."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chain.tests.conftest import (
    TEST_CHANNEL,
    TEST_CONTRACT,
    Bot,
    StopTest,
    block_time,
    transfer_log,
)
from app.core.store import EventKind, PostStatus
from app.nft.models import ZERO_ADDRESS
from app.nft.tests.fake_names import FakeNameChain
from app.nft.wallet_names import BASE_REVERSE_SUFFIX, ENS_REVERSE_SUFFIX, WalletNames

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


async def run_loop_once(bot: Bot) -> None:
    """One pass of the 60-second loop: reload settings, then retry pending posts."""

    async def retry_then_stop() -> None:
        await bot.publisher.retry_pending()
        raise StopTest

    with pytest.raises(StopTest):
        await bot.reloader.run(interval=0, after_reload=retry_then_stop)


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
    assert card.values("From") == ["Treasury"]
    assert "#1" in card.text


async def test_empty_wallet_table_posts_no_transfers(bot: Bot) -> None:
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, HOLDER, OTHER))

    assert bot.discord.sent == {}
    assert statuses(bot, EventKind.TRANSFER) == [PostStatus.SKIPPED]


async def test_off_mode_posts_no_transfers_even_from_a_company_wallet(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await set_mode(bot, "off")

    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER))

    assert bot.discord.sent == {}
    assert statuses(bot, EventKind.TRANSFER) == [PostStatus.SKIPPED]


async def test_all_mode_posts_every_transfer_and_marks_company_senders(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await set_mode(bot, "all")

    await read_transfers(
        bot,
        transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER),
        transfer_log(TEST_CONTRACT, 2, 101, TX_B, 1, HOLDER, OTHER),
    )

    company, plain = bot.discord.messages(TEST_CHANNEL)
    assert company.values("From") == ["Treasury"]
    assert plain.values("From") == ["0x0000...00d2"]


async def test_transfer_shows_wallet_names_and_leaves_a_company_sender_unresolved(
    bot: Bot,
) -> None:
    ens = FakeNameChain(ENS_REVERSE_SUFFIX)
    ens.set_name(TREASURY, "treasury.eth")
    ens.set_name(HOLDER, "holder.eth")
    bot.publisher.wallet_names = WalletNames(ens, FakeNameChain(BASE_REVERSE_SUFFIX), bot.store)
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await set_mode(bot, "all")

    await read_transfers(
        bot,
        transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER),
        transfer_log(TEST_CONTRACT, 2, 101, TX_B, 1, HOLDER, OTHER),
    )

    company, plain = bot.discord.messages(TEST_CHANNEL)
    assert company.values("From") == ["Treasury"]
    assert company.values("To") == ["holder.eth"]
    assert plain.values("From") == ["holder.eth"]
    assert plain.values("To") == ["0x0000...00e3"]
    assert TREASURY not in bot.store.wallet_names  # the label won, so it was never looked up


async def test_wallet_added_in_the_store_is_picked_up_on_the_next_reload(bot: Bot) -> None:
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, TREASURY, HOLDER))
    assert bot.discord.sent == {}

    bot.store.add_company_wallet(TREASURY, "Treasury")
    await bot.reloader.reload()
    bot.alchemy.head = 102
    bot.alchemy.logs.append(transfer_log(TEST_CONTRACT, 2, 102, TX_B, 0, TREASURY, HOLDER))
    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("From") == ["Treasury"]


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
    await run_loop_once(bot)

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

    bot.clock.current = event_time + timedelta(hours=6)  # exactly 6 hours is still retried
    await run_loop_once(bot)
    assert statuses(bot, event_kind) == [PostStatus.PENDING]

    bot.discord.missing_channels = frozenset()
    bot.clock.current = event_time + timedelta(hours=6, seconds=1)
    await run_loop_once(bot)

    assert statuses(bot, event_kind) == [PostStatus.EXPIRED]
    assert bot.discord.sent == {}


async def test_pending_mints_and_transfers_are_posted_on_retry(bot: Bot) -> None:
    bot.store.add_company_wallet(TREASURY, "Treasury")
    await bot.reloader.reload()
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    await read_transfers(
        bot,
        transfer_log(TEST_CONTRACT, 1, 101, TX_A, 0, ZERO_ADDRESS, HOLDER),
        transfer_log(TEST_CONTRACT, 2, 101, TX_A, 1, ZERO_ADDRESS, HOLDER),
        transfer_log(TEST_CONTRACT, 3, 101, TX_B, 2, TREASURY, OTHER),
    )
    assert bot.discord.sent == {}

    bot.discord.missing_channels = frozenset()
    bot.clock.current = datetime.fromtimestamp(block_time(101), UTC) + timedelta(seconds=60)
    await run_loop_once(bot)

    mint_card, transfer_card = bot.discord.messages(TEST_CHANNEL)
    assert "#1" in mint_card.text and "#2" in mint_card.text
    assert transfer_card.values("From") == ["Treasury"]
    assert statuses(bot, EventKind.MINT) == [PostStatus.POSTED] * 2
    assert statuses(bot, EventKind.TRANSFER) == [PostStatus.POSTED]


async def test_pending_post_of_a_removed_collection_is_logged(
    bot: Bot, capsys: pytest.CaptureFixture[str]
) -> None:
    bot.discord.missing_channels = frozenset({TEST_CHANNEL})
    await read_transfers(bot, transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS))
    bot.store.collections.clear()
    await bot.reloader.reload()

    await run_loop_once(bot)

    assert "post.retry.collection_missing" in capsys.readouterr().out
    assert statuses(bot, EventKind.BURN) == [PostStatus.PENDING]


async def test_retry_does_not_repost_an_event_whose_live_post_is_still_sending(bot: Bot) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    original = bot.discord.client.get_channel.side_effect

    def holding_channel(channel_id: int) -> MagicMock | None:
        channel = original(channel_id)
        send = channel.send

        async def held_send(**kwargs: Any) -> None:
            started.set()
            await release.wait()
            await send(**kwargs)

        channel.send = AsyncMock(side_effect=held_send)
        return channel  # type: ignore[no-any-return]

    bot.discord.client.get_channel.side_effect = holding_channel

    live = asyncio.create_task(
        read_transfers(bot, transfer_log(TEST_CONTRACT, 9, 101, TX_A, 0, HOLDER, ZERO_ADDRESS))
    )
    await started.wait()
    assert statuses(bot, EventKind.BURN) == [PostStatus.PENDING]

    bot.clock.current = datetime.fromtimestamp(block_time(101), UTC) + timedelta(seconds=60)
    await bot.publisher.retry_pending()
    assert bot.discord.messages(TEST_CHANNEL) == []

    release.set()
    await live
    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
    assert statuses(bot, EventKind.BURN) == [PostStatus.POSTED]

    await bot.publisher.retry_pending()
    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
