"""The grouped Forum One listings card: one container, a row per listing, oldest first."""

from collections.abc import Mapping

import discord
from discord import ui

from app.discord.nft_embeds import (
    FORUM_ONE_NFT_URL,
    NO_NAMES,
    _browse_button,
    _format_price,
    _wallet,
)
from app.discord.nft_event_colors import LISTING_COLOR
from app.nft.coin_symbol import sanitize_symbol
from app.nft.models import NFTListingEvent

MAX_ROWS = 10
# 10 rows of name, link, price and seller must stay under Discord's 4000 characters per view
MAX_NAME_CHARS = 80
MAX_SELLER_CHARS = 40


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _row_text(
    event: NFTListingEvent, collection_name: str, contract_address: str, names: Mapping[str, str]
) -> str:
    name = _clip(event.token_name or f"{collection_name} #{event.token_id}", MAX_NAME_CHARS)
    # square brackets would end the link text early
    name = discord.utils.escape_markdown(name).replace("[", "(").replace("]", ")")
    url = FORUM_ONE_NFT_URL.format(contract_address=contract_address, token_id=event.token_id)
    symbol = sanitize_symbol(event.currency) if event.currency else None
    seller = _clip(
        _wallet(names, event.seller_address, event.short_seller_address), MAX_SELLER_CHARS
    )
    return f"[{name}]({url})\n{_format_price(event.price_native, symbol)} · {seller}"


def create_listing_group_card(
    live: list[NFTListingEvent],
    collection_name: str,
    chain: str,
    contract_address: str,
    names: Mapping[str, str] = NO_NAMES,
) -> ui.LayoutView:
    """The card for the still-live listings of one post, oldest first.

    Shows the first MAX_ROWS as rows (36 of Discord's 40 components at most) and counts the rest.
    """
    shown = sorted(live, key=lambda event: event.event_timestamp)[:MAX_ROWS]
    count = len(live)
    container: ui.Container[ui.LayoutView] = ui.Container(accent_colour=LISTING_COLOR)
    container.add_item(
        ui.TextDisplay(f"## {count} new listing{'s' if count != 1 else ''}: {collection_name}")
    )
    for event in shown:
        text: ui.TextDisplay[ui.LayoutView] = ui.TextDisplay(
            _row_text(event, collection_name, contract_address, names)
        )
        if event.token_image_url:
            container.add_item(
                ui.Section(text, accessory=ui.Thumbnail(media=event.token_image_url))
            )
        else:
            container.add_item(text)
    if count > len(shown):
        container.add_item(ui.TextDisplay(f"and {count - len(shown)} more listed"))
    if buttons := _browse_button(chain, contract_address):
        container.add_item(ui.Separator())
        container.add_item(ui.ActionRow(*buttons))
    view = ui.LayoutView()
    view.add_item(container)
    return view
