"""Token image URLs and the Alchemy RPC URL per chain."""

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.store import Collection

logger = get_logger(__name__)

# Alchemy network name per chain, for contract calls
ALCHEMY_NETWORKS: dict[str, str] = {
    "base": "base-mainnet",
    "base-sepolia": "base-sepolia",
}


def alchemy_rpc_url(chain: str) -> str | None:
    """Get the Alchemy HTTPS RPC URL for a chain, or None if unsupported."""
    network = ALCHEMY_NETWORKS.get(chain)
    if network is None:
        return None
    return f"https://{network}.g.alchemy.com/v2/{get_settings().alchemy_api_key}"


def token_image_url(collection: Collection, token_id: str) -> str | None:
    """The token's image URL from the collection's image_url_template, or None when it has none."""
    if not collection.image_url_template:
        logger.warning(
            "nft.image.no_template", collection=collection.collection_id, token_id=token_id
        )
        return None
    return collection.image_url_template.replace("{token_id}", token_id)
