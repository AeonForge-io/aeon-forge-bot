"""Discord embed builders for NFT events."""

from decimal import Decimal

import discord

from app.discord.nft_event_colors import (
    BURN_COLOR,
    LISTING_COLOR,
    MINT_COLOR,
    SALE_COLOR,
    TRANSFER_COLOR,
)
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

# Chain to block explorer URL mapping
CHAIN_EXPLORERS: dict[str, str] = {
    "base": "https://basescan.org",
    "base-sepolia": "https://sepolia.basescan.org",
    "ethereum": "https://etherscan.io",
    "polygon": "https://polygonscan.com",
    "arbitrum": "https://arbiscan.io",
    "optimism": "https://optimistic.etherscan.io",
}


def _get_explorer_url(chain: str, tx_hash: str) -> str:
    """Get block explorer URL for a transaction.

    Args:
        chain: Blockchain network name
        tx_hash: Transaction hash

    Returns:
        Full URL to transaction on block explorer
    """
    base_url = CHAIN_EXPLORERS.get(chain, CHAIN_EXPLORERS["base"])
    return f"{base_url}/tx/{tx_hash}"


# Marketplace display name mapping
MARKETPLACE_DISPLAY_NAMES: dict[str, str] = {
    "magic_eden": "Magic Eden",
    "opensea": "OpenSea",
    "blur": "Blur",
}


def _format_marketplace(marketplace: str) -> str:
    """Format marketplace identifier for display.

    Args:
        marketplace: Internal marketplace identifier (e.g., 'magic_eden')

    Returns:
        Human-readable marketplace name (e.g., 'Magic Eden')
    """
    return MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace.replace("_", " ").title())


def _get_magic_eden_item_url(chain: str, contract_address: str, token_id: str) -> str:
    """Get Magic Eden item detail URL.

    Args:
        chain: Blockchain network name
        contract_address: NFT contract address
        token_id: Token ID

    Returns:
        URL to item on Magic Eden
    """
    return f"https://magiceden.us/item-details/{chain}/{contract_address}/{token_id}"


def _format_eth_price(price: Decimal | None, price_usd: Decimal | None = None) -> str:
    """Format ETH price with optional USD value.

    Args:
        price: Price in ETH
        price_usd: Optional USD value

    Returns:
        Formatted price string
    """
    if price is None:
        return "N/A"

    eth_str = f"{price:.4f}".rstrip("0").rstrip(".") + " ETH"

    if price_usd is not None:
        usd_str = f"${price_usd:,.2f}"
        return f"{eth_str} ({usd_str})"

    return eth_str


def _format_floor_comparison(price: Decimal, floor: Decimal | None) -> str | None:
    """Format price as multiple of floor.

    Args:
        price: Event price
        floor: Floor price

    Returns:
        Formatted comparison string, or None if no floor
    """
    if floor is None or floor <= 0:
        return None

    multiple = float(price / floor)
    if multiple >= 1.0:
        return f"{multiple:.1f}x floor"
    else:
        pct = (1 - multiple) * 100
        return f"{pct:.0f}% below floor"


def create_mint_embed(event: NFTMintEvent, collection_name: str) -> discord.Embed:
    """Create Discord embed for mint event.

    Args:
        event: Mint event data
        collection_name: Human-readable collection name

    Returns:
        Discord embed ready to send
    """
    embed = discord.Embed(
        title=f"🎨 New Mint | {collection_name} #{event.token_id}",
        color=MINT_COLOR,
        timestamp=event.event_timestamp,
    )

    if event.token_image_url:
        embed.set_image(url=event.token_image_url)

    # Two-column layout
    embed.add_field(
        name="Minted By",
        value=f"`{event.short_to_address}`",
        inline=True,
    )

    if event.price_native is not None:
        embed.add_field(
            name="Price",
            value=_format_eth_price(event.price_native, event.price_usd),
            inline=True,
        )

    if event.transaction_hash:
        explorer_url = _get_explorer_url(event.chain, event.transaction_hash)
        embed.add_field(
            name="Transaction",
            value=f"[View on Explorer]({explorer_url})",
            inline=False,
        )

    return embed


def create_transfer_embed(event: NFTTransferEvent, collection_name: str) -> discord.Embed:
    """Create Discord embed for transfer event.

    Args:
        event: Transfer event data
        collection_name: Human-readable collection name

    Returns:
        Discord embed ready to send
    """
    embed = discord.Embed(
        title=f"🔄 Transfer | {collection_name} #{event.token_id}",
        color=TRANSFER_COLOR,
        timestamp=event.event_timestamp,
    )

    if event.token_image_url:
        embed.set_image(url=event.token_image_url)

    # Two-column layout
    embed.add_field(
        name="From",
        value="Aeon Forge",
        inline=True,
    )

    embed.add_field(
        name="To",
        value=f"`{event.short_to_address}`",
        inline=True,
    )

    if event.transaction_hash:
        explorer_url = _get_explorer_url(event.chain, event.transaction_hash)
        embed.add_field(
            name="Transaction",
            value=f"[View on Explorer]({explorer_url})",
            inline=False,
        )

    return embed


def create_burn_embed(event: NFTBurnEvent, collection_name: str) -> discord.Embed:
    """Create Discord embed for burn event.

    Args:
        event: Burn event data
        collection_name: Human-readable collection name

    Returns:
        Discord embed ready to send
    """
    embed = discord.Embed(
        title=f"🔥 Burned | {collection_name} #{event.token_id}",
        color=BURN_COLOR,
        timestamp=event.event_timestamp,
    )

    if event.token_image_url:
        embed.set_image(url=event.token_image_url)

    # Two-column layout
    embed.add_field(
        name="Burned By",
        value=f"`{event.short_from_address}`",
        inline=True,
    )

    if event.transaction_hash:
        explorer_url = _get_explorer_url(event.chain, event.transaction_hash)
        embed.add_field(
            name="Transaction",
            value=f"[View on Explorer]({explorer_url})",
            inline=True,
        )

    return embed


def create_listing_embed(
    event: NFTListingEvent,
    collection_name: str,
    chain: str | None = None,
    contract_address: str | None = None,
) -> discord.Embed:
    """Create Discord embed for listing event.

    Args:
        event: Listing event data
        collection_name: Human-readable collection name
        chain: Blockchain network (for Magic Eden link)
        contract_address: NFT contract address (for Magic Eden link)

    Returns:
        Discord embed ready to send
    """
    # Use token name if available, otherwise collection + token ID
    title_name = event.token_name or f"{collection_name} #{event.token_id}"

    embed = discord.Embed(
        title=f"📋 Listed | {title_name}",
        color=LISTING_COLOR,
        timestamp=event.event_timestamp,
    )

    # Image (Discord always places set_image at bottom)
    if event.token_image_url:
        embed.set_image(url=event.token_image_url)

    # Row 1: Seller | Price
    embed.add_field(
        name="Seller",
        value=f"`{event.short_seller_address}`",
        inline=True,
    )

    embed.add_field(
        name="Price",
        value=_format_eth_price(event.price_native, event.price_usd),
        inline=True,
    )

    # Row 2: Rarity | View on Marketplace
    marketplace_name = _format_marketplace(event.marketplace)
    if chain and contract_address:
        me_url = _get_magic_eden_item_url(chain, contract_address, event.token_id)
        marketplace_value = f"[View on {marketplace_name}]({me_url})"
    else:
        marketplace_value = marketplace_name

    if event.rarity_rank:
        embed.add_field(
            name="Rarity",
            value=f"#{event.rarity_rank}",
            inline=False,  # Force new row
        )
        embed.add_field(
            name="Preferred Marketplace",
            value=marketplace_value,
            inline=True,
        )
    else:
        embed.add_field(
            name="Preferred Marketplace",
            value=marketplace_value,
            inline=False,  # Full width when alone
        )

    return embed


def create_sale_embed(
    event: NFTSaleEvent,
    collection_name: str,
    chain: str | None = None,
) -> discord.Embed:
    """Create Discord embed for sale event.

    Args:
        event: Sale event data
        collection_name: Human-readable collection name
        chain: Blockchain network (for transaction link)

    Returns:
        Discord embed ready to send
    """
    # Use token name if available, otherwise collection + token ID
    title_name = event.token_name or f"{collection_name} #{event.token_id}"

    embed = discord.Embed(
        title=f"💰 Sold | {title_name}",
        color=SALE_COLOR,
        timestamp=event.event_timestamp,
    )

    # Image (Discord always places set_image at bottom)
    if event.token_image_url:
        embed.set_image(url=event.token_image_url)

    # Row 1: Seller | Buyer
    embed.add_field(
        name="Seller",
        value=f"`{event.short_seller_address}`",
        inline=True,
    )

    embed.add_field(
        name="Buyer",
        value=f"`{event.short_buyer_address}`",
        inline=True,
    )

    # Row 2: Price (full width for emphasis)
    embed.add_field(
        name="Price",
        value=_format_eth_price(event.price_native, event.price_usd),
        inline=False,
    )

    # Row 3: Rarity | Transaction
    if event.rarity_rank:
        embed.add_field(
            name="Rarity",
            value=f"#{event.rarity_rank}",
            inline=True,
        )

    # Transaction link (sale_id is the transaction hash from Magic Eden)
    if chain and event.sale_id:
        explorer_url = _get_explorer_url(chain, event.sale_id)
        embed.add_field(
            name="Transaction",
            value=f"[View on Explorer]({explorer_url})",
            inline=True,
        )

    return embed
