"""Wallet primary names for Discord cards: ENS first, then Basename, else no name.

Lookups cost Alchemy calls, so every answer is cached, "no name" included: in a dict for
the life of the process and in the wallet_names table for 7 days. A failed lookup is not
cached, so the next post tries again.

Contract addresses and the reverse-node scheme were checked against the live chains
(public RPCs, no key) on 2026-10-28:
- ENS registry 0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e on Ethereum: 0xd8dA...6045
  reverses to vitalik.eth through <address>.addr.reverse, and vitalik.eth forwards back.
- Basenames registry 0xB94704422c2a1E396835A571837Aa5AE53285a95 on Base: jesse.base.eth
  forwards to 0x2211...7da9, whose <address>.80002105.reverse node (ENSIP-11 coin type of
  Base) has the registry resolver 0xC6d566A56A1aFf6508b41f6c90ff131615583BCD, and
  name(node) on it returns jesse.base.eth.
"""

import asyncio
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, TypeVar

from Crypto.Hash import keccak

from app.chain.rpc import ChainConnectionError, RpcResponseError
from app.core.logging import get_logger
from app.core.store import Store, WalletNameRecord
from app.nft.models import ZERO_ADDRESS
from app.shared.exceptions import DatabaseError

logger = get_logger(__name__)

ENS_REGISTRY = "0x00000000000c2e074ec69a0dfb2997ba6c7d2e1e"  # Ethereum mainnet
BASENAMES_REGISTRY = "0xb94704422c2a1e396835a571837aa5ae53285a95"  # Base mainnet
BASE_REVERSE_SUFFIX = ".80002105.reverse"  # ENSIP-11 coin type of Base: 0x80000000 | 8453
ENS_REVERSE_SUFFIX = ".addr.reverse"

RESOLVER_SELECTOR = "0x0178b8bf"  # resolver(bytes32), on the registry
NAME_SELECTOR = "0x691f3431"  # name(bytes32), on a resolver
ADDR_SELECTOR = "0x3b3b57de"  # addr(bytes32), on a resolver

CACHE_TTL = timedelta(days=7)
LOOKUP_TIMEOUT = 5.0  # seconds for all the names of one post
MAX_NAME_LENGTH = 40
SAFE_NAME = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.eth$")
_T = TypeVar("_T")


class Requester(Protocol):
    """The one transport call a lookup needs."""

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        """Send one JSON-RPC call and return its result."""
        ...


def _keccak(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


def namehash(name: str) -> bytes:
    """The ENS namehash of a dotted name."""
    node = bytes(32)
    if name:
        for label in reversed(name.split(".")):
            node = _keccak(node + _keccak(label.encode()))
    return node


def _address_in(word: str) -> str | None:
    """The address in an eth_call result of one address word, None when empty or zero."""
    if len(word) < 42:
        return None
    address = "0x" + word[-40:]
    return None if int(address, 16) == 0 else address.lower()


def _string_in(result: str) -> str | None:
    """The string in an eth_call result holding one ABI-encoded string, None when malformed."""
    try:
        raw = bytes.fromhex(result.removeprefix("0x"))
        length = int.from_bytes(raw[32:64], "big")
        if len(raw) < 64 + length or length == 0:
            return None
        return raw[64 : 64 + length].decode()
    except ValueError:
        return None


def is_safe_name(name: str) -> bool:
    """A name safe to put in Discord text: lowercase ASCII, no markdown, short."""
    return len(name) <= MAX_NAME_LENGTH and SAFE_NAME.fullmatch(name) is not None


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

        async def look_up(address: str) -> None:
            try:
                ens_name = await self._reverse(
                    self._ethereum, ENS_REGISTRY, ENS_REVERSE_SUFFIX, address
                )
                base_name = None
                if ens_name is None:
                    base_name = await self._reverse(
                        self._base, BASENAMES_REGISTRY, BASE_REVERSE_SUFFIX, address, ".base.eth"
                    )
            except ChainConnectionError as e:
                logger.warning("wallet_names.lookup_failed", address=address, error=str(e))
                return
            record = WalletNameRecord(address, ens_name, base_name, self._clock())
            self._known[address] = record
            try:
                await self._store.set_wallet_names(record)
            except DatabaseError as e:
                logger.error("wallet_names.write_failed", address=address, error=str(e))

        # Names that finish before a timeout are cached and shown; the rest wait for next time
        async def look_up_and_show(address: str) -> None:
            await look_up(address)
            self._show(address, found)

        for address in wanted - set(missing):
            self._show(address, found)
        await asyncio.gather(*(look_up_and_show(a) for a in missing))

    def _fresh(self, record: WalletNameRecord | None) -> bool:
        return record is not None and self._clock() - record.checked_at < CACHE_TTL

    def _show(self, address: str, found: dict[str, str]) -> None:
        record = self._known.get(address)
        if record is not None and (name := record.ens_name or record.base_name):
            found[address] = name

    async def _reverse(
        self,
        chain: Requester,
        registry: str,
        reverse_suffix: str,
        address: str,
        required_suffix: str = ".eth",
    ) -> str | None:
        """The verified primary name of an address on one chain, None when it has none.

        Reads the name from the address's reverse record, then checks that the name
        forwards back to the address: a reverse record can claim any name.
        """
        reverse_node = namehash(address.removeprefix("0x") + reverse_suffix)
        resolver = await self._resolver(chain, registry, reverse_node)
        if resolver is None:
            return None
        name = await self._call(chain, resolver, NAME_SELECTOR, reverse_node, _string_in)
        if name is None:
            return None
        if not (is_safe_name(name) and name.endswith(required_suffix)):
            logger.warning("wallet_names.unsafe_name", address=address, name=name[:80])
            return None
        node = namehash(name)
        forward_resolver = await self._resolver(chain, registry, node)
        if forward_resolver is None:
            return None
        resolved = await self._call(chain, forward_resolver, ADDR_SELECTOR, node, _address_in)
        if resolved != address:
            logger.info("wallet_names.forward_mismatch", address=address, name=name)
            return None
        return name

    async def _resolver(self, chain: Requester, registry: str, node: bytes) -> str | None:
        return await self._call(chain, registry, RESOLVER_SELECTOR, node, _address_in)

    @staticmethod
    async def _call(
        chain: Requester,
        to: str,
        selector: str,
        node: bytes,
        decode: Callable[[str], _T | None],
    ) -> _T | None:
        """eth_call a one-bytes32-argument function; a revert or empty answer decodes to None."""
        try:
            result = await chain.request(
                "eth_call", [{"to": to, "data": selector + node.hex()}, "latest"]
            )
        except RpcResponseError as e:
            # An offchain-resolver name reverts for good; any other refusal is retried next time
            if "execution reverted" in str(e):
                return None
            raise
        if not isinstance(result, str) or result == "0x":
            return None
        return decode(result)
