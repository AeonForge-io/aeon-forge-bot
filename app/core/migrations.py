"""Applies the numbered SQL files in migrations/ at startup.

Each pending file runs in its own transaction and is recorded in schema_migrations,
so a failed file leaves no partial schema and is retried on the next start.
"""

import re
from pathlib import Path

import asyncpg

from app.core.logging import get_logger
from app.shared.exceptions import DatabaseError

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"
MIGRATION_NAME = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """The migration files in apply order; refuses a file not named NNN_name.sql."""
    if not directory.is_dir():
        raise DatabaseError(f"Migrations folder not found: {directory}")
    files = sorted(directory.glob("*.sql"))
    bad = [f.name for f in files if not MIGRATION_NAME.match(f.name)]
    if bad:
        raise DatabaseError(f"Migration files not named NNN_name.sql: {', '.join(bad)}")
    return files


async def apply_migrations(pool: asyncpg.Pool, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order; returns the names applied this time."""
    files = migration_files(directory)
    applied_now: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        done = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        for path in files:
            if path.name in done:
                continue
            try:
                async with conn.transaction():
                    await conn.execute(path.read_text())
                    await conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES ($1)", path.name
                    )
            except asyncpg.PostgresError as e:
                logger.error("database.migration.failed", migration=path.name, error=str(e))
                raise DatabaseError(f"Migration {path.name} failed: {e}") from e
            logger.info("database.migration.applied", migration=path.name)
            applied_now.append(path.name)
    return applied_now
