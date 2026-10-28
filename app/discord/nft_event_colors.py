"""Color constants for NFT event Discord embeds."""

# Discord color values (hex integers)

# On-chain events
MINT_COLOR = 0x00FF00  # Green
TRANSFER_COLOR = 0x3498DB  # Blue
BURN_COLOR = 0xE67E22  # Orange

# Marketplace events
LISTING_COLOR = 0x9B59B6  # Purple
SALE_COLOR = 0xF1C40F  # Gold

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
