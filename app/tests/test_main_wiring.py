"""The hookup between the settings reloader and the chain readers in app.main."""

import asyncio
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from app import main


class FakeTransport:
    def __init__(self, chain: str) -> None:
        self.chain = chain

    async def __aenter__(self) -> "FakeTransport":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def aclose(self) -> None:
        return None


class FakeReader:
    instances: ClassVar[list["FakeReader"]] = []
    fail: ClassVar[bool] = False

    def __init__(self, chain: str, *_: Any) -> None:
        self.chain = chain
        self.replaced: list[frozenset[str]] = []
        FakeReader.instances.append(self)

    def replace_contracts(self, contracts: frozenset[str]) -> None:
        self.replaced.append(contracts)

    async def run(self) -> None:
        if FakeReader.fail:
            raise RuntimeError("reader failed")
        await asyncio.Event().wait()


@pytest.fixture(autouse=True)
def wired(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeReader.instances = []
    FakeReader.fail = False
    monkeypatch.setattr(main, "ChainReader", FakeReader)
    monkeypatch.setattr(main, "AlchemyTransport", FakeTransport)
    monkeypatch.setattr(main, "ChainRpc", lambda transport: transport)
    monkeypatch.setattr(main, "settings_reloader", SimpleNamespace())
    monkeypatch.setattr(main, "database_client", SimpleNamespace())
    monkeypatch.setattr(main, "nft_poster", SimpleNamespace())
    monkeypatch.setattr(main, "chain_readers", {})
    monkeypatch.setattr(main, "chain_tasks", {})
    monkeypatch.setattr(main, "reader_ended", asyncio.Event())


async def stop_tasks() -> None:
    for task in main.chain_tasks.values():
        task.cancel()
    await asyncio.gather(*main.chain_tasks.values(), return_exceptions=True)


async def test_new_chain_starts_a_reader_and_known_chain_replaces_contracts() -> None:
    await main.on_contracts_changed("base", frozenset({"0xa"}))
    assert [r.chain for r in FakeReader.instances] == ["base"]

    await main.on_contracts_changed("base", frozenset({"0xb"}))
    assert len(FakeReader.instances) == 1
    assert FakeReader.instances[0].replaced == [frozenset({"0xb"})]
    await stop_tasks()


async def test_empty_set_on_a_chain_without_reader_starts_nothing() -> None:
    await main.on_contracts_changed("base", frozenset())
    assert FakeReader.instances == []


async def test_a_reader_started_later_that_fails_wakes_main() -> None:
    FakeReader.fail = True
    await main.on_contracts_changed("base-sepolia", frozenset({"0xa"}))
    await asyncio.wait_for(main.reader_ended.wait(), timeout=1)
