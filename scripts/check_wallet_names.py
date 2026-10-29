"""Live check of wallet-name lookups against the public RPCs: names and calls per case.

Run from the repo root: python -m scripts.check_wallet_names
"""

import asyncio
from typing import Any

from app.chain.rpc import HttpTransport
from app.core.memory_store import MemoryStore
from app.main import PUBLIC_BASE_RPC, PUBLIC_ETHEREUM_RPC
from app.nft.wallet_names import WalletNames

VITALIK = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
JESSE = "0x2211d1d0020daea8039e46cf1367962070d77da9"
DEAD = "0x000000000000000000000000000000000000dead"


class CountingTransport:
    """Wraps a transport and counts the requests made."""

    def __init__(self, inner: HttpTransport) -> None:
        self._inner = inner
        self.calls = 0

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        self.calls += 1
        return await self._inner.request(method, params)


async def main() -> None:
    async with HttpTransport(PUBLIC_ETHEREUM_RPC) as eth, HttpTransport(PUBLIC_BASE_RPC) as base:
        for label, wallets in [
            ("vitalik", [VITALIK]),
            ("jesse", [JESSE]),
            ("dead", [DEAD]),
            ("all three", [VITALIK, JESSE, DEAD]),
        ]:
            counted_eth, counted_base = CountingTransport(eth), CountingTransport(base)
            names = await WalletNames(counted_eth, counted_base, MemoryStore()).names(wallets)
            print(
                f"{label}: {names} ({counted_eth.calls} Ethereum + {counted_base.calls} Base calls)"
            )


asyncio.run(main())
