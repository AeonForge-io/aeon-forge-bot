"""Tests for NFT Discord embed builders."""

from datetime import UTC, datetime
from decimal import Decimal

from app.discord.nft_embeds import (
    create_burn_embed,
    create_listing_embed,
    create_mint_embed,
    create_sale_embed,
    create_transfer_embed,
)
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


class TestMintEmbed:
    """Tests for mint embed creation."""

    def test_create_mint_embed_basic(self) -> None:
        """Test creating a basic mint embed."""
        event = NFTMintEvent(
            collection_id=1,
            token_id="42",
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_mint_embed(event, "Test Collection")

        assert "New Mint" in embed.title
        assert "Test Collection #42" in embed.title
        assert embed.color.value == MINT_COLOR

    def test_create_mint_embed_with_price(self) -> None:
        """Test mint embed includes price when available."""
        event = NFTMintEvent(
            collection_id=1,
            token_id="42",
            to_address="0xabcdef1234567890abcdef1234567890abcdef12",
            price_native=Decimal("0.05"),
            price_usd=Decimal("150.00"),
            event_timestamp=datetime.now(UTC),
        )

        embed = create_mint_embed(event, "Test Collection")

        # Check price field exists
        field_names = [f.name for f in embed.fields]
        assert "Price" in field_names


class TestTransferEmbed:
    """Tests for transfer embed creation."""

    def test_create_transfer_embed(self) -> None:
        """Test creating a transfer embed."""
        event = NFTTransferEvent(
            collection_id=1,
            token_id="42",
            from_address="0xabcdef1234567890abcdef1234567890abcdef12",
            to_address="0x1234567890abcdef1234567890abcdef12345678",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_transfer_embed(event, "Test Collection")

        assert "Transfer" in embed.title
        assert embed.color.value == TRANSFER_COLOR

        field_names = [f.name for f in embed.fields]
        assert "From" in field_names
        assert "To" in field_names


class TestBurnEmbed:
    """Tests for burn embed creation."""

    def test_create_burn_embed(self) -> None:
        """Test creating a burn embed."""
        event = NFTBurnEvent(
            collection_id=1,
            token_id="42",
            from_address="0xabcdef1234567890abcdef1234567890abcdef12",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_burn_embed(event, "Test Collection")

        assert "Burned" in embed.title
        assert embed.color.value == BURN_COLOR

        field_names = [f.name for f in embed.fields]
        assert "Burned By" in field_names


class TestListingEmbed:
    """Tests for listing embed creation."""

    def test_create_listing_embed_basic(self) -> None:
        """Test creating a basic listing embed."""
        event = NFTListingEvent(
            collection_id=1,
            token_id="42",
            seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
            marketplace="magic_eden",
            price_native=Decimal("0.5"),
            listing_id="list_123",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_listing_embed(event, "Test Collection")

        assert "Listed" in embed.title
        assert embed.color.value == LISTING_COLOR

        field_names = [f.name for f in embed.fields]
        assert "Seller" in field_names
        assert "Price" in field_names
        assert "Preferred Marketplace" in field_names

    def test_create_listing_embed_with_magic_eden_link(self) -> None:
        """Test listing embed includes Magic Eden link when chain/contract provided."""
        event = NFTListingEvent(
            collection_id=1,
            token_id="42",
            seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
            marketplace="magic_eden",
            price_native=Decimal("0.5"),
            listing_id="list_123",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_listing_embed(
            event, "Test Collection", chain="base", contract_address="0x1234"
        )

        # Check that marketplace field has a link
        marketplace_field = next(f for f in embed.fields if f.name == "Preferred Marketplace")
        assert "View on Magic Eden" in marketplace_field.value
        assert "magiceden.us" in marketplace_field.value

    def test_create_listing_embed_with_rarity(self) -> None:
        """Test listing embed includes rarity when available."""
        event = NFTListingEvent(
            collection_id=1,
            token_id="42",
            seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
            marketplace="rarible",
            price_native=Decimal("0.5"),
            rarity_rank=100,
            listing_id="list_123",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_listing_embed(event, "Test Collection")

        field_names = [f.name for f in embed.fields]
        assert "Rarity" in field_names

    def test_create_listing_embed_uses_token_name(self) -> None:
        """Test listing embed uses token name in title when available."""
        event = NFTListingEvent(
            collection_id=1,
            token_id="42",
            token_name="Cool NFT #42",
            seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
            marketplace="magic_eden",
            price_native=Decimal("0.5"),
            listing_id="list_123",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_listing_embed(event, "Test Collection")

        assert "Cool NFT #42" in embed.title


class TestSaleEmbed:
    """Tests for sale embed creation."""

    def test_create_sale_embed(self) -> None:
        """Test creating a sale embed."""
        event = NFTSaleEvent(
            collection_id=1,
            token_id="42",
            seller_address="0xabcdef1234567890abcdef1234567890abcdef12",
            buyer_address="0x1234567890abcdef1234567890abcdef12345678",
            marketplace="magic_eden",
            price_native=Decimal("0.5"),
            sale_id="0xabc123",
            event_timestamp=datetime.now(UTC),
        )

        embed = create_sale_embed(event, "Test Collection", chain="base")

        assert "Sold" in embed.title
        assert embed.color.value == SALE_COLOR

        field_names = [f.name for f in embed.fields]
        assert "Seller" in field_names
        assert "Buyer" in field_names
        assert "Price" in field_names
        assert "Transaction" in field_names
