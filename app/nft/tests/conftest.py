"""Pytest fixtures for NFT module tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)


@pytest.fixture
def sample_mint_event() -> NFTMintEvent:
    """Create a sample NFT mint event."""
    return NFTMintEvent(
        collection_id=1,
        token_id="123",
        to_address="0xabcdef1234567890abcdef1234567890abcdef12",
        price_native=Decimal("0.05"),
        price_usd=Decimal("150.00"),
        transaction_hash="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        block_number=12345678,
        event_timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_transfer_event() -> NFTTransferEvent:
    """Create a sample NFT transfer event."""
    return NFTTransferEvent(
        collection_id=1,
        token_id="123",
        from_address="0xabcdef1234567890abcdef1234567890abcdef12",
        to_address="0x1234567890abcdef1234567890abcdef12345678",
        transaction_hash="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        block_number=12345679,
        event_timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_burn_event() -> NFTBurnEvent:
    """Create a sample NFT burn event."""
    return NFTBurnEvent(
        collection_id=1,
        token_id="123",
        from_address="0xabcdef1234567890abcdef1234567890abcdef12",
        transaction_hash="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        block_number=12345680,
        event_timestamp=datetime.now(UTC),
    )


@pytest.fixture
def sample_listing_event() -> NFTListingEvent:
    """Create a sample NFT listing event."""
    return NFTListingEvent(
        collection_id=1,
        token_id="123",
        token_name="Test NFT #123",
        token_image_url="https://example.com/nft/123.png",
        seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
        marketplace="magic_eden",
        price_native=Decimal("0.5"),
        price_usd=Decimal("1500.00"),
        floor_price_native=Decimal("0.25"),
        rarity_rank=42,
        listing_id="list_123",
        event_timestamp=datetime.now(UTC),
        is_active=True,
    )


@pytest.fixture
def sample_sale_event() -> NFTSaleEvent:
    """Create a sample NFT sale event."""
    return NFTSaleEvent(
        collection_id=1,
        token_id="123",
        token_name="Test NFT #123",
        token_image_url="https://example.com/nft/123.png",
        seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
        buyer_address="0x1234567890abcdef1234567890abcdef12345678",
        marketplace="magic_eden",
        price_native=Decimal("0.5"),
        price_usd=Decimal("1500.00"),
        floor_price_native=Decimal("0.25"),
        rarity_rank=42,
        sale_id="sale_123",
        event_timestamp=datetime.now(UTC),
    )
