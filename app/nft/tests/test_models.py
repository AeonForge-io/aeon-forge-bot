"""Tests for NFT Pydantic models."""

from datetime import UTC, datetime
from decimal import Decimal

from app.nft.models import (
    ZERO_ADDRESS,
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)


class TestNFTMintEvent:
    """Tests for NFTMintEvent model."""

    def test_create_mint_event(self, sample_mint_event: NFTMintEvent) -> None:
        """Test creating a mint event."""
        assert sample_mint_event.token_id == "123"
        assert sample_mint_event.collection_id == 1
        assert sample_mint_event.price_native == Decimal("0.05")

    def test_address_normalized_to_lowercase(self) -> None:
        """Test that addresses are normalized to lowercase."""
        event = NFTMintEvent(
            collection_id=1,
            token_id="1",
            to_address="0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
            event_timestamp=datetime.now(UTC),
        )
        assert event.to_address == "0xabcdef1234567890abcdef1234567890abcdef12"

    def test_short_address(self, sample_mint_event: NFTMintEvent) -> None:
        """Test shortened address formatting."""
        assert sample_mint_event.short_to_address == "0xabcd...ef12"


class TestNFTTransferEvent:
    """Tests for NFTTransferEvent model."""

    def test_create_transfer_event(self, sample_transfer_event: NFTTransferEvent) -> None:
        """Test creating a transfer event."""
        assert sample_transfer_event.token_id == "123"
        assert "abcd" in sample_transfer_event.short_from_address
        assert "5678" in sample_transfer_event.short_to_address


class TestNFTBurnEvent:
    """Tests for NFTBurnEvent model."""

    def test_create_burn_event(self, sample_burn_event: NFTBurnEvent) -> None:
        """Test creating a burn event."""
        assert sample_burn_event.token_id == "123"
        assert sample_burn_event.from_address.startswith("0x")


class TestNFTListingEvent:
    """Tests for NFTListingEvent model."""

    def test_create_listing_event(self, sample_listing_event: NFTListingEvent) -> None:
        """Test creating a listing event."""
        assert sample_listing_event.token_id == "123"
        assert sample_listing_event.marketplace == "forum_one"
        assert sample_listing_event.price_native == Decimal("0.5")


class TestNFTSaleEvent:
    """Tests for NFTSaleEvent model."""

    def test_create_sale_event(self, sample_sale_event: NFTSaleEvent) -> None:
        """Test creating a sale event."""
        assert sample_sale_event.token_id == "123"
        assert sample_sale_event.marketplace == "forum_one"
        assert sample_sale_event.seller_address.startswith("0x")
        assert sample_sale_event.buyer_address.startswith("0x")

    def test_short_addresses(self, sample_sale_event: NFTSaleEvent) -> None:
        """Test shortened address formatting for both parties."""
        assert "..." in sample_sale_event.short_seller_address
        assert "..." in sample_sale_event.short_buyer_address


class TestZeroAddress:
    """Tests for zero address constant and detection."""

    def test_zero_address_constant(self) -> None:
        """Test the zero address constant is correct."""
        assert ZERO_ADDRESS == "0x0000000000000000000000000000000000000000"
        assert len(ZERO_ADDRESS) == 42
