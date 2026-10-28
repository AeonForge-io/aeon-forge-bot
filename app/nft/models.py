"""Pydantic models for NFT events."""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

# Zero address constant for mint/burn detection
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _format_address(address: str) -> str:
    """Format address with checksum removed (lowercase).

    Args:
        address: Ethereum address

    Returns:
        Lowercase address
    """
    return address.lower()


def _short_address(address: str) -> str:
    """Create shortened address for display.

    Args:
        address: Full Ethereum address

    Returns:
        Shortened format (0x1234...5678)
    """
    if len(address) < 12:
        return address
    return f"{address[:6]}...{address[-4:]}"


class NFTMintEvent(BaseModel):
    """NFT mint event from on-chain data.

    Attributes:
        collection_id: Database ID of the collection
        token_id: NFT token ID
        to_address: Address receiving the minted NFT
        chain: Blockchain network (e.g., 'base', 'ethereum')
        token_image_url: NFT image URL (if available)
        price_native: Mint price in native currency (ETH)
        price_usd: Mint price in USD (if available)
        transaction_hash: On-chain transaction hash
        block_number: Block number of the transaction
        event_timestamp: When the mint occurred
    """

    collection_id: int = Field(..., description="Database collection ID")
    token_id: str = Field(..., description="NFT token ID")
    to_address: str = Field(..., description="Minter/recipient address")
    chain: str = Field(default="base", description="Blockchain network")
    token_image_url: str | None = Field(None, description="NFT image URL")
    price_native: Decimal | None = Field(None, description="Mint price in ETH")
    price_usd: Decimal | None = Field(None, description="Mint price in USD")
    progress_number: int | None = Field(None, description="N in '#N of M'")
    max_supply: int | None = Field(None, description="M in '#N of M'")
    transaction_hash: str | None = Field(None, description="Transaction hash")
    block_number: int | None = Field(None, description="Block number")
    event_timestamp: datetime = Field(..., description="Event timestamp")

    @field_validator("to_address", mode="before")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        """Normalize address to lowercase."""
        return _format_address(v)

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | str) -> datetime:
        """Ensure timestamp is timezone-aware."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @property
    def short_to_address(self) -> str:
        """Get shortened to_address for display."""
        return _short_address(self.to_address)


class NFTTransferEvent(BaseModel):
    """NFT transfer event from on-chain data.

    Attributes:
        collection_id: Database ID of the collection
        token_id: NFT token ID
        from_address: Address sending the NFT
        to_address: Address receiving the NFT
        chain: Blockchain network (e.g., 'base', 'ethereum')
        token_image_url: NFT image URL (if available)
        transaction_hash: On-chain transaction hash
        block_number: Block number of the transaction
        event_timestamp: When the transfer occurred
    """

    collection_id: int = Field(..., description="Database collection ID")
    token_id: str = Field(..., description="NFT token ID")
    from_address: str = Field(..., description="Sender address")
    to_address: str = Field(..., description="Recipient address")
    chain: str = Field(default="base", description="Blockchain network")
    token_image_url: str | None = Field(None, description="NFT image URL")
    transaction_hash: str | None = Field(None, description="Transaction hash")
    block_number: int | None = Field(None, description="Block number")
    event_timestamp: datetime = Field(..., description="Event timestamp")

    @field_validator("from_address", "to_address", mode="before")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        """Normalize address to lowercase."""
        return _format_address(v)

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | str) -> datetime:
        """Ensure timestamp is timezone-aware."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @property
    def short_from_address(self) -> str:
        """Get shortened from_address for display."""
        return _short_address(self.from_address)

    @property
    def short_to_address(self) -> str:
        """Get shortened to_address for display."""
        return _short_address(self.to_address)


class NFTBurnEvent(BaseModel):
    """NFT burn event from on-chain data.

    Attributes:
        collection_id: Database ID of the collection
        token_id: NFT token ID
        from_address: Address burning the NFT
        chain: Blockchain network (e.g., 'base', 'ethereum')
        token_image_url: NFT image URL (if available)
        transaction_hash: On-chain transaction hash
        block_number: Block number of the transaction
        event_timestamp: When the burn occurred
    """

    collection_id: int = Field(..., description="Database collection ID")
    token_id: str = Field(..., description="NFT token ID")
    from_address: str = Field(..., description="Burner address")
    chain: str = Field(default="base", description="Blockchain network")
    token_image_url: str | None = Field(None, description="NFT image URL")
    transaction_hash: str | None = Field(None, description="Transaction hash")
    block_number: int | None = Field(None, description="Block number")
    event_timestamp: datetime = Field(..., description="Event timestamp")

    @field_validator("from_address", mode="before")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        """Normalize address to lowercase."""
        return _format_address(v)

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | str) -> datetime:
        """Ensure timestamp is timezone-aware."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @property
    def short_from_address(self) -> str:
        """Get shortened from_address for display."""
        return _short_address(self.from_address)


class NFTListingEvent(BaseModel):
    """NFT listing event from marketplace.

    Attributes:
        collection_id: Database ID of the collection
        token_id: NFT token ID
        token_name: NFT name (if available)
        token_image_url: NFT image URL (if available)
        seller_address: Seller's address
        marketplace: Marketplace name (magic_eden, opensea, rarible)
        price_native: Listing price in native currency (ETH)
        price_usd: Listing price in USD (if available)
        floor_price_native: Collection floor price at listing time
        rarity_rank: NFT rarity rank (if available)
        listing_id: Marketplace's unique listing ID
        event_timestamp: When the listing was created
    """

    collection_id: int = Field(..., description="Database collection ID")
    token_id: str = Field(..., description="NFT token ID")
    token_name: str | None = Field(None, description="NFT name")
    token_image_url: str | None = Field(None, description="NFT image URL")
    seller_address: str = Field(..., description="Seller address")
    marketplace: str = Field(..., description="Marketplace name")
    price_native: Decimal = Field(..., description="Price in ETH")
    price_usd: Decimal | None = Field(None, description="Price in USD")
    currency: str | None = Field(None, description="Coin symbol of the price")
    floor_price_native: Decimal | None = Field(None, description="Floor price in ETH")
    rarity_rank: int | None = Field(None, description="Rarity rank")
    listing_id: str = Field(..., description="Marketplace listing ID")
    expires_at: datetime | None = Field(None, description="When the listing expires")
    event_timestamp: datetime = Field(..., description="Event timestamp")
    is_active: bool = Field(True, description="Whether listing is active")

    @field_validator("seller_address", mode="before")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        """Normalize address to lowercase."""
        return _format_address(v)

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | str) -> datetime:
        """Ensure timestamp is timezone-aware."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @property
    def short_seller_address(self) -> str:
        """Get shortened seller_address for display."""
        return _short_address(self.seller_address)

    @property
    def floor_multiple(self) -> float | None:
        """Calculate price as multiple of floor price."""
        if self.floor_price_native and self.floor_price_native > 0:
            return float(self.price_native / self.floor_price_native)
        return None


class NFTSaleEvent(BaseModel):
    """NFT sale event from marketplace.

    Attributes:
        collection_id: Database ID of the collection
        token_id: NFT token ID
        token_name: NFT name (if available)
        token_image_url: NFT image URL (if available)
        seller_address: Seller's address
        buyer_address: Buyer's address
        marketplace: Marketplace name (magic_eden, opensea, rarible)
        price_native: Sale price in native currency (ETH)
        price_usd: Sale price in USD (if available)
        floor_price_native: Collection floor price at sale time
        rarity_rank: NFT rarity rank (if available)
        sale_id: Marketplace's unique sale/transaction ID
        event_timestamp: When the sale occurred
    """

    collection_id: int = Field(..., description="Database collection ID")
    token_id: str = Field(..., description="NFT token ID")
    token_name: str | None = Field(None, description="NFT name")
    token_image_url: str | None = Field(None, description="NFT image URL")
    seller_address: str = Field(..., description="Seller address")
    buyer_address: str = Field(..., description="Buyer address")
    marketplace: str = Field(..., description="Marketplace name")
    price_native: Decimal = Field(..., description="Price in ETH")
    price_usd: Decimal | None = Field(None, description="Price in USD")
    currency: str | None = Field(None, description="Coin symbol of the price")
    floor_price_native: Decimal | None = Field(None, description="Floor price in ETH")
    rarity_rank: int | None = Field(None, description="Rarity rank")
    sale_id: str = Field(..., description="Marketplace sale ID")
    transaction_hash: str | None = Field(None, description="Transaction hash")
    event_timestamp: datetime = Field(..., description="Event timestamp")

    @field_validator("seller_address", "buyer_address", mode="before")
    @classmethod
    def normalize_address(cls, v: str) -> str:
        """Normalize address to lowercase."""
        return _format_address(v)

    @field_validator("event_timestamp", mode="before")
    @classmethod
    def ensure_timezone(cls, v: datetime | str) -> datetime:
        """Ensure timestamp is timezone-aware."""
        if isinstance(v, str):
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v

    @property
    def short_seller_address(self) -> str:
        """Get shortened seller_address for display."""
        return _short_address(self.seller_address)

    @property
    def short_buyer_address(self) -> str:
        """Get shortened buyer_address for display."""
        return _short_address(self.buyer_address)

    @property
    def floor_multiple(self) -> float | None:
        """Calculate price as multiple of floor price."""
        if self.floor_price_native and self.floor_price_native > 0:
            return float(self.price_native / self.floor_price_native)
        return None
