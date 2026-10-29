"""Wallet names: ENS first, Basename second, cached, and never trusting a claimed name."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.chain.rpc import ChainConnectionError, RpcResponseError
from app.core.memory_store import MemoryStore
from app.core.store import WalletNameRecord
from app.nft.tests.fake_names import FakeNameChain
from app.nft.wallet_names import (
    BASE_REVERSE_SUFFIX,
    ENS_REVERSE_SUFFIX,
    WalletNames,
    is_safe_name,
)

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
MALLORY = "0x" + "c3" * 20
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class Setup:
    def __init__(self) -> None:
        self.ens = FakeNameChain(ENS_REVERSE_SUFFIX)
        self.base = FakeNameChain(BASE_REVERSE_SUFFIX)
        self.store = MemoryStore()
        self.now = NOW
        self.names = WalletNames(self.ens, self.base, self.store, lambda: self.now)

    @property
    def rpc_calls(self) -> int:
        return len(self.ens.calls) + len(self.base.calls)

    def fresh_instance(self) -> WalletNames:
        """A restarted process: empty in-process cache, same database."""
        return WalletNames(self.ens, self.base, self.store, lambda: self.now)


async def test_ens_name_is_used_and_basename_is_not_asked() -> None:
    s = Setup()
    s.ens.set_name(ALICE, "alice.eth")
    s.base.set_name(ALICE, "alice.base.eth")

    assert await s.names.names([ALICE]) == {ALICE: "alice.eth"}
    assert s.base.calls == []
    assert len(s.ens.calls) == 4  # reverse resolver, name, forward resolver, addr


async def test_basename_is_used_when_there_is_no_ens_name() -> None:
    s = Setup()
    s.base.set_name(BOB, "bob.base.eth")

    assert await s.names.names([BOB]) == {BOB: "bob.base.eth"}
    assert len(s.ens.calls) == 1  # no reverse resolver set
    assert len(s.base.calls) == 4


async def test_ens_name_whose_forward_address_differs_falls_to_basename() -> None:
    s = Setup()
    s.ens.set_name(MALLORY, "vitalik.eth", forward=ALICE)
    s.base.set_name(MALLORY, "mallory.base.eth")

    assert await s.names.names([MALLORY]) == {MALLORY: "mallory.base.eth"}


async def test_claimed_name_that_does_not_forward_back_is_no_name() -> None:
    s = Setup()
    s.base.set_name(MALLORY, "vitalik.base.eth", forward=ALICE)

    assert await s.names.names([MALLORY]) == {}


async def test_wallet_with_no_name_gets_no_entry_and_costs_two_calls() -> None:
    s = Setup()

    assert await s.names.names([ALICE]) == {}
    assert s.rpc_calls == 2


async def test_basename_must_end_in_base_eth() -> None:
    s = Setup()
    s.base.set_name(ALICE, "alice.eth")

    assert await s.names.names([ALICE]) == {}


async def test_unsafe_names_are_rejected() -> None:
    s = Setup()
    s.ens.set_name(ALICE, "**bold**.eth")
    s.ens.set_name(BOB, "A" * 10 + ".eth")
    s.base.set_name(MALLORY, "x" * 40 + ".base.eth")  # over 40 characters

    assert await s.names.names([ALICE, BOB, MALLORY]) == {}
    assert is_safe_name("alice.eth")
    assert is_safe_name("a-b.base.eth")
    assert not is_safe_name("alice.eth/[x](http://evil)")
    assert not is_safe_name("al\u0131ce.eth")
    assert not is_safe_name("alice.com")
    assert not is_safe_name(".eth")


async def test_second_lookup_of_the_same_address_makes_no_calls() -> None:
    s = Setup()
    s.ens.set_name(ALICE, "alice.eth")

    await s.names.names([ALICE, BOB])
    calls = s.rpc_calls
    again = await s.names.names([ALICE, BOB])

    assert again == {ALICE: "alice.eth"}
    assert s.rpc_calls == calls  # the name and the lack of one are both remembered


async def test_database_row_younger_than_seven_days_makes_no_calls() -> None:
    s = Setup()
    s.store.wallet_names[ALICE] = WalletNameRecord(
        ALICE, "alice.eth", None, NOW - timedelta(days=6)
    )
    s.store.wallet_names[BOB] = WalletNameRecord(BOB, None, None, NOW - timedelta(days=6))

    assert await s.names.names([ALICE, BOB]) == {ALICE: "alice.eth"}
    assert s.rpc_calls == 0


async def test_database_row_older_than_seven_days_is_checked_again() -> None:
    s = Setup()
    s.store.wallet_names[ALICE] = WalletNameRecord(ALICE, "old.eth", None, NOW - timedelta(days=8))
    s.ens.set_name(ALICE, "new.eth")

    assert await s.names.names([ALICE]) == {ALICE: "new.eth"}
    assert s.store.wallet_names[ALICE].ens_name == "new.eth"
    assert s.store.wallet_names[ALICE].checked_at == NOW


async def test_process_cache_also_expires_after_seven_days() -> None:
    s = Setup()
    await s.names.names([ALICE])
    s.now += timedelta(days=8)
    s.ens.set_name(ALICE, "alice.eth")

    assert await s.names.names([ALICE]) == {ALICE: "alice.eth"}


async def test_result_is_stored_so_a_restart_makes_no_calls() -> None:
    s = Setup()
    s.base.set_name(BOB, "bob.base.eth")
    await s.names.names([BOB, ALICE])
    calls = s.rpc_calls

    assert await s.fresh_instance().names([BOB, ALICE]) == {BOB: "bob.base.eth"}
    assert s.rpc_calls == calls
    assert s.store.wallet_names[ALICE] == WalletNameRecord(ALICE, None, None, NOW)


async def test_failed_lookup_shows_no_name_and_is_not_cached() -> None:
    s = Setup()
    s.ens.set_name(ALICE, "alice.eth")
    s.ens.error = ChainConnectionError("down")

    assert await s.names.names([ALICE]) == {}
    assert s.store.wallet_names == {}

    s.ens.error = RpcResponseError("rate limited")
    assert await s.names.names([ALICE]) == {}
    assert s.store.wallet_names == {}

    s.ens.error = None
    assert await s.names.names([ALICE]) == {ALICE: "alice.eth"}


async def test_failure_on_the_basename_step_is_not_cached_either() -> None:
    s = Setup()
    s.base.error = ChainConnectionError("down")

    assert await s.names.names([ALICE]) == {}
    assert s.store.wallet_names == {}


async def test_execution_revert_means_no_name_and_is_cached() -> None:
    s = Setup()
    s.ens.error = RpcResponseError("eth_call returned an error: {'message': 'execution reverted'}")

    assert await s.names.names([ALICE]) == {}
    assert ALICE in s.store.wallet_names


async def test_one_failing_address_does_not_hide_the_others() -> None:
    s = Setup()
    s.ens.set_name(ALICE, "alice.eth")
    original = s.ens.request

    async def flaky(method: str, params: list[object]) -> object:
        if BOB[2:] in str(params) or s.ens.error:
            raise ChainConnectionError("down")
        return await original(method, params)

    s.ens.request = flaky  # type: ignore[method-assign]
    assert await s.names.names([ALICE, BOB]) == {ALICE: "alice.eth"}


async def test_slow_lookup_is_cut_off_and_not_cached(monkeypatch: object) -> None:
    s = Setup()

    async def never(method: str, params: list[object]) -> object:
        await asyncio.sleep(3600)
        return None

    s.ens.request = never  # type: ignore[method-assign]
    monkeypatch.setattr("app.nft.wallet_names.LOOKUP_TIMEOUT", 0.05)  # type: ignore[attr-defined]

    assert await s.names.names([ALICE]) == {}
    assert s.store.wallet_names == {}


async def test_zero_address_is_never_looked_up() -> None:
    s = Setup()

    assert await s.names.names(["0x" + "0" * 40]) == {}
    assert s.rpc_calls == 0
