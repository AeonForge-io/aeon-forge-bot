"""HttpTransport: a plain JSON-RPC POST to any URL, failing with the same errors as Alchemy's."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import BaseTestServer, TestServer

from app.chain.rpc import ChainConnectionError, HttpTransport, RpcResponseError


async def serve(status: int, body: dict[str, Any]) -> AsyncIterator[BaseTestServer]:
    async def handler(request: web.Request) -> web.Response:
        assert (await request.json())["method"] == "eth_call"
        return web.json_response(body, status=status)

    app = web.Application()
    app.router.add_post("/", handler)
    async with TestServer(app) as server:
        yield server


async def call(server: BaseTestServer) -> Any:
    async with HttpTransport(str(server.make_url("/"))) as transport:
        return await transport.request("eth_call", [])


async def test_returns_the_result() -> None:
    async for server in serve(200, {"jsonrpc": "2.0", "id": 1, "result": "0x01"}):
        assert await call(server) == "0x01"


async def test_rate_limit_is_a_connection_error() -> None:
    async for server in serve(429, {"error": "rate limited"}):
        with pytest.raises(ChainConnectionError) as raised:
            await call(server)
        assert not isinstance(raised.value, RpcResponseError)
        assert "429" in str(raised.value)


async def test_json_rpc_error_is_a_response_error() -> None:
    async for server in serve(200, {"jsonrpc": "2.0", "id": 1, "error": {"message": "nope"}}):
        with pytest.raises(RpcResponseError):
            await call(server)


async def test_unreachable_node_is_a_connection_error() -> None:
    async with HttpTransport("http://127.0.0.1:1/") as transport:
        with pytest.raises(ChainConnectionError):
            await transport.request("eth_call", [])


async def test_alchemy_keeps_its_response_error_on_a_non_200_with_an_rpc_error() -> None:
    async for server in serve(429, {"jsonrpc": "2.0", "id": 1, "error": {"message": "limit"}}):
        async with HttpTransport(str(server.make_url("/")), strict_status=False) as transport:
            with pytest.raises(RpcResponseError):
                await transport.request("eth_call", [])
