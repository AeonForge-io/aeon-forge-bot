"""Discord bot lifecycle management."""

import asyncio
from types import TracebackType

import discord

from app.core.logging import get_logger
from app.shared.exceptions import DiscordAPIError

logger = get_logger(__name__)


class DiscordBot:
    """Discord bot manager with async context manager lifecycle.

    Provides the connected client; each post picks its channel by ID.
    """

    def __init__(self, token: str) -> None:
        """Initialize Discord bot with its token.

        Args:
            token: Discord bot token
        """
        self.token = token
        self.client: discord.Client | None = None
        self._connect_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "DiscordBot":
        """Context manager entry: create client and login.

        Returns:
            Self for use in async with statement

        Raises:
            DiscordAPIError: If login fails
        """
        intents = discord.Intents.default()
        self.client = discord.Client(intents=intents)

        # Set up ready event handler
        @self.client.event
        async def on_ready() -> None:
            """Log when bot is ready."""
            if self.client and self.client.user:
                logger.info("discord.bot.ready", username=self.client.user.name)

        try:
            # Login without running the event loop (we manage it in main.py)
            await self.client.login(self.token)
            logger.info("discord.bot.login.success")

            # Start the client (this will trigger on_ready)
            # We need to start the websocket connection but not block
            self._connect_task = asyncio.create_task(self.client.connect(reconnect=True))

            # Wait for the client to be ready
            await self.client.wait_until_ready()

        except discord.HTTPException as e:
            logger.error("discord.bot.login.failed", error=str(e), exc_info=True)
            raise DiscordAPIError(f"Failed to login: {e}") from e

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit: close Discord client.

        Args:
            exc_type: Exception type if raised
            exc_val: Exception value if raised
            exc_tb: Exception traceback if raised
        """
        if self.client:
            await self.client.close()
            logger.info("discord.bot.closed")
