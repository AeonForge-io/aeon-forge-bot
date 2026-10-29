"""A fake chain answering the ENS-style eth_calls of app.nft.wallet_names, no network."""

from typing import Any

from app.core.store import Store
from app.nft.wallet_names import (
    ADDR_SELECTOR,
    BASE_REVERSE_SUFFIX,
    ENS_REVERSE_SUFFIX,
    NAME_SELECTOR,
    RESOLVER_SELECTOR,
    WalletNames,
    namehash,
)

RESOLVER = "0x" + "9" * 40
ZERO_WORD = "0x" + "0" * 64


class FakeNameChain:
    """One chain's name registry and resolver, set up with set_name; counts the calls made."""

    def __init__(self, reverse_suffix: str) -> None:
        self.reverse_suffix = reverse_suffix
        self.calls: list[str] = []
        self.error: Exception | None = None
        self._resolvers: dict[str, str] = {}
        self._names: dict[str, str] = {}
        self._addresses: dict[str, str] = {}

    def set_name(self, address: str, name: str, forward: str | None = None) -> None:
        """Give an address a reverse record claiming name; forward is where the name points."""
        reverse = namehash(address.removeprefix("0x") + self.reverse_suffix).hex()
        self._resolvers[reverse] = RESOLVER
        self._names[reverse] = name
        node = namehash(name).hex()
        self._resolvers[node] = RESOLVER
        self._addresses[node] = forward or address

    async def request(self, method: str, params: list[Any]) -> Any:
        assert method == "eth_call"
        data: str = params[0]["data"]
        selector, node = data[:10], data[10:]
        self.calls.append(selector)
        if self.error is not None:
            raise self.error
        if selector == RESOLVER_SELECTOR:
            resolver = self._resolvers.get(node)
            return "0x" + resolver.removeprefix("0x").rjust(64, "0") if resolver else ZERO_WORD
        if selector == NAME_SELECTOR:
            raw = self._names[node].encode()
            padded = raw.ljust(-(-len(raw) // 32) * 32, b"\0")
            return (
                "0x"
                + (32).to_bytes(32, "big").hex()
                + len(raw).to_bytes(32, "big").hex()
                + padded.hex()
            )
        assert selector == ADDR_SELECTOR
        return "0x" + self._addresses[node].removeprefix("0x").rjust(64, "0")


def no_wallet_names(store: Store) -> WalletNames:
    """A WalletNames whose chains know no names, for tests that only care about short addresses."""
    return WalletNames(FakeNameChain(ENS_REVERSE_SUFFIX), FakeNameChain(BASE_REVERSE_SUFFIX), store)
