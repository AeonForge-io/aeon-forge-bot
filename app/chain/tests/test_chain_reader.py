"""Mints through the chain reader: Alchemy in, Discord messages and event status out."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from app.chain.reader import MAX_SUPPLY_SELECTOR, POLL_INTERVAL_SECONDS
from app.chain.rpc import ChainConnectionError, RpcResponseError, SubscriptionError
from app.chain.tests.conftest import (
    MAIN_CHANNEL,
    SECOND_CONTRACT,
    TEST_CHANNEL,
    TEST_CONTRACT,
    Bot,
    StopTest,
    block_time,
    build_bot,
    mint_log,
    sepolia_collection,
    transfer_log,
)
from app.core.store import PostStatus
from app.discord.tests.card_view import Card

TX_A = "0x" + "a1" * 32
TX_B = "0x" + "b2" * 32
HOLDER = "0x00000000000000000000000000000000000000d2"
OTHER = "0x00000000000000000000000000000000000000e3"


async def start_at(bot: Bot, block: int) -> None:
    """Put the cursor at a block, as if the bot had been running up to it."""
    await bot.store.set_cursor(
        "base-sepolia", block, datetime.fromtimestamp(block_time(block), UTC)
    )


def progress(card: Card) -> list[str]:
    """'N / M' of each token in the message."""
    return [value.split(" ", 1)[1] for value in card.values("Progress")]


async def test_test_contract_mint_posts_in_test_channel_with_progress(bot: Bot) -> None:
    bot.store.add_collection(
        sepolia_collection(
            collection_id="main",
            name="Main",
            contract_address=SECOND_CONTRACT,
            discord_channel_id=MAIN_CHANNEL,
        )
    )
    await bot.reloader.reload()
    bot.reader.replace_contracts(bot.reloader.current.tracked_contracts["base-sepolia"])
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.initial_supply = 211
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert progress(card) == ["212 / 750"]
    assert "#7" in card.text
    assert card.images == [
        "https://images.test/ipfs/cid/7.jpg"
    ]  # the collection's image_url_template
    assert bot.discord.messages(MAIN_CHANNEL) == []
    assert bot.mint_statuses() == [PostStatus.POSTED]


async def test_mint_post_links_to_the_collections_mint_url_when_it_has_one(bot: Bot) -> None:
    [collection] = bot.store.collections
    bot.store.update_collection(replace(collection, mint_url="https://aeonforge.io/mint"))
    await bot.reloader.reload()
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert [label for label, _ in card.buttons] == ["Transaction", "Mint yours"]
    assert card.buttons[1][1] == "https://aeonforge.io/mint"


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
    assert (len(first.images), len(second.images)) == (10, 2)
    assert progress(first) + progress(second) == [f"{n} / 750" for n in range(1, 13)]


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
    assert progress(first) == ["41 / 750", "42 / 750"]
    assert progress(second) == ["43 / 750"]


async def test_paid_mint_shows_price_per_token(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, i, 101, TX_A, i) for i in range(3)]
    bot.alchemy.tx_values_wei = {TX_A: 150_000_000_000_000_000}

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("Price") == ["0.05 ETH"] * 3


async def test_free_mint_shows_no_price(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("Price") == []


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

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert "#2" in card.text
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

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert "#2" in card.text
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

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert "#2" in card.text
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


async def test_connection_failure_while_polling_reconnects_with_backoff(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.subscription_error = SubscriptionError("no logs subscription")
    bot.alchemy.head = 101
    original_sleep = bot.reader.sleep

    async def sleep_and_break_the_next_poll(seconds: float) -> None:
        if not bot.sleeps:
            bot.alchemy.failing_requests = 1
        await original_sleep(seconds)

    bot.reader.sleep = sleep_and_break_the_next_poll

    with pytest.raises(StopTest):
        await bot.reader.run()

    assert bot.sleeps == [POLL_INTERVAL_SECONDS, 2.0, POLL_INTERVAL_SECONDS]


async def test_no_tracked_contract_opens_no_subscription(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.reader.replace_contracts(frozenset())  # the last collection on the chain was switched off

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(bot.reader.connect_once(), timeout=0.05)

    assert bot.alchemy.subscription_filters == []


async def test_collection_without_image_template_posts_without_image(bot: Bot) -> None:
    [collection] = bot.store.collections
    bot.store.update_collection(replace(collection, image_url_template=None))
    await bot.reloader.reload()
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.images == []
    assert bot.mint_statuses() == [PostStatus.POSTED]


def reject_calls(bot: Bot, selector: str) -> None:
    """Make the node answer a JSON-RPC error to an eth_call with this selector."""
    original = bot.alchemy.request

    async def request(method: str, params: list[Any]) -> Any:
        if method == "eth_call" and params[0]["data"] == selector:
            raise RpcResponseError("eth_call returned an error: execution reverted")
        return await original(method, params)

    bot.alchemy.request = request  # type: ignore[method-assign]


async def test_max_supply_error_posts_the_mint_without_progress_and_logs(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]
    reject_calls(bot, MAX_SUPPLY_SELECTOR)

    with capture_logs() as logs:
        await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert "#7" in card.text
    assert card.values("Progress") == []
    assert bot.mint_statuses() == [PostStatus.POSTED]
    assert (await bot.store.get_cursor("base-sepolia")).last_block == 101
    [entry] = [e for e in logs if e["event"] == "chain.mint.supply_unreadable"]
    assert entry["log_level"] == "error"
    assert entry["contract"] == TEST_CONTRACT
    assert entry["block"] == 101


async def test_zero_max_supply_posts_the_mint_without_progress(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.max_supply = 0
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]

    await bot.reader.connect_once()

    [card] = bot.discord.messages(TEST_CHANNEL)
    assert card.values("Progress") == []
    assert bot.mint_statuses() == [PostStatus.POSTED]


async def test_transport_failure_reading_supply_still_retries_the_block(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)]
    original = bot.alchemy.request

    async def request(method: str, params: list[Any]) -> Any:
        if method == "eth_call":
            raise ChainConnectionError("down")
        return await original(method, params)

    bot.alchemy.request = request  # type: ignore[method-assign]

    with pytest.raises(ChainConnectionError):
        await bot.reader.connect_once()

    assert bot.discord.messages(TEST_CHANNEL) == []
    assert (await bot.store.get_cursor("base-sepolia")).last_block == 100


@pytest.mark.parametrize(
    "null_method", ["eth_getTransactionByHash", "eth_getBlockByNumber", "eth_getTransactionReceipt"]
)
async def test_null_result_is_a_transient_failure_that_leaves_the_cursor(
    bot: Bot, null_method: str
) -> None:
    chain = "base-sepolia"
    if null_method == "eth_getTransactionReceipt":
        # Receipts are only read to detect sales, which the sepolia test contract never has
        chain = "base"
        bot = await build_bot(
            chain,
            sepolia_collection(
                chain=chain,
                contract_address=SECOND_CONTRACT,
                track_marketplace=True,
                marketplaces=("forum_one",),
            ),
        )
        log = transfer_log(SECOND_CONTRACT, 7, 101, TX_A, 0, sender=HOLDER, recipient=OTHER)
    else:
        log = mint_log(TEST_CONTRACT, 7, 101, TX_A, 0)
    await bot.store.set_cursor(chain, 100, datetime.fromtimestamp(block_time(100), UTC))
    bot.alchemy.head = 101
    bot.alchemy.logs = [log]
    bot.alchemy.tx_values_wei = {TX_A: 1}
    original = bot.alchemy.request

    async def request(method: str, params: list[Any]) -> Any:
        if method == null_method and params[0] != "latest":
            return None
        return await original(method, params)

    bot.alchemy.request = request  # type: ignore[method-assign]

    with pytest.raises(ChainConnectionError) as raised:
        await bot.reader.connect_once()

    assert not isinstance(raised.value, RpcResponseError)
    assert null_method in str(raised.value)
    assert (await bot.store.get_cursor(chain)).last_block == 100


def tracked_mint_notification(block: int, tx: str = TX_A) -> dict[str, object]:
    return mint_log(TEST_CONTRACT, 1, block, tx, 0)


async def test_contract_change_failing_during_adoption_backs_off_instead_of_spinning(
    bot: Bot,
) -> None:
    bot.reader.replace_contracts(frozenset({TEST_CONTRACT, SECOND_CONTRACT}))
    bot.alchemy.failing_requests = 100

    with pytest.raises(StopTest):
        await asyncio.wait_for(bot.reader.run(), timeout=2)

    assert bot.sleeps == [2.0, 4.0, 8.0]


async def test_backoff_resets_after_a_healthy_connection(bot: Bot) -> None:
    bot.alchemy.failing_requests = 1
    bot.alchemy.subscription_failure = ChainConnectionError("dropped")

    with pytest.raises(StopTest):
        await bot.reader.run()

    assert bot.sleeps == [2.0, 2.0, 2.0]


async def test_refused_subscription_on_a_chain_without_polling_backs_off_and_retries() -> None:
    bot = await build_bot("base", sepolia_collection(chain="base"))
    bot.alchemy.subscription_error = SubscriptionError("no logs subscription")

    with pytest.raises(StopTest):
        await bot.reader.run()

    assert bot.sleeps == [2.0, 4.0, 8.0]
    assert len(bot.alchemy.subscription_filters) == 3


async def test_log_between_the_catch_up_head_and_the_subscription_is_read(bot: Bot) -> None:
    await start_at(bot, 100)

    def block_arrives_while_subscribing() -> None:
        bot.alchemy.head = 101
        bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]

    bot.alchemy.on_subscribe = block_arrives_while_subscribing
    bot.alchemy.hold_subscription_open = True

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(bot.reader.connect_once(), timeout=0.2)

    assert len(bot.discord.messages(TEST_CHANNEL)) == 1


async def test_lagging_node_is_retried_until_it_serves_the_announced_log(bot: Bot) -> None:
    await start_at(bot, 100)
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]
    bot.alchemy.notifications = [tracked_mint_notification(101)]
    bot.alchemy.hidden_log_reads = 2
    lag_sleeps: list[float] = []

    async def record_lag_sleep(seconds: float) -> None:
        lag_sleeps.append(seconds)

    bot.reader.sleep = record_lag_sleep

    await bot.reader.connect_once()

    assert lag_sleeps == [2.0, 2.0]
    assert len(bot.discord.messages(TEST_CHANNEL)) == 1


async def test_lagging_node_that_never_serves_the_log_leaves_the_cursor_for_a_retry(
    bot: Bot,
) -> None:
    await start_at(bot, 100)
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]
    bot.alchemy.notifications = [tracked_mint_notification(101)]
    bot.alchemy.hidden_log_reads = 100

    async def no_sleep(seconds: float) -> None:
        return None

    bot.reader.sleep = no_sleep

    with pytest.raises(ChainConnectionError):
        await bot.reader.connect_once()

    cursor = await bot.store.get_cursor("base-sepolia")
    assert cursor is not None
    assert cursor.last_block == 100
    assert bot.discord.messages(TEST_CHANNEL) == []


async def test_log_at_a_block_the_cursor_already_passed_is_read_again(bot: Bot) -> None:
    await start_at(bot, 101)
    bot.alchemy.head = 101
    bot.alchemy.logs = [mint_log(TEST_CONTRACT, 1, 101, TX_A, 0)]  # replaced the block's logs
    bot.alchemy.notifications = [tracked_mint_notification(101)]

    await bot.reader.connect_once()

    assert len(bot.discord.messages(TEST_CHANNEL)) == 1
    cursor = await bot.store.get_cursor("base-sepolia")
    assert cursor is not None
    assert cursor.last_block == 101
