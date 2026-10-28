"""NFT metadata fetching via IPFS."""

import aiohttp

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# IPFS gateway for fetching metadata and images
IPFS_GATEWAY = "https://aeonforge.mypinata.cloud/ipfs/"

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


def convert_ipfs_url(url: str) -> str:
    """Convert an IPFS URL to use the configured gateway.

    Args:
        url: URL that may start with ipfs:// or use ipfs.io gateway

    Returns:
        URL converted to use IPFS gateway, or original if not IPFS
    """
    if not url:
        return url

    if url.startswith("ipfs://"):
        return url.replace("ipfs://", IPFS_GATEWAY)

    if url.startswith("https://ipfs.io/ipfs/"):
        return url.replace("https://ipfs.io/ipfs/", IPFS_GATEWAY)

    return url


async def fetch_token_image(
    contract_address: str,
    token_id: str,
    chain: str = "base",
) -> str | None:
    """Fetch token image URL from on-chain metadata.

    Calls the contract's tokenURI function, fetches the metadata JSON,
    and extracts the image URL, converting IPFS URLs to use the gateway.

    Args:
        contract_address: NFT contract address
        token_id: Token ID
        chain: Blockchain network (base or base-sepolia)

    Returns:
        Image URL using IPFS gateway, or None if fetch fails
    """
    rpc_url = alchemy_rpc_url(chain)
    if not rpc_url:
        logger.debug("metadata.fetch.unsupported_chain", chain=chain)
        return None

    try:
        # Encode tokenURI(uint256) call
        # Function selector: 0xc87b56dd
        token_id_int = int(token_id)
        data = "0xc87b56dd" + hex(token_id_int)[2:].zfill(64)

        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": contract_address, "data": data}, "latest"],
            "id": 1,
        }

        async with aiohttp.ClientSession() as session:
            # Call tokenURI on contract
            async with session.post(rpc_url, json=payload) as response:
                result = await response.json()

                if "result" not in result or result["result"] == "0x":
                    logger.debug(
                        "metadata.tokenuri.empty",
                        contract=contract_address[:10],
                        token_id=token_id,
                    )
                    return None

                # Decode ABI-encoded string response
                hex_data = result["result"]
                if len(hex_data) <= 130:
                    return None

                # ABI encoded string: offset (32 bytes) + length (32 bytes) + data
                length = int(hex_data[66:130], 16)
                uri_hex = hex_data[130 : 130 + length * 2]
                token_uri = bytes.fromhex(uri_hex).decode("utf-8")

            # Convert IPFS URI to gateway URL
            metadata_url = convert_ipfs_url(token_uri)

            # Fetch metadata JSON
            async with session.get(
                metadata_url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    logger.debug(
                        "metadata.fetch.failed",
                        token_id=token_id,
                        status=response.status,
                    )
                    return None

                metadata = await response.json()

            # Extract and convert image URL
            image_url = metadata.get("image")
            if image_url:
                return convert_ipfs_url(image_url)

            return None

    except Exception as e:
        logger.debug(
            "metadata.fetch.error",
            contract=contract_address[:10],
            token_id=token_id,
            error=str(e),
        )
        return None
