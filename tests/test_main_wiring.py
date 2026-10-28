"""The hookup between the settings reloader and the chain readers in app.main."""

import asyncio
from unittest.mock import MagicMock

import pytest

from app import main


@pytest.fixture(autouse=True)
def started(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    chains: list[str] = []

    async def fake_start(chain: str) -> None:
        chains.append(chain)

    monkeypatch.setattr(main, "chain_readers", {})
    monkeypatch.setattr(main, "start_chain_reader", fake_start)
    return chains


async def test_new_chain_with_contracts_starts_a_reader(started: list[str]) -> None:
    await main.on_contracts_changed("base", frozenset({"0xabc"}))
    await main.on_contracts_changed("base-sepolia", frozenset())

    assert started == ["base"]


async def test_existing_reader_gets_the_new_contract_set() -> None:
    reader = MagicMock()
    main.chain_readers["base"] = reader

    await main.on_contracts_changed("base", frozenset({"0xabc"}))

    reader.replace_contracts.assert_called_once_with(frozenset({"0xabc"}))


async def test_a_failed_reader_wakes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "reader_ended", asyncio.Event())

    async def fail() -> None:
        raise RuntimeError("reader died")

    task = asyncio.create_task(fail())
    task.add_done_callback(main._note_reader_end)
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)

    assert main.reader_ended.is_set()
