"""Aeon Forge bot main entry point."""

import asyncio
import signal
import sys
from contextlib import AsyncExitStack

from app.chain.reader import ChainReader
from app.chain.rpc import AlchemyTransport, ChainRpc
from app.core.config import get_settings
from app.core.database import DatabaseClient
from app.core.logging import get_logger, setup_logging
from app.core.migrations import apply_migrations
from app.core.settings_reload import SettingsReloader
from app.discord.bot import DiscordBot
from app.discord.nft_poster import NFTPoster
from app.shared.exceptions import ConfigError, DatabaseError

logger = get_logger(__name__)

# Module-level variables for lifecycle management
database_client: DatabaseClient | None = None
discord_bot: DiscordBot | None = None
nft_poster: NFTPoster | None = None
settings_reloader: SettingsReloader | None = None
chain_readers: dict[str, ChainReader] = {}
chain_tasks: dict[str, asyncio.Task[None]] = {}
transports: AsyncExitStack = AsyncExitStack()
reader_ended = asyncio.Event()


def _note_reader_end(task: asyncio.Task[None]) -> None:
    """Wake main() when any reader ends, including one started after startup."""
    if not task.cancelled():
        reader_ended.set()


async def start_chain_reader(chain: str) -> None:
    """Start the reader of a chain that has tracked contracts."""
    if settings_reloader is None or database_client is None or nft_poster is None:
        raise RuntimeError("Chain reader started before the bot was initialised")
    transport = await transports.enter_async_context(AlchemyTransport(chain))
    reader = ChainReader(
        chain,
        ChainRpc(transport),
        database_client,
        settings_reloader,
        nft_poster,
    )
    chain_readers[chain] = reader
    task = asyncio.create_task(reader.run())
    task.add_done_callback(_note_reader_end)
    chain_tasks[chain] = task
    logger.info("chain.reader.started", chain=chain)


async def on_contracts_changed(chain: str, contracts: frozenset[str]) -> None:
    """Replace a chain's subscription when its tracked contracts change."""
    reader = chain_readers.get(chain)
    if reader is not None:
        reader.replace_contracts(contracts)
    elif contracts:
        await start_chain_reader(chain)


async def startup() -> None:
    """Initialize application on startup."""
    global database_client, discord_bot, nft_poster, settings_reloader

    settings = get_settings()

    logger.info("application.lifecycle.started", log_level=settings.log_level)

    # Initialize database client
    database_client = DatabaseClient()
    pool = (await database_client.__aenter__()).pool
    logger.info("database.client.initialized")

    if pool is None:
        raise DatabaseError("Connection pool not initialized")
    await apply_migrations(pool)

    # Initialize Discord bot
    discord_bot = DiscordBot(settings.discord_token)
    await discord_bot.__aenter__()
    logger.info("discord.bot.initialized")

    nft_poster = NFTPoster(discord_bot)

    # The first reload reports every tracked chain as changed, which starts its reader,
    # so it runs only once everything a reader needs exists
    settings_reloader = SettingsReloader(database_client, on_contracts_changed)
    await settings_reloader.reload()

    logger.info("application.initialization.completed")


async def shutdown() -> None:
    """Cleanup on application shutdown."""
    logger.info("application.shutdown.started")

    for task in chain_tasks.values():
        task.cancel()
    await asyncio.gather(*chain_tasks.values(), return_exceptions=True)
    await transports.aclose()

    # Close Discord bot
    if discord_bot:
        await discord_bot.__aexit__(None, None, None)

    # Close database client
    if database_client:
        await database_client.__aexit__(None, None, None)

    logger.info("application.shutdown.completed")


async def main() -> None:
    """Main application loop."""
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def signal_handler(sig: int) -> None:
        logger.info("application.signal.received", signal=signal.Signals(sig).name)
        task = loop.create_task(shutdown())

        def stop_loop(_: asyncio.Task[None]) -> None:
            loop.stop()

        task.add_done_callback(stop_loop)

    for sig in (signal.SIGINT, signal.SIGTERM):

        def make_handler(s: int = sig) -> None:
            signal_handler(s)

        loop.add_signal_handler(sig, make_handler)

    try:
        await startup()

        if settings_reloader is None:
            raise RuntimeError("Settings reloader not started")
        reload_task = asyncio.create_task(settings_reloader.run())
        # A failed reader or reload ends the bot instead of leaving it half-running
        reader_wait = asyncio.create_task(reader_ended.wait())
        await asyncio.wait({reload_task, reader_wait}, return_when=asyncio.FIRST_COMPLETED)
        reader_wait.cancel()
        for task in (reload_task, *chain_tasks.values()):
            if task.done():
                task.result()

    except KeyboardInterrupt:
        logger.info("application.interrupted")
        await shutdown()
    except Exception as e:
        logger.error("application.error.fatal", error=str(e), exc_info=True)
        await shutdown()
        raise


def run() -> None:
    """Entry point for running the bot."""
    try:
        # Load settings first to validate configuration
        settings = get_settings()

        # Setup logging with configured level
        setup_logging(log_level=settings.log_level)

        # Run the async main loop
        asyncio.run(main())

    except ConfigError as e:
        # Configuration errors should exit immediately with clear message
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C
        pass
    except Exception as e:
        # Unexpected errors should be logged and exit with error code
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run()
