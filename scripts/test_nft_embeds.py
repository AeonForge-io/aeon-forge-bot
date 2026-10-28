"""Test script to post sample NFT embeds to Discord.

Run with: uv run python scripts/test_nft_embeds.py

This will post one of each embed type (mint, transfer, burn, listing, sale)
to the configured Discord channel for visual testing.

Images are fetched from IPFS via the configured gateway, just like production.
"""

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# Add parent directory to path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import discord

from app.core.config import get_settings
from app.discord.nft_embeds import (
    create_burn_embed,
    create_listing_embed,
    create_mint_embed,
    create_sale_embed,
    create_transfer_embed,
)
from app.nft.metadata import fetch_token_image
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

# Sample addresses
SAMPLE_SELLER = "0x1234567890abcdef1234567890abcdef12345678"
SAMPLE_BUYER = "0xabcdef1234567890abcdef1234567890abcdef12"
SAMPLE_MINTER = "0x9876543210fedcba9876543210fedcba98765432"
SAMPLE_TX_HASH = "0xabc123def456789abc123def456789abc123def456789abc123def456789abc1"

# Collection info - DragonZ Series 1
COLLECTION_NAME = "DragonZ Series 1"
TEST_CHAIN = "base"
TEST_CONTRACT = "0xc7c1b8a5d8777dac959cb2b274debeda1c0ecc09"

# Token IDs to use for testing (will fetch real images from IPFS)
# Each embed uses a unique token ID to avoid rate limiting
TEST_TOKEN_IDS = {
    "mint": "1",
    "transfer": "2",
    "burn": "3",
    "listing": "4",
    "listing_rarity": "5",
    "sale": "6",
    "sale_rarity": "7",
}


async def create_sample_mint_event() -> NFTMintEvent:
    """Create a sample mint event for testing with real IPFS image."""
    token_id = TEST_TOKEN_IDS["mint"]
    image_url = await fetch_token_image(TEST_CONTRACT, token_id, TEST_CHAIN)
    return NFTMintEvent(
        collection_id=1,
        token_id=token_id,
        to_address=SAMPLE_MINTER,
        chain=TEST_CHAIN,
        token_image_url=image_url,
        price_native=Decimal("0.05"),
        price_usd=Decimal("125.50"),
        transaction_hash=SAMPLE_TX_HASH,
        block_number=12345678,
        event_timestamp=datetime.now(UTC),
    )


async def create_sample_transfer_event() -> NFTTransferEvent:
    """Create a sample transfer event for testing with real IPFS image."""
    token_id = TEST_TOKEN_IDS["transfer"]
    image_url = await fetch_token_image(TEST_CONTRACT, token_id, TEST_CHAIN)
    return NFTTransferEvent(
        collection_id=1,
        token_id=token_id,
        from_address=SAMPLE_SELLER,
        to_address=SAMPLE_BUYER,
        chain=TEST_CHAIN,
        token_image_url=image_url,
        transaction_hash=SAMPLE_TX_HASH,
        block_number=12345679,
        event_timestamp=datetime.now(UTC),
    )


async def create_sample_burn_event() -> NFTBurnEvent:
    """Create a sample burn event for testing with real IPFS image."""
    token_id = TEST_TOKEN_IDS["burn"]
    image_url = await fetch_token_image(TEST_CONTRACT, token_id, TEST_CHAIN)
    return NFTBurnEvent(
        collection_id=1,
        token_id=token_id,
        from_address=SAMPLE_SELLER,
        chain=TEST_CHAIN,
        token_image_url=image_url,
        transaction_hash=SAMPLE_TX_HASH,
        block_number=12345680,
        event_timestamp=datetime.now(UTC),
    )


async def create_sample_listing_event(with_rarity: bool = False) -> NFTListingEvent:
    """Create a sample listing event for testing with real IPFS image."""
    token_id = TEST_TOKEN_IDS["listing_rarity" if with_rarity else "listing"]
    image_url = await fetch_token_image(TEST_CONTRACT, token_id, TEST_CHAIN)
    return NFTListingEvent(
        collection_id=1,
        token_id=token_id,
        token_name=None,
        token_image_url=image_url,
        seller_address=SAMPLE_SELLER,
        marketplace="magic_eden",
        price_native=Decimal("0.15"),
        price_usd=Decimal("375.00"),
        floor_price_native=Decimal("0.10"),
        rarity_rank=42 if with_rarity else None,
        listing_id="listing-123456",
        event_timestamp=datetime.now(UTC),
        is_active=True,
    )


async def create_sample_sale_event(with_rarity: bool = False) -> NFTSaleEvent:
    """Create a sample sale event for testing with real IPFS image."""
    token_id = TEST_TOKEN_IDS["sale_rarity" if with_rarity else "sale"]
    image_url = await fetch_token_image(TEST_CONTRACT, token_id, TEST_CHAIN)
    return NFTSaleEvent(
        collection_id=1,
        token_id=token_id,
        token_name=None,
        token_image_url=image_url,
        seller_address=SAMPLE_SELLER,
        buyer_address=SAMPLE_BUYER,
        marketplace="magic_eden",
        price_native=Decimal("0.25"),
        price_usd=Decimal("625.00"),
        floor_price_native=Decimal("0.10"),
        rarity_rank=15 if with_rarity else None,
        sale_id=SAMPLE_TX_HASH,
        event_timestamp=datetime.now(UTC),
    )


async def main() -> None:
    """Post sample embeds to Discord for testing."""
    settings = get_settings()

    channel_id = 1215729486994210897  # Live DragonZ NFT channel, not a test channel

    print(f"Posting test embeds to channel {channel_id}...")

    # Create Discord client
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        print(f"Logged in as {client.user}")

        try:
            channel = client.get_channel(channel_id)
            if not channel:
                channel = await client.fetch_channel(channel_id)

            if not isinstance(channel, discord.TextChannel):
                print(f"Error: Channel {channel_id} is not a text channel")
                await client.close()
                return

            print(f"Found channel: #{channel.name}")

            # Post header message
            await channel.send("**--- NFT Embed Test Suite ---**")

            # 1. Mint embed
            print("Fetching mint image from IPFS...")
            mint_event = await create_sample_mint_event()
            print("Posting mint embed...")
            mint_embed = create_mint_embed(mint_event, COLLECTION_NAME)
            await channel.send(content="**1. Mint Event**", embed=mint_embed)
            await asyncio.sleep(5)

            # 2. Transfer embed
            print("Fetching transfer image from IPFS...")
            transfer_event = await create_sample_transfer_event()
            print("Posting transfer embed...")
            transfer_embed = create_transfer_embed(transfer_event, COLLECTION_NAME)
            await channel.send(content="**2. Transfer Event**", embed=transfer_embed)
            await asyncio.sleep(5)

            # 3. Burn embed
            print("Fetching burn image from IPFS...")
            burn_event = await create_sample_burn_event()
            print("Posting burn embed...")
            burn_embed = create_burn_embed(burn_event, COLLECTION_NAME)
            await channel.send(content="**3. Burn Event**", embed=burn_embed)
            await asyncio.sleep(5)

            # 4. Listing embed without rarity
            print("Fetching listing image from IPFS...")
            listing_event = await create_sample_listing_event(with_rarity=False)
            print("Posting listing embed (no rarity)...")
            listing_embed = create_listing_embed(
                listing_event, COLLECTION_NAME, chain=TEST_CHAIN, contract_address=TEST_CONTRACT
            )
            await channel.send(content="**4. Listing Event** (without rarity)", embed=listing_embed)
            await asyncio.sleep(5)

            # 5. Listing embed with rarity
            print("Fetching listing (rarity) image from IPFS...")
            listing_event_rarity = await create_sample_listing_event(with_rarity=True)
            print("Posting listing embed (with rarity)...")
            listing_embed_rarity = create_listing_embed(
                listing_event_rarity,
                COLLECTION_NAME,
                chain=TEST_CHAIN,
                contract_address=TEST_CONTRACT,
            )
            await channel.send(
                content="**5. Listing Event** (with rarity)", embed=listing_embed_rarity
            )
            await asyncio.sleep(5)

            # 6. Sale embed without rarity
            print("Fetching sale image from IPFS...")
            sale_event = await create_sample_sale_event(with_rarity=False)
            print("Posting sale embed (no rarity)...")
            sale_embed = create_sale_embed(sale_event, COLLECTION_NAME, chain=TEST_CHAIN)
            await channel.send(content="**6. Sale Event** (without rarity)", embed=sale_embed)
            await asyncio.sleep(5)

            # 7. Sale embed with rarity
            print("Fetching sale (rarity) image from IPFS...")
            sale_event_rarity = await create_sample_sale_event(with_rarity=True)
            print("Posting sale embed (with rarity)...")
            sale_embed_rarity = create_sale_embed(
                sale_event_rarity, COLLECTION_NAME, chain=TEST_CHAIN
            )
            await channel.send(content="**7. Sale Event** (with rarity)", embed=sale_embed_rarity)

            # Post footer message
            await channel.send("**--- End of Test Suite ---**")

            print("All embeds posted successfully!")

        except Exception as e:
            print(f"Error posting embeds: {e}")
            import traceback

            traceback.print_exc()

        finally:
            await client.close()

    # Run the client
    await client.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
