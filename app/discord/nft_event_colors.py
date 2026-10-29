"""Accent colours for NFT event Discord cards."""

# Discord color values (hex integers)

# Aeon Forge website palette (af-website Tailwind theme)

# On-chain events
MINT_COLOR = 0x00F3FF  # Brand cyan
TRANSFER_COLOR = 0x00AAFF  # Brand blue
BURN_COLOR = 0xB93931  # Red

# Marketplace events
LISTING_COLOR = 0xBC13FE  # Purple
SALE_COLOR = 0xFF4D00  # Orange

# Collection colors by chain (for embed sidebar)
CHAIN_COLORS = {
    "base": 0x0052FF,  # Base blue
    "ethereum": 0x627EEA,  # Ethereum purple-blue
    "polygon": 0x8247E5,  # Polygon purple
    "arbitrum": 0x28A0F0,  # Arbitrum blue
    "optimism": 0xFF0420,  # Optimism red
}


def get_chain_color(chain: str) -> int:
    """Get embed color for a blockchain.

    Args:
        chain: Blockchain name

    Returns:
        Discord color integer
    """
    return CHAIN_COLORS.get(chain.lower(), 0x7289DA)  # Discord blurple default
