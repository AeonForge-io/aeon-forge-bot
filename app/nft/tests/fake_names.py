"""A fake chain answering the Multicall3 aggregate3 eth_calls of app.nft.wallet_names, no network."""

from typing import Any

from app.core.store import Store
from app.nft.multicall import AGGREGATE3_SELECTOR, MULTICALL3, WORD, address_word, padded, word
from app.nft.wallet_names import (
    ADDR_SELECTOR,
    BASE_L2_RESOLVER,
    BASE_REVERSE_REGISTRAR,
    BASE_REVERSE_SUFFIX,
    BASENAMES_REGISTRY,
    NAME_FOR_ADDR_SELECTOR,
    NAME_SELECTOR,
    RESOLVER_SELECTOR,
    REVERSE_SELECTOR,
    UNIVERSAL_RESOLVER,
    WalletNames,
    namehash,
)


def _abi_string(text: str) -> bytes:
    raw = text.encode()
    return word(WORD) + word(len(raw)) + padded(raw)


class FakeNameChain:
    """One chain's name contracts behind Multicall3, set up with the set_* methods.

    calls holds the selector of every eth_call made, so len(calls) is the number of requests.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.error: Exception | None = None
        self._universal: dict[str, str] = {}  # address -> primary name; absent reverts
        self._resolver_names: dict[str, str] = {}  # reverse node hex -> name
        self._registrar_names: dict[str, str] = {}  # address -> name
        self._registry: dict[str, str] = {}  # node hex -> resolver
        self._addresses: dict[tuple[str, str], str] = {}  # (resolver, node hex) -> address

    def set_ens_name(self, address: str, name: str) -> None:
        """The Universal Resolver's reverse(address, 60) returns name; others revert."""
        self._universal[address] = name

    def set_basename(
        self,
        address: str,
        name: str,
        forward: str | None = None,
        via_registrar: bool = False,
        registry_resolver: str = BASE_L2_RESOLVER,
    ) -> None:
        """A reverse record claiming name, read from the L2 Resolver or else the registrar.

        forward is where the name points; the registry names registry_resolver for it.
        """
        if via_registrar:
            self._registrar_names[address] = name
        else:
            reverse = namehash(address.removeprefix("0x") + BASE_REVERSE_SUFFIX).hex()
            self._resolver_names[reverse] = name
        node = namehash(name).hex()
        self._registry[node] = registry_resolver
        self._addresses[(registry_resolver, node)] = forward or address

    async def request(self, method: str, params: list[Any]) -> Any:
        assert method == "eth_call"
        assert params[0]["to"] == MULTICALL3
        data: str = params[0]["data"]
        assert data[:10] == AGGREGATE3_SELECTOR
        self.calls.append(data[:10])
        if self.error is not None:
            raise self.error
        raw = bytes.fromhex(data[10:])
        count = int.from_bytes(raw[WORD : 2 * WORD], "big")
        results = []
        for i in range(count):
            start = 2 * WORD + int.from_bytes(raw[(2 + i) * WORD : (3 + i) * WORD], "big")
            target = "0x" + raw[start + 12 : start + WORD].hex()
            assert int.from_bytes(raw[start + WORD : start + 2 * WORD], "big") == 1
            length = int.from_bytes(raw[start + 3 * WORD : start + 4 * WORD], "big")
            call_data = raw[start + 4 * WORD : start + 4 * WORD + length]
            results.append(self._answer(target, call_data))
        encoded = [
            word(1 if answer is not None else 0)
            + word(2 * WORD)
            + word(len(answer or b""))
            + padded(answer or b"")
            for answer in results
        ]
        offsets, position = [], len(encoded) * WORD
        for item in encoded:
            offsets.append(word(position))
            position += len(item)
        body = word(WORD) + word(count) + b"".join(offsets) + b"".join(encoded)
        return "0x" + body.hex()

    def _answer(self, target: str, call_data: bytes) -> bytes | None:
        """The return data of one subcall, None for a revert."""
        selector, argument = call_data[:4].hex(), call_data[4:]
        if target == UNIVERSAL_RESOLVER:
            assert selector == REVERSE_SELECTOR
            assert int.from_bytes(argument[WORD : 2 * WORD], "big") == 60
            address = "0x" + argument[3 * WORD : 3 * WORD + 20].hex()
            ens_name = self._universal.get(address)
            if ens_name is None:
                return None
            return word(3 * WORD) + address_word("0x" + "9" * 40) * 2 + _abi_string(ens_name)[WORD:]
        if target == BASE_REVERSE_REGISTRAR:
            assert selector == NAME_FOR_ADDR_SELECTOR
            name = self._registrar_names.get("0x" + argument[12:WORD].hex())
            return _abi_string(name or "")
        node = argument[:WORD].hex()
        if target == BASENAMES_REGISTRY:
            assert selector == RESOLVER_SELECTOR
            return address_word(self._registry.get(node, "0x" + "0" * 40))
        if selector == NAME_SELECTOR:
            assert target == BASE_L2_RESOLVER
            return _abi_string(self._resolver_names.get(node, ""))
        assert selector == ADDR_SELECTOR
        forward = self._addresses.get((target, node))
        return address_word(forward or "0x" + "0" * 40)


def no_wallet_names(store: Store) -> WalletNames:
    """A WalletNames whose chains know no names, for tests that only care about short addresses."""
    return WalletNames(FakeNameChain(), FakeNameChain(), store)
