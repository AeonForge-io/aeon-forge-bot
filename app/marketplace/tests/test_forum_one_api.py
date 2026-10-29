"""The forumone.io client against a local HTTP server."""

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.marketplace.forum_one import ForumOneApi, ForumOneError
from app.marketplace.tests.conftest import LE_CONTRACT


async def test_requests_the_collection_listings_url_with_all_and_offset() -> None:
    seen: list[tuple[str, dict[str, str]]] = []

    async def listings(request: web.Request) -> web.Response:
        seen.append((request.path, dict(request.query)))
        return web.json_response({"listings": [], "hasMore": False, "offset": 50})

    app = web.Application()
    app.router.add_get("/collection/{chain}/{contract}/listings", listings)
    async with TestServer(app) as server, aiohttp.ClientSession() as session:
        api = ForumOneApi(session, str(server.make_url("")).rstrip("/"))
        page = await api.listings_page("base", LE_CONTRACT, 50)

    assert page["hasMore"] is False
    assert seen == [(f"/collection/8453/{LE_CONTRACT}/listings", {"all": "1", "offset": "50"})]


async def test_a_chain_forum_one_does_not_serve_fails_naming_it() -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(ForumOneError, match="base-sepolia"):
            await ForumOneApi(session).listings_page("base-sepolia", LE_CONTRACT, 0)
