"""The cards each post type builds: image, token id, links and buttons."""

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
from app.discord.tests.card_view import Card
from app.nft.models import (
    NFTBurnEvent,
    NFTListingEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

ADDRESS = "0xabcdef1234567890abcdef1234567890abcdef12"
CONTRACT = "0xa02fff7fe01eeb235cb65d501efc65c65d7ad509"
IMAGE = "https://images.test/42.jpg"
TX_HASH = "0x" + "ab" * 32
TX_URL = f"https://basescan.org/tx/{TX_HASH}"
BROWSE_URL = f"https://forumone.io/collection/8453/{CONTRACT}"
MINT_URL = "https://aeonforge.io/mint"
NOW = datetime.now(UTC)


def mint_event(nft_id: str = "42", **overrides: object) -> NFTMintEvent:
    values: dict[str, object] = {
        "collection_id": 1,
        "token_id": nft_id,
        "to_address": ADDRESS,
        "token_image_url": IMAGE,
        "progress_number": 212,
        "max_supply": 750,
        "transaction_hash": TX_HASH,
        "event_timestamp": NOW,
    }
    return NFTMintEvent(**{**values, **overrides})


async def test_mint_card_shows_image_token_progress_and_both_links() -> None:
    card = Card(create_mint_embed([mint_event(price_native=Decimal("0.05"))], "DragonZ", MINT_URL))

    assert card.accent == MINT_COLOR
    assert card.images == [IMAGE]
    assert "## DragonZ #42" in card.text
    assert "-# minted on Base" in card.text
    assert card.values("Progress") == ["▰▰▰▱▱▱▱▱▱▱ 212 / 750"]
    assert card.values("Price") == ["0.05 ETH"]
    assert card.buttons == [("Transaction", TX_URL), ("Mint yours", MINT_URL)]


async def test_mint_without_mint_url_has_no_mint_yours_button() -> None:
    card = Card(create_mint_embed([mint_event()], "DragonZ", None))

    assert card.buttons == [("Transaction", TX_URL)]


async def test_batch_mint_lists_every_token_with_its_own_image_and_progress() -> None:
    events = [
        mint_event("301", token_image_url="https://images.test/301.jpg", progress_number=210),
        mint_event("7", token_image_url="https://images.test/7.jpg", progress_number=211),
    ]
    card = Card(create_mint_embed(events, "DragonZ", MINT_URL))

    assert card.images == ["https://images.test/301.jpg", "https://images.test/7.jpg"]
    assert card.values("Progress") == ["▰▰▰▱▱▱▱▱▱▱ 210 / 750", "▰▰▰▱▱▱▱▱▱▱ 211 / 750"]
    assert card.text.index("DragonZ #301") < card.text.index("DragonZ #7")
    assert card.buttons == [("Transaction", TX_URL), ("Mint yours", MINT_URL)]


async def test_ten_token_mint_fits_the_40_component_limit() -> None:
    card = Card(create_mint_embed([mint_event(str(i)) for i in range(10)], "DragonZ", MINT_URL))

    assert len(card.items) <= 40


async def test_transfer_card_from_aeon_forge_has_browse_and_no_mint_button() -> None:
    event = NFTTransferEvent(
        collection_id=1,
        token_id="42",
        from_address=ADDRESS,
        to_address="0x1111111111111111111111111111111111111111",
        token_image_url=IMAGE,
        transaction_hash=TX_HASH,
        event_timestamp=NOW,
    )
    card = Card(create_transfer_embed(event, "DragonZ", CONTRACT))

    assert card.accent == TRANSFER_COLOR
    assert card.images == [IMAGE]
    assert "DragonZ #42" in card.text
    assert card.values("From") == ["Aeon Forge"]
    assert card.buttons == [("Transaction", TX_URL), ("Browse Forum One", BROWSE_URL)]


async def test_burn_card() -> None:
    event = NFTBurnEvent(
        collection_id=1,
        token_id="42",
        from_address=ADDRESS,
        token_image_url=IMAGE,
        transaction_hash=TX_HASH,
        event_timestamp=NOW,
    )
    card = Card(create_burn_embed(event, "DragonZ", CONTRACT))

    assert card.accent == BURN_COLOR
    assert card.images == [IMAGE]
    assert "DragonZ #42" in card.text
    assert card.buttons == [("Transaction", TX_URL), ("Browse Forum One", BROWSE_URL)]


async def test_listing_card_has_only_browse_and_names_the_marketplace() -> None:
    event = NFTListingEvent(
        collection_id=1,
        token_id="42",
        token_name="DragonZ #42",
        token_image_url=IMAGE,
        seller_address=ADDRESS,
        marketplace="forum_one",
        price_native=Decimal("0.045"),
        rarity_rank=12,
        listing_id="0xorder",
        event_timestamp=NOW,
    )
    card = Card(create_listing_embed(event, "DragonZ", "base", CONTRACT))

    assert card.accent == LISTING_COLOR
    assert card.images == [IMAGE]
    assert card.values("Price") == ["0.045 ETH"]
    assert card.values("Marketplace") == ["Forum One"]
    assert card.values("Rarity") == ["#12"]
    assert card.buttons == [("Browse Forum One", BROWSE_URL)]


async def test_sale_card_for_another_marketplace_still_browses_forum_one() -> None:
    event = NFTSaleEvent(
        collection_id=1,
        token_id="42",
        token_image_url=IMAGE,
        seller_address=ADDRESS,
        buyer_address="0x1111111111111111111111111111111111111111",
        marketplace="opensea",
        price_native=Decimal("0.5"),
        sale_id=TX_HASH,
        event_timestamp=NOW,
    )
    card = Card(create_sale_embed(event, "DragonZ", "base", CONTRACT))

    assert card.accent == SALE_COLOR
    assert card.images == [IMAGE]
    assert "DragonZ #42" in card.text
    assert card.values("Marketplace") == ["OpenSea"]
    assert card.buttons == [("Transaction", TX_URL), ("Browse Forum One", BROWSE_URL)]


async def test_test_chain_posts_have_no_forum_one_button() -> None:
    event = NFTBurnEvent(
        collection_id=1,
        token_id="1",
        from_address=ADDRESS,
        chain="base-sepolia",
        transaction_hash=TX_HASH,
        event_timestamp=NOW,
    )
    card = Card(create_burn_embed(event, "Test", CONTRACT))

    assert [label for label, _ in card.buttons] == ["Transaction"]
    assert card.buttons[0][1] == f"https://sepolia.basescan.org/tx/{TX_HASH}"
