"""Aeon Forge bot main entry point."""

import asyncio
import signal
import sys

from app.core.config import get_settings
from app.core.database import DatabaseClient
from app.core.logging import get_logger, setup_logging
from app.discord.bot import DiscordBot
from app.discord.nft_poster import NFTPoster
from app.shared.exceptions import ConfigError

logger = get_logger(__name__)

# Module-level variables for lifecycle management
database_client: DatabaseClient | None = None
discord_bot: DiscordBot | None = None
nft_poster: NFTPoster | None = None


async def startup() -> None:
    """Initialize application on startup."""
    global database_client, discord_bot, nft_poster

    settings = get_settings()

    logger.info("application.lifecycle.started", log_level=settings.log_level)

    # Initialize database client
    database_client = DatabaseClient()
    await database_client.__aenter__()
    logger.info("database.client.initialized")

    # Initialize Discord bot
    discord_bot = DiscordBot(settings.discord_token)
    await discord_bot.__aenter__()
    logger.info("discord.bot.initialized")

    nft_poster = NFTPoster(discord_bot)

    logger.info("application.initialization.completed")


async def shutdown() -> None:
    """Cleanup on application shutdown."""
    logger.info("application.shutdown.started")

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

        # Idle until the chain reader and pollers are added
        while True:
            await asyncio.sleep(60)

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
