"""Fixtures for core tests: the two Store implementations and a throwaway Postgres.

Integration tests need TEST_DATABASE_URL, a Postgres URL whose user may create
databases (the compose postgres user can). Each test gets a new database, dropped
afterwards, so the URL's own database is never touched.
"""

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from app.core.database import DatabaseClient
from app.core.memory_store import MemoryStore
from app.core.migrations import apply_migrations
from app.core.store import Collection, Store


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


@asynccontextmanager
async def throwaway_database() -> AsyncIterator[str]:
    """URL of a new empty database, dropped afterwards; skips without TEST_DATABASE_URL."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    name = f"aeon_forge_bot_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        yield _with_database(url, name)
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@asynccontextmanager
async def migrated_client() -> AsyncIterator[DatabaseClient]:
    """A connected client on a freshly migrated throwaway database."""
    async with throwaway_database() as dsn, DatabaseClient(dsn) as client:
        assert client.pool is not None
        await apply_migrations(client.pool)
        yield client


@pytest.fixture
async def pg_dsn() -> AsyncIterator[str]:
    async with throwaway_database() as dsn:
        yield dsn


@pytest.fixture
async def pg_client() -> AsyncIterator[DatabaseClient]:
    async with migrated_client() as client:
        yield client


TEST_COLLECTION = Collection(
    id=0,
    collection_id="dragonz-series-1",
    name="DragonZ Series 1",
    chain="base",
    contract_address="0xc7c1b8a5d8777dac959cb2b274debeda1c0ecc09",
    discord_channel_id=1445253310574755912,
)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("postgres", marks=pytest.mark.integration),
    ]
)
async def store_with_collection(
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[Store, int]]:
    """Each Store implementation, holding the DragonZ Series 1 collection."""
    if request.param == "memory":
        memory = MemoryStore()
        yield memory, memory.add_collection(TEST_COLLECTION).id
        return
    async with migrated_client() as client:
        collections = await client.list_collections()
        yield client, next(c.id for c in collections if c.collection_id == "dragonz-series-1")
