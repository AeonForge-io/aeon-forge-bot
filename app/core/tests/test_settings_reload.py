"""Settings reload: store edits show on the next reload; contract changes are signalled."""

import asyncio
from dataclasses import replace

import pytest

from app.core.memory_store import MemoryStore
from app.core.settings_reload import SettingsReloader
from app.core.tests.conftest import TEST_COLLECTION
from app.shared.exceptions import DatabaseError

SEPOLIA = replace(
    TEST_COLLECTION,
    collection_id="sepolia-test",
    chain="base-sepolia",
    contract_address="0xad1f02d8b22fed6798a6474b65a5778cc0918afc",
    discord_channel_id=1215729486994210897,
)


class Signals:
    """Records each contracts-changed call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, frozenset[str]]] = []

    async def __call__(self, chain: str, contracts: frozenset[str]) -> None:
        self.calls.append((chain, contracts))


async def test_added_collection_wallet_and_mark_show_on_next_reload() -> None:
    store = MemoryStore()
    reloader = SettingsReloader(store, Signals())
    await reloader.reload()
    assert reloader.current.collections == ()

    store.add_collection(TEST_COLLECTION)
    store.add_company_wallet("0xabcdef0000000000000000000000000000000001", "Treasury")
    store.add_marketplace_mark("calldata_tag", "0x360c6ebe", "OpenSea")
    settings = await reloader.reload()

    assert [c.collection_id for c in settings.collections] == ["dragonz-series-1"]
    assert settings.company_label("0xabcdef0000000000000000000000000000000001") == "Treasury"
    assert [(m.kind, m.value, m.marketplace) for m in settings.marketplace_marks] == [
        ("calldata_tag", "0x360c6ebe", "OpenSea")
    ]


async def test_new_contract_on_a_chain_is_signalled_once() -> None:
    store = MemoryStore()
    signals = Signals()
    reloader = SettingsReloader(store, signals)
    store.add_collection(TEST_COLLECTION)
    await reloader.reload()
    assert signals.calls == [("base", frozenset({TEST_COLLECTION.contract_address}))]

    store.add_collection(SEPOLIA)
    await reloader.reload()
    await reloader.reload()
    assert signals.calls[1:] == [
        ("base-sepolia", frozenset({"0xad1f02d8b22fed6798a6474b65a5778cc0918afc"}))
    ]


async def test_deactivating_or_untracking_a_collection_signals_its_chain() -> None:
    store = MemoryStore()
    signals = Signals()
    reloader = SettingsReloader(store, signals)
    added = store.add_collection(TEST_COLLECTION)
    await reloader.reload()

    store.update_collection(replace(added, is_active=False))
    await reloader.reload()
    store.update_collection(replace(added, is_active=True, track_onchain=False))
    await reloader.reload()

    assert signals.calls[1:] == [("base", frozenset())]


async def test_changing_a_switch_does_not_signal() -> None:
    store = MemoryStore()
    signals = Signals()
    reloader = SettingsReloader(store, signals)
    added = store.add_collection(TEST_COLLECTION)
    await reloader.reload()

    store.update_collection(replace(added, post_mints=False, transfer_mode="all"))
    settings = await reloader.reload()

    assert len(signals.calls) == 1
    assert settings.collections[0].post_mints is False


async def test_run_reloads_each_interval() -> None:
    store = MemoryStore()
    reloader = SettingsReloader(store, Signals())
    task = asyncio.create_task(reloader.run(interval=0.01))
    store.add_collection(TEST_COLLECTION)
    await asyncio.sleep(0.1)
    task.cancel()
    assert [c.collection_id for c in reloader.current.collections] == ["dragonz-series-1"]


async def test_run_fails_loudly_when_a_reload_fails() -> None:
    class Broken(MemoryStore):
        async def list_collections(self) -> list:  # type: ignore[type-arg]
            raise DatabaseError("connection lost")

    reloader = SettingsReloader(Broken(), Signals())
    with pytest.raises(DatabaseError):
        await reloader.run(interval=0.01)


def test_memory_store_refuses_what_the_schema_refuses() -> None:
    store = MemoryStore()
    with pytest.raises(DatabaseError):
        store.add_collection(replace(TEST_COLLECTION, contract_address="0xABC"))
    with pytest.raises(DatabaseError):
        store.add_company_wallet("0xABC", "Treasury")
    with pytest.raises(DatabaseError):
        store.add_marketplace_mark("calldata_tag", "0xABC", "X")
