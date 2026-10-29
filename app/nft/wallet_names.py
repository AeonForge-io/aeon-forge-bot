"""Wallet primary names for Discord cards: ENS first, then Basename, else no name.

Lookups run on free public RPCs, so the aim is few calls, not few compute units: every
step is one Multicall3 aggregate3 covering all the uncached wallets of a post. Every answer
is cached, "no name" included: in a dict for the life of the process and in the
wallet_names table for 7 days. A failed lookup is not cached, so the next post tries again.

- Ethereum: the ENS Universal Resolver's reverse(address, 60) returns the primary name and
  has already checked that it forwards back to the address. A name only registered in
  ENSv2 resolves here too, which the v1 registry reads would miss. A subcall that reverts
  (OffchainLookup, ReverseAddressMismatch) means no ENS name: there is no CCIP-Read client.
- Base: the Universal Resolver's Base path reverts for every wallet (the verifier does not
  support Base's game type yet), so Basenames are read directly. Step 2 reads the reverse
  name from the L2 Resolver, else from the ENSIP-19 L2ReverseRegistrar. Step 3 checks that
  the name forwards back: the Basenames registry names the L2 Resolver, whose addr is the
  wallet. A registry naming another resolver costs one more call to that resolver.

Contracts and examples were checked against the live chains (public RPCs, no key) on
2026-10-29: vitalik.eth is 0xd8dA...6045's ENS name; jesse.base.eth is 0x2211...7da9's
Basename, and that wallet's coin-60 lookup on the Universal Resolver reverts.
"""

import asyncio
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from Crypto.Hash import keccak

from app.chain.rpc import ChainConnectionError
from app.core.logging import get_logger
from app.core.store import Store, WalletNameRecord
from app.nft.models import ZERO_ADDRESS
from app.nft.multicall import Call, Requester, address_in, aggregate3, string_in, word
from app.shared.exceptions import DatabaseError

logger = get_logger(__name__)

UNIVERSAL_RESOLVER = "0xeeeeeeee14d718c2b47d9923deab1335e144eeee"  # Ethereum mainnet
BASENAMES_REGISTRY = "0xb94704422c2a1e396835a571837aa5ae53285a95"  # Base mainnet
BASE_L2_RESOLVER = "0xc6d566a56a1aff6508b41f6c90ff131615583bcd"  # Base mainnet
BASE_REVERSE_REGISTRAR = "0x0000000000d8e504002cc26e3ec46d81971c1664"  # Base mainnet, ENSIP-19
BASE_REVERSE_SUFFIX = ".80002105.reverse"  # ENSIP-11 coin type of Base: 0x80000000 | 8453
ETHEREUM_COIN_TYPE = 60

REVERSE_SELECTOR = "5d78a217"  # reverse(bytes lookupAddress, uint256 coinType), on the UR
NAME_FOR_ADDR_SELECTOR = "4ec3bd23"  # nameForAddr(address), on the L2ReverseRegistrar
RESOLVER_SELECTOR = "0178b8bf"  # resolver(bytes32), on the registry
NAME_SELECTOR = "691f3431"  # name(bytes32), on a resolver
ADDR_SELECTOR = "3b3b57de"  # addr(bytes32), on a resolver

CACHE_TTL = timedelta(days=7)
LOOKUP_TIMEOUT = 5.0  # seconds for all the names of one post
MAX_NAME_LENGTH = 40
SAFE_NAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.eth$")


def _keccak(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


def namehash(name: str) -> bytes:
    """The ENS namehash of a dotted name."""
    node = bytes(32)
    if name:
        for label in reversed(name.split(".")):
            node = _keccak(node + _keccak(label.encode()))
    return node


def is_safe_name(name: str) -> bool:
    """A name safe to put in Discord text: lowercase ASCII, no markdown, short."""
    return len(name) <= MAX_NAME_LENGTH and SAFE_NAME.fullmatch(name) is not None


def _address_bytes(address: str) -> bytes:
    return bytes.fromhex(address.removeprefix("0x"))


def _universal_reverse(address: str) -> Call:
    raw = _address_bytes(address)
    data = (
        bytes.fromhex(REVERSE_SELECTOR)
        + word(64)  # the bytes start after the two head words
        + word(ETHEREUM_COIN_TYPE)
        + word(len(raw))
        + raw.ljust(32, b"\0")
    )
    return Call(UNIVERSAL_RESOLVER, data)


def _node_call(target: str, selector: str, node: bytes) -> Call:
    return Call(target, bytes.fromhex(selector) + node)


def _name_for_addr(address: str) -> Call:
    data = bytes.fromhex(NAME_FOR_ADDR_SELECTOR) + _address_bytes(address).rjust(32, b"\0")
    return Call(BASE_REVERSE_REGISTRAR, data)


class WalletNames:
    """Finds the display name of wallets: ENS name, else Basename, else none."""

    def __init__(
        self,
        ethereum: Requester,
        base: Requester,
        store: Store,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._ethereum = ethereum
        self._base = base
        self._store = store
        self._clock = clock
        self._known: dict[str, WalletNameRecord] = {}

    async def names(self, addresses: Iterable[str]) -> dict[str, str]:
        """Display names by address, only for addresses that have one.

        Never raises and never takes longer than LOOKUP_TIMEOUT: an address that could not
        be looked up in time is left out, so the card shows its short address.
        """
        wanted = {a.lower() for a in addresses if a.lower() != ZERO_ADDRESS}
        found: dict[str, str] = {}
        try:
            async with asyncio.timeout(LOOKUP_TIMEOUT):
                await self._collect(wanted, found)
        except TimeoutError:
            logger.warning("wallet_names.timeout", addresses=len(wanted))
        return found

    async def _collect(self, wanted: set[str], found: dict[str, str]) -> None:
        stale = {a for a in wanted if not self._fresh(self._known.get(a))}
        if stale:
            try:
                rows = await self._store.get_wallet_names(sorted(stale))
            except DatabaseError as e:
                logger.error("wallet_names.read_failed", error=str(e))
                rows = {}
            for address, record in rows.items():
                if self._fresh(record):
                    self._known[address] = record
        missing = [a for a in wanted if not self._fresh(self._known.get(a))]
        for address in wanted - set(missing):
            self._show(address, found)
        if missing:
            await self._look_up(missing)
            for address in missing:
                self._show(address, found)

    async def _look_up(self, addresses: list[str]) -> None:
        """Find, remember and store the names of addresses; a failed step leaves its wallets unchecked."""
        try:
            ens_names = await self._ens_names(addresses)
        except ChainConnectionError as e:
            logger.warning("wallet_names.lookup_failed", chain="ethereum", error=str(e))
            return
        without_ens = [a for a in addresses if a not in ens_names]
        base_names: dict[str, str] = {}
        if without_ens:
            try:
                base_names = await self._basenames(without_ens)
            except ChainConnectionError as e:
                logger.warning("wallet_names.lookup_failed", chain="base", error=str(e))
                addresses = list(ens_names)
        for address in addresses:
            record = WalletNameRecord(
                address, ens_names.get(address), base_names.get(address), self._clock()
            )
            self._known[address] = record
            try:
                await self._store.set_wallet_names(record)
            except DatabaseError as e:
                logger.error("wallet_names.write_failed", address=address, error=str(e))

    def _fresh(self, record: WalletNameRecord | None) -> bool:
        return record is not None and self._clock() - record.checked_at < CACHE_TTL

    def _show(self, address: str, found: dict[str, str]) -> None:
        record = self._known.get(address)
        if record is not None and (name := record.ens_name or record.base_name):
            found[address] = name

    async def _ens_names(self, addresses: list[str]) -> dict[str, str]:
        """The ENS primary names of addresses, in one call; the Universal Resolver verifies them."""
        answers = await aggregate3(self._ethereum, [_universal_reverse(a) for a in addresses])
        names: dict[str, str] = {}
        for address, answer in zip(addresses, answers, strict=True):
            if (name := self._safe(address, string_in(answer), ".eth")) is not None:
                names[address] = name
        return names

    async def _basenames(self, addresses: list[str]) -> dict[str, str]:
        """The verified Basenames of addresses: two calls, a third when a name needs another resolver."""
        calls = []
        for address in addresses:
            node = namehash(address.removeprefix("0x") + BASE_REVERSE_SUFFIX)
            calls.append(_node_call(BASE_L2_RESOLVER, NAME_SELECTOR, node))
            calls.append(_name_for_addr(address))
        answers = await aggregate3(self._base, calls)
        candidates: dict[str, str] = {}
        for i, address in enumerate(addresses):
            from_resolver, from_registrar = answers[2 * i], answers[2 * i + 1]
            claimed = string_in(from_resolver) or string_in(from_registrar)
            if (name := self._safe(address, claimed, ".base.eth")) is not None:
                candidates[address] = name
        if not candidates:
            return {}

        forward = []
        for name in candidates.values():
            node = namehash(name)
            forward.append(_node_call(BASENAMES_REGISTRY, RESOLVER_SELECTOR, node))
            forward.append(_node_call(BASE_L2_RESOLVER, ADDR_SELECTOR, node))
        answers = await aggregate3(self._base, forward)
        verified: dict[str, str] = {}
        elsewhere: dict[str, tuple[str, str]] = {}  # address -> (name, resolver the registry names)
        for i, (address, name) in enumerate(candidates.items()):
            registry_resolver = address_in(answers[2 * i])
            resolved = address_in(answers[2 * i + 1])
            if registry_resolver == BASE_L2_RESOLVER:
                if resolved == address:
                    verified[address] = name
            elif registry_resolver:
                elsewhere[address] = (name, registry_resolver)
        if elsewhere:
            answers = await aggregate3(
                self._base,
                [
                    _node_call(resolver, ADDR_SELECTOR, namehash(name))
                    for name, resolver in elsewhere.values()
                ],
            )
            for address, answer in zip(elsewhere, answers, strict=True):
                if address_in(answer) == address:
                    verified[address] = elsewhere[address][0]
        for address in candidates.keys() - verified.keys():
            logger.info("wallet_names.forward_mismatch", address=address, name=candidates[address])
        return verified

    @staticmethod
    def _safe(address: str, name: str | None, required_suffix: str) -> str | None:
        """The name when it is safe text with the required ending, None when empty or unsafe."""
        if not name:
            return None
        if not (is_safe_name(name) and name.endswith(required_suffix)):
            logger.warning("wallet_names.unsafe_name", address=address, name=name[:80])
            return None
        return name
