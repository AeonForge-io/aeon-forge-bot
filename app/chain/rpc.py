"""JSON-RPC: the transports (HTTP, and Alchemy with websocket) and typed reads on top of them.

The Transport protocol is the network boundary; tests fake it with Alchemy-shaped replies.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, Self, TypeVar

import aiohttp

from app.nft.metadata import alchemy_rpc_url
from app.shared.exceptions import AeonForgeBotError

SYMBOL_SELECTOR = "0x95d89b41"
DECIMALS_SELECTOR = "0x313ce567"
TX_CACHE_SIZE = 256
HTTP_OK = 200
_T = TypeVar("_T")


class ChainConnectionError(AeonForgeBotError):
    """The node connection failed or dropped; the caller reconnects."""


class RpcResponseError(ChainConnectionError):
    """The node answered but refused or could not serve the call; retrying will not help."""


class SubscriptionError(AeonForgeBotError):
    """Alchemy refused the eth_subscribe request."""


class Transport(Protocol):
    """Raw JSON-RPC access to one chain."""

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        """Send one JSON-RPC call over HTTP and return its result."""
        ...

    def subscribe_logs(
        self, log_filter: dict[str, Any], opened: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        """Open an eth_subscribe logs subscription and yield each log notification.

        The opened event is set once the node has accepted the subscription.
        """
        ...


class HttpTransport:
    """JSON-RPC calls over HTTP to any node URL, such as a free public RPC."""

    def __init__(self, http_url: str) -> None:
        self._http_url = http_url
        self._session = aiohttp.ClientSession()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._session.close()

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            async with self._session.post(self._http_url, json=payload) as response:
                if response.status != HTTP_OK:
                    raise ChainConnectionError(f"{method} failed: HTTP {response.status}")
                body = await response.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            # str(e) can carry the URL, which can hold an API key
            raise ChainConnectionError(f"{method} failed: {type(e).__name__}") from None
        if "error" in body:
            raise RpcResponseError(f"{method} returned an error: {body['error']}")
        return body["result"]


class AlchemyTransport(HttpTransport):
    """Transport for one chain on Alchemy, over https and wss."""

    def __init__(self, chain: str) -> None:
        http_url = alchemy_rpc_url(chain)
        if http_url is None:
            raise ValueError(f"No Alchemy network for chain {chain}")
        super().__init__(http_url)
        self._ws_url = "wss://" + http_url.removeprefix("https://")

    async def subscribe_logs(
        self, log_filter: dict[str, Any], opened: asyncio.Event
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            async with self._session.ws_connect(self._ws_url, heartbeat=30) as ws:
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_subscribe",
                        "params": ["logs", log_filter],
                    }
                )
                reply = await ws.receive_json()
                if "error" in reply:
                    raise SubscriptionError(f"eth_subscribe refused: {reply['error']}")
                opened.set()
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        break
                    body = message.json()
                    if body.get("method") == "eth_subscription":
                        yield body["params"]["result"]
        except (aiohttp.ClientError, TimeoutError) as e:
            raise ChainConnectionError(f"websocket failed: {type(e).__name__}") from None


@dataclass(frozen=True)
class Coin:
    """An ERC-20's symbol and decimals."""

    symbol: str
    decimals: int


@dataclass(frozen=True)
class Block:
    """A block's number and time."""

    number: int
    timestamp: int


@dataclass(frozen=True)
class Transaction:
    """The parts of a transaction the bot reads; to is None for a deployment."""

    sender: str
    to: str | None
    value_wei: int
    input: str


def hex_to_int(value: str) -> int:
    """Decode a 0x quantity."""
    return int(value, 16)


class ChainRpc:
    """The reads the chain reader needs, decoded."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport
        self._erc20_coins: dict[str, Coin] = {}
        self._transactions: dict[str, Transaction] = {}
        self._traces: dict[str, dict[str, Any]] = {}

    async def block(self, number: int | None = None) -> Block:
        """A block by number, or the head when number is None."""
        tag = "latest" if number is None else hex(number)
        raw = await self.transport.request("eth_getBlockByNumber", [tag, False])
        if raw is None:
            raise ChainConnectionError(f"eth_getBlockByNumber returned null for block {tag}")
        return Block(hex_to_int(raw["number"]), hex_to_int(raw["timestamp"]))

    async def logs(
        self, from_block: int, to_block: int, addresses: list[str], topics: list[str]
    ) -> list[dict[str, Any]]:
        """Logs of the addresses in the block range, with the first topic in topics."""
        log_filter = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "address": addresses,
            "topics": [topics],
        }
        logs: list[dict[str, Any]] = await self.transport.request("eth_getLogs", [log_filter])
        return logs

    async def call_uint(self, to: str, selector: str, block_number: int | str) -> int:
        """eth_call a no-argument function returning one uint256, at a block."""
        result = await self.transport.request(
            "eth_call",
            [
                {"to": to, "data": selector},
                block_number if isinstance(block_number, str) else hex(block_number),
            ],
        )
        if not result or result == "0x":
            raise RpcResponseError(f"eth_call {selector} on {to} returned an empty result")
        return hex_to_int(result)

    async def transaction(self, tx_hash: str) -> Transaction:
        """A transaction's sender, target, ETH value and calldata; kept for repeat reads."""
        if tx_hash not in self._transactions:
            tx = await self.transport.request("eth_getTransactionByHash", [tx_hash])
            if tx is None:
                raise ChainConnectionError(f"eth_getTransactionByHash returned null for {tx_hash}")
            to = tx["to"]
            self._remember(
                self._transactions,
                tx_hash,
                Transaction(
                    tx["from"].lower(),
                    to.lower() if to else None,
                    hex_to_int(tx["value"]),
                    tx["input"],
                ),
            )
        return self._transactions[tx_hash]

    async def call_trace(self, tx_hash: str) -> dict[str, Any]:
        """A transaction's call tree from Alchemy's callTracer, internal ETH transfers included."""
        if tx_hash not in self._traces:
            trace: dict[str, Any] = await self.transport.request(
                "debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}]
            )
            self._remember(self._traces, tx_hash, trace)
        return self._traces[tx_hash]

    @staticmethod
    def _remember(cache: dict[str, _T], key: str, value: _T) -> None:
        if len(cache) >= TX_CACHE_SIZE:
            cache.clear()
        cache[key] = value

    async def transaction_logs(self, tx_hash: str) -> list[dict[str, Any]]:
        """The logs of a transaction's receipt."""
        receipt = await self.transport.request("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            raise ChainConnectionError(f"eth_getTransactionReceipt returned null for {tx_hash}")
        logs: list[dict[str, Any]] = receipt["logs"]
        return logs

    async def erc20_coin(self, token: str) -> Coin:
        """An ERC-20's symbol() and decimals(), read once per token and cached."""
        if token not in self._erc20_coins:
            symbol_result = await self.transport.request(
                "eth_call", [{"to": token, "data": SYMBOL_SELECTOR}, "latest"]
            )
            raw = bytes.fromhex(symbol_result.removeprefix("0x"))
            length = int.from_bytes(raw[32:64], "big")
            if len(raw) < 64 + length or length == 0:
                raise RpcResponseError(
                    f"ERC-20 {token} symbol() is not an ABI string: {symbol_result!r}"
                )
            try:
                symbol = raw[64 : 64 + length].decode()
            except UnicodeDecodeError:
                raise RpcResponseError(f"ERC-20 {token} symbol() is not valid UTF-8") from None
            self._erc20_coins[token] = Coin(
                symbol,
                await self.call_uint(token, DECIMALS_SELECTOR, "latest"),
            )
        return self._erc20_coins[token]
