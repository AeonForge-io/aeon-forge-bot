"""Post sample bot posts to the test channel, built by the bot's own card builders.

Usage: uv run python scripts/preview_designs.py [--type mint|batch|transfer|burn|listing|sale]

Posts only to the test channel. Takes DISCORD_TOKEN from the environment, else from
the nearest .env above this script (a worktree finds the main checkout's .env).
"""

import argparse
import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import discord
from discord import ui

from app.core.config import Settings
from app.discord.nft_embeds import (
    create_burn_card,
    create_listing_card,
    create_mint_card,
    create_sale_card,
    create_transfer_card,
)
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

TEST_CHANNEL_ID = 1215729486994210897

MINT_URL = "https://aeonforge.io/mint"
SERIES_1_CONTRACT = "0xc7c1b8a5d8777dac959cb2b274debeda1c0ecc09"
LIMITED_EDITION_CONTRACT = "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
SERIES_1_IMAGE = (
    "https://aeonforge.myfilebase.com/ipfs/QmbzChm6thk9y9DcooXKyxVfharxQ98ubPhsxSfFmg8eDW/{id}.jpg"
)
LIMITED_EDITION_IMAGE = "https://aeonforge.myfilebase.com/ipfs/bafybeihzuj42qllwqgnz4snidjexn5lbca6x6mvhu5qn7hzgcdwnqadr7q/{id}.jpg"
TX_HASH = "0x9f2c61d4a7b35e08c1d94f6a2b7e83051c6d4ab9e2f7380d5c1a46b79e03d8ab"
MINTER = "0xab12345678901234567890123456789012345cd4"
HOLDER = "0x7c03000000000000000000000000000000a9e1aa"
BUYER = "0xb8f6000000000000000000000000000000002d5e"
KINDS = ["mint", "batch", "transfer", "burn", "listing", "sale"]


def _mint(token_id: int, progress: int) -> NFTMintEvent:
    return NFTMintEvent(
        collection_id=1,
        token_id=str(token_id),
        to_address=MINTER,
        token_image_url=LIMITED_EDITION_IMAGE.format(id=token_id),
        price_native=Decimal("0.0015"),
        progress_number=progress,
        max_supply=750,
        transaction_hash=TX_HASH,
        event_timestamp=datetime.now(UTC),
    )


def build_views() -> dict[str, ui.LayoutView]:
    """One sample view per post type, from the production builders."""
    now = datetime.now(UTC)
    series_1 = "DragonZ Series 1"
    image = SERIES_1_IMAGE.format(id=412)
    return {
        "mint": create_mint_card([_mint(289, 212)], "DragonZ Limited Edition", MINT_URL),
        "batch": create_mint_card(
            [_mint(301, 210), _mint(302, 211), _mint(303, 212)],
            "DragonZ Limited Edition",
            MINT_URL,
        ),
        "transfer": create_transfer_card(
            NFTTransferEvent(
                collection_id=1,
                token_id=str(77),
                from_address=HOLDER,
                to_address=BUYER,
                token_image_url=SERIES_1_IMAGE.format(id=77),
                transaction_hash=TX_HASH,
                event_timestamp=now,
            ),
            series_1,
            SERIES_1_CONTRACT,
            "Treasury",
        ),
        "burn": create_burn_card(
            NFTBurnEvent(
                collection_id=1,
                token_id=str(904),
                from_address=HOLDER,
                token_image_url=SERIES_1_IMAGE.format(id=904),
                transaction_hash=TX_HASH,
                event_timestamp=now,
            ),
            series_1,
            SERIES_1_CONTRACT,
        ),
        "listing": create_listing_card(
            NFTListingEvent(
                collection_id=1,
                token_id=str(412),
                token_image_url=image,
                seller_address=HOLDER,
                marketplace="forum_one",
                price_native=Decimal("0.045"),
                listing_id="0xorderhash",
                event_timestamp=now,
            ),
            series_1,
            "base",
            SERIES_1_CONTRACT,
        ),
        "sale": create_sale_card(
            NFTSaleEvent(
                collection_id=1,
                token_id=str(412),
                token_image_url=image,
                seller_address=HOLDER,
                buyer_address=BUYER,
                marketplace="opensea",
                price_native=Decimal("0.045"),
                sale_id=TX_HASH,
                transaction_hash=TX_HASH,
                event_timestamp=now,
            ),
            series_1,
            "base",
            SERIES_1_CONTRACT,
        ),
    }


def read_token() -> str:
    token = os.environ.get("DISCORD_TOKEN")
    if token:
        return token
    for folder in Path(__file__).resolve().parents:
        env_file = folder / ".env"
        if env_file.is_file():
            return Settings(_env_file=env_file).discord_token
    raise SystemExit("Set DISCORD_TOKEN or provide a .env above this script")


async def post(kinds: list[str]) -> None:
    views = build_views()
    client = discord.Client(intents=discord.Intents.none())
    await client.login(read_token())
    try:
        channel = await client.fetch_channel(TEST_CHANNEL_ID)
        if not isinstance(channel, discord.abc.Messageable):
            raise SystemExit(f"Channel {TEST_CHANNEL_ID} cannot take messages")
        for kind in kinds:
            await channel.send(f"Sample {kind} post")
            await channel.send(view=views[kind])
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", choices=KINDS, help="one post type (default all)")
    args = parser.parse_args()
    asyncio.run(post([args.type] if args.type else KINDS))


if __name__ == "__main__":
    main()
