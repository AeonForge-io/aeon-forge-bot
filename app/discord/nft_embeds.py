"""Discord card builders for NFT events: one Components V2 message per event."""

from decimal import Decimal

import discord
from discord import ui

from app.discord.nft_event_colors import (
    BURN_COLOR,
    LISTING_COLOR,
    MINT_COLOR,
    SALE_COLOR,
    TRANSFER_COLOR,
)
from app.nft.coin_symbol import sanitize_symbol
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


CHAIN_NAMES: dict[str, str] = {
    "base": "Base",
    "base-sepolia": "Base Sepolia",
    "ethereum": "Ethereum",
    "polygon": "Polygon",
    "arbitrum": "Arbitrum",
    "optimism": "Optimism",
}

# Forum One serves Base only (chain id 8453) among the chains this bot tracks
FORUM_ONE_COLLECTION_URL = "https://forumone.io/collection/8453/{contract_address}"
FORUM_ONE_NFT_URL = "https://forumone.io/token/8453/{contract_address}/{token_id}"

# Internal marketplace ids; any other value is already a display name (from marketplace_marks)
MARKETPLACE_DISPLAY_NAMES: dict[str, str] = {"forum_one": "Forum One"}


def _format_marketplace(marketplace: str) -> str:
    """The display name of a sale's or listing's marketplace."""
    return MARKETPLACE_DISPLAY_NAMES.get(marketplace, marketplace)


def _format_price(
    price: Decimal | None, price_usd: Decimal | None = None, currency: str | None = None
) -> str:
    """Format a price in its coin (ETH when currency is None) with optional USD value.

    Args:
        price: Price in the coin
        price_usd: Optional USD value
        currency: Coin symbol, None for ETH

    Returns:
        Formatted price string
    """
    if price is None:
        return "N/A"

    eth_str = f"{price:.6f}".rstrip("0").rstrip(".") + f" {currency or 'ETH'}"

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


def _link_button(label: str, url: str) -> ui.Button[ui.LayoutView]:
    return ui.Button(style=discord.ButtonStyle.link, label=label, url=url)


def _card(
    colour: int,
    sections: list[tuple[str, str, str | None, str]],
    buttons: list[ui.Button[ui.LayoutView]],
) -> ui.LayoutView:
    """One container: per token a heading, its image and its detail lines, then the link buttons.

    Args:
        colour: Accent colour of the container
        sections: (heading, subline, image URL, detail text) per token
        buttons: Link buttons, in display order
    """
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=colour)
    for heading, subline, image_url, details in sections:
        container.add_item(ui.TextDisplay(f"## {heading}\n-# {subline}"))
        if image_url:
            gallery: ui.MediaGallery[ui.LayoutView] = ui.MediaGallery()
            gallery.add_item(media=image_url, description=heading)
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(details))
    if buttons:
        container.add_item(ui.Separator())
        container.add_item(ui.ActionRow(*buttons))
    view = ui.LayoutView()
    view.add_item(container)
    return view


def _lines(*pairs: tuple[str, str | None]) -> str:
    return "\n".join(f"**{label}** {value}" for label, value in pairs if value)


def _transaction_button(chain: str, tx_hash: str | None) -> list[ui.Button[ui.LayoutView]]:
    return [_link_button("Transaction", _get_explorer_url(chain, tx_hash))] if tx_hash else []


def _browse_button(chain: str, contract_address: str) -> list[ui.Button[ui.LayoutView]]:
    if chain != "base":
        return []
    return [
        _link_button(
            "Browse Forum One", FORUM_ONE_COLLECTION_URL.format(contract_address=contract_address)
        )
    ]


def create_mint_card(
    events: list[NFTMintEvent], collection_name: str, mint_url: str | None
) -> ui.LayoutView:
    """Create the card for one mint transaction (one message), a section per token.

    Args:
        events: Mint events of one transaction, in one message
        collection_name: Human-readable collection name
        mint_url: Where to mint, or None for a collection that has no mint page

    Returns:
        Layout view ready to send
    """
    first = events[0]
    sections = [
        (
            f"{collection_name} #{event.token_id}",
            f"minted on {CHAIN_NAMES[event.chain]}",
            event.token_image_url,
            _lines(
                ("Minter", event.short_to_address),
                (
                    "Price",
                    _format_price(event.price_native, event.price_usd)
                    if event.price_native is not None
                    else None,
                ),
                (
                    "Progress",
                    _progress_bar(event.progress_number, event.max_supply)
                    if event.progress_number is not None and event.max_supply
                    else None,
                ),
            ),
        )
        for event in events
    ]
    buttons = _transaction_button(first.chain, first.transaction_hash)
    if mint_url:
        buttons.append(_link_button("Mint yours", mint_url))
    return _card(MINT_COLOR, sections, buttons)


def _progress_bar(number: int, max_supply: int) -> str:
    filled = min(10, round(10 * number / max_supply))
    return "▰" * filled + "▱" * (10 - filled) + f" {number} / {max_supply}"


def create_transfer_card(
    event: NFTTransferEvent,
    collection_name: str,
    contract_address: str,
    from_label: str | None,
) -> ui.LayoutView:
    """Create the card for a transfer; from_label is the company wallet label of the sender."""
    section = (
        f"{collection_name} #{event.token_id}",
        f"sent on {CHAIN_NAMES[event.chain]}",
        event.token_image_url,
        _lines(
            ("From", f"Aeon Forge ({from_label})" if from_label else event.short_from_address),
            ("To", event.short_to_address),
        ),
    )
    buttons = _transaction_button(event.chain, event.transaction_hash) + _browse_button(
        event.chain, contract_address
    )
    return _card(TRANSFER_COLOR, [section], buttons)


def create_burn_card(
    event: NFTBurnEvent, collection_name: str, contract_address: str
) -> ui.LayoutView:
    """Create the card for a burn."""
    section = (
        f"{collection_name} #{event.token_id}",
        f"burned on {CHAIN_NAMES[event.chain]}",
        event.token_image_url,
        _lines(("Burned by", event.short_from_address)),
    )
    buttons = _transaction_button(event.chain, event.transaction_hash) + _browse_button(
        event.chain, contract_address
    )
    return _card(BURN_COLOR, [section], buttons)


def create_listing_card(
    event: NFTListingEvent, collection_name: str, chain: str, contract_address: str
) -> ui.LayoutView:
    """Create the card for a marketplace listing (no transaction: listings are off-chain)."""
    title_name = event.token_name or f"{collection_name} #{event.token_id}"
    listing_symbol = sanitize_symbol(event.currency) if event.currency else None
    section = (
        title_name,
        f"listed on {CHAIN_NAMES[chain]}",
        event.token_image_url,
        _lines(
            ("Seller", event.short_seller_address),
            ("Price", _format_price(event.price_native, event.price_usd, listing_symbol)),
            ("Marketplace", _format_marketplace(event.marketplace)),
            ("Rarity", f"#{event.rarity_rank}" if event.rarity_rank else None),
        ),
    )
    token_button = _link_button(
        "View on Forum One",
        FORUM_ONE_NFT_URL.format(contract_address=contract_address, token_id=event.token_id),
    )
    return _card(LISTING_COLOR, [section], [token_button, *_browse_button(chain, contract_address)])


def create_sale_card(
    event: NFTSaleEvent, collection_name: str, chain: str, contract_address: str
) -> ui.LayoutView:
    """Create the card for a sale."""
    title_name = event.token_name or f"{collection_name} #{event.token_id}"
    section = (
        title_name,
        f"sold on {CHAIN_NAMES[chain]}",
        event.token_image_url,
        _lines(
            ("Seller", event.short_seller_address),
            ("Buyer", event.short_buyer_address),
            (
                "Seller received" if event.seller_received else "Price",
                _format_price(event.price_native, event.price_usd, event.currency),
            ),
            ("Marketplace", _format_marketplace(event.marketplace)),
            ("Rarity", f"#{event.rarity_rank}" if event.rarity_rank else None),
        ),
    )
    buttons = _transaction_button(chain, event.transaction_hash) + _browse_button(
        chain, contract_address
    )
    return _card(SALE_COLOR, [section], buttons)
