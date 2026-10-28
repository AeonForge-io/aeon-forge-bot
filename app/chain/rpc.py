"""Alchemy JSON-RPC: the transport (HTTP + websocket) and typed reads on top of it.

The Transport protocol is the network boundary; tests fake it with Alchemy-shaped replies.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol

import aiohttp

from app.core.config import get_settings
from app.nft.metadata import ALCHEMY_NETWORKS
from app.shared.exceptions import AeonForgeBotError


class ChainConnectionError(AeonForgeBotError):
    """The Alchemy connection failed or dropped; the caller reconnects."""


class SubscriptionError(AeonForgeBotError):
    """Alchemy refused the eth_subscribe request."""


class Transport(Protocol):
    """Raw JSON-RPC access to one chain."""

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        """Send one JSON-RPC call over HTTP and return its result."""
        ...

    def subscribe_logs(self, log_filter: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Open an eth_subscribe logs subscription and yield each log notification."""
        ...


class AlchemyTransport:
    """Transport for one chain on Alchemy, over https and wss."""

    def __init__(self, chain: str) -> None:
        network = ALCHEMY_NETWORKS[chain]
        key = get_settings().alchemy_api_key
        self._http_url = f"https://{network}.g.alchemy.com/v2/{key}"
        self._ws_url = f"wss://{network}.g.alchemy.com/v2/{key}"
        self._session = aiohttp.ClientSession()

    async def __aenter__(self) -> "AlchemyTransport":
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
                body = await response.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            # str(e) can carry the URL, which holds the API key
            raise ChainConnectionError(f"{method} failed: {type(e).__name__}") from None
        if "error" in body:
            raise ChainConnectionError(f"{method} returned an error: {body['error']}")
        return body["result"]

    async def subscribe_logs(self, log_filter: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
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
                async for message in ws:
                    if message.type != aiohttp.WSMsgType.TEXT:
                        break
                    body = message.json()
                    if body.get("method") == "eth_subscription":
                        yield body["params"]["result"]
        except (aiohttp.ClientError, TimeoutError) as e:
            raise ChainConnectionError(f"websocket failed: {type(e).__name__}") from None


@dataclass(frozen=True)
class Block:
    """A block's number and time."""

    number: int
    timestamp: int


def hex_to_int(value: str) -> int:
    """Decode a 0x quantity."""
    return int(value, 16)


class ChainRpc:
    """The reads the chain reader needs, decoded."""

    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    async def block(self, number: int | None = None) -> Block:
        """A block by number, or the head when number is None."""
        tag = "latest" if number is None else hex(number)
        raw = await self.transport.request("eth_getBlockByNumber", [tag, False])
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

    async def call_uint(self, to: str, selector: str, block_number: int) -> int:
        """eth_call a no-argument function returning one uint256, at a block."""
        result = await self.transport.request(
            "eth_call", [{"to": to, "data": selector}, hex(block_number)]
        )
        return hex_to_int(result)

    async def transaction_value_wei(self, tx_hash: str) -> int:
        """The ETH value (wei) sent with a transaction."""
        tx = await self.transport.request("eth_getTransactionByHash", [tx_hash])
        return hex_to_int(tx["value"])
