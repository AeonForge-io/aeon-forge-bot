"""Discord poster for NFT events."""

from typing import TYPE_CHECKING

import discord

from app.core.logging import get_logger
from app.discord.nft_embeds import (
    create_burn_embed,
    create_listing_embed,
    create_mint_embed,
    create_sale_embed,
    create_transfer_embed,
)
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)
from app.shared.exceptions import DiscordAPIError

if TYPE_CHECKING:
    from app.discord.bot import DiscordBot

logger = get_logger(__name__)


class NFTPoster:
    """Posts NFT events to Discord channels.

    Routes events to the appropriate Discord channel based on
    collection configuration.
    """

    def __init__(self, bot: "DiscordBot") -> None:
        """Initialize NFT poster.

        Args:
            bot: Discord bot instance for sending messages
        """
        self.bot = bot

    async def _get_channel(self, channel_id: int) -> discord.TextChannel:
        """Get Discord channel by ID.

        Args:
            channel_id: Discord channel ID

        Returns:
            Discord text channel

        Raises:
            DiscordAPIError: If channel not found or not accessible
        """
        if not self.bot.client:
            raise DiscordAPIError("Discord client not connected")

        channel = self.bot.client.get_channel(channel_id)
        if channel is None:
            raise DiscordAPIError(f"Channel {channel_id} not found")

        if not isinstance(channel, discord.TextChannel):
            raise DiscordAPIError(f"Channel {channel_id} is not a text channel")

        return channel

    async def post_mint(
        self,
        event: NFTMintEvent,
        collection_name: str,
        channel_id: int,
    ) -> None:
        """Post mint event to Discord.

        Args:
            event: Mint event data
            collection_name: Human-readable collection name
            channel_id: Discord channel ID to post to
        """
        try:
            channel = await self._get_channel(channel_id)
            embed = create_mint_embed(event, collection_name)
            await channel.send(embed=embed)

            logger.info(
                "nft.post.mint.success",
                collection=collection_name,
                token_id=event.token_id,
                channel_id=channel_id,
            )
        except DiscordAPIError:
            raise
        except Exception as e:
            logger.error(
                "nft.post.mint.failed",
                collection=collection_name,
                token_id=event.token_id,
                error=str(e),
                exc_info=True,
            )
            raise DiscordAPIError(f"Failed to post mint: {e}") from e

    async def post_transfer(
        self,
        event: NFTTransferEvent,
        collection_name: str,
        channel_id: int,
    ) -> None:
        """Post transfer event to Discord.

        Args:
            event: Transfer event data
            collection_name: Human-readable collection name
            channel_id: Discord channel ID to post to
        """
        try:
            channel = await self._get_channel(channel_id)
            embed = create_transfer_embed(event, collection_name)
            await channel.send(embed=embed)

            logger.info(
                "nft.post.transfer.success",
                collection=collection_name,
                token_id=event.token_id,
                channel_id=channel_id,
            )
        except DiscordAPIError:
            raise
        except Exception as e:
            logger.error(
                "nft.post.transfer.failed",
                collection=collection_name,
                token_id=event.token_id,
                error=str(e),
                exc_info=True,
            )
            raise DiscordAPIError(f"Failed to post transfer: {e}") from e

    async def post_burn(
        self,
        event: NFTBurnEvent,
        collection_name: str,
        channel_id: int,
    ) -> None:
        """Post burn event to Discord.

        Args:
            event: Burn event data
            collection_name: Human-readable collection name
            channel_id: Discord channel ID to post to
        """
        try:
            channel = await self._get_channel(channel_id)
            embed = create_burn_embed(event, collection_name)
            await channel.send(embed=embed)

            logger.info(
                "nft.post.burn.success",
                collection=collection_name,
                token_id=event.token_id,
                channel_id=channel_id,
            )
        except DiscordAPIError:
            raise
        except Exception as e:
            logger.error(
                "nft.post.burn.failed",
                collection=collection_name,
                token_id=event.token_id,
                error=str(e),
                exc_info=True,
            )
            raise DiscordAPIError(f"Failed to post burn: {e}") from e

    async def post_listing(
        self,
        event: NFTListingEvent,
        collection_name: str,
        channel_id: int,
        chain: str | None = None,
        contract_address: str | None = None,
    ) -> None:
        """Post listing event to Discord.

        Args:
            event: Listing event data
            collection_name: Human-readable collection name
            channel_id: Discord channel ID to post to
            chain: Blockchain network (for marketplace link)
            contract_address: NFT contract address (for marketplace link)
        """
        try:
            channel = await self._get_channel(channel_id)
            embed = create_listing_embed(event, collection_name, chain, contract_address)
            await channel.send(embed=embed)

            logger.info(
                "nft.post.listing.success",
                collection=collection_name,
                token_id=event.token_id,
                marketplace=event.marketplace,
                channel_id=channel_id,
            )
        except DiscordAPIError:
            raise
        except Exception as e:
            logger.error(
                "nft.post.listing.failed",
                collection=collection_name,
                token_id=event.token_id,
                error=str(e),
                exc_info=True,
            )
            raise DiscordAPIError(f"Failed to post listing: {e}") from e

    async def post_sale(
        self,
        event: NFTSaleEvent,
        collection_name: str,
        channel_id: int,
        chain: str | None = None,
    ) -> None:
        """Post sale event to Discord.

        Args:
            event: Sale event data
            collection_name: Human-readable collection name
            channel_id: Discord channel ID to post to
            chain: Blockchain network (for transaction link)
        """
        try:
            channel = await self._get_channel(channel_id)
            embed = create_sale_embed(event, collection_name, chain)
            await channel.send(embed=embed)

            logger.info(
                "nft.post.sale.success",
                collection=collection_name,
                token_id=event.token_id,
                marketplace=event.marketplace,
                channel_id=channel_id,
            )
        except DiscordAPIError:
            raise
        except Exception as e:
            logger.error(
                "nft.post.sale.failed",
                collection=collection_name,
                token_id=event.token_id,
                error=str(e),
                exc_info=True,
            )
            raise DiscordAPIError(f"Failed to post sale: {e}") from e
