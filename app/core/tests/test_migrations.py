"""Migrations: files, apply order, records, seeds and the schema's rules."""

import re

import asyncpg
import pytest

from app.core.database import DatabaseClient
from app.core.migrations import MIGRATIONS_DIR, apply_migrations, migration_files

REMOVED_TABLE_WORDS = ("github", "quote", "stats", "achievement", "delisting", "summar")


def test_migration_files_are_numbered_with_no_down_files() -> None:
    names = [f.name for f in migration_files()]
    assert names == sorted(names)
    assert names[0].startswith("001_")
    assert not [n for n in names if "down" in n]


def test_migrations_create_no_removed_tables() -> None:
    sql = "\n".join(f.read_text().lower() for f in migration_files())
    tables = re.findall(r"create table (?:if not exists )?(\w+)", sql)
    assert tables
    assert not [t for t in tables if any(word in t for word in REMOVED_TABLE_WORDS)]


@pytest.mark.integration
async def test_migrations_apply_in_order_and_are_recorded(pg_dsn: str) -> None:
    async with DatabaseClient(pg_dsn) as client:
        assert client.pool is not None
        applied = await apply_migrations(client.pool)
        assert applied == [f.name for f in migration_files(MIGRATIONS_DIR)]
        # A second start applies nothing
        assert await apply_migrations(client.pool) == []
        async with client.pool.acquire() as conn:
            recorded = [
                r["version"]
                for r in await conn.fetch("SELECT version FROM schema_migrations ORDER BY version")
            ]
            tables = {
                r["tablename"]
                for r in await conn.fetch(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                )
            }
        assert recorded == applied
        assert not [t for t in tables if any(word in t for word in REMOVED_TABLE_WORDS)]


@pytest.mark.integration
async def test_seed_rows(pg_client: DatabaseClient) -> None:
    collections = {c.collection_id: c for c in await pg_client.list_collections()}
    assert set(collections) == {"dragonz-series-1", "dragonz-limited-edition", "sepolia-test"}

    le = collections["dragonz-limited-edition"]
    assert le.chain == "base"
    assert le.contract_address == "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
    assert le.discord_channel_id == 1445253310574755912
    assert (le.track_onchain, le.track_marketplace, le.marketplaces) == (True, True, ("forum_one",))
    assert (le.post_mints, le.post_burns, le.post_sales, le.post_listings) == (True,) * 4
    assert le.transfer_mode == "company"

    test = collections["sepolia-test"]
    assert test.chain == "base-sepolia"
    assert test.discord_channel_id == 1215729486994210897
    assert (test.track_onchain, test.track_marketplace, test.marketplaces) == (True, False, ())

    assert await pg_client.list_company_wallets() == []

    marks = {(m.kind, m.value): m for m in await pg_client.list_marketplace_marks()}
    assert len(marks) == 15
    assert marks[("calldata_tag", "0x360c6ebe")].marketplace == "OpenSea"
    assert marks[("fee_wallet", "0x0000a26b00c1f0df003000390027140000faa719")].marketplace == (
        "OpenSea"
    )
    assert all(m.note for m in marks.values())
    # Magic Eden's EVM marketplace is closed; its fee wallet is not seeded
    assert not [m for m in marks.values() if m.marketplace == "Magic Eden"]


@pytest.mark.integration
async def test_schema_refuses_bad_settings_rows(pg_client: DatabaseClient) -> None:
    assert pg_client.pool is not None
    async with pg_client.pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE nft_collections SET transfer_mode = 'some' WHERE collection_id = 'sepolia-test'"
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO company_wallets (address, label) VALUES ('0xABC', 'Treasury')"
            )
        await conn.execute(
            "INSERT INTO company_wallets (address, label) VALUES ('0xabc', 'Treasury')"
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO company_wallets (address, label) VALUES ('0xabc', 'Ops')"
            )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO marketplace_marks (kind, value, marketplace) "
                "VALUES ('calldata_tag', '0x360c6ebe', 'Someone')"
            )
